"""Audit events.

A closed vocabulary of things worth recording, plus a typed helper that writes
them as structured logs. Events are named ``<component>.<past-tense-verb>`` so
they group naturally and are easy to filter.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from core.logging_config import get_logger, log_event
from core.model_run import ModelRun

__all__ = ["AuditEvent", "emit", "log_model_run"]


class AuditEvent(str, Enum):
    """Events the assistant records.

    These are the moments that matter later when someone asks "why does it
    think that?" or "what happened at 3pm?".
    """

    PROFILE_CREATED = "profile.created"
    PROFILE_FACT_UPDATED = "profile.fact_updated"
    PROFILE_VALIDATED = "profile.validated"
    PROFILE_IMPORTED = "profile.imported"

    RESUME_INGESTED = "resume.ingested"
    RESUME_DUPLICATE_DETECTED = "resume.duplicate_detected"
    RESUME_PARSE_FAILED = "resume.parse_failed"
    RESUME_DELETED = "resume.deleted"

    DATABASE_INITIALIZED = "database.initialized"
    MIGRATION_APPLIED = "database.migration_applied"

    AI_HEALTH_CHECK = "ai.health_check"
    AI_GENERATE_TEXT = "ai.generate_text"
    AI_GENERATE_STRUCTURED = "ai.generate_structured"
    AI_EMBED = "ai.embed"
    AI_CALL_FAILED = "ai.call_failed"

    SAFETY_BLOCKED = "safety.blocked"
    SAFETY_VIOLATION = "safety.violation"


def emit(event: AuditEvent | str, **context: Any) -> None:
    """Write one audit event as a structured log record.

    Context is redacted before it reaches the handler, so passing a credential
    by mistake is survivable.
    """
    log_event(get_logger("audit"), str(event), **context)


def log_model_run(run: ModelRun, **context: Any) -> None:
    """Record a model run.

    Only metadata is included. The prompt body is not logged, because prompts
    for this project contain resume text.
    """
    emit(
        AuditEvent.AI_GENERATE_TEXT,
        run_id=run.id,
        provider=run.provider,
        model=run.model,
        task=run.task.value,
        status=run.status.value,
        analysis_source=run.analysis_source.value,
        prompt_version=run.prompt_version,
        input_chars=run.input_chars,
        output_chars=run.output_chars,
        latency_ms=run.latency_ms,
        **context,
    )
