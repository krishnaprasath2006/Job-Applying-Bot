"""Shared response pieces.

Success and failure shapes live here so every route returns the same
structures and the OpenAPI document describes them once.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ErrorBody", "ErrorEnvelope", "CountSummary", "HealthReport", "ReadyReport"]


class ErrorBody(BaseModel):
    """The single error payload.

    ``message`` is human-readable and already redacted; ``details`` holds
    structured context such as which field failed validation or which states a
    lifecycle move was allowed to reach. Neither ever carries a traceback.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Redacted human-readable explanation.")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Structured, reportable context. Never a stack trace."
    )


class ErrorEnvelope(BaseModel):
    """Envelope wrapping :class:`ErrorBody`."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


class CountSummary(BaseModel):
    """A row count with the query that produced it."""

    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=0)
    query: Optional[str] = None


class HealthReport(BaseModel):
    """Liveness. Answers "is this process running", nothing more.

    Deliberately dependency-free: a liveness probe that touches SQLite turns a
    database blip into a container restart loop.
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="``alive`` when the process is serving.")
    service: str
    version: str


class ReadyReport(BaseModel):
    """Readiness. Every field is measured, never assumed.

    ``checks`` reports what was actually exercised. ``sqlite.readable`` means a
    query returned; ``migrations.applied`` means the schema version on disk
    matches the migrations bundled with this code.
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="``ready`` only when every check passed.")
    checks: dict[str, bool]
    migration_version: Optional[str] = Field(
        default=None, description="Count of migrations recorded as applied."
    )
    detail: Optional[str] = None