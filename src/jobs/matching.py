"""Hybrid matching: evidence decides what it can, similarity weighs the rest.

"Hybrid" is an order of authority, not a blend:

1. **The hard gate** — years and sponsorship, read from facts. It vetoes
   and is never outvoted; when it is not ``PASS`` this module does not
   score at all, because a score that could soften a veto would be the
   veto's undoing.
2. **Claim membership** — a requirement whose comparison form names
   something the profile claims is decided by the profile. ``VERIFIED``
   claims match as ``VERIFIED_MATCH``; ``INFERRED`` claims match too, as
   ``DERIVED_MATCH`` — honest but weaker, and the label keeps the
   difference visible.
3. **Semantic similarity** — only where no claim answers. The scorer's
   best score against any single claim decides, in three bands: strong
   enough is a derived match, close is a human question, far apart is a
   derived miss. A scorer that fails, or the absence of one, yields
   ``UNKNOWN``: no score is not a small score.
4. **Empty evidence** — a profile with no claims at all makes every open
   row ``UNKNOWN`` rather than mismatching. Nothing stated is not
   something contradicted.

The top-level decision follows published rules only. ``HARD_MISMATCH``
comes from the gate and nowhere else; a derived miss on a stated must
downgrades to ``PARTIAL_MATCH``, because arithmetic on a resume parse is
not the same order of fact as a profile that says no.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    FactStatus,
    HardGateStatus,
    MatchDecision,
    RequirementEvaluation,
    RequirementPriority,
)
from core.logging_config import get_logger
from jobs.candidate import CandidateEvidence
from jobs.hard_gate import HardGateResult, evaluate_hard_gate, is_gated
from jobs.models import Requirement, RequirementKind

if TYPE_CHECKING:
    # Typing only: matching holds the protocol, not the provider. Nothing
    # in this module imports ai at runtime, so the seam stays where it is.
    from ai.embeddings import SemanticScorer

__all__ = ["MatchResult", "RequirementScore", "evaluate_match"]

log = get_logger(__name__)

#: At or above this, the closest claim is taken as the requirement said it.
MATCH_BAND = 0.75
#: At or above this — but below MATCH_BAND — the resemblance is close
#: enough to be worth a human's eyes and not close enough to decide.
REVIEW_BAND = 0.45


class RequirementScore(BaseModel):
    """How one requirement stands against the candidate, and why.

    Attributes:
        requirement_text: The row as the extractor read it.
        kind: Its category.
        priority: Its priority; only ``REQUIRED`` and ``PREFERRED`` rows
            influence the decision, and ``REQUIRED`` ones weigh hardest.
        evaluation: The verdict for this row.
        similarity: The scorer's number when similarity decided, else
            ``None`` — facts do not produce scores.
        reason: One sentence naming the claim or number behind it.
        candidate_field_path: Profile field of the claim that answered, if
            one did.
        requirement_index: Position of the row in the requirements list the
            match ran over, so an explanation can line every artifact back
            up with the posting.
    """

    model_config = ConfigDict(extra="forbid")

    requirement_text: str
    kind: RequirementKind
    priority: RequirementPriority
    evaluation: RequirementEvaluation
    similarity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reason: str
    candidate_field_path: Optional[str] = None
    requirement_index: Optional[int] = None


class MatchResult(BaseModel):
    """The matcher's verdict: the gate's, the row scores, and a summary.

    Attributes:
        decision: Composed by fixed rules from the gate and the scores;
            never chosen by a model.
        gate: The embedded hard-gate result — the rows it claimed are not
            repeated in ``scores``, they are the gate's to explain.
        scores: Every row the matcher judged, in document order.
        similarity_score: Mean of the similarities that were computed,
            or ``None`` when similarity decided nothing (all claims, or no
            scorer). Sorts review queues; never overrides ``decision``.
    """

    model_config = ConfigDict(extra="forbid")

    decision: MatchDecision
    gate: HardGateResult
    scores: list[RequirementScore] = Field(default_factory=list)
    similarity_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @property
    def is_positive(self) -> bool:
        return self.decision.is_positive

    @property
    def requires_human(self) -> bool:
        return self.decision.requires_human


def evaluate_match(
    requirements: Sequence[Requirement],
    evidence: CandidateEvidence,
    *,
    scorer: Optional["SemanticScorer"] = None,
    gate: Optional[HardGateResult] = None,
) -> MatchResult:
    """Match one posting against one candidate, in the published order.

    Args:
        requirements: Rows as the extractor produced them.
        evidence: The candidate's claims, years, and sponsorship answer.
        scorer: Similarity implementation, or ``None`` to leave open rows
            ``UNKNOWN`` — the safe default, since matching must work with
            no model configured.
        gate: A precomputed gate result to reuse; computed here when
            omitted.

    Returns:
        The decision, the gate it rests on, and the scores behind both.
    """
    if gate is None:
        gate = evaluate_hard_gate(requirements, evidence)
    if gate.status is not HardGateStatus.PASS:
        decision = _decision_from_gate(gate)
        log.info(
            "match decided by the gate",
            extra={"match": {"decision": decision.value, "gate": gate.status.value}},
        )
        return MatchResult(decision=decision, gate=gate, scores=[])

    scores = [
        _score_row(requirement, evidence, scorer, index)
        for index, requirement in enumerate(requirements)
        if not is_gated(requirement)
    ]
    decision = _decision_from_scores(scores)
    similarities = [
        score.similarity for score in scores if score.similarity is not None
    ]
    similarity_score = (
        round(sum(similarities) / len(similarities), 4) if similarities else None
    )
    log.info(
        "match evaluated",
        extra={
            "match": {
                "decision": decision.value,
                "scores": len(scores),
                "similarity": similarity_score,
            }
        },
    )
    return MatchResult(
        decision=decision,
        gate=gate,
        scores=scores,
        similarity_score=similarity_score,
    )


def _decision_from_gate(gate: HardGateResult) -> MatchDecision:
    if gate.status is HardGateStatus.HARD_MISMATCH:
        return MatchDecision.HARD_MISMATCH
    if gate.status is HardGateStatus.UNKNOWN:
        return MatchDecision.INSUFFICIENT_EVIDENCE
    if gate.status is HardGateStatus.REVIEW_REQUIRED:
        return MatchDecision.REVIEW_REQUIRED
    return MatchDecision.MATCH


def _score_row(
    requirement: Requirement,
    evidence: CandidateEvidence,
    scorer: Optional["SemanticScorer"],
    index: int,
) -> RequirementScore:
    key = requirement.normalized or requirement.text
    claim = evidence.claim_for(key)
    if claim is not None:
        verified = claim.source.status is FactStatus.VERIFIED
        evaluation = (
            RequirementEvaluation.VERIFIED_MATCH
            if verified
            else RequirementEvaluation.DERIVED_MATCH
        )
        reason = f'the profile claims "{claim.text}"'
        if not verified:
            reason += " (inferred)"
        return RequirementScore(
            requirement_text=requirement.text,
            kind=requirement.kind,
            priority=requirement.priority,
            evaluation=evaluation,
            reason=reason,
            candidate_field_path=claim.source.field_path,
            requirement_index=index,
        )
    return _score_by_similarity(requirement, evidence, scorer, index)


def _score_by_similarity(
    requirement: Requirement,
    evidence: CandidateEvidence,
    scorer: Optional["SemanticScorer"],
    index: int,
) -> RequirementScore:
    base = {
        "requirement_text": requirement.text,
        "kind": requirement.kind,
        "priority": requirement.priority,
        "requirement_index": index,
    }
    if not evidence.claims:
        return RequirementScore(
            **base,
            evaluation=RequirementEvaluation.UNKNOWN,
            reason="the profile states no claims to compare against",
        )
    if scorer is None:
        return RequirementScore(
            **base,
            evaluation=RequirementEvaluation.UNKNOWN,
            reason="no claim matches and no scorer is configured",
        )
    try:
        best_similarity, best_claim = max(
            (
                (scorer.similarity(requirement.text, claim.text), claim)
                for claim in evidence.claims
            ),
            key=lambda pair: pair[0],
        )
    except Exception:
        # Any failure is UNKNOWN, never a miss: a scorer that broke must
        # not be able to turn silence into a verdict against the candidate.
        log.warning("scorer failed; leaving the row undecided")
        return RequirementScore(
            **base,
            evaluation=RequirementEvaluation.UNKNOWN,
            reason="the scorer failed; nothing may be decided",
        )
    reason = f'closest claim "{best_claim.text}" scores {best_similarity:.2f}'
    if best_similarity >= MATCH_BAND:
        evaluation = RequirementEvaluation.DERIVED_MATCH
    elif best_similarity >= REVIEW_BAND:
        evaluation = RequirementEvaluation.REVIEW_REQUIRED
    else:
        evaluation = RequirementEvaluation.DERIVED_MISMATCH
    return RequirementScore(
        **base,
        evaluation=evaluation,
        similarity=best_similarity,
        reason=reason,
        candidate_field_path=best_claim.source.field_path,
    )


def _decision_from_scores(scores: Sequence[RequirementScore]) -> MatchDecision:
    """Fixed composition of the row scores. Precedence, top to bottom:

    an undecided stated must means the evidence is insufficient (or a
    human is needed, when only ambiguity remains); a derived miss on a
    stated must downgrades to partial; an unmet preference downgrades to
    partial; otherwise the posting is a match. Rows the posting did not
    state a priority for are reported but never weighed.
    """
    required = [s for s in scores if s.priority is RequirementPriority.REQUIRED]
    preferred = [s for s in scores if s.priority is RequirementPriority.PREFERRED]

    if any(s.evaluation is RequirementEvaluation.UNKNOWN for s in required):
        return MatchDecision.INSUFFICIENT_EVIDENCE
    if any(s.evaluation is RequirementEvaluation.REVIEW_REQUIRED for s in required):
        return MatchDecision.REVIEW_REQUIRED
    if any(s.evaluation.is_mismatch for s in required):
        return MatchDecision.PARTIAL_MATCH
    if any(s.evaluation.is_mismatch for s in preferred):
        return MatchDecision.PARTIAL_MATCH
    return MatchDecision.MATCH
