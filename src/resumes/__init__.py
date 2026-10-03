"""Resume ingestion: parsing, hashing, storage, retrieval.

``resumes.models``, ``resumes.hashing``, and ``resumes.parser`` are the domain
layer. ``resumes.service`` depends on the database layer, so it is exported
lazily via PEP 562 to keep the package import acyclic.
"""

from typing import TYPE_CHECKING, Any

from resumes.hashing import (
    DuplicateCheck,
    detect_file_type,
    ensure_ingestable,
    hash_file,
    hash_text,
)
from resumes.models import Resume, ResumeSection
from resumes.parser import ResumeParser, extract_text

if TYPE_CHECKING:  # pragma: no cover - typing only
    from resumes.service import ResumeService

__all__ = [
    "DuplicateCheck",
    "Resume",
    "ResumeParser",
    "ResumeSection",
    "ResumeService",
    "detect_file_type",
    "ensure_ingestable",
    "extract_text",
    "hash_file",
    "hash_text",
]

_LAZY = {"ResumeService": "resumes.service"}


def __getattr__(name: str) -> Any:
    """Resolve application-layer exports on first access (PEP 562)."""
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted(__all__)
