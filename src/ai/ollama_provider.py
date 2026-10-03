"""Ollama provider.

Local, private, and free: no API key, no network egress, no per-token cost.
That makes it the sensible default for handling someone's real resume and
personal data.

Implemented on the standard library only. Ollama is local, so the latency and
payload sizes do not justify adding an HTTP client dependency, and using
``urllib`` keeps the offline guarantee obvious.

When Ollama is not running, every operation raises
:class:`~core.errors.ProviderUnavailableError` with an actionable message. It
does not fall back to another provider and it does not produce output.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Optional, Type

from pydantic import BaseModel

from core.enums import AnalysisSource, ModelRunStatus, ModelRunTask
from core.errors import (
    AIProviderError,
    ModelNotFoundError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from core.logging_config import get_logger, log_event
from core.model_run import PROMPT_VERSION
from ai.provider import (
    AIProvider,
    EmbeddingResult,
    GenerationOptions,
    HealthStatus,
    StructuredResult,
    TextResult,
    T,
)
from core.settings import AISettings

__all__ = ["OllamaProvider"]

_log = get_logger("ai.ollama")


class OllamaProvider(AIProvider):
    """Talks to a local Ollama server over its HTTP API.

    Usage::

        provider = OllamaProvider(AISettings(model="qwen2.5:7b"))
        status = provider.health_check()
        if not status.available:
            ...  # handle cleanly; do not substitute fake output
    """

    name = "ollama"
    requires_api_key = False
    supports_embeddings = True

    def __init__(
        self,
        settings: Optional[AISettings] = None,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.settings = settings or AISettings()
        self.base_url = (base_url or self.settings.base_url).rstrip("/")
        self.model = model or self.settings.model
        self.timeout_seconds = timeout_seconds or self.settings.timeout_seconds
        self.connect_timeout = self.settings.connect_timeout_seconds

    # -- transport -----------------------------------------------------------
    def _url(self, endpoint: str) -> str:
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        # Ollama normally needs no key. If one is configured for a proxy in
        # front of it, use it, and never log it.
        if self.settings.has_api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key.get_secret_value()}"
        return headers

    def _post(self, endpoint: str, payload: dict[str, Any], *, timeout: Optional[float] = None) -> dict[str, Any]:
        """POST JSON and decode the JSON response.

        Raises:
            ProviderUnavailableError: The server is not reachable.
            ProviderTimeoutError: The server did not respond in time.
            AIProviderError: The response was not valid JSON.
        """
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._url(endpoint), data=body, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = self._safe_detail(exc.read().decode("utf-8", errors="replace"))
            if exc.code == 404:
                raise ModelNotFoundError(
                    "Ollama does not have that model; pull it first",
                    endpoint=endpoint,
                    model=payload.get("model"),
                    detail=detail,
                ) from exc
            raise AIProviderError(
                "Ollama returned an error",
                status_code=exc.code,
                endpoint=endpoint,
                detail=detail,
            ) from exc
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            raise ProviderUnavailableError(
                "cannot reach Ollama; start it with 'ollama serve'",
                base_url=self.base_url,
                cause=type(exc).__name__,
            ) from exc
        except TimeoutError as exc:
            raise ProviderTimeoutError(
                "Ollama did not respond in time",
                timeout_seconds=timeout or self.timeout_seconds,
            ) from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AIProviderError("Ollama returned a non-JSON response") from exc

    def _get(self, endpoint: str, *, timeout: Optional[float] = None) -> dict[str, Any]:
        request = urllib.request.Request(self._url(endpoint), headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.connect_timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            raise ProviderUnavailableError(
                "cannot reach Ollama; start it with 'ollama serve'",
                base_url=self.base_url,
                cause=type(exc).__name__,
            ) from exc
        except TimeoutError as exc:
            raise ProviderTimeoutError("Ollama did not respond in time") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AIProviderError("Ollama returned a non-JSON response") from exc

    @staticmethod
    def _safe_detail(raw: str) -> str:
        """Trim a server error body to something safe to log."""
        return " ".join(raw.split())[:200]

    # -- health --------------------------------------------------------------
    def health_check(self, model: Optional[str] = None) -> HealthStatus:
        """Probe the server and check the configured model is present.

        Never raises. Returns ``available=False`` with an actionable detail
        string so the CLI can report the problem without a traceback.
        """
        target = model or self.model
        started = time.monotonic()
        try:
            payload = self._get("/api/tags", timeout=self.connect_timeout)
        except ProviderUnavailableError as exc:
            return HealthStatus(
                available=False,
                provider=self.name,
                model=target,
                detail=str(exc),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except (ProviderTimeoutError, AIProviderError) as exc:
            return HealthStatus(
                available=False,
                provider=self.name,
                model=target,
                detail=str(exc),
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        names = [m.get("name", "") for m in payload.get("models", [])]
        latency = int((time.monotonic() - started) * 1000)
        present = any(_model_matches(n, target) for n in names)

        log_event(
            _log,
            "ai.health_check",
            duration_ms=latency,
            provider=self.name,
            model=target,
            available=present,
            model_count=len(names),
        )

        if not present:
            return HealthStatus(
                available=False,
                provider=self.name,
                model=target,
                models_available=names,
                detail=(
                    f"Ollama is running but model {target!r} is not pulled; "
                    f"run: ollama pull {target}"
                ),
                latency_ms=latency,
            )
        return HealthStatus(
            available=True, provider=self.name, model=target, models_available=names, latency_ms=latency
        )

    def list_models(self) -> list[str]:
        """Return the models the server has.

        Raises:
            ProviderUnavailableError: The server is not reachable.
        """
        payload = self._get("/api/tags", timeout=self.connect_timeout)
        return [m.get("name", "") for m in payload.get("models", [])]

    # -- generation ----------------------------------------------------------
    def generate_text(
        self,
        prompt: str,
        *,
        task: ModelRunTask = ModelRunTask.GENERATE_TEXT,
        model: Optional[str] = None,
        analysis_source: AnalysisSource = AnalysisSource.AI_GENERAL,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        options: Optional[GenerationOptions] = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> TextResult:
        """Generate text.

        Raises:
            ProviderUnavailableError: Ollama is not running.
            ModelNotFoundError: The model is not pulled.
            ProviderTimeoutError: Generation exceeded the timeout.
            AIProviderError: Any other transport or protocol failure.
        """
        chosen = model or self.model
        temp = self.settings.temperature if temperature is None else temperature
        run = self._start_run(
            model=chosen,
            task=task,
            prompt=prompt,
            analysis_source=analysis_source,
            prompt_version=prompt_version,
            temperature=temp,
        )

        payload: dict[str, Any] = {
            "model": chosen,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temp, **(dict(options) if options else {})},
        }
        if system:
            payload["system"] = system

        started = time.monotonic()
        try:
            response = self._post("/api/generate", payload)
        except (ProviderUnavailableError, ProviderTimeoutError, AIProviderError) as exc:
            run.fail(str(exc), status=ModelRunStatus.TIMEOUT if isinstance(exc, ProviderTimeoutError) else ModelRunStatus.FAILED)
            raise

        text = response.get("response", "") or ""
        latency = int((time.monotonic() - started) * 1000)
        run.complete(text, latency)
        run.prompt_tokens = response.get("prompt_eval_count")
        run.completion_tokens = response.get("eval_count")
        run.model_run_metadata = {"done_reason": response.get("done_reason") or "stop"}

        log_event(
            _log,
            "ai.generate_text",
            duration_ms=latency,
            provider=self.name,
            model=chosen,
            task=task.value,
            analysis_source=analysis_source.value,
            output_chars=len(text),
        )
        return TextResult(text=text, run=run, analysis_source=analysis_source)

    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        *,
        task: ModelRunTask = ModelRunTask.EXTRACT,
        model: Optional[str] = None,
        analysis_source: AnalysisSource = AnalysisSource.AI_GENERAL,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        options: Optional[GenerationOptions] = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> StructuredResult[T]:
        """Generate output matching ``response_model``.

        JSON mode is requested from Ollama, but the response is still parsed
        defensively, because a model that ignores the format instruction will
        happily return prose.

        Raises:
            ProviderUnavailableError: Ollama is not running.
            ModelNotFoundError: The model is not pulled.
            AIProviderError: The output does not match ``response_model``. The
                invalid text is included in the error detail so it can be
                inspected, and is never coerced into a valid object.
        """
        merged = {"num_predict": 1024, **(dict(options) if options else {})}
        if self.settings.json_mode:
            merged["format"] = response_model.model_json_schema()

        result = self.generate_text(
            prompt,
            task=task,
            model=model,
            analysis_source=analysis_source,
            system=system,
            temperature=temperature,
            options=GenerationOptions(merged),
            prompt_version=prompt_version,
        )

        parsed, error = self._parse_structured(result.text, response_model)
        if parsed is None:
            failed = result.run.fail(f"structured parse failed: {error}", status=ModelRunStatus.FAILED)
            raise AIProviderError(
                "model output did not match the requested schema",
                schema=response_model.__name__,
                detail=error,
                run_id=failed.id,
                output_preview=result.text[:200],
            )

        result.run.model_run_metadata = {**result.run.model_run_metadata, "schema": response_model.__name__}
        return StructuredResult(
            value=parsed, run=result.run, raw_text=result.text, analysis_source=analysis_source
        )

    def embed(
        self,
        texts: list[str],
        *,
        model: Optional[str] = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> EmbeddingResult:
        """Return embeddings for ``texts``.

        Raises:
            ProviderUnavailableError: Ollama is not running.
            AIProviderError: The model does not support embeddings.
        """
        chosen = model or self.settings.embedding_model or self.model
        if not texts:
            return EmbeddingResult(vectors=[], run=self._start_run(
                model=chosen, task=ModelRunTask.EMBED, prompt="", analysis_source=AnalysisSource.AI_GENERAL,
                prompt_version=prompt_version, temperature=None,
            ), model=chosen, dimensions=0)

        run = self._start_run(
            model=chosen,
            task=ModelRunTask.EMBED,
            prompt="\n".join(texts),
            analysis_source=AnalysisSource.CANDIDATE_DATA,
            prompt_version=prompt_version,
            temperature=None,
        )
        started = time.monotonic()
        try:
            response = self._post("/api/embeddings", {"model": chosen, "prompt": texts[0]})
        except (ProviderUnavailableError, ProviderTimeoutError, AIProviderError) as exc:
            run.fail(str(exc))
            raise

        vector = response.get("embedding")
        if not isinstance(vector, list):
            run.fail("response contained no embedding", status=ModelRunStatus.FAILED)
            raise AIProviderError("Ollama did not return an embedding", model=chosen)

        latency = int((time.monotonic() - started) * 1000)
        run.complete("", latency)
        run.model_run_metadata = {"dimensions": len(vector)}

        # Ollama's /api/embeddings handles one prompt at a time; the caller gets
        # one vector back. Reporting a single-element result keeps the contract
        # honest instead of pretending the other inputs were embedded.
        if len(texts) > 1:
            run.model_run_metadata["note"] = (
                f"only the first of {len(texts)} texts was embedded; "
                "use /api/embed for batches"
            )
        return EmbeddingResult(
            vectors=[[float(x) for x in vector]],
            run=run,
            model=chosen,
            dimensions=len(vector),
        )


def _model_matches(available: str, requested: str) -> bool:
    """Compare model names tolerating Ollama's implicit ``:latest`` tag."""
    if not available or not requested:
        return False
    a = available.split(":")[0]
    b = requested.split(":")[0]
    return a == b
