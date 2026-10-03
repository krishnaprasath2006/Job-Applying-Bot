"""Candidate profile: domain model, template, validation, persistence.

``profile.models`` and ``profile.validator`` are the domain layer and depend on
nothing but ``core``. ``profile.service`` is the application layer and depends
on the database layer.

``ProfileService`` is therefore exported lazily via PEP 562 rather than eagerly.
Importing it at module scope would create a cycle:

    profile/__init__ -> profile.service -> database.repositories
      -> database/repositories/__init__ -> profiles -> profile.models -> profile/__init__

The names below keep working; only the import timing changed.
"""

from typing import TYPE_CHECKING, Any

from profile.models import CandidateProfile, build_empty_profile, with_fact_update
from profile.validator import (
    REQUIRED_FOR_APPLICATION,
    CandidateProfileValidator,
    ValidationIssue,
    ValidationReport,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from profile.service import ProfileService

__all__ = [
    "CandidateProfile",
    "CandidateProfileValidator",
    "ProfileService",
    "REQUIRED_FOR_APPLICATION",
    "ValidationIssue",
    "ValidationReport",
    "build_empty_profile",
    "with_fact_update",
]

_LAZY = {"ProfileService": "profile.service"}


def __getattr__(name: str) -> Any:
    """Resolve application-layer exports on first access (PEP 562)."""
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted(__all__)
