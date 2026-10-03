"""The hard gate: deterministic eligibility checks that run before any scoring.

Some things about a posting are not a matter of degree. If the posting asks
for three years and the profile states one, no amount of keyword overlap or
semantic similarity changes the answer, so the answer is decided here — from
evidence only — and the scorer never gets a vote. The enum says it plainly:
"a high semantic similarity cannot move this to PASS".

What gates, and what deliberately does not:

* **Years.** A stated minimum (``min_years`` on a required row) against the
  profile's total years. Below it is a ``DERIVED_MISMATCH`` — derived,
  because arithmetic on two stated values is still one step away from a
  quote. The profile having no figure is ``UNKNOWN``, never a pass and
  never a fail: nobody knows, so nothing may be decided.
* **Sponsorship.** A required row that says the posting will not sponsor
  against the profile's ``requires_sponsorship``. Both sides read directly,
  so the outcomes are ``VERIFIED_*``. A row whose direction cannot be read
  safely is ``REVIEW_REQUIRED`` — an unreadable disqualifier is exactly the
  thing a human should see.
* **Nothing else.** A missing skill or a lower degree is not gated: a
  profile that does not mention Python has not proven it lacks Python, and
  failing candidates on absence of a word would reject people for how they
  wrote a resume. Skills are scored (``jobs.matching``) and explained, not
  gated.

Only requirements the posting states as ``REQUIRED`` gate at all. A
"nice to have five years" preference cannot fail anyone.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    HardGateStatus,
    RequirementEvaluation,
    RequirementPriority,
)
from core.logging_config import get_logger
from jobs.candidate import CandidateEvidence
from jobs.models import Requirement, RequirementKind

__all__ = ["GateCheck", "HardGateResult", "evaluate_hard_gate", "is_gated"]

log = get_logger(__name__)

# Sponsorship direction, read from the requirement's own words. Substring
# order matters: "no sponsorship available" contains "sponsorship available",
# so the forbidding phrases are always asked first.
_FORBIDS_MARKERS = (
    "no sponsorship",
    "without sponsorship",
    "not require sponsorship",
    "not requiring sponsorship",
    "cannot sponsor",
    "can't sponsor",
    "will not sponsor",
    "won't sponsor",
)
_ALLOWS_MARKERS = (
    "sponsorship available",
    "sponsorship offered",
    "sponsorship provided",
    "offer sponsorship",
    "we sponsor",
    "we can sponsor",
)


class _Direction(Enum):
    FORBIDS = "FORBIDS"
    ALLOWS = "ALLOWS"
    UNCLEAR = "UNCLEAR"


class GateCheck(BaseModel):
    """One hard requirement read against the candidate's evidence.

    Attributes:
        requirement_text: The row as the extractor read it, quoted so a
            reviewer can find it in the posting.
        kind: Category of the requirement.
        priority: Priority the posting gave it; only ``REQUIRED`` rows
            appear in a gate result at all.
        evaluation: How the evidence stands against it.
        reason: One sentence a human can act on, with both sides of the
            comparison in it.
        candidate_field_path: The profile field the answer came from, or
            ``None`` when the profile says nothing.
        requirement_index: Position of the row in the requirements list the
            gate ran over, so an explanation can line every artifact back
            up with the posting. ``None`` only when constructed outside a
            gate run.
    """

    model_config = ConfigDict(extra="forbid")

    requirement_text: str
    kind: RequirementKind
    priority: RequirementPriority
    evaluation: RequirementEvaluation
    reason: str
    candidate_field_path: Optional[str] = None
    requirement_index: Optional[int] = None


class HardGateResult(BaseModel):
    """The gate's verdict, with every check that produced it.

    The status is composed from the checks by fixed precedence — a
    definitive mismatch outranks an unreadable one, which outranks silence:
    ``HARD_MISMATCH`` then ``UNKNOWN`` then ``REVIEW_REQUIRED``, else
    ``PASS``. Nothing outside this module composes it, so the same inputs
    always give the same verdict.
    """

    model_config = ConfigDict(extra="forbid")

    status: HardGateStatus
    checks: list[GateCheck] = Field(default_factory=list)

    @property
    def mismatches(self) -> list[GateCheck]:
        return [check for check in self.checks if check.evaluation.is_mismatch]

    @property
    def uncertain(self) -> list[GateCheck]:
        return [check for check in self.checks if check.evaluation.is_uncertain]

    @property
    def blocks(self) -> bool:
        """Whether this verdict may prevent a ``MATCH`` decision."""
        return self.status.blocks_match


def is_gated(requirement: Requirement) -> bool:
    """Whether this row belongs to the gate rather than to scoring.

    A stated must with a hard dimension — a number of years, or a
    sponsorship answer — is decided from evidence alone. Everything else,
    including every preference, is left for scoring: this predicate is the
    single definition of the split, used by the gate itself and by the
    matcher, so the two can never disagree about which rows they own.
    """
    if requirement.priority is not RequirementPriority.REQUIRED:
        return False
    return requirement.min_years is not None or (
        requirement.kind is RequirementKind.SPONSORSHIP
    )


def evaluate_hard_gate(
    requirements: Sequence[Requirement],
    evidence: CandidateEvidence,
) -> HardGateResult:
    """Run the deterministic gate over one posting's requirements.

    Args:
        requirements: Rows as the extractor produced them, any source.
        evidence: The candidate's claims, years, and sponsorship answer.

    Returns:
        The composed status and the checks behind it. With no required rows
        to gate there is nothing that can fail, which is a ``PASS`` with an
        empty check list — a clean posting is not the same as an untested
        one, and the check list is what tells them apart.
    """
    checks: list[GateCheck] = []
    for index, requirement in enumerate(requirements):
        if not is_gated(requirement):
            continue
        if requirement.min_years is not None:
            checks.append(_check_years(requirement, evidence, index))
        if requirement.kind is RequirementKind.SPONSORSHIP:
            direction = _direction_of(requirement)
            if direction is _Direction.ALLOWS:
                # The posting sponsors; no sponsorship answer can disqualify.
                continue
            checks.append(_check_sponsorship(requirement, evidence, direction, index))

    status = _compose(checks)
    log.info(
        "hard gate evaluated",
        extra={"gate": {"status": status.value, "checks": len(checks)}},
    )
    return HardGateResult(status=status, checks=checks)


def _check_years(
    requirement: Requirement, evidence: CandidateEvidence, index: int
) -> GateCheck:
    minimum = requirement.min_years or 0.0
    years = evidence.years_of_experience
    field_path = (
        evidence.years_source.field_path if evidence.years_source is not None else None
    )
    if years is None:
        evaluation = RequirementEvaluation.UNKNOWN
        reason = (
            f"the posting requires {minimum:g}+ years; the profile states nothing"
        )
    elif years < minimum:
        evaluation = RequirementEvaluation.DERIVED_MISMATCH
        reason = (
            f"the posting requires {minimum:g}+ years; the profile states "
            f"{years:g}"
        )
    else:
        evaluation = RequirementEvaluation.DERIVED_MATCH
        reason = (
            f"the posting requires {minimum:g}+ years; the profile states "
            f"{years:g}"
        )
    return GateCheck(
        requirement_text=requirement.text,
        kind=requirement.kind,
        priority=requirement.priority,
        evaluation=evaluation,
        reason=reason,
        candidate_field_path=field_path,
        requirement_index=index,
    )


def _check_sponsorship(
    requirement: Requirement,
    evidence: CandidateEvidence,
    direction: _Direction,
    index: int,
) -> GateCheck:
    field_path = (
        evidence.sponsorship_source.field_path
        if evidence.sponsorship_source is not None
        else None
    )
    if direction is _Direction.UNCLEAR:
        evaluation = RequirementEvaluation.REVIEW_REQUIRED
        reason = "the posting's sponsorship requirement could not be read safely"
        field_path = None
    elif evidence.requires_sponsorship is None:
        evaluation = RequirementEvaluation.UNKNOWN
        reason = (
            "the posting does not sponsor and the profile does not say whether "
            "sponsorship is needed"
        )
    elif evidence.requires_sponsorship:
        evaluation = RequirementEvaluation.VERIFIED_MISMATCH
        reason = (
            "the posting does not sponsor and the profile says sponsorship "
            "is required"
        )
    else:
        evaluation = RequirementEvaluation.VERIFIED_MATCH
        reason = (
            "the posting does not sponsor and the profile says sponsorship "
            "is not required"
        )
    return GateCheck(
        requirement_text=requirement.text,
        kind=requirement.kind,
        priority=requirement.priority,
        evaluation=evaluation,
        reason=reason,
        candidate_field_path=field_path,
        requirement_index=index,
    )


def _direction_of(requirement: Requirement) -> _Direction:
    text = (requirement.normalized or requirement.text).lower()
    if any(marker in text for marker in _FORBIDS_MARKERS):
        return _Direction.FORBIDS
    if any(marker in text for marker in _ALLOWS_MARKERS):
        return _Direction.ALLOWS
    # A row that mentions sponsorship without one of the phrases above —
    # "case by case", "visa status required" — says nothing this reader can
    # act on, and a disqualifier nobody can read is for a human, not a gate.
    return _Direction.UNCLEAR


def _compose(checks: Iterable[GateCheck]) -> HardGateStatus:
    evaluations = [check.evaluation for check in checks]
    if any(evaluation.is_mismatch for evaluation in evaluations):
        return HardGateStatus.HARD_MISMATCH
    if RequirementEvaluation.UNKNOWN in evaluations:
        return HardGateStatus.UNKNOWN
    if RequirementEvaluation.REVIEW_REQUIRED in evaluations:
        return HardGateStatus.REVIEW_REQUIRED
    return HardGateStatus.PASS
