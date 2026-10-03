"""Repositories for the Phase 2 tables.

Only what Phase 2 uses is present. Job, application, and question-memory
repositories arrive with the phases that need them, so there are no empty
classes standing in for future work.

Imports are lazy via PEP 562. ``profiles`` and ``resumes`` reach into the domain
packages, and those packages re-export application-layer modules, so eager
imports here would close the cycle.
"""

from typing import Any

from database.repositories.base import BaseRepository, new_id
from database.repositories.documents import DocumentRepository, EvidenceRepository
from database.repositories.model_runs import ModelRunRepository

__all__ = [
    "BaseRepository",
    "DocumentRepository",
    "EvidenceRepository",
    "ModelRunRepository",
    "ProfileRepository",
    "ResumeRepository",
    "classify_actor",
    "new_id",
]

_LAZY = {
    "ProfileRepository": "database.repositories.profiles",
    "ResumeRepository": "database.repositories.resumes",
    "classify_actor": "database.repositories.profiles",
}


def __getattr__(name: str) -> Any:
    """Resolve domain-coupled exports on first access (PEP 562)."""
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted(__all__)
