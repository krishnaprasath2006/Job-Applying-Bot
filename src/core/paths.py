"""Filesystem path resolution for the assistant.

All runtime paths derive from a single project root so the package works on
Windows, Linux, and in containers without scattered ``Path("data")`` literals
that silently resolve to different directories depending on the working
directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.errors import ConfigurationError

__all__ = ["Paths", "get_paths", "reset_paths", "set_data_root", "get_data_root"]


class Paths:
    """Resolved locations for every file the assistant reads or writes.

    Attributes:
        root: Project root (the directory containing ``src``).
        data: Root of the tracked-by-default data directory.
        profile_dir: Candidate profile JSON files.
        resume_dir: Ingested resume originals and extracted text.
        db: SQLite database file.
        logs: Structured log output.
        exports: Derived JSON exports (may contain personal data).
    """

    def __init__(self, root: Path | None = None, data_root: Optional[Path] = None) -> None:
        detected = root if root is not None else self._detect_root()
        if not detected.is_dir():
            raise ConfigurationError("project root does not exist", root=str(detected))
        self.root = detected.resolve()
        # Use explicit data root if provided, otherwise fall back to global data root
        if data_root is not None and data_root.is_dir():
            self.data = data_root
        elif _DATA_ROOT is not None and _DATA_ROOT.is_dir():
            self.data = _DATA_ROOT
        else:
            self.data = self.root / "data"
        self.profile_dir = self.data / "profile"
        self.resume_dir = self.data / "resumes"
        self.logs = self.data / "logs"
        self.exports = self.data / "exports"

    @staticmethod
    def _detect_root() -> Path:
        """Walk up from this file until the project root is found.

        ``src/core/paths.py`` -> ``src/core`` -> ``src`` -> project root.
        Falls back to the current working directory so a packaged install
        does not crash on import.
        """
        here = Path(__file__).resolve()
        for parent in here.parents:
            if (parent / "src").is_dir() and (parent / "config.py").is_file():
                return parent
        return Path.cwd()

    @property
    def db(self) -> Path:
        return self.data / "assistant.db"

    @property
    def candidate_profile(self) -> Path:
        return self.profile_dir / "candidate_profile.json"

    @property
    def candidate_profile_example(self) -> Path:
        return self.profile_dir / "candidate_profile.example.json"

    def ensure_runtime_dirs(self) -> None:
        """Create writable directories.

        Called by the CLI and by repositories. Never called at import time so
        that merely importing the package cannot touch the filesystem.
        """
        for directory in (self.data, self.profile_dir, self.resume_dir, self.logs):
            directory.mkdir(parents=True, exist_ok=True)

    def describe(self) -> dict[str, str]:
        """Return every path as a string, for logging and diagnostics."""
        return {
            "root": str(self.root),
            "data": str(self.data),
            "profile_dir": str(self.profile_dir),
            "resume_dir": str(self.resume_dir),
            "db": str(self.db),
            "logs": str(self.logs),
            "exports": str(self.exports),
        }


_CACHE: type[Paths] | None = None
_DATA_ROOT: Optional[Path] = None


def get_data_root() -> Optional[Path]:
    """Return the currently configured data root, or ``None``."""
    return _DATA_ROOT


def set_data_root(data_root: Optional[Path] = None) -> None:
    """Set the data root for path resolution.

    When ``data_root`` is provided, all data paths (``data``, ``profile_dir``,
    ``resume_dir``, ``logs``, ``exports``) will be rooted under it, allowing
    the application to operate in per-user or per-machine directories on Windows
    via the ``ASSISTANT_DESKTOP_DATA_ROOT`` environment variable.

    When ``data_root`` is ``None``, the default behaviour is restored: paths are
    resolved relative to the project root detected from ``src/core/paths.py``.

    This function does not create directories or modify files. It only configures
    the path resolution logic. Runtime directories are created only through
    ``Paths.ensure_runtime_dirs()``.

    Args:
        data_root: Optional path to set as the data root. When ``None``, the
            default behaviour is restored.
    """
    global _DATA_ROOT, _CACHE
    _DATA_ROOT = data_root
    _CACHE = None  # Reset cache so next get_paths() call uses new settings


def reset_paths() -> None:
    """Drop the cache. Used by tests that redirect the project root."""
    global _CACHE
    _CACHE = None


def get_paths(root: Path | None = None) -> Paths:
    """Return the cached :class:`Paths` for this process.

    If an explicit ``root`` is given, a new ``Paths(root)`` is returned
    (ignoring the configured data root). Otherwise the cached instance is
    returned if available, otherwise a new ``Paths`` is created with the
    currently configured data root.
    """
    global _CACHE, _DATA_ROOT
    # If an explicit root is given, use it (ignoring the data root setting)
    if root is not None:
        return Paths(root)
    # If cache is populated, return it
    if _CACHE is not None:
        return _CACHE
    # Otherwise create new Paths with the configured data root
    _CACHE = Paths(data_root=_DATA_ROOT)
    return _CACHE


# Convenience: camelCase alias for test compatibility
setDataRoot = set_data_root  # type: ignore[name-defined]


def get_data_root() -> Optional[Path]:
    """Return the currently configured data root, or ``None``."""
    return _DATA_ROOT
