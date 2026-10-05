"""Candidate profile: domain model, template, validation, persistence.

``candidate_profile.models`` and ``candidate_profile.validator`` are the domain
layer and depend on nothing but ``core``. ``candidate_profile.service`` is the
application layer and depends on the database layer.

``ProfileService`` is therefore exported lazily via PEP 562 rather than eagerly.
Importing it at module scope would create a cycle:

    candidate_profile/__init__
      -> candidate_profile.service
      -> database.repositories
      -> database/repositories/__init__
      -> profiles
      -> candidate_profile.models
      -> candidate_profile/__init__

The names below keep working; only the import timing changed.
"""

from typing import TYPE_CHECKING, Any

from candidate_profile.models import CandidateProfile, build_empty_profile, with_fact_update
from candidate_profile.validator import (
    REQUIRED_FOR_APPLICATION,
    CandidateProfileValidator,
    ValidationIssue,
    ValidationReport,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from candidate_profile.service import ProfileService

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

_LAZY = {"ProfileService": "candidate_profile.service"}


def __getattr__(name: str) -> Any:
    """Resolve application-layer exports on first access (PEP 562)."""
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted(__all__)
