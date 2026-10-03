"""The eleven-dimension report: where a job fits, one dimension at a time.

A single number cannot say *which* part of a profile a fit came from, so
the report scores eleven dimensions independently and carries the posting's
hard blockers alongside them. The rules this module keeps:

* **Deterministic.** Same inputs, byte-identical report: no clocks, no
  randomness, fixed iteration order over the published dimension list.
* **``NOT_SCORED`` is not ``0.0``.** A dimension the posting or the profile
  gives no data for scores ``None``; a dimension that measured and found
  nothing scores ``0.0``. Collapsing the two would let an empty profile
  look like a perfect anti-match.
* **Every dimension explains itself.** ``explanation`` is never empty, and
  ``evidence`` quotes the posting and profile text the verdict rests on.
* **Scores clamp to ``[0, 1]``**, enforced by the model itself.
* **An all-zero report raises an alarm** rather than passing quietly.
* **The gate's verdict travels intact.** ``decision`` and
  ``hard_blockers`` come from the match result; no dimension, however
  high it scores, can unblock a hard mismatch.

The dimension vocabulary follows the phase-7 spec
(``docs/IMPLEMENTATION_PLAN.md``): skill, experience, education, location,
workplace, seniority, must-have, nice-to-have, authorization, domain, and
resume-evidence coverage. Row-based dimensions read the requirement rows
and their evaluations (scoring rows *and* gate checks, so a gated years
row is still an experience answer); location, workplace and seniority may
fall back to the posting's own fields when the extractor stated no row.
"""

from __future__ import annotations

from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    DimensionStatus,
    FactStatus,
    MatchDecision,
    RequirementEvaluation,
    RequirementPriority,
)
from core.logging_config import get_logger
from jobs.candidate import CandidateEvidence
from jobs.hard_gate import HardGateStatus
from jobs.matching import MatchResult, RequirementScore
from jobs.models import Job, Requirement, RequirementKind

__all__ = [
    "DEFAULT_WEIGHTS",
    "DIMENSIONS",
    "DimensionResult",
    "MatchReport",
    "build_report",
]

log = get_logger(__name__)

#: The published dimension set, in spec order. The report always carries
#: all eleven keys, in this order - a missing dimension would read as a
#: dimension nobody thought about, not as one the posting never stated.
DIMENSIONS: tuple[str, ...] = (
    "skill_match",
    "experience_match",
    "education_match",
    "location_match",
    "workplace_match",
    "seniority_match",
    "must_have_match",
    "nice_to_have_match",
    "authorization_match",
    "domain_match",
    "resume_evidence_coverage",
)

#: Equal weights until ``data/matching.yaml`` lands: eleven voices at equal
#: volume is a choice, and an honest one - any other split would pretend
#: the market had told us what matters, which it has not.
DEFAULT_WEIGHTS: dict[str, float] = {name: 1.0 for name in DIMENSIONS}

#: Status bands, shared with the matcher so a dimension saying STRONG and
#: a row saying DERIVED_MATCH never mean opposite things.
STRONG_BAND = 0.75
PARTIAL_BAND = 0.45

_MATCHES = frozenset(
    {RequirementEvaluation.VERIFIED_MATCH, RequirementEvaluation.DERIVED_MATCH}
)
_MISSES = frozenset(
    {RequirementEvaluation.VERIFIED_MISMATCH, RequirementEvaluation.DERIVED_MISMATCH}
)
_UNCERTAIN = frozenset(
    {RequirementEvaluation.UNKNOWN, RequirementEvaluation.REVIEW_REQUIRED}
)

_SKILL_KINDS = frozenset(
    {
        RequirementKind.SKILL,
        RequirementKind.TOOL,
        RequirementKind.TECHNOLOGY,
        RequirementKind.PROGRAMMING_LANGUAGE,
        RequirementKind.FRAMEWORK,
        RequirementKind.DATABASE,
        RequirementKind.CLOUD,
        RequirementKind.LANGUAGE,
        RequirementKind.SOFT_SKILL,
    }
)
_EXPERIENCE_KINDS = frozenset(
    {RequirementKind.EXPERIENCE, RequirementKind.YEARS_OF_EXPERIENCE}
)
_EDUCATION_KINDS = frozenset({RequirementKind.EDUCATION, RequirementKind.CERTIFICATION})
_LOCATION_KINDS = frozenset({RequirementKind.LOCATION})
_WORKPLACE_KINDS = frozenset(
    {RequirementKind.WORKPLACE_TYPE, RequirementKind.EMPLOYMENT_TYPE}
)
_AUTHORIZATION_KINDS = frozenset(
    {RequirementKind.AUTHORIZATION, RequirementKind.SPONSORSHIP}
)
_DOMAIN_KINDS = frozenset({RequirementKind.DOMAIN})

#: Cap on quoted excerpts per dimension, so a long posting cannot drown
#: the report in its own text.
_EVIDENCE_LIMIT = 5

#: Sentinels for the two verdicts that mean "scored nothing".
_NOT_SCORED: Optional[float] = None


class DimensionResult(BaseModel):
    """One dimension's verdict, with the evidence and reasoning behind it.

    Attributes:
        status: The five-way verdict. ``NOT_APPLICABLE`` (the posting
            states nothing for this dimension) is kept distinct from
            ``UNKNOWN`` (it states something; the profile answers neither
            way).
        score: ``0.0``-``1.0``, or ``None`` for not scored - never a
            fabricated number.
        evidence: Verbatim quotes the verdict rests on: posting rows and
            profile excerpts, capped.
        source: Which inputs participated - ``posting``, ``profile``, and
            ``similarity`` joined by ``+``.
        confidence: ``decidable / total`` for row dimensions: how much of
            this dimension the evidence could actually answer.
        explanation: One non-empty sentence a human can check.
    """

    model_config = ConfigDict(extra="forbid")

    status: DimensionStatus
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    source: str = "posting"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    explanation: str


class MatchReport(BaseModel):
    """The full report: gate verdict, eleven dimensions, requirement lists.

    Attributes:
        decision: The match decision exactly as the matcher composed it -
            the report explains it, it never re-decides it.
        gate_status: The hard gate's verdict behind that decision.
        hard_blockers: One sentence per blocking check. Non-empty exactly
            when the gate is vetoing, so a reader can see why no score
            could rescue this posting.
        dimension_scores: All eleven dimensions, in :data:`DIMENSIONS`
            order.
        overall_match: Weighted mean over the dimensions that scored;
            ``None`` when nothing scored (not scored is not zero).
        matched_requirements: Row texts the evidence answered yes to.
        missing_requirements: Row texts the evidence answered no to.
        uncertain_requirements: Row texts nobody could answer.
        explanations: One sentence per dimension, same order as the keys.
        confidence: Mean of the per-dimension confidences - how much of
            the eleven the evidence could speak to at all.
        evidence_source: Which input families backed this report.
        grounded_in: Profile field paths and the posting, sorted.
        alarms: Report-level warnings; non-empty means something needs a
            human's attention before the report is trusted.
    """

    model_config = ConfigDict(extra="forbid")

    decision: MatchDecision
    gate_status: HardGateStatus
    hard_blockers: list[str] = Field(default_factory=list)
    dimension_scores: dict[str, DimensionResult]
    overall_match: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    uncertain_requirements: list[str] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_source: str = "posting"
    grounded_in: list[str] = Field(default_factory=list)
    alarms: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Row slicing: which requirements answer which dimension
# ---------------------------------------------------------------------------
def _band(score: float) -> DimensionStatus:
    if score >= STRONG_BAND:
        return DimensionStatus.STRONG
    if score >= PARTIAL_BAND:
        return DimensionStatus.PARTIAL
    return DimensionStatus.WEAK


def _row_value(evaluation: RequirementEvaluation) -> float:
    if evaluation in _MATCHES:
        return 1.0
    if evaluation is RequirementEvaluation.REVIEW_REQUIRED:
        return 0.5
    if evaluation in _MISSES:
        return 0.0
    raise ValueError(f"{evaluation.value} has no row value; it is not decidable")


def _quote(texts: Sequence[str]) -> list[str]:
    if len(texts) <= _EVIDENCE_LIMIT:
        return list(texts)
    return [
        *texts[:_EVIDENCE_LIMIT],
        f"... and {len(texts) - _EVIDENCE_LIMIT} more",
    ]


def _dimension_from_rows(
    name: str,
    rows: Sequence[tuple[Requirement, Optional[RequirementScore], Optional[RequirementEvaluation]]],
) -> DimensionResult:
    """Score one dimension from its (requirement, score-or-gate) rows.

    ``score`` is ``None`` for gated rows (their evaluation lives in the
    gate, not the score list); a row with neither is a row nobody
    evaluated - skipped, because inventing an evaluation for it would be
    exactly the kind of guess this report exists to avoid.
    """
    evaluated = [
        (requirement, score, evaluation)
        for requirement, score, evaluation in rows
        if evaluation is not None
    ]
    if not evaluated:
        return DimensionResult(
            status=DimensionStatus.NOT_APPLICABLE,
            score=_NOT_SCORED,
            source="posting",
            confidence=1.0,
            explanation=(
                f"the posting states no {name.replace('_match', '').replace('_', ' ')}"
                " requirement that could be measured"
            ),
        )

    decidable = [
        (requirement, score, evaluation)
        for requirement, score, evaluation in evaluated
        if evaluation is not RequirementEvaluation.UNKNOWN
    ]
    met = [
        (requirement, score, evaluation)
        for requirement, score, evaluation in evaluated
        if evaluation in _MATCHES
    ]
    missed = [
        (requirement, score, evaluation)
        for requirement, score, evaluation in evaluated
        if evaluation in _MISSES
    ]
    review = [
        (requirement, score, evaluation)
        for requirement, score, evaluation in evaluated
        if evaluation is RequirementEvaluation.REVIEW_REQUIRED
    ]
    undecided = [
        (requirement, score, evaluation)
        for requirement, score, evaluation in evaluated
        if evaluation is RequirementEvaluation.UNKNOWN
    ]
    confidence = round(len(decidable) / len(evaluated), 4)
    similarity_used = any(
        score is not None and score.similarity is not None
        for _, score, _ in evaluated
    )
    source = "posting+similarity" if similarity_used else "posting"

    if not decidable:
        return DimensionResult(
            status=DimensionStatus.UNKNOWN,
            score=_NOT_SCORED,
            evidence=_quote([r.text for r, _, _ in evaluated]),
            source=source,
            confidence=0.0,
            explanation=(
                f"{len(evaluated)} {name.replace('_', ' ')} row(s) stated, "
                "and the profile answers none of them"
            ),
        )

    score = round(sum(_row_value(ev) for _, _, ev in decidable) / len(decidable), 4)
    explanation = (
        f"{len(met)} of {len(decidable)} decidable row(s) met, "
        f"{len(missed)} missed, {len(review)} awaiting review"
        + (
            f"; {len(undecided)} row(s) undecided"
            if undecided
            else ""
        )
    )
    return DimensionResult(
        status=_band(score),
        score=score,
        evidence=_quote([r.text for r, _, _ in evaluated]),
        source=source,
        confidence=confidence,
        explanation=explanation,
    )


def _rows_where(
    requirements: Sequence[Requirement],
    score_by_index: dict[int, RequirementScore],
    evaluation_by_index: dict[int, RequirementEvaluation],
    predicate,  # Callable[[Requirement], bool]
) -> list[tuple[Requirement, Optional[RequirementScore], Optional[RequirementEvaluation]]]:
    """Slice the posting into dimension rows, attaching each row's verdict.

    A scored row's evaluation lives on its score; a gated row's lives in
    the gate's checks; a row nobody evaluated carries neither - that
    absence is preserved, never filled in.
    """
    rows = []
    for index, requirement in enumerate(requirements):
        if not predicate(requirement):
            continue
        score = score_by_index.get(index)
        evaluation = (
            score.evaluation if score is not None else evaluation_by_index.get(index)
        )
        rows.append((requirement, score, evaluation))
    return rows


def _rows_for_kinds(
    requirements: Sequence[Requirement],
    score_by_index: dict[int, RequirementScore],
    evaluation_by_index: dict[int, RequirementEvaluation],
    kinds: frozenset[RequirementKind],
) -> list[tuple[Requirement, Optional[RequirementScore], Optional[RequirementEvaluation]]]:
    return _rows_where(
        requirements,
        score_by_index,
        evaluation_by_index,
        lambda requirement: requirement.kind in kinds,
    )


def _rows_for_priority(
    requirements: Sequence[Requirement],
    score_by_index: dict[int, RequirementScore],
    evaluation_by_index: dict[int, RequirementEvaluation],
    priority: RequirementPriority,
) -> list[tuple[Requirement, Optional[RequirementScore], Optional[RequirementEvaluation]]]:
    return _rows_where(
        requirements,
        score_by_index,
        evaluation_by_index,
        lambda requirement: requirement.priority is priority,
    )


# ---------------------------------------------------------------------------
# Field-based dimensions: the posting says it in fields, not in rows
# ---------------------------------------------------------------------------
def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        token
        for token in "".join(
            char.lower() if char.isalnum() else " " for char in text
        ).split()
        if len(token) > 1
    )


def _location_dimension(job: Job, evidence: CandidateEvidence) -> DimensionResult:
    place_claims = [
        claim
        for claim in evidence.claims
        if claim.source.field_path.startswith("location.")
        or claim.source.field_path.startswith("preferences.desired_locations")
    ]
    if not job.location and not place_claims:
        return DimensionResult(
            status=DimensionStatus.NOT_APPLICABLE,
            score=_NOT_SCORED,
            source="posting",
            explanation="neither the posting nor the profile names a location",
        )
    if not job.location:
        return DimensionResult(
            status=DimensionStatus.UNKNOWN,
            score=_NOT_SCORED,
            evidence=_quote([claim.text for claim in place_claims]),
            source="profile",
            confidence=0.0,
            explanation="the profile names locations; the posting states none",
        )
    if not place_claims:
        return DimensionResult(
            status=DimensionStatus.UNKNOWN,
            score=_NOT_SCORED,
            evidence=_quote([job.location]),
            source="posting",
            confidence=0.0,
            explanation=f"the posting asks for {job.location!r}; the profile states no location",
        )
    posting_tokens = _tokens(job.location)
    overlaps = [
        claim
        for claim in place_claims
        if posting_tokens & _tokens(claim.text)
    ]
    score = 1.0 if overlaps else 0.0
    return DimensionResult(
        status=_band(score),
        score=score,
        evidence=_quote([job.location, *[claim.text for claim in place_claims]]),
        source="posting+profile",
        confidence=1.0,
        explanation=(
            f"the profile's location evidence shares words with {job.location!r}"
            if overlaps
            else f"the profile's locations share nothing with {job.location!r}"
        ),
    )


def _workplace_dimension(job: Job, evidence: CandidateEvidence) -> DimensionResult:
    preference_claims = [
        claim
        for claim in evidence.claims
        if claim.source.field_path.startswith("preferences.remote")
        or claim.source.field_path.endswith(".employment_type")
        or claim.source.field_path == "preferences.workplace_type"
    ]
    if not job.workplace_type and not preference_claims:
        return DimensionResult(
            status=DimensionStatus.NOT_APPLICABLE,
            score=_NOT_SCORED,
            source="posting",
            explanation="the posting states no workplace arrangement to compare",
        )
    if not job.workplace_type or not preference_claims:
        silent = "posting" if not job.workplace_type else "profile"
        stated = job.workplace_type or ", ".join(c.text for c in preference_claims)
        return DimensionResult(
            status=DimensionStatus.UNKNOWN,
            score=_NOT_SCORED,
            evidence=_quote([stated]),
            source="posting" if not preference_claims else "profile",
            confidence=0.0,
            explanation=f"the {silent} states an arrangement the other side does not",
        )
    wanted = set(_tokens(job.workplace_type))
    overlaps = any(wanted & _tokens(claim.text) for claim in preference_claims)
    score = 1.0 if overlaps else 0.0
    return DimensionResult(
        status=_band(score),
        score=score,
        evidence=_quote(
            [job.workplace_type, *[claim.text for claim in preference_claims]]
        ),
        source="posting+profile",
        confidence=1.0,
        explanation=(
            f"the profile's work preference overlaps {job.workplace_type!r}"
            if overlaps
            else f"the profile's work preference does not match {job.workplace_type!r}"
        ),
    )


def _seniority_dimension(job: Job) -> DimensionResult:
    if not job.experience_level:
        return DimensionResult(
            status=DimensionStatus.NOT_APPLICABLE,
            score=_NOT_SCORED,
            source="posting",
            explanation="the posting states no seniority level",
        )
    return DimensionResult(
        status=DimensionStatus.UNKNOWN,
        score=_NOT_SCORED,
        evidence=_quote([job.experience_level]),
        source="posting",
        confidence=0.0,
        explanation=(
            f"the posting asks for {job.experience_level!r}; "
            "the profile states no seniority fact to compare it with"
        ),
    )


# ---------------------------------------------------------------------------
# The candidate-side dimension: how much of the profile carries evidence
# ---------------------------------------------------------------------------
def _coverage_dimension(evidence: CandidateEvidence) -> DimensionResult:
    if not evidence.claims:
        return DimensionResult(
            status=DimensionStatus.UNKNOWN,
            score=_NOT_SCORED,
            source="profile",
            confidence=0.0,
            explanation="the profile states no claims to check for evidence",
        )
    backed = [
        claim
        for claim in evidence.claims
        if claim.source.evidence
        and any(
            excerpt.text_excerpt.strip() for excerpt in claim.source.evidence
        )
    ]
    verified = [claim for claim in backed if claim.source.status is FactStatus.VERIFIED]
    score = round(len(backed) / len(evidence.claims), 4)
    return DimensionResult(
        status=_band(score),
        score=score,
        evidence=_quote([claim.text for claim in backed] or [claim.text for claim in evidence.claims]),
        source="profile",
        confidence=1.0,
        explanation=(
            f"{len(backed)} of {len(evidence.claims)} profile claim(s) carry a "
            f"verbatim excerpt ({len(verified)} verified)"
        ),
    )


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------
def build_report(
    job: Job,
    requirements: Sequence[Requirement],
    evidence: CandidateEvidence,
    result: MatchResult,
) -> MatchReport:
    """Compose the eleven-dimension report from a finished match.

    Args:
        job: The posting, for the field-based dimensions.
        requirements: The rows the analysis produced, in document order.
        evidence: The candidate's claims and facts as the matcher saw them.
        result: The match result; its decision and gate are taken as-is.

    Returns:
        A report carrying all eleven dimensions. Deterministic: the same
        inputs always produce an equal model dump.
    """
    score_by_index: dict[int, RequirementScore] = {
        score.requirement_index: score
        for score in result.scores
        if score.requirement_index is not None
    }
    evaluation_by_index: dict[int, RequirementEvaluation] = {
        check.requirement_index: check.evaluation
        for check in result.gate.checks
        if check.requirement_index is not None
    }

    dimensions: dict[str, DimensionResult] = {}

    def from_kinds(name: str, kinds: frozenset[RequirementKind]) -> DimensionResult:
        return _dimension_from_rows(
            name,
            _rows_for_kinds(requirements, score_by_index, evaluation_by_index, kinds),
        )

    def from_priority(
        name: str, priority: RequirementPriority
    ) -> DimensionResult:
        return _dimension_from_rows(
            name,
            _rows_for_priority(
                requirements, score_by_index, evaluation_by_index, priority
            ),
        )

    dimensions["skill_match"] = from_kinds("skill_match", _SKILL_KINDS)
    dimensions["experience_match"] = _dimension_from_rows(
        "experience_match",
        _rows_where(
            requirements,
            score_by_index,
            evaluation_by_index,
            lambda requirement: requirement.kind in _EXPERIENCE_KINDS
            or requirement.min_years is not None,
        ),
    )
    dimensions["education_match"] = from_kinds("education_match", _EDUCATION_KINDS)
    dimensions["location_match"] = _location_dimension(job, evidence)
    dimensions["workplace_match"] = _workplace_dimension(job, evidence)
    dimensions["seniority_match"] = _seniority_dimension(job)
    dimensions["must_have_match"] = from_priority(
        "must_have_match", RequirementPriority.REQUIRED
    )
    dimensions["nice_to_have_match"] = from_priority(
        "nice_to_have_match", RequirementPriority.PREFERRED
    )
    dimensions["authorization_match"] = from_kinds(
        "authorization_match", _AUTHORIZATION_KINDS
    )
    dimensions["domain_match"] = from_kinds("domain_match", _DOMAIN_KINDS)
    dimensions["resume_evidence_coverage"] = _coverage_dimension(evidence)

    scored = [
        dimension.score
        for dimension in dimensions.values()
        if dimension.score is not None
    ]
    overall: Optional[float] = None
    alarms: list[str] = []
    if scored:
        weights = [
            DEFAULT_WEIGHTS[name]
            for name in DIMENSIONS
            if dimensions[name].score is not None
        ]
        overall = round(
            sum(
                dimension.score * DEFAULT_WEIGHTS[name]
                for name, dimension in dimensions.items()
                if dimension.score is not None
            )
            / sum(weights),
            4,
        )
        if overall == 0.0:
            alarms.append(
                "every scored dimension is zero; the profile may be empty "
                "rather than wrong"
            )
            log.warning("report alarmed: all dimensions zero", extra={"job": {"id": job.id}})

    matched = [
        score.requirement_text
        for score in result.scores
        if score.evaluation in _MATCHES
    ]
    missing = [
        score.requirement_text
        for score in result.scores
        if score.evaluation in _MISSES
    ]
    uncertain = [
        score.requirement_text
        for score in result.scores
        if score.evaluation in _UNCERTAIN
    ]

    blockers = [check.reason for check in result.gate.mismatches]

    grounded = sorted(
        {claim.source.field_path for claim in evidence.claims}
        | {"job_description"}
    )
    has_profile = bool(evidence.claims) or evidence.years_of_experience is not None
    has_similarity = any(score.similarity is not None for score in result.scores)
    source_parts = ["posting"]
    if has_profile:
        source_parts.append("profile")
    if has_similarity:
        source_parts.append("similarity")

    confidence = round(
        sum(dimension.confidence for dimension in dimensions.values())
        / len(DIMENSIONS),
        4,
    )

    return MatchReport(
        decision=result.decision,
        gate_status=result.gate.status,
        hard_blockers=blockers,
        dimension_scores=dimensions,
        overall_match=overall,
        matched_requirements=matched,
        missing_requirements=missing,
        uncertain_requirements=uncertain,
        explanations=[dimensions[name].explanation for name in DIMENSIONS],
        confidence=confidence,
        evidence_source="+".join(source_parts),
        grounded_in=grounded,
        alarms=alarms,
    )
