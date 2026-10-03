"""Application status payloads.

The shape mirrors ``Assistant.status()`` and
``AssistantSettings.redacted_summary()`` rather than restating them. Duplicating
those structures here would create a second definition that drifts the moment a
setting is added.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai.registry import available_providers
from core.enums import SourceMode

__all__ = [
    "SafetyReport",
    "DatabaseReport",
    "AiStatusReport",
    "ApiStatusReport",
]


class _DictModel(BaseModel):
    """Accepts the assistant's own dict output verbatim.

    ``extra="allow"`` is correct here: the source is a trusted internal report,
    and forbidding unknown keys would mean editing this file every time a
    setting is added.
    """

    model_config = ConfigDict(extra="allow")


class SafetyReport(_DictModel):
    """Safety configuration as the policy object reports it.

    Read-only. No route writes safety settings; they are server-side only.
    """

    dry_run: bool = True
    safe_mode: bool = True
    require_human_approval: bool = True
    allow_final_submission: bool = False


class DatabaseReport(_DictModel):
    """SQLite location and per-table row counts."""

    path: str
    tables: list[str] = Field(default_factory=list)
    profiles: int = Field(default=0, ge=0)
    resumes: int = Field(default=0, ge=0)
    evidence: int = Field(default=0, ge=0)
    model_runs: int = Field(default=0, ge=0)
    jobs: int = Field(default=0, ge=0)
    queued_for_review: int = Field(default=0, ge=0)
    open_reviews: int = Field(default=0, ge=0)


class AiStatusReport(BaseModel):
    """What AI is configured to do, and what is actually usable.

    ``configured`` reflects settings. ``embedding_scorer_available`` is computed
    from the provider's own ``supports_embeddings`` flag. Neither claims the
    provider answered a request, because nothing here contacts a model — an
    endpoint that probed the network on every status poll would make the
    boundary harder to run offline and would report latency as health.
    """

    model_config = ConfigDict(extra="forbid")

    configured: bool
    provider: str
    model: str
    api_key_present: bool
    providers_available: list[str] = Field(default_factory=list)
    embedding_scorer_available: bool
    source_mode: SourceMode
    allows_application: bool


class ApiStatusReport(BaseModel):
    """The whole system in one document."""

    model_config = ConfigDict(extra="forbid")

    service: str
    version: str
    safety: SafetyReport
    paths: dict[str, Any]
    database: DatabaseReport
    configuration: dict[str, Any]
    ai: AiStatusReport