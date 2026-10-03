"""Resume routes.

Everything here delegates to ``ResumeService``. Parsing, duplicate detection by
content hash, section indexing, and deletion all live there; a route that
re-implemented any of them would be a second implementation that disagrees with
the CLI's.

Two signature details are worth stating, because they are the service's
contract and not this layer's choice:

* ``check_duplicate`` takes a **content hash**, not a path. The boundary does
  not hash a file to answer the question — that is exactly the work
  ``ResumeService`` performs during ingestion, and doing it here would mean two
  places computing what counts as the same content.
* ``section_index`` and ``list_variants`` are keyed by **candidate**, not by
  resume. A section index for one resume is a filter over the candidate's
  index, not a second query with different rules.

There is no file-upload endpoint. The API takes a server-side path, which keeps
"which files may be read" a server-side decision and leaves file handling to the
parser that already handles it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from api.dependencies import AssistantDep, CandidateIdDep
from api.schemas import (
    DuplicateCheckResponse,
    ResumeIngestRequest,
    ResumeListResponse,
    ResumeResponse,
    ResumeSectionsResponse,
    ResumeVariantsResponse,
)
from core.errors import ResumeNotFoundError

router = APIRouter(prefix="/resumes", tags=["resumes"])


@router.get("", response_model=ResumeListResponse, summary="List stored resumes")
def list_resumes(assistant: AssistantDep, candidate_id: CandidateIdDep) -> ResumeListResponse:
    """Every stored resume for this candidate."""
    rows = assistant.resume_service.list_resumes(candidate_id)
    stored = [assistant.resume_service.get_resume(row["id"]) for row in rows]
    resumes = [resume for resume in stored if resume is not None]
    return ResumeListResponse(resumes=resumes, count=len(resumes))


@router.post(
    "",
    response_model=ResumeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a resume file",
    responses={
        409: {"description": "The content is already stored and allow_duplicate was false."},
        422: {"description": "The file could not be parsed or failed validation."},
    },
)
def ingest_resume(
    payload: ResumeIngestRequest,
    assistant: AssistantDep,
    candidate_id: CandidateIdDep,
) -> ResumeResponse:
    """Run the full ingestion pipeline for one file on the server.

    ``is_synthetic`` is not accepted from a request. The flag exists so test
    data is never mistaken for real data, and letting an HTTP caller set it
    would defeat that; synthetic resumes are created by tests and fixtures.
    """
    resume = assistant.resume_service.ingest(
        payload.path,
        variant=payload.variant,
        candidate_id=candidate_id,
        allow_duplicate=payload.allow_duplicate,
        role_focus=payload.role_focus,
        skills=payload.skills,
        version=payload.version,
    )
    return ResumeResponse(resume=resume)


@router.get(
    "/duplicates",
    response_model=DuplicateCheckResponse,
    summary="Check whether content is already stored",
)
def check_duplicate(
    assistant: AssistantDep,
    candidate_id: CandidateIdDep,
    file_hash: str = Query(min_length=1, max_length=200),
) -> DuplicateCheckResponse:
    """Whether a content hash has already been ingested.

    The hash is supplied by the caller. It is a value the caller already has
    from its own ingestion, and recomputing it here would put the definition of
    "same content" in two places.
    """
    check = assistant.resume_service.check_duplicate(file_hash, candidate_id)
    return DuplicateCheckResponse(
        file_hash=check.file_hash,
        is_duplicate=check.is_duplicate,
        existing_resume_id=check.existing_resume_id,
        existing_filename=check.existing_filename,
    )


@router.get(
    "/duplicates/stored",
    summary="Content hashes stored more than once",
)
def find_duplicates(
    assistant: AssistantDep, candidate_id: CandidateIdDep
) -> dict[str, object]:
    """Hashes the unique constraint should have prevented.

    Reported rather than raised: an empty list is the healthy answer, and this
    is a repository-integrity signal, not a request failure.
    """
    rows = assistant.resume_service.find_duplicates(candidate_id)
    return {"candidate_id": candidate_id, "duplicates": rows, "count": len(rows)}


@router.get(
    "/variants", response_model=ResumeVariantsResponse, summary="List stored variants"
)
def list_variants(
    assistant: AssistantDep, candidate_id: CandidateIdDep
) -> ResumeVariantsResponse:
    """Variant names stored for this candidate.

    Names, not resumes: a variant is a label the caller attached at ingestion,
    and it selects nothing.
    """
    variants = assistant.resume_service.list_variants(candidate_id)
    return ResumeVariantsResponse(
        candidate_id=candidate_id, variants=list(variants), count=len(variants)
    )


@router.get(
    "/sections",
    response_model=ResumeSectionsResponse,
    summary="Section index for the candidate",
)
def section_index(
    assistant: AssistantDep, candidate_id: CandidateIdDep
) -> ResumeSectionsResponse:
    """Sections grouped by type, as the repository indexes them."""
    index = assistant.resume_service.section_index(candidate_id)
    return ResumeSectionsResponse(
        candidate_id=candidate_id, by_section_type=index, section_types=sorted(index)
    )


@router.get("/{resume_id}", response_model=ResumeResponse, summary="Read one resume")
def get_resume(resume_id: str, assistant: AssistantDep) -> ResumeResponse:
    """One stored resume, or a 404."""
    resume = assistant.resume_service.get_resume(resume_id)
    if resume is None:
        # ``get_resume`` returns None while ``ingest`` raises on a missing file;
        # the boundary normalises to one typed error so both read the same to a
        # client.
        raise ResumeNotFoundError(f"no resume with id {resume_id!r}", resume_id=resume_id)
    return ResumeResponse(resume=resume)


@router.delete(
    "/{resume_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a resume",
    responses={404: {"description": "No such resume."}},
)
def delete_resume(resume_id: str, assistant: AssistantDep) -> None:
    """Remove a stored resume and its sections.

    The service reports how many rows it removed. Zero means there was nothing
    to delete, which is a 404 rather than a silent success.
    """
    removed = assistant.resume_service.delete_resume(resume_id)
    if not removed:
        raise ResumeNotFoundError(f"no resume with id {resume_id!r}", resume_id=resume_id)