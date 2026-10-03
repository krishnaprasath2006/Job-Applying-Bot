"""Why a job came out the way it did — one row per requirement, with lineage
on both sides.

A decision nobody can audit is a decision nobody can trust, and the review
queue (and the human reading it) needs more than a verdict. This module
assembles the audit record from the artifacts the pipeline already keeps:

* the **posting side** of every row — how the requirement was extracted
  (deterministically or by a model), whether its analysis rested on the
  job's own data, the excerpt quoted from the description, and the
  extractor's confidence;
* the **candidate side** — the profile field that answered, its truth
  status, and the evidence records behind it;
* the **verdict side** — the evaluation, the reason, and any similarity
  the scorer computed, keyed back to the row's position in the posting via
  ``requirement_index``.

Rows the gate claimed are explained from the gate's checks; rows scoring
judged are explained from the scores; a row neither touched says so rather
than borrowing an answer. Nothing here recomputes anything: an explanation
that disagreed with the decision it explains would be worse than silence.
"""

from __future__ import annotations

from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AnalysisSource,
    ExtractionMethod,
    FactStatus,
    HardGateStatus,
    MatchDecision,
    RequirementEvaluation,
    RequirementPriority,
)
from core.evidence import Evidence
from jobs.candidate import CandidateEvidence
from jobs.hard_gate import GateCheck, is_gated
from jobs.matching import MatchResult, RequirementScore
from jobs.models import Job, Requirement, RequirementKind

__all__ = [
    "CandidateLineage",
    "MatchExplanation",
    "PostingLineage",
    "RowExplanation",
    "explain_match",
]

_NOT_SCORED = "not scored: the gate decided before scoring ran"
_OFFERS_WHAT_IT_ASKS = (
    "not evaluated: the posting offers what this row asks, so no answer "
    "could fail it"
)


class PostingLineage(BaseModel):
    """Where the requirement came from, on the posting side."""

    model_config = ConfigDict(extra="forbid")

    method: ExtractionMethod
    analysis_source: AnalysisSource = AnalysisSource.JOB_DATA
    excerpt: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class CandidateLineage(BaseModel):
    """Where the answer came from, on the candidate side."""

    model_config = ConfigDict(extra="forbid")

    field_path: str
    status: FactStatus
    evidence: list[Evidence] = Field(default_factory=list)


class RowExplanation(BaseModel):
    """One requirement, decided, with both sides of its lineage.

    ``evaluation`` is ``None`` only for a row nothing evaluated — the gate
    short-circuited before scoring, or the row was one the gate read as
    already satisfied. It is never filled in from somewhere else: a row
    without an answer shows a row without an answer.
    """

    model_config = ConfigDict(extra="forbid")

    index: int
    requirement_text: str
    kind: RequirementKind
    priority: RequirementPriority
    evaluation: Optional[RequirementEvaluation] = None
    reason: str
    similarity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    posting: PostingLineage
    candidate: Optional[CandidateLineage] = None


class MatchExplanation(BaseModel):
    """The full audit record for one job/candidate decision.

    Attributes:
        decision: The verdict this explains.
        gate_status: What the hard gate said, since everything else is
            downstream of it.
        similarity_score: Mean scorer output the matcher computed, if any.
        job_id / job_title / job_company: Identity of the posting, when a
            job was supplied.
        rows: Every requirement in the posting, in document order.
    """

    model_config = ConfigDict(extra="forbid")

    decision: MatchDecision
    gate_status: HardGateStatus
    similarity_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    job_id: Optional[str] = None
    job_title: Optional[str] = None
    job_company: Optional[str] = None
    rows: list[RowExplanation] = Field(default_factory=list)

    def rows_with(
        self, evaluation: RequirementEvaluation
    ) -> list[RowExplanation]:
        """Every row the gate or the scorer judged with ``evaluation``."""
        return [row for row in self.rows if row.evaluation is evaluation]

    @property
    def undecided_rows(self) -> list[RowExplanation]:
        """Rows nothing could decide — the ones a human should start with."""
        return [row for row in self.rows if row.evaluation is None]

    def render(self) -> str:
        """A plain-text report, one block per requirement.

        Plain text on purpose: the CLI, the acceptance run, and a terminal
        in a review session all read the same string, and none of them
        need a table borders library to see why a job failed.
        """
        heading = f"{self.decision.value} (gate: {self.gate_status.value})"
        if self.job_title:
            company = f" @ {self.job_company}" if self.job_company else ""
            heading += f" — {self.job_title}{company}"
        if self.similarity_score is not None:
            heading += f"\nsimilarity: {self.similarity_score:.2f}"
        lines = [heading]
        for row in self.rows:
            evaluation = (
                row.evaluation.value if row.evaluation is not None else "NOT EVALUATED"
            )
            lines.append(
                f"  [{row.index}] {row.priority.value} {row.requirement_text}"
                f" — {evaluation}"
            )
            lines.append(f"      why: {row.reason}")
            excerpt = row.posting.excerpt or ""
            if len(excerpt) > 120:
                excerpt = excerpt[:117] + "..."
            lines.append(
                "      posting: "
                f"{row.posting.method.value} "
                f"({row.posting.confidence:.2f}"
                + (f', "{excerpt}"' if excerpt else "")
                + ")"
            )
            if row.candidate is not None:
                lines.append(
                    "      candidate: "
                    f"{row.candidate.field_path} ({row.candidate.status.value}, "
                    f"{len(row.candidate.evidence)} evidence)"
                )
            elif row.similarity is not None:
                lines.append(f"      candidate: closest claim scores {row.similarity:.2f}")
            else:
                lines.append("      candidate: (nothing answered)")
        return "\n".join(lines)


def explain_match(
    result: MatchResult,
    requirements: Sequence[Requirement],
    evidence: CandidateEvidence,
    *,
    job: Optional[Job] = None,
) -> MatchExplanation:
    """Assemble the audit record for one already-made decision.

    Args:
        result: The decision and the artifacts behind it.
        requirements: The same list the match ran over — rows are lined up
            by ``requirement_index``, so a different list would explain the
            wrong posting.
        evidence: The same candidate evidence the match used.
        job: Optional posting, for identity fields on the report.

    Returns:
        One row per requirement, in document order, each carrying its
        posting lineage, its candidate lineage when something answered,
        and the evaluation — or an honest absence of one.
    """
    checks_by_index = {}
    for check in result.gate.checks:
        if check.requirement_index is not None:
            checks_by_index.setdefault(check.requirement_index, check)
    scores_by_index = {
        score.requirement_index: score
        for score in result.scores
        if score.requirement_index is not None
    }

    rows = [
        _explain_row(
            index,
            requirement,
            checks_by_index.get(index),
            scores_by_index.get(index),
            evidence,
        )
        for index, requirement in enumerate(requirements)
    ]
    return MatchExplanation(
        decision=result.decision,
        gate_status=result.gate.status,
        similarity_score=result.similarity_score,
        job_id=job.id if job is not None else None,
        job_title=job.title if job is not None else None,
        job_company=job.company if job is not None else None,
        rows=rows,
    )


def _explain_row(
    index: int,
    requirement: Requirement,
    check: Optional[GateCheck],
    score: Optional[RequirementScore],
    evidence: CandidateEvidence,
) -> RowExplanation:
    if check is not None:
        evaluation = check.evaluation
        reason = check.reason
        similarity = None
        field_path = check.candidate_field_path
    elif score is not None:
        evaluation = score.evaluation
        reason = score.reason
        similarity = score.similarity
        field_path = score.candidate_field_path
    elif is_gated(requirement):
        evaluation = None
        reason = _OFFERS_WHAT_IT_ASKS
        similarity = None
        field_path = None
    else:
        evaluation = None
        reason = _NOT_SCORED
        similarity = None
        field_path = None
    return RowExplanation(
        index=index,
        requirement_text=requirement.text,
        kind=requirement.kind,
        priority=requirement.priority,
        evaluation=evaluation,
        reason=reason,
        similarity=similarity,
        posting=PostingLineage(
            method=requirement.extraction_source,
            analysis_source=requirement.analysis_source,
            excerpt=requirement.source_excerpt,
            confidence=requirement.confidence,
        ),
        candidate=_candidate_lineage(field_path, evidence),
    )


def _candidate_lineage(
    field_path: Optional[str], evidence: CandidateEvidence
) -> Optional[CandidateLineage]:
    if not field_path:
        return None
    if field_path == "experience.total_years_experience":
        reference = evidence.years_source
    elif field_path == "authorization.requires_sponsorship":
        reference = evidence.sponsorship_source
    else:
        reference = next(
            (
                claim.source
                for claim in evidence.claims
                if claim.source.field_path == field_path
            ),
            None,
        )
    if reference is None:
        return None
    return CandidateLineage(
        field_path=reference.field_path,
        status=reference.status,
        evidence=list(reference.evidence),
    )
