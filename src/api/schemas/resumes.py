"""Resume request and response models.

``Resume`` comes from ``resumes.models``. The only new types are the ingestion
request and small response wrappers.

The ingestion request carries the parameters
:meth:`resumes.service.ResumeService.ingest` already accepts and nothing else —
in particular no way to mark something synthetic for real use, because that flag
exists so test data is never mistaken for real data and letting an HTTP caller
set it would defeat the purpose.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from resumes.models import Resume

__all__ = [
    "ResumeIngestRequest",
    "ResumeResponse",
    "ResumeListResponse",
    "ResumeSectionsResponse",
    "ResumeVariantsResponse",
    "DuplicateCheckResponse",
]


class ResumeIngestRequest(BaseModel):
    """Ingest one already-present resume file.

    ``path`` is a server-side path, never an upload. The boundary has no
    multipart endpoint: accepting an uploaded file would put file handling,
    temp-file lifetime, and size limits on the HTTP layer, all of which the
    parser and the safety policy already own.
    """

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4_000)
    variant: Optional[str] = Field(default=None, max_length=200)
    role_focus: Optional[str] = Field(default=None, max_length=200)
    skills: Optional[list[str]] = Field(default=None, max_length=200)
    version: Optional[str] = Field(default=None, max_length=64)
    allow_duplicate: bool = Field(
        default=False,
        description="Return the existing record instead of a 409 when the content hash already exists.",
    )


class ResumeResponse(BaseModel):
    """One stored resume."""

    model_config = ConfigDict(extra="forbid")

    resume: Resume


class ResumeListResponse(BaseModel):
    """Stored resumes, in the repository's own order."""

    model_config = ConfigDict(extra="forbid")

    resumes: list[Resume] = Field(default_factory=list)
    count: int = Field(default=0, ge=0)


class ResumeSectionsResponse(BaseModel):
    """The candidate's section index, grouped by section type.

    ``by_section_type`` mirrors the repository's ``dict[str, list[dict]]``
    rather than being re-grouped here. The grouping is part of what the index
    means, so reshaping it at the boundary would produce a second answer to a
    question the repository already answers.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    by_section_type: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    section_types: list[str] = Field(default_factory=list)


class ResumeVariantsResponse(BaseModel):
    """Variant labels stored for the candidate."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    variants: list[str] = Field(default_factory=list)
    count: int = Field(default=0, ge=0)


class DuplicateCheckResponse(BaseModel):
    """Whether a content hash is already stored."""

    model_config = ConfigDict(extra="forbid")

    file_hash: str
    is_duplicate: bool
    existing_resume_id: Optional[str] = None
    existing_filename: Optional[str] = None