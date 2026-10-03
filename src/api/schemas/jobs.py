"""Job request and response models.

Responses reuse the ``jobs`` package types: ``Job``, ``RequirementAnalysis``,
``MatchOutcome``, ``MatchReport``, ``ResumeRelevance``, ``MatchExplanation``,
and ``ReviewQueue``. Restating them here would mean a field added to a
requirement or a match dimension silently vanishes from the API, which is how a
UI and a service start disagreeing about the same row.

The request models exist because the HTTP edge is the only place a partial
choice — this status filter, this scorer — becomes an argument.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from jobs.analysis import MatchOutcome, RequirementAnalysis
from jobs.dimensions import MatchReport
from jobs.explain import MatchExplanation
from jobs.matching import MatchResult
from jobs.models import Job, JobStatus
from jobs.relevance import ResumeRelevance
from jobs.review import ReviewQueue

__all__ = [
    "JobIngestRequest",
    "MatchRequest",
    "JobListResponse",
    "JobResponse",
    "AnalysisResponse",
    "MatchResponse",
    "ReportResponse",
    "RelevanceResponse",
    "ExplanationResponse",
    "ReviewQueueResponse",
    "SubmitApplicationResponse",
]


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------
class JobIngestRequest(BaseModel):
    """Store a job from a local page capture.

    ``html`` is supplied by the caller rather than fetched. Nothing here
    navigates: the endpoint takes bytes in hand and runs them through the same
    parser the CLI uses, so ingesting a fixture and ingesting a capture take
    one code path.
    """

    model_config = ConfigDict(extra="forbid")

    html: str = Field(min_length=1, max_length=5_000_000)
    source: str = Field(default="local", min_length=1, max_length=100)
    page_url: str = Field(default="", max_length=2_000)
    source_path: str = Field(default="", max_length=4_000)


class MatchRequest(BaseModel):
    """Match one job, optionally with a similarity scorer.

    ``scorer`` is restricted to the names ``Assistant.build_scorer`` accepts.
    ``embedding`` is accepted here so the failure is a typed 4xx from the
    boundary rather than a 500 from deep inside a match, but it will fail when
    no embedding-capable provider is configured — and it is never quietly
    downgraded to ``lexical``. An unmeasured similarity is not a zero.
    """

    model_config = ConfigDict(extra="forbid")

    scorer: Optional[str] = Field(
        default=None,
        pattern="^(none|lexical|embedding)$",
        description="Similarity implementation. Omit to use the service default (no scorer).",
    )


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------
class JobListResponse(BaseModel):
    """Stored jobs."""

    model_config = ConfigDict(extra="forbid")

    jobs: list[Job] = Field(default_factory=list)
    count: int = Field(default=0, ge=0)
    limit: Optional[int] = None
    offset: int = Field(default=0, ge=0)


class JobResponse(BaseModel):
    """One job."""

    model_config = ConfigDict(extra="forbid")

    job: Job


class AnalysisResponse(BaseModel):
    """Requirements extracted for one job."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    analysis: RequirementAnalysis
    requirements: list = Field(
        default_factory=list,
        description="``jobs.models.Requirement`` rows, as stored.",
    )


class MatchResponse(BaseModel):
    """A match verdict plus the review reasons it raised."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    outcome: MatchOutcome
    result: MatchResult
    review_reasons: list = Field(default_factory=list)


class ReportResponse(BaseModel):
    """The dimension-by-dimension report."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    report: MatchReport


class RelevanceResponse(BaseModel):
    """Which stored resume fits the posting."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    relevance: ResumeRelevance


class ExplanationResponse(BaseModel):
    """The audit record for a stored match."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    explanation: MatchExplanation


class ReviewQueueResponse(BaseModel):
    """What still waits for a human."""

    model_config = ConfigDict(extra="forbid")

    queue: ReviewQueue
    open_reviews: int = Field(default=0, ge=0)
    counts_by_reason: dict[str, int] = Field(default_factory=dict)


class SubmitApplicationResponse(BaseModel):
    """The refusal returned by the application endpoint.

    This exists so the boundary is explicit about what it cannot do rather than
    leaving the caller to discover it from a 404. ``submission_possible`` is
    always ``False`` and no state changes: the route consults
    :class:`safety.policies.SafetyPolicy` and reports the refusal the policy
    produced.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str
    submitted: bool = False
    submission_possible: bool = False
    reason: str
    application_status: Optional[JobStatus] = None