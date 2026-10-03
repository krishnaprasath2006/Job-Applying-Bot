"""Model-run metadata.

Every AI call is recorded so that later phases can answer "where did this
artefact come from". Two rules are enforced here rather than left to callers:

* No secrets. There is deliberately no field for an API key, token, or
  credential, so there is nothing to leak.
* Sensitive inputs are stored as hashes and counts. The prompt body itself is
  never persisted by default; ``prompt_preview`` is opt-in and truncated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.enums import AnalysisSource, ModelRunStatus, ModelRunTask
from core.hashing import sha256_text, utc_now

__all__ = ["ModelRun", "PROMPT_VERSION"]

PROMPT_VERSION = "phase2-v1"

_PREVIEW_LIMIT = 280


class ModelRun(BaseModel):
    """One recorded AI invocation.

    Attributes:
        id: Deterministic-ish run identifier.
        provider: Provider key, e.g. ``ollama``.
        model: Model name exactly as configured. Never hardcoded in business
            logic.
        prompt_version: Version of the prompt used, so results can be
            compared like-for-like after a prompt change.
        task: What the call was for.
        input_hash: SHA-256 of the input, for comparison without storage.
        input_chars: Size of the input, useful for spotting truncation.
        output_hash: SHA-256 of the output.
        output_chars: Size of the output.
        analysis_source: Whether the output was grounded in job data,
            candidate data, user input, or general model knowledge. This is
            the field that prevents an ungrounded generation from being filed
            as a grounded one.
        created_at: When the run happened.
        latency_ms: Wall-clock duration.
        status: Outcome.
        error: Short, redacted failure description when ``status != SUCCESS``.
        temperature / options: Generation settings, no credentials.
        prompt_preview: Opt-in, truncated, never the full prompt.
        token counts: Populated when the provider reports them.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"run_{utc_now().strftime('%Y%m%dT%H%M%S%f')}")
    provider: str
    model: str
    prompt_version: str = PROMPT_VERSION
    task: ModelRunTask
    input_hash: str = Field(description="SHA-256 of the input payload.")
    input_chars: int = Field(default=0, ge=0)
    output_hash: Optional[str] = None
    output_chars: Optional[int] = Field(default=None, ge=0)
    analysis_source: AnalysisSource = AnalysisSource.AI_GENERAL
    created_at: datetime = Field(default_factory=utc_now)
    latency_ms: Optional[int] = Field(default=None, ge=0)
    status: ModelRunStatus = ModelRunStatus.SUCCESS
    error: Optional[str] = Field(default=None, max_length=500)
    temperature: Optional[float] = None
    prompt_preview: Optional[str] = Field(default=None, max_length=_PREVIEW_LIMIT)
    prompt_tokens: Optional[int] = Field(default=None, ge=0)
    completion_tokens: Optional[int] = Field(default=None, ge=0)
    model_run_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-sensitive provider metadata (finish reason, model digest).",
    )

    @field_validator("id", mode="before")
    @classmethod
    def _normalise_id(cls, value: Any) -> str:
        """Accept an explicit id, or generate a timestamped one for ``None``."""
        if value:
            return str(value)
        return f"run_{utc_now().strftime('%Y%m%dT%H%M%S%f')}"

    @field_validator("prompt_preview")
    @classmethod
    def _clamp_preview(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        collapsed = " ".join(value.split())
        return collapsed[:_PREVIEW_LIMIT]

    @field_validator("error")
    @classmethod
    def _collapse_error(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return " ".join(value.split())[:500]

    @field_validator("model_run_metadata")
    @classmethod
    def _reject_secret_shaped_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        banned = ("key", "token", "secret", "password", "cookie", "auth")
        for k in value:
            if any(marker in k.lower() for marker in banned):
                raise ValueError(
                    f"model_run_metadata may not contain credential-shaped key {k!r}"
                )
        return value

    @classmethod
    def start(
        cls,
        *,
        provider: str,
        model: str,
        task: ModelRunTask,
        prompt: str,
        analysis_source: AnalysisSource,
        prompt_version: str = PROMPT_VERSION,
        temperature: float | None = None,
        record_preview: bool = False,
    ) -> "ModelRun":
        """Create a run record for an about-to-be-made call.

        Records only the input hash and length. The prompt body is kept out of
        the database unless ``record_preview`` is explicitly set.
        """
        return cls(
            provider=provider,
            model=model,
            task=task,
            input_hash=sha256_text(prompt),
            input_chars=len(prompt),
            analysis_source=analysis_source,
            prompt_version=prompt_version,
            temperature=temperature,
            prompt_preview=prompt if record_preview else None,
        )

    def complete(self, output: str, latency_ms: int) -> "ModelRun":
        """Return a copy marked successful with the output hashed."""
        self.output_hash = sha256_text(output)
        self.output_chars = len(output)
        self.latency_ms = latency_ms
        self.status = ModelRunStatus.SUCCESS
        self.error = None
        return self

    def fail(self, error: str, status: ModelRunStatus = ModelRunStatus.FAILED) -> "ModelRun":
        """Return a copy marked failed with a redacted error description."""
        self.status = status
        self.error = error
        return self
