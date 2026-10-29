"""Filesystem path resolution for the assistant.

All runtime paths derive from a single project root so the package works on
Windows, Linux, and in containers without scattered ``Path("data")`` literals
that silently resolve to different directories depending on the working
directory.
"""

from __future__ import annotations

from pathlib import Path

from core.errors import ConfigurationError

__all__ = ["Paths", "get_paths", "reset_paths", "set_data_root"]


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

    def __init__(self, root: Path | None = None) -> None:
        detected = root if root is not None else self._detect_root()
        if not detected.is_dir():
            raise ConfigurationError("project root does not exist", root=str(detected))
        self.root = detected.resolve()
        self.data = self.root / "data"
        self.profile_dir = self.data / "profile"
        self.resume_dir = self.data / "resumes"
        self.logs = self.root / "logs"
        self.exports = self.data / "exports"

    @staticmethod
    def _detect_root() -> Path:
        """Walk up from this file until the project root is found.

        ``src/core/paths.py`` -> ``src/core`` -> ``src`` -> project root.
        Falls back to the current working directory so a packaged install does
        not crash on import.
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


_CACHE: Paths | None = None


def get_paths(root: Path | None = None) -> Paths:
    """Return the cached :class:`Paths` for this process."""
    global _CACHE
    if root is not None:
        return Paths(root)
    if _CACHE is None:
        _CACHE = Paths()
    return _CACHE


def reset_paths() -> None:
    """Drop the cache. Used by tests that redirect the project root."""
    global _CACHE
    _CACHE = None


def set_data_root(root: Path) -> None:
    """Set the data root path used by ``get_paths()`` when ``ASSISTANT_DESKTOP_DATA_ROOT`` is active.

    When called, subsequent calls to :func:`get_paths` will return a ``Paths`` instance
    rooted under ``root`` rather than the default project-relative data directory.
    This mirrors the behaviour of the ``ASSISTANT_DESKTOP_DATA_ROOT`` environment variable
    on Windows per-user per-machine directories.

    The ``root`` argument is the path to the data root directory (e.g. the value of
    ``ASSISTANT_DESKTOP_DATA_ROOT``).  After calling this function, ``get_paths()``
    returns a ``Paths`` instance whose ``data``, ``profile_dir``, ``resume_dir``,
    ``db``, ``logs``, and ``exports`` attributes are rooted under ``root`` while the
    ``root`` attribute remains the project root.
    """
    global _CACHE
    # Determine the project root using the same logic as Paths._detect_root
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "src").is_dir() and (parent / "config.py").is_file():
            project_root = parent
            break
    else:
        project_root = Path.cwd()

    # Create a Paths instance with the project root, then override all paths
    paths = Paths(project_root)
    if root is not None:
        paths.data = root / "data"
        paths.profile_dir = root / "profile"
        paths.resume_dir = root / "resumes"
        # logs is under data root
        paths.logs = root / "logs"
        # exports is under data root
        paths.exports = root / "exports"
    else:
        paths.data = project_root / "data"
        paths.profile_dir = project_root / "data" / "profile"
        paths.resume_dir = project_root / "data" / "resumes"
        paths.logs = project_root / "logs"
        paths.exports = project_root / "data" / "exports"

    _CACHE = paths
