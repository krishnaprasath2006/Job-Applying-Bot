"""Secret redaction for logs.

A logging filter is the last line of defence for the rule "passwords,
cookies, API keys, and session tokens must never be logged". It scrubs
values that are registered as secrets plus anything that looks like a
credential, so a careless ``logger.debug(payload)`` still cannot leak.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

__all__ = ["SecretRedactor", "register_secret", "redact", "MASK"]

MASK = "***REDACTED***"

# Keys whose values are masked whenever they appear in structured log context.
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(pass(word|wd)?|secret|token|api[_-]?key|cookie|session[_-]?id|authorization|bearer|"
    r"auth|credential|private[_-]?key|access[_-]?key|refresh[_-]?token|otp|mfa|2fa)",
    re.IGNORECASE,
)

# Inline shapes that are credentials regardless of the key they hang off.
_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
    re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[baprs])-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bli_li_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)

# "password=hunter2" inside free-form message text. Structured context is
# already handled key-by-key, but a message can carry the same leak in prose
# ("retrying with token=..."), and by the time it reaches the formatter the
# value is indistinguishable from any other word.
_INLINE_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<key>" + _SENSITIVE_KEY_PATTERN.pattern + r")(?P<sep>\s*[=:]\s*)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|\S+)",
    re.IGNORECASE,
)


class SecretRedactor:
    """Holds known secret values and scrubs them from log output."""

    def __init__(self, extra_patterns: Iterable[re.Pattern[str]] = ()) -> None:
        self._literals: set[str] = set()
        self._extra = list(extra_patterns)

    def register(self, secret: Any) -> None:
        """Remember a literal secret value so it can never be logged."""
        if secret is None:
            return
        text = str(secret)
        # Very short values would mask harmless text everywhere.
        if len(text) >= 4:
            self._literals.add(text)

    def register_many(self, secrets: Iterable[Any]) -> None:
        for secret in secrets:
            self.register(secret)

    def unregister_all(self) -> None:
        """Forget every registered literal. Used by tests."""
        self._literals.clear()

    def scrub(self, text: str) -> str:
        """Replace every registered literal and credential-shaped pattern."""
        if not text:
            return text
        result = text
        for literal in sorted(self._literals, key=len, reverse=True):
            if literal in result:
                result = result.replace(literal, MASK)
        for pattern in (*_VALUE_PATTERNS, *self._extra):
            result = pattern.sub(MASK, result)
        result = _INLINE_ASSIGNMENT_PATTERN.sub(
            lambda m: f"{m.group('key')}{m.group('sep')}{MASK}", result
        )
        return result

    def scrub_mapping(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of ``context`` with sensitive keys and values masked."""
        cleaned: dict[str, Any] = {}
        for key, value in context.items():
            if _SENSITIVE_KEY_PATTERN.search(str(key)):
                cleaned[key] = MASK
                continue
            cleaned[key] = self._scrub_value(value)
        return cleaned

    def _scrub_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return self.scrub_mapping(value)
        if isinstance(value, (list, tuple)):
            return [self._scrub_value(item) for item in value]
        if isinstance(value, str):
            return self.scrub(value)
        return value


#: Process-wide redactor. Populated by config loading with any credentials
#: read from the environment.
REDACTOR = SecretRedactor()


def register_secret(secret: Any) -> None:
    """Register a literal secret with the process-wide redactor."""
    REDACTOR.register(secret)


def redact(text: str) -> str:
    """Scrub ``text`` with the process-wide redactor."""
    return REDACTOR.scrub(text)


class RedactingFilter(logging.Filter):
    """Logging filter that scrubs the formatted message and arguments.

    Applied to every handler by :func:`core.logging_config.configure_logging`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = REDACTOR.scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = REDACTOR.scrub_mapping(record.args)
            else:
                record.args = tuple(
                    REDACTOR.scrub_mapping({"v": a})["v"] if not isinstance(a, dict)
                    else REDACTOR.scrub_mapping(a)
                    for a in record.args
                )
        return True
