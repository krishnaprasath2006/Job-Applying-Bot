"""Provider-agnostic AI interface.

Two rules shape this module.

**Model names are configuration.** No business logic may name a model. A
provider is asked for a model by name at call time, so switching models is an
``.env`` change rather than a refactor.

**An unavailable provider fails loudly.** When Ollama is not running, the
caller gets :class:`~core.errors.ProviderUnavailableError`. The provider does
not silently fall back to a different model, and it never fabricates output. A
fabricated answer to a job application question is worse than no answer,
because it is indistinguishable from a real one at the point of submission.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from core.enums import AnalysisSource, ModelRunStatus, ModelRunTask
from core.errors import (
    AIProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from core.model_run import PROMPT_VERSION, ModelRun

__all__ = [
    "AIProvider",
    "GenerationOptions",
    "TextResult",
    "EmbeddingResult",
    "HealthStatus",
    "ProviderCapability",
]

T = TypeVar("T", bound=BaseModel)


class ProviderCapability(str):
    """Capability names, kept as plain strings for easy comparison."""


class GenerationOptions(dict):
    """Provider-neutral generation options.

    Passed through to the provider. Unknown keys are the provider's business;
    this exists so call sites do not hardcode provider-specific parameters.
    """


@dataclass
class TextResult:
    """Result of :meth:`AIProvider.generate_text`.

    Attributes:
        text: The generated text.
        run: Metadata for the call, always present, so every generation is
            recorded even when nothing else uses the result.
        analysis_source: What the output was grounded in.
    """

    text: str
    run: ModelRun
    analysis_source: AnalysisSource = AnalysisSource.AI_GENERAL

    @property
    def is_grounded(self) -> bool:
        """False when the output came from general model knowledge.

        Callers should check this before treating output as a fact.
        """
        return self.analysis_source is not AnalysisSource.AI_GENERAL


@dataclass
class StructuredResult(Generic[T]):
    """Result of :meth:`AIProvider.generate_structured`."""

    value: T
    run: ModelRun
    raw_text: str = ""
    analysis_source: AnalysisSource = AnalysisSource.AI_GENERAL


@dataclass
class EmbeddingResult:
    """Result of :meth:`AIProvider.embed`.

    Attributes:
        vectors: One vector per input, in order.
        run: Metadata for the call.
        model: Embedding model actually used.
        dimensions: Vector length.
    """

    vectors: list[list[float]]
    run: ModelRun
    model: str = ""
    dimensions: int = 0


@dataclass
class HealthStatus:
    """Result of :meth:`AIProvider.health_check`.

    Attributes:
        available: Whether the provider responded.
        provider: Provider key.
        model: Model that was probed.
        models_available: Model names the provider reports, when it lists them.
        detail: Short diagnostic. Never contains credentials.
        latency_ms: Round-trip time of the probe.
    """

    available: bool
    provider: str
    model: str
    models_available: list[str] = field(default_factory=list)
    detail: str = ""
    latency_ms: Optional[int] = None

    def describe(self) -> str:
        state = "available" if self.available else "UNAVAILABLE"
        suffix = f" - {self.detail}" if self.detail else ""
        return f"{self.provider}/{self.model}: {state}{suffix}"


class AIProvider(ABC):
    """Base class every provider implements.

    Subclasses must implement the four operations. Each raises a specific
    :class:`~core.errors.AIProviderError` subclass on failure so callers can
    distinguish "not running" from "timed out" from "returned nonsense".
    """

    #: Provider key used in configuration and in the registry.
    name: str = "abstract"

    #: Whether this provider needs an API key. The default local provider does
    #: not, which is why the assistant can be fully functional offline.
    requires_api_key: bool = False

    #: Whether the provider can produce embeddings. Ollama can, but only for
    #: models that support it, so this is reported rather than assumed.
    supports_embeddings: bool = False

    @abstractmethod
    def health_check(self) -> HealthStatus:
        """Report whether the provider is reachable and the model is present.

        Must not raise for an ordinary "not running" condition; return
        ``available=False`` with a diagnostic instead.
        """

    @abstractmethod
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
        """Generate free text.

        Args:
            prompt: The user prompt. Never logged in full.
            task: What this call is for, recorded in the run metadata.
            model: Override the configured model for this call.
            analysis_source: What the prompt is grounded in. The honest value
                matters: a prompt built only from a resume is
                ``CANDIDATE_DATA``, one built only from a job description is
                ``JOB_DATA``, and one that asks the model what it happens to
                know is ``AI_GENERAL``.
            system: Optional system prompt.
            temperature: Per-call override.
            options: Provider-specific generation options.
            prompt_version: Prompt version recorded in the run.

        Raises:
            ProviderUnavailableError: The provider is not reachable.
            ProviderTimeoutError: The provider did not respond in time.
            AIProviderError: Any other failure.
        """

    @abstractmethod
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
        """Generate output validated against a Pydantic model.

        Args:
            prompt: Instruction plus data.
            response_model: The schema to validate against.
            task: Recorded in the run metadata.
            model: Model override.
            analysis_source: Grounding of the prompt.
            system: Optional system prompt.
            temperature: Per-call override.
            options: Provider-specific options.
            prompt_version: Prompt version.

        Raises:
            ProviderUnavailableError: Not reachable.
            ProviderTimeoutError: Timed out.
            AIProviderError: The model returned output that does not match
                ``response_model``. The invalid output is never coerced into
                something plausible.
        """

    @abstractmethod
    def embed(
        self,
        texts: list[str],
        *,
        model: Optional[str] = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> EmbeddingResult:
        """Return embeddings for ``texts``.

        Raises:
            ProviderUnavailableError: Not reachable.
            AIProviderError: The model does not support embeddings.
        """

    # -- shared helpers ------------------------------------------------------
    def _start_run(
        self,
        *,
        model: str,
        task: ModelRunTask,
        prompt: str,
        analysis_source: AnalysisSource,
        prompt_version: str,
        temperature: Optional[float],
    ) -> ModelRun:
        return ModelRun.start(
            provider=self.name,
            model=model,
            task=task,
            prompt=prompt,
            analysis_source=analysis_source,
            prompt_version=prompt_version,
            temperature=temperature,
        )

    @staticmethod
    def _parse_structured(
        raw: str, response_model: Type[T]
    ) -> tuple[Optional[T], Optional[str]]:
        """Parse model output into ``response_model``.

        Tries a bare JSON parse, then the contents of the first fenced code
        block, then the first balanced JSON object. Returns ``(model, error)``
        where exactly one is ``None``.

        Does not invent fields and does not coerce types: a mismatch is
        reported so the caller can retry or degrade to ``UNKNOWN``.
        """
        candidates = [raw.strip()]

        if "```" in raw:
            block = raw.split("```")
            for index in range(1, len(block), 2):
                segment = block[index]
                if segment.lower().startswith("json"):
                    segment = segment[4:]
                candidates.append(segment.strip())

        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            candidates.append(raw[start : end + 1])

        for candidate in candidates:
            if not candidate:
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            try:
                return response_model.model_validate(payload), None
            except ValidationError as exc:
                return None, f"output did not match {response_model.__name__}: {exc.error_count()} error(s)"

        return None, "output was not valid JSON"
