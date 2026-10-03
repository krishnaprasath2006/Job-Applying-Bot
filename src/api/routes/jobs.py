"""Job routes: ingest, analyse, match, report, explain, review.

Every route is a delegation. The decisions live in ``jobs`` and
``assistant.job_service``; these functions choose a service method, pass
arguments the caller supplied, and serialise the result.

Two routes deserve their own note:

``POST /api/jobs/{id}/apply``
    This does not apply to anything. It consults
    :meth:`safety.policies.SafetyPolicy.check` for
    :attr:`safety.policies.Action.SUBMIT_APPLICATION` and returns the refusal.
    The job's stored state is read to report what the job is waiting for, and
    nothing is written. Keeping a route that answers the question explicitly is
    better than a 404: a client learns the boundary is deliberate rather than
    missing.

``POST /api/jobs/{id}/match`` with ``scorer="embedding"``
    Accepted so the failure arrives as a typed error from the boundary. It is
    never silently downgraded to lexical scoring — an unmeasured similarity is
    not a score of zero, and reporting one as the other would misstate why a
    candidate did or did not match.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from api.dependencies import AssistantDep
from api.schemas import (
    AnalysisResponse,
    ExplanationResponse,
    JobIngestRequest,
    JobListResponse,
    JobResponse,
    MatchRequest,
    MatchResponse,
    RelevanceResponse,
    ReportResponse,
    ReviewQueueResponse,
    SubmitApplicationResponse,
)
from jobs.models import JobStatus
from safety.policies import Action

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=JobListResponse, summary="List stored jobs")
def list_jobs(
    assistant: AssistantDep,
    job_status: Optional[JobStatus] = Query(
        default=None, alias="status", description="Filter by lifecycle state."
    ),
    source: Optional[str] = Query(default=None, max_length=100),
    candidate_id: Optional[str] = Query(default=None, max_length=200),
    limit: Optional[int] = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> JobListResponse:
    """Stored jobs, filtered by the repository's own parameters."""
    jobs = assistant.job_service.list_jobs(
        status=job_status,
        source=source,
        candidate_id=candidate_id,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(
        jobs=jobs, count=len(jobs), limit=limit, offset=offset
    )


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a local page capture",
)
def ingest_job(payload: JobIngestRequest, assistant: AssistantDep) -> JobResponse:
    """Parse a page the caller already has and store the job it describes.

    No navigation, no network. The bytes arrive in the request and go through
    the same parser the CLI uses, so a fixture and a capture share one path.
    """
    result = assistant.job_service.ingest_page(
        payload.html,
        source=payload.source,
        page_url=payload.page_url,
        source_path=payload.source_path,
    )
    return JobResponse(job=result.job)


@router.get("/reviews", response_model=ReviewQueueResponse, summary="The review queue")
def review_queue(assistant: AssistantDep) -> ReviewQueueResponse:
    """What still waits for a human, and how many open reviews exist."""
    queue = assistant.job_service.review_queue()
    return ReviewQueueResponse(
        queue=queue,
        open_reviews=assistant.job_service.open_review_count(),
        counts_by_reason=queue.counts_by_reason(),
    )


@router.get("/{job_id}", response_model=JobResponse, summary="Read one job")
def get_job(job_id: str, assistant: AssistantDep) -> JobResponse:
    """One stored job, or a 404 from ``JobService.get``."""
    return JobResponse(job=assistant.job_service.get(job_id))


@router.post(
    "/{job_id}/analysis",
    response_model=AnalysisResponse,
    summary="Extract requirements",
)
def analyze_job(job_id: str, assistant: AssistantDep) -> AnalysisResponse:
    """Deterministic requirement analysis.

    Offline by default. The AI reading exists in ``JobService.analyze`` but is
    not exposed here yet: it needs a provider the caller cannot supply over
    HTTP, and defaulting it to on would make a status endpoint depend on a model
    being reachable.
    """
    analysis = assistant.job_service.analyze(job_id, ai=False)
    return AnalysisResponse(
        job_id=job_id,
        analysis=analysis,
        requirements=list(analysis.requirements),
    )


@router.post("/{job_id}/match", response_model=MatchResponse, summary="Match against the candidate")
def match_job(
    job_id: str,
    payload: MatchRequest,
    assistant: AssistantDep,
) -> MatchResponse:
    """Compute the match verdict and record any doubt it raises.

    Analysis runs first inside the service, so matching a job that has never
    been analysed yields the same verdict as matching one that has.
    """
    scorer = assistant.build_scorer(payload.scorer) if payload.scorer else None
    outcome = assistant.job_service.match(job_id, scorer=scorer)
    return MatchResponse(
        job_id=job_id,
        outcome=outcome,
        result=outcome.result,
        review_reasons=list(outcome.review_reasons),
    )


@router.get("/{job_id}/report", response_model=ReportResponse, summary="Dimension report")
def job_report(job_id: str, assistant: AssistantDep) -> ReportResponse:
    """The eleven-dimension report. Explains the verdict; never re-decides it."""
    return ReportResponse(job_id=job_id, report=assistant.job_service.report(job_id))


@router.get(
    "/{job_id}/relevance",
    response_model=RelevanceResponse,
    summary="Which resume fits this job",
)
def job_relevance(job_id: str, assistant: AssistantDep) -> RelevanceResponse:
    """Resume relevance from stored data only. Nothing is generated."""
    return RelevanceResponse(
        job_id=job_id, relevance=assistant.job_service.relevance(job_id)
    )


@router.get(
    "/{job_id}/explanation",
    response_model=ExplanationResponse,
    summary="Explain a stored match",
)
def explain_match(job_id: str, assistant: AssistantDep) -> ExplanationResponse:
    """The audit record for the stored match.

    Raises when no match has been stored rather than inventing a verdict: a
    404 here means "match first", which is true.
    """
    return ExplanationResponse(
        job_id=job_id, explanation=assistant.job_service.explain(job_id)
    )


@router.get("/{job_id}/review", summary="Review state for one job")
def job_review_status(job_id: str, assistant: AssistantDep) -> dict[str, object]:
    """The persisted lifecycle review state for one posting."""
    state = assistant.job_service.review_status(job_id)
    return {"job_id": job_id, "review_status": state, "open": state == "OPEN"}


@router.post("/{job_id}/review/resolve", summary="Resolve an open review")
def resolve_review(
    job_id: str,
    assistant: AssistantDep,
    note: str = Query(default="", max_length=2_000),
) -> dict[str, object]:
    """Mark this candidate's review resolved.

    ``resolved`` is ``False`` when there was no open review to resolve — an
    idempotent no-op, reported honestly rather than as a success.
    """
    resolved = assistant.job_service.resolve_review(job_id, note=note)
    return {
        "job_id": job_id,
        "resolved": resolved,
        "review_status": assistant.job_service.review_status(job_id),
    }


@router.post(
    "/{job_id}/apply",
    response_model=SubmitApplicationResponse,
    summary="Application submission is disabled",
    responses={403: {"description": "Always. Submission is disabled by policy."}},
)
def submit_application(
    job_id: str,
    assistant: AssistantDep,
) -> SubmitApplicationResponse:
    """Refuse to submit, and say why.

    The only state read is the job's stored lifecycle, reported back so a client
    can see what the job is waiting for. Nothing is written and no browser is
    touched: the route answers the policy question and stops.
    """
    reason = assistant.safety.check(
        Action.SUBMIT_APPLICATION, application_id=job_id
    )
    # ``check`` returning None would mean policy was changed out from under the
    # invariants. It cannot happen through settings — there is no route that
    # writes them, and ``assert_phase2_invariants`` runs at startup — but
    # reporting a refusal anyway is the correct failure direction.
    return SubmitApplicationResponse(
        job_id=job_id,
        submitted=False,
        submission_possible=False,
        reason=reason or "REAL SUBMISSION IS DISABLED by assistant safety policy",
        application_status=assistant.job_service.get(job_id).status,
    )


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Not supported",
    responses={405: {"description": "Jobs are not deleted over HTTP."}},
)
def delete_job(job_id: str) -> None:
    """Job deletion is intentionally unavailable at this boundary.

    Deleting a job cascades to requirements, matches, and review rows. That is a
    destructive, non-reversible operation with no undo, and it belongs to a
    deliberate operator action rather than an HTTP call that a UI might make by
    accident.
    """
    raise HTTPException(
        status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="jobs are not deleted over HTTP; use the CLI for destructive operations",
    )