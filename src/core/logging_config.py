"""Structured logging.

Log records carry ``component``, ``event``, ``level``, ``duration_ms``, and
arbitrary key/value context. Values are redacted on the way out, so a
structured log can include useful context without becoming a place where
secrets accumulate.

Three formats are supported:

* ``json`` - one JSON object per line, for machines.
* ``text`` - human readable, still structured.
* ``silent`` - no output. The default for test runs and library import.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from core.redaction import REDACTOR, RedactingFilter

__all__ = ["configure_logging", "get_logger", "log_event", "JsonFormatter", "TextFormatter"]

_RESERVED = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
    | {"message", "asctime", "taskName"}
)


class JsonFormatter(logging.Formatter):
    """Render each record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "component": getattr(record, "component", record.name),
            "event": getattr(record, "event", record.msg),
            "logger": record.name,
        }
        duration = getattr(record, "duration_ms", None)
        if duration is not None:
            payload["duration_ms"] = duration
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload["context"] = context
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(REDACTOR.scrub_mapping(payload), default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable line that keeps the same structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} "
            f"{getattr(record, 'component', record.name):<12} "
            f"{getattr(record, 'event', record.msg)}"
        )
        duration = getattr(record, "duration_ms", None)
        if duration is not None:
            base += f" ({duration}ms)"
        context = getattr(record, "context", None)
        if isinstance(context, dict) and context:
            rendered = " ".join(
                f"{k}={v!r}" for k, v in sorted(REDACTOR.scrub_mapping(context).items())
            )
            base += f" | {rendered}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return REDACTOR.scrub(base)


class _StructuredLogger(logging.LoggerAdapter):
    """Logger adapter that injects ``component`` into every record."""

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        extra = dict(self.extra or {})
        extra.update(kwargs.pop("extra", None) or {})
        kwargs["extra"] = extra
        return msg, kwargs


def configure_logging(
    level: str = "INFO",
    fmt: str = "json",
    *,
    stream: Any = None,
    propagate: bool = False,
) -> logging.Logger:
    """Install a redacting handler on the ``assistant`` logger tree.

    Args:
        level: Minimum level name.
        fmt: ``json``, ``text``, or ``silent``.
        stream: Output stream; defaults to stdout.
        propagate: Whether records also reach the root logger.

    Returns:
        The configured root ``assistant`` logger.

    Raises:
        ValueError: If ``fmt`` is not a supported format.
    """
    logger = logging.getLogger("assistant")
    logger.handlers.clear()
    logger.propagate = propagate

    if fmt == "silent":
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.CRITICAL + 1)
        return logger

    if fmt not in ("json", "text"):
        raise ValueError(f"unsupported log format {fmt!r}; use json, text or silent")

    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger


def get_logger(component: str, **context: Any) -> logging.LoggerAdapter:
    """Return a structured logger tagged with a component name.

    Args:
        component: Dotted module path or short name, e.g. ``"profile.service"``.
        **context: Default context merged into every record.

    Returns:
        A logger adapter. Call ``.event("name", context={...})`` via
        :func:`log_event`, or use normal logging methods.
    """
    return _StructuredLogger(logging.getLogger("assistant"), {"component": component, **context})


def log_event(
    logger: logging.LoggerAdapter,
    event: str,
    *,
    level: int = logging.INFO,
    duration_ms: int | None = None,
    **context: Any,
) -> None:
    """Emit one structured event.

    Args:
        logger: Adapter from :func:`get_logger`.
        event: Stable event name, e.g. ``"resume.ingested"``.
        level: Logging level.
        duration_ms: Operation duration, included when given.
        **context: Structured context. Redacted before output.
    """
    extra: dict[str, Any] = {"event": event, "context": context}
    if duration_ms is not None:
        extra["duration_ms"] = duration_ms
    logger.log(level, event, extra=extra)


def sanitize_context(context: dict[str, Any]) -> dict[str, Any]:
    """Drop reserved logging attributes from a context dict."""
    return {k: v for k, v in context.items() if k not in _RESERVED}
