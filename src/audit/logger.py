"""Audit logger.

A thin façade over :mod:`core.logging_config` for call sites that are auditing
an action rather than debugging code. Keeps the audit trail in one namespace so
it can be enabled, filtered, or shipped separately later.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from audit.events import AuditEvent, emit, log_model_run
from core.logging_config import configure_logging, get_logger, log_event
from core.model_run import ModelRun

__all__ = [
    "AuditLogger",
    "AuditEvent",
    "configure_logging",
    "emit",
    "get_logger",
    "log_event",
    "log_model_run",
]


class AuditLogger:
    """Records actions with a consistent shape.

    Usage::

        audit = AuditLogger("resume.ingest")
        audit.record("resume.ingested", resume_id=resume.id, chars=1234)
    """

    def __init__(self, component: str = "assistant") -> None:
        self._logger = get_logger(component)

    def record(
        self,
        event: AuditEvent | str,
        *,
        level: int = logging.INFO,
        duration_ms: Optional[int] = None,
        **context: Any,
    ) -> None:
        """Write one structured audit record."""
        log_event(self._logger, str(event), level=level, duration_ms=duration_ms, **context)

    def failure(self, event: AuditEvent | str, error: BaseException, **context: Any) -> None:
        """Record a failure at ERROR level with a short, redacted description."""
        self.record(
            event,
            level=logging.ERROR,
            error_type=type(error).__name__,
            error=str(error)[:300],
            **context,
        )

    def blocked(self, action: str, reason: str, **context: Any) -> None:
        """Record a refusal by a safety policy."""
        self.record(AuditEvent.SAFETY_BLOCKED, level=logging.WARNING, action=action, reason=reason, **context)

    def model_run(self, run: ModelRun, **context: Any) -> None:
        """Record an AI call's metadata."""
        log_model_run(run, **context)

    @property
    def logger(self) -> logging.LoggerAdapter:
        return self._logger
