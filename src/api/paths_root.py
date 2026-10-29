# """Runtime path resolution with ASSISTANT_DESKTOP_DATA_ROOT support.
#
# This module extends the canonical ``src.core.paths.Paths`` with Windows data
# root mapping via the ``ASSISTANT_DESKTOP_DATA_ROOT`` environment variable.
#
# When ``ASSISTANT_DESKTOP_DATA_ROOT`` is set, all data paths (database,
# profile, resume, logs, exports) are rooted under it, allowing the application
# to operate in per-user or per-machine directories on Windows without hardcoding
# paths.
#
# When unset, existing behaviour is preserved: paths are resolved relative to
# the project root detected from ``src/core/paths.py``.
#"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from core.errors import ConfigurationError
from core.paths import Paths, get_paths, reset_paths, _CACHE, set_data_root


def load_paths_with_data_root(
    root: Optional[Path] = None,
    data_root_env: str = 'ASSISTANT_DESKTOP_DATA_ROOT',
    test_env: Optional[dict[str, str]] = None,
) -> Paths:
    """Return :class:`Paths` respecting ``ASSISTANT_DESKTOP_DATA_ROOT``.

    Args:
        root: Optional project root. If ``None``, the default detector is used.
        data_root_env: Environment variable name that contains the Windows data
            root. Defaults to ``ASSISTANT_DESKTOP_DATA_ROOT``.
        test_env: Optional environment dict for testing (overrides os.environ).

    Returns:
        A :class:`Paths` instance with data paths mapped under the data root
        when the environment variable is set.

    Example:
        >>> paths = load_paths_with_data_root()
        >>> paths.db
        PosixPath('/data/assistant.db')  # when ASSISTANT_DESKTOP_DATA_ROOT is set
    """
    # Determine the data root value: use test_env if provided, otherwise os.environ
    env = test_env or os.environ
    data_root_str = env.get(data_root_env)
    if data_root_str:
        set_data_root(Path(data_root_str))
    else:
        set_data_root(None)

    if root is not None:
        return Paths(root)
    return get_paths()


def get_paths_root() -> dict[str, str]:
    """Return every path as a string, respecting ASSISTANT_DESKTOP_DATA_ROOT.

    Compatible with the ``describe()`` interface from ``core.paths.Paths``.
    """
    paths = load_paths_with_data_root()

    return {
        'root': str(paths.root),
        'data': str(paths.data),
        'profile_dir': str(paths.profile_dir),
        'resume_dir': str(paths.resume_dir),
        'db': str(paths.db),
        'logs': str(paths.logs),
        'exports': str(paths.exports),
    }


# Module-level convenience: when this module is imported directly (e.g. from
# Tauri Rust side), provide a cached instance keyed by the data root path.
_INSTANCE_CACHE: dict[str, Paths] = {}


def get_cached_paths(root: Optional[Path] = None) -> Paths:
    """Cache :class:`Paths` instances keyed by resolved root path."""
    key = str(root) if root else 'default'
    if key not in _INSTANCE_CACHE:
        _INSTANCE_CACHE[key] = load_paths_with_data_root(root)
    return _INSTANCE_CACHE[key]


def reset_cached_paths() -> None:
    """Drop the per-root cache. Used by tests and restarts."""
    global _INSTANCE_CACHE
    _INSTANCE_CACHE = {}
    reset_paths()


def detect_root_with_data_root(data_root: str) -> Path | None:
    """Detect the project root mapped under the given data root string.

    Args:
        data_root: Path string for the Windows data root.

    Returns:
        The project root Path if the data root directory exists, else None.
    """
    p = Path(data_root)
    if p.is_dir():
        # Return the detected project root (from config.py parent walk)
        # mapped under this data root - for simplicity, return the data root itself
        # as the base, and the caller can derive project-relative paths from it.
        return p if p.is_dir() else None
    return None


# Provide camelCase alias for test compatibility
detectRootWithDataRoot = detect_root_with_data_root  # type: ignore[name-defined]