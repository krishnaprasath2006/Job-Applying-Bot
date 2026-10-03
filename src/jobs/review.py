"""The review queue: what a human is asked to decide, and why.

A decision that needs a person is only useful if the person is told what
to look at. This module derives :class:`ReviewReason` values from an
already-made match — never guessing a new verdict, only naming the doubt
the verdict already carries — and assembles them into items a queue can
list.

One enum value is deliberately never derived here: ``STATE_REQUIRES_HUMAN``
belongs to the state machine's refusals, not to a match result; a
transition that cannot proceed reports it itself. ``EXTRACTION_CONFLICT``
is derived only when the caller passes a conflict count from
:mod:`jobs.reconcile` - it names a disagreement between two extractions
of the same posting, so without a cross-check's number there is nothing
for it to say.

    The queue's membership rule has two doors, both about work a human
    still owes: a match joins when its decision ``requires_human``
    (``REVIEW_REQUIRED`` or ``INSUFFICIENT_EVIDENCE``), and an *open*
    captured review joins even when its match was confident - that is the
    suspicious-or-inconsistent analysis someone decided to put on record.
    A resolved review drops out of both doors until its doubt changes,
    and everything else has been decided, correctly or not, and asking a
    human to re-decide it would be a queue that never drains.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    HardGateStatus,
    MatchDecision,
    RequirementEvaluation,
    RequirementPriority,
    ReviewReason,
)
from jobs.explain import MatchExplanation
from jobs.matching import MatchResult
from jobs.models import Job, JobStatus

__all__ = ["ReviewItem", "ReviewQueue", "derive_review_reasons"]

#: Extraction outcomes that mean the description never fully arrived.
_INCOMPLETE_EXTRACTIONS = frozenset({"PARTIAL", "FAILED", "UNAVAILABLE"})

#: A mean similarity below the matcher's own review band is a doubt worth
#: naming even when the rows individually squeaked past.
_LOW_SIMILARITY_BAND = 0.45


def derive_review_reasons(
    result: MatchResult,
    *,
    explanation: Optional[MatchExplanation] = None,
    extraction_status: Optional[str] = None,
    job_status: Optional[JobStatus] = None,
    conflicts: int = 0,
) -> list[ReviewReason]:
    """Name the doubts behind a match that needs a human.

    Args:
        result: The decision and its artifacts.
        explanation: The rendered audit record, when available; adds the
            mean-similarity signal.
        extraction_status: The job's description-extraction status, if it
            is known — ``PARTIAL``/``FAILED`` mean the requirements were
            read from a description that never fully arrived.
        job_status: The job's lifecycle state, for the same signal when it
            is carried there instead.
        conflicts: How many disagreements the cross-checker found between
            the two extractions of this posting. Above zero the doubt is
            named ``EXTRACTION_CONFLICT``, whichever other doubts the
            verdict carries.

    Returns:
        Deduplicated reasons in a fixed order, or ``[]`` when the decision
        does not require a human — no reason to name a doubt the verdict
        never had.
    """
    if not result.decision.requires_human:
        return []
    reasons: list[ReviewReason] = []

    def add(reason: ReviewReason) -> None:
        if reason not in reasons:
            reasons.append(reason)

    # Gate first: it is the strongest statement the match makes.
    if result.gate.status is HardGateStatus.UNKNOWN:
        add(ReviewReason.ELIGIBILITY_UNKNOWN)
    if result.gate.status is HardGateStatus.REVIEW_REQUIRED:
        add(ReviewReason.AMBIGUOUS_HARD_REQUIREMENT)

    required = [
        score
        for score in result.scores
        if score.priority is RequirementPriority.REQUIRED
    ]
    if result.decision is MatchDecision.INSUFFICIENT_EVIDENCE:
        if result.gate.status is not HardGateStatus.UNKNOWN:
            add(ReviewReason.INSUFFICIENT_EVIDENCE)
    if any(score.evaluation is RequirementEvaluation.UNKNOWN for score in required):
        if result.gate.status is not HardGateStatus.UNKNOWN:
            add(ReviewReason.INSUFFICIENT_EVIDENCE)
    if any(
        score.evaluation is RequirementEvaluation.REVIEW_REQUIRED for score in required
    ):
        add(ReviewReason.LOW_AI_CONFIDENCE)

    if explanation is not None and explanation.similarity_score is not None:
        if explanation.similarity_score < _LOW_SIMILARITY_BAND:
            add(ReviewReason.LOW_AI_CONFIDENCE)

    status = extraction_status or (job_status.value if job_status else None)
    if status is not None and status.upper() in _INCOMPLETE_EXTRACTIONS:
        add(ReviewReason.JD_EXTRACTION_INCOMPLETE)
    if job_status in (JobStatus.JD_PARTIAL, JobStatus.JD_FAILED):
        add(ReviewReason.JD_EXTRACTION_INCOMPLETE)
    if conflicts > 0:
        add(ReviewReason.EXTRACTION_CONFLICT)
    return reasons


class ReviewItem(BaseModel):
    """One job parked in front of a human, with the reasons it is there.

    Attributes:
        job_id: Which posting.
        title / company / url: Identity enough to open it.
        decision: The match verdict that queued it.
        reasons: Why, in the derived order.
        similarity_score: Mean scorer output, when it was computed.
        matched_at: When the stored match was written.
        report: The rendered explanation, when the caller had one at hand.
            A queue row loaded from the database carries ``None`` rather
            than a guess - the report is reproducible from the stored
            match, not from this row.
        status: The persisted lifecycle state (``OPEN``), when a
            :mod:`database.repositories.reviews` record exists for this
            posting. ``None`` means no one has recorded a look either
            way - not that the item is fine.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str
    title: str = ""
    company: str = ""
    url: Optional[str] = None
    decision: MatchDecision
    reasons: list[ReviewReason] = Field(default_factory=list)
    similarity_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    matched_at: Optional[str] = None
    report: Optional[str] = None
    status: Optional[str] = None

    @classmethod
    def from_match(
        cls,
        job: Job,
        result: MatchResult,
        *,
        explanation: Optional[MatchExplanation] = None,
        reasons: Optional[Iterable[ReviewReason]] = None,
    ) -> "ReviewItem":
        """Build an item from a live decision.

        ``reasons`` is accepted when the caller already derived them (the
        cache does, to store them); otherwise they are derived here.
        """
        return cls(
            job_id=job.id,
            title=job.title,
            company=job.company,
            url=job.canonical_url or job.url,
            decision=result.decision,
            reasons=list(reasons) if reasons is not None else derive_review_reasons(
                result, explanation=explanation
            ),
            similarity_score=result.similarity_score,
            report=explanation.render() if explanation is not None else None,
        )

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ReviewItem":
        """Build an item from a repository ``review_required()`` row.

        That query returns the newest match per job with only its summary
        columns, so the report and the similarity are absent by
        construction; ``review_reasons`` arrives as JSON text because the
        query does not decode it.
        """
        reasons = row.get("review_reasons") or []
        if isinstance(reasons, str):
            try:
                decoded = json.loads(reasons)
            except (TypeError, ValueError):
                decoded = []
            reasons = decoded if isinstance(decoded, list) else []
        return cls(
            job_id=str(row.get("id", "")),
            title=str(row.get("title") or ""),
            company=str(row.get("company") or ""),
            url=row.get("canonical_url"),
            decision=MatchDecision(str(row.get("decision", ""))),
            reasons=[ReviewReason(str(reason)) for reason in reasons],
            matched_at=row.get("matched_at"),
        )

    @classmethod
    def from_review_row(cls, row: Mapping[str, Any]) -> "ReviewItem":
        """Build an item from a repository ``open_reviews()`` row.

        These are the captured reviews whose match did not queue itself:
        the analysis was suspicious or inconsistent enough that someone
        put it on record. ``status`` arrives as ``OPEN`` by construction
        (the query only asks for open rows), and ``similarity_score`` is
        absent because the capture stored it under ``supporting``.
        """
        reasons = row.get("reasons") or []
        if isinstance(reasons, str):
            try:
                decoded = json.loads(reasons)
            except (TypeError, ValueError):
                decoded = []
            reasons = decoded if isinstance(decoded, list) else []
        return cls(
            job_id=str(row.get("job_id", "")),
            title=str(row.get("title") or ""),
            company=str(row.get("company") or ""),
            url=row.get("canonical_url"),
            decision=MatchDecision(str(row.get("decision", ""))),
            reasons=[ReviewReason(str(reason)) for reason in reasons],
            matched_at=row.get("created_at"),
            status=str(row.get("status") or "OPEN"),
        )


class ReviewQueue(BaseModel):
    """A list of review items with just enough order to work a queue.

    Order is the caller's: rows arrive newest-match-first from the
    repository, and a live build keeps the order it was given. Nothing
    here sorts by similarity — a queue sorted by a number nobody agreed on
    is a queue that hides its worst doubts at the bottom.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[ReviewItem] = Field(default_factory=list)

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, Any]]) -> "ReviewQueue":
        """Assemble a queue from repository ``review_required()`` rows."""
        return cls(items=[ReviewItem.from_row(row) for row in rows])

    @classmethod
    def from_matches(
        cls, matches: Iterable[tuple[Job, MatchResult, Optional[MatchExplanation]]]
    ) -> "ReviewQueue":
        """Assemble a queue from live (job, result, explanation) triples,
        keeping only the decisions that require a human."""
        items = [
            ReviewItem.from_match(job, result, explanation=explanation)
            for job, result, explanation in matches
            if result.decision.requires_human
        ]
        return cls(items=items)

    def __len__(self) -> int:
        return len(self.items)

    def counts_by_reason(self) -> dict[ReviewReason, int]:
        """How many items each reason appears on — one item can have
        several, so these do not sum to the queue's length."""
        counts: dict[ReviewReason, int] = {}
        for item in self.items:
            for reason in item.reasons:
                counts[reason] = counts.get(reason, 0) + 1
        return counts

    def only(self, reason: ReviewReason) -> list[ReviewItem]:
        """Every item carrying ``reason``, queue order preserved."""
        return [item for item in self.items if reason in item.reasons]

    def job_ids(self) -> list[str]:
        """The queued job ids, in queue order."""
        return [item.job_id for item in self.items]
