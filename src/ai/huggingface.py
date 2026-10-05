"""Local Hugging Face embedding provider.

Real semantic embeddings on CPU, with no API key and no hosted inference. The
model runs through ONNX Runtime via ``fastembed`` and is cached on disk after
the first download, so a warm machine embeds with no network at all.

**This provider never fabricates a vector.** An earlier version of this module
fell back to a hash-based trigram projection whenever the model failed to load,
and reported the result as semantic inference. That is precisely the failure
this codebase exists to prevent: a fake similarity is indistinguishable from a
real one at the point it is trusted, so a broken model silently produced
confident, wrong verdicts. Every failure path here raises instead.

The provider is *embedding-only*. ``all-MiniLM-L6-v2`` is a sentence encoder,
not a text generator, so :meth:`generate_text` and :meth:`generate_structured`
raise :class:`~core.errors.AIProviderError` rather than pretending. Use
``ollama`` for generation.

``fastembed`` is imported lazily, so this module always imports — the package
must be importable without an optional extra installed. When it is missing,
:func:`health_check` reports the provider unavailable with the install command,
and :meth:`embed` raises with the same message.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from ai.provider import (
    AIProvider,
    EmbeddingResult,
    GenerationOptions,
    HealthStatus,
    StructuredResult,
    TextResult,
)
from core.enums import AnalysisSource, ModelRunTask
from core.errors import AIProviderError, ProviderUnavailableError
from core.logging_config import get_logger, log_event
from core.model_run import PROMPT_VERSION

__all__ = ["DEFAULT_HF_MODEL_ID", "HuggingFaceLocalProvider"]

_log = get_logger("ai.huggingface")

#: A real sentence-transformers checkpoint, 384 dimensions, Apache-2.0, roughly
#: 90 MB on disk. Chosen because it is the smallest model in the family that
#: still produces embeddings competitive with much larger ones; this project
#: compares short strings such as "Experience with PyTorch", where a 384-dim
#: bi-encoder is the appropriate tool and a large model would only cost RAM.
DEFAULT_HF_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

#: Dimensions ``all-MiniLM-L6-v2`` emits. Verified against the model, not assumed.
EXPECTED_DIMENSION = 384

_INSTALL_HINT = (
    "the local embedding extra is not installed; "
    "run: pip install -e \".[embeddings]\""
)


class HuggingFaceLocalProvider(AIProvider):
    """Sentence-transformer embeddings computed locally.

    Args:
        settings: Provider configuration. ``settings.embedding_model`` overrides
            the checkpoint; ``settings.model`` is ignored, because a sentence
            encoder and a chat model are not interchangeable and silently using
            one for the other would be a lie about what ran.
        cache_dir: Where downloaded model files live. Defaults to
            ``data/models/cache`` under the working directory.
    """

    name = "huggingface"
    requires_api_key = False
    supports_embeddings = True

    def __init__(self, settings: Any = None, *, cache_dir: Optional[str] = None) -> None:
        self.settings = settings
        configured = getattr(settings, "embedding_model", None)
        self.model: str = configured or DEFAULT_HF_MODEL_ID
        self.dimension = EXPECTED_DIMENSION
        self.cache_dir = cache_dir or os.path.abspath(
            os.path.join(os.getcwd(), "data", "models", "cache")
        )
        self._model: Any = None
        self._loaded = False

    # -- loading -------------------------------------------------------------

    def _load(self) -> Any:
        """Return the loaded model, or raise. Never returns a stand-in."""
        if self._loaded and self._model is not None:
            return self._model
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise ProviderUnavailableError(
                f"{self.name}: {_INSTALL_HINT}"
            ) from exc
        try:
            self._model = TextEmbedding(
                model_name=self.model, cache_dir=self.cache_dir
            )
        except Exception as exc:  # download failure, bad checkpoint, no disk
            raise ProviderUnavailableError(
                f"{self.name}: could not load {self.model}: {exc}"
            ) from exc
        self._loaded = True
        return self._model

    # -- AIProvider contract -------------------------------------------------

    def health_check(self) -> HealthStatus:
        """Report whether the model can actually be loaded.

        Embeds one short string, so ``available=True`` means inference really
        ran. A provider that only inspected its own configuration would report
        available for a model that was never downloaded.
        """
        started = time.monotonic()
        try:
            vectors = self._embed_texts(["health check"])
        except AIProviderError as exc:
            return HealthStatus(
                available=False,
                provider=self.name,
                model=self.model,
                detail=str(exc),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        dimension = len(vectors[0]) if vectors else 0
        log_event(
            _log,
            "ai.health_check",
            duration_ms=int((time.monotonic() - started) * 1000),
            provider=self.name,
            model=self.model,
            available=True,
            dimension=dimension,
        )
        return HealthStatus(
            available=True,
            provider=self.name,
            model=self.model,
            detail=f"loaded locally, {dimension} dimensions",
            latency_ms=int((time.monotonic() - started) * 1000),
        )

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
        raise AIProviderError(
            f"{self.name} is an embedding-only provider; "
            f"{self.model} encodes text and cannot generate it. "
            "Use the ollama provider for generation.",
            model=model or self.model,
        )

    def generate_structured(
        self,
        prompt: str,
        response_model: Any,
        *,
        task: ModelRunTask = ModelRunTask.EXTRACT,
        model: Optional[str] = None,
        analysis_source: AnalysisSource = AnalysisSource.AI_GENERAL,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        options: Optional[GenerationOptions] = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> StructuredResult[Any]:
        raise AIProviderError(
            f"{self.name} is an embedding-only provider; "
            f"{self.model} cannot produce structured output. "
            "Use the ollama provider for generation.",
            model=model or self.model,
        )

    def embed(
        self,
        texts: list[str],
        *,
        model: Optional[str] = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> EmbeddingResult:
        """Return one real embedding per input text.

        Raises:
            ProviderUnavailableError: ``fastembed`` is missing, or the model
                could not be loaded. There is no fallback: a caller that needs
                a number gets an answer computed by the model or an exception.
        """
        chosen = model or self.model
        run = self._start_run(
            model=chosen,
            task=ModelRunTask.EMBED,
            prompt="\n".join(texts),
            analysis_source=AnalysisSource.AI_GENERAL,
            prompt_version=prompt_version,
            temperature=None,
        )
        if not texts:
            run.complete("", 0)
            return EmbeddingResult(vectors=[], run=run, model=chosen, dimensions=0)

        started = time.monotonic()
        previous_model, previous_dimension = self.model, self.dimension
        if model and model != self.model:
            self.model, self._loaded, self._model = model, False, None
        try:
            vectors = self._embed_texts(texts)
        except AIProviderError as exc:
            run.fail(str(exc))
            raise
        finally:
            if model and model != previous_model:
                self.model, self._loaded, self._model = (
                    previous_model,
                    self._loaded,
                    self._model,
                )

        latency = int((time.monotonic() - started) * 1000)
        run.complete("", latency)
        log_event(
            _log,
            "ai.embed",
            duration_ms=latency,
            provider=self.name,
            model=chosen,
            count=len(vectors),
            dimension=self.dimension,
        )
        return EmbeddingResult(
            vectors=vectors,
            run=run,
            model=chosen,
            dimensions=self.dimension,
        )

    # -- internals -----------------------------------------------------------

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Run the model. Order and length of the input are preserved."""
        handle = self._load()
        try:
            produced = [self._as_vector(item) for item in handle.embed(list(texts))]
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError(
                f"{self.name}: inference failed for {self.model}: {exc}",
                model=self.model,
            ) from exc

        if len(produced) != len(texts):
            raise AIProviderError(
                f"{self.name}: model returned {len(produced)} vectors "
                f"for {len(texts)} inputs",
                model=self.model,
            )
        for vector in produced:
            if len(vector) != self.dimension:
                raise AIProviderError(
                    f"{self.name}: expected {self.dimension} dimensions, "
                    f"model returned {len(vector)}",
                    model=self.model,
                )
        return produced

    @staticmethod
    def _as_vector(item: Any) -> list[float]:
        """Normalise one model output to a plain float list.

        fastembed yields numpy arrays, but accepting any real sequence keeps the
        provider working with an alternative backend. Every element is coerced
        to float, so a mis-shaped model output fails the dimension check below
        rather than producing a vector of strings.
        """
        raw = item.tolist() if hasattr(item, "tolist") else item
        return [float(value) for value in raw]