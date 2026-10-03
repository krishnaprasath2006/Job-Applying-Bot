"""Read-only bridge to the legacy root ``config.py``.

The old bot's configuration stays exactly where it is and stays the source of
truth for the browser run. This module imports it and exposes the values the
assistant needs to reason about compatibility, without ever writing to it and
without importing ``linkedin`` (which would pull in Selenium).

Importing root ``config`` requires the project root on ``sys.path``. That is
arranged by ``assistant.py`` and by ``tests/conftest.py``; if it is missing we
say so clearly instead of raising an opaque ``ModuleNotFoundError``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.errors import ConfigurationError
from core.logging_config import get_logger
from core.paths import get_paths

__all__ = ["LegacySettings", "load_legacy_settings", "legacy_available"]

log = get_logger(__name__)


@dataclass(frozen=True)
class LegacySettings:
    """A read-only snapshot of the legacy configuration.

    Attributes:
        dry_run: The legacy ``dryRun`` flag.
        browser: Preferred legacy browser.
        headless: Legacy headless preference.
        max_applications: Legacy ``maxApplicationsPerRun``.
        search_keywords / search_locations: Legacy search defaults.
        preferences: Legacy preference flags, e.g. ``only_easy_apply``.
        raw: The original module, for anything not modelled above.
    """

    dry_run: bool
    browser: str
    headless: bool
    max_applications: int
    search_keywords: list[str] = field(default_factory=list)
    search_locations: list[str] = field(default_factory=list)
    preferences: dict[str, Any] = field(default_factory=dict)
    raw: Any = None


def _ensure_root_on_path() -> Path:
    root = get_paths().root
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def legacy_available() -> bool:
    """Whether the legacy root ``config`` module can be imported.

    This is a probe, so a failure is reported as ``False`` rather than raised.
    The reason is logged at debug level so a broken legacy module is
    diagnosable instead of silently reporting as unavailable.
    """
    try:
        _ensure_root_on_path()
        import config  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - an import can fail many ways
        log.debug(
            "legacy config module is not importable",
            extra={"legacy": {"error": type(exc).__name__, "detail": str(exc)}},
        )
        return False
    return True


def load_legacy_settings() -> LegacySettings:
    """Import root ``config`` and snapshot the values the assistant needs.

    Raises:
        ConfigurationError: If the legacy module cannot be imported.
    """
    root = _ensure_root_on_path()

    # Import once. Re-importing would hand out a second module object while
    # the legacy ``linkedin``/``utils`` modules still hold the first, and those
    # two copies could then disagree about dry-run status.
    if "config" in sys.modules:
        legacy_config = sys.modules["config"]
    else:
        try:
            import config as legacy_config  # type: ignore[no-redef]
        except Exception as exc:
            raise ConfigurationError(
                "legacy root config.py could not be imported",
                root=str(root),
                cause=str(exc),
            ) from exc

    def _first(value: Any) -> Any:
        """Legacy search terms are lists; take the first for a single value."""
        if isinstance(value, (list, tuple)) and value:
            return value[0]
        return value

    preferences = getattr(legacy_config, "preferences", {}) or {}
    return LegacySettings(
        dry_run=bool(getattr(legacy_config, "dryRun", True)),
        browser=str(getattr(legacy_config, "browser", ("edge",))[0]),
        headless=bool(getattr(legacy_config, "headless", False)),
        max_applications=int(getattr(legacy_config, "maxApplicationsPerRun", 5)),
        search_keywords=list(getattr(legacy_config, "searchKeywords", []) or []),
        search_locations=list(getattr(legacy_config, "searchLocations", []) or []),
        preferences=dict(preferences),
        raw=legacy_config,
    )
