"""Content hashing and clock helpers.

Hashes are used for three distinct jobs and must not be conflated:

* ``sha256_file`` / ``sha256_bytes`` - identity of resume content, used for
  duplicate detection.
* ``sha256_text`` - short stable id for values embedded in JSON, used by the
  profile template.
* ``input_hash`` in a :class:`ModelRun` - a hash of the AI input so a run can
  be compared later without storing the sensitive payload itself.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from core.errors import ConfigurationError

__all__ = [
    "sha256_bytes",
    "sha256_text",
    "sha256_file",
    "short_hash",
    "utc_now",
    "parse_iso_date",
    "parse_iso_datetime",
    "ensure_utc",
]

_HASH_READ_CHUNK = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Return the hex SHA-256 digest of ``text`` encoded as UTF-8."""
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path | str) -> str:
    """Stream ``path`` through SHA-256 and return the hex digest.

    Streaming keeps memory flat for large files. The file is read, never
    written or moved.
    """
    target = Path(path)
    if not target.is_file():
        raise ConfigurationError("cannot hash missing file", path=str(target))
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        while chunk := handle.read(_HASH_READ_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def short_hash(text: str, length: int = 12) -> str:
    """Return a truncated, URL-safe digest for embedding in ids.

    Args:
        text: Value to digest.
        length: Number of hex characters to keep.

    Raises:
        ConfigurationError: If ``length`` is not positive.
    """
    if length <= 0:
        raise ConfigurationError("short_hash length must be positive", length=length)
    digest = sha256_text(text)
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24]
    return f"{slug}-{digest[:length]}" if slug else digest[:length]


def utc_now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Attach UTC to a naive datetime, or convert an aware one to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_iso_date(value: Any) -> date | None:
    """Parse ``YYYY-MM-DD`` or a full ISO timestamp into a :class:`date`.

    Returns ``None`` for unparseable input rather than raising, because this
    helper is used by the validator, whose job is to *report* bad data. A
    partially specified date such as ``2019`` or ``2019-06`` is accepted and
    resolved to the first day of the period.

    Raises:
        ConfigurationError: If the value is not a string, number, or date.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value).date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        raise ConfigurationError("numeric dates are ambiguous", value=str(value))
    if not isinstance(value, str):
        raise ConfigurationError("cannot parse date", value_type=type(value).__name__)

    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Deliberate format probing: each attempt is allowed to fail and the next is
    # tried. ValueError is the control signal here, so it is caught by name and
    # the reason is recorded rather than swallowed silently.
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass  # not a bare date; try a full datetime
    try:
        return ensure_utc(datetime.fromisoformat(text)).date()
    except ValueError:
        pass  # not an ISO datetime either; fall through to the loose formats
    # Each format is paired with the day to use when the text does not carry
    # one: "2026" means January, everything else means the first of the month.
    for fmt, default_day in (("%Y-%m", 1), ("%Y", 1), ("%m/%Y", 1), ("%b %Y", 1)):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return date(parsed.year, parsed.month, default_day)
    return None


def parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp into an aware UTC datetime, or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return ensure_utc(datetime.fromisoformat(text))
    except ValueError:
        return None
