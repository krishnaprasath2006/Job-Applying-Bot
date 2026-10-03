"""Hybrid matching: the gate vetoes, claims decide, similarity only fills in.

The order of authority is what these tests pin down. A hard-gate failure
must short-circuit before any scorer runs; an exact claim must beat any
similarity; and where nothing can decide the answer must be *unknown* —
never a quiet pass, and never a quiet fail dressed as a small score.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai.embeddings import LexicalScorer
from core.enums import (
    EvidenceSourceType,
    FactStatus,
    HardGateStatus,
    MatchDecision,
    RequirementEvaluation,
    RequirementPriority,
)
from core.evidence import Evidence
from jobs.candidate import CandidateClaim, CandidateEvidence, FactRef
from jobs.hard_gate import HardGateResult
from jobs.matching import MatchResult, RequirementScore, evaluate_match
from jobs.models import Requirement, RequirementKind


def a_requirement(
    text: str,
    *,
    kind: RequirementKind = RequirementKind.OTHER,
    priority: RequirementPriority = RequirementPriority.REQUIRED,
    min_years: float | None = None,
) -> Requirement:
    return Requirement(
        text=text, kind=kind, priority=priority, min_years=min_years
    )


def a_candidate(
    *,
    claims: tuple[str, ...] = (),
    years: float | None = None,
    sponsorship: bool | None = None,
    inferred: bool = False,
) -> CandidateEvidence:
    status = FactStatus.INFERRED if inferred else FactStatus.VERIFIED
    return CandidateEvidence(
        claims=[
            CandidateClaim(
                text=text,
                source=FactRef(
                    field_path="skills.proficient",
                    status=status,
                    evidence=[
                        Evidence(
                            source_type=EvidenceSourceType.RESUME,
                            source_id="resume.txt",
                            text_excerpt=text,
                        )
                    ],
                ),
            )
            for text in claims
        ],
        years_of_experience=years,
        years_source=(
            FactRef(
                field_path="experience.total_years_experience",
                status=FactStatus.VERIFIED,
            )
            if years is not None
            else None
        ),
        requires_sponsorship=sponsorship,
        sponsorship_source=(
            FactRef(
                field_path="authorization.requires_sponsorship",
                status=FactStatus.VERIFIED,
            )
            if sponsorship is not None
            else None
        ),
    )


class ThrowingScorer:
    def similarity(self, left: str, right: str) -> float:
        raise RuntimeError("the model is down")


# ---------------------------------------------------------------------------
# The veto
# ---------------------------------------------------------------------------
class TestTheVeto:
    def test_a_gate_failure_never_reaches_scoring(self) -> None:
        result = evaluate_match(
            [
                a_requirement("3+ years required", min_years=3.0),
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                ),
            ],
            a_candidate(claims=("Python",), years=1.0),
            scorer=LexicalScorer(),
        )
        assert result.decision is MatchDecision.HARD_MISMATCH
        assert result.gate.status is HardGateStatus.HARD_MISMATCH
        assert result.scores == []
        assert result.similarity_score is None

    def test_an_unknown_gate_becomes_insufficient_evidence(self) -> None:
        result = evaluate_match(
            [a_requirement("3+ years required", min_years=3.0)],
            a_candidate(),
            scorer=LexicalScorer(),
        )
        assert result.decision is MatchDecision.INSUFFICIENT_EVIDENCE
        assert result.scores == []

    def test_a_gate_review_becomes_a_review_request(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "Sponsorship case by case",
                    kind=RequirementKind.SPONSORSHIP,
                )
            ],
            a_candidate(),
            scorer=LexicalScorer(),
        )
        assert result.decision is MatchDecision.REVIEW_REQUIRED
        assert result.scores == []

    def test_a_precomputed_gate_is_reused_not_recomputed(self) -> None:
        result = evaluate_match(
            [],
            a_candidate(),
            gate=HardGateResult(status=HardGateStatus.HARD_MISMATCH),
        )
        assert result.decision is MatchDecision.HARD_MISMATCH
        assert result.gate.checks == []


# ---------------------------------------------------------------------------
# Claim membership
# ---------------------------------------------------------------------------
class TestClaimMembership:
    def test_an_exact_claim_is_a_verified_match(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                )
            ],
            a_candidate(claims=("Python",)),
            scorer=LexicalScorer(),
        )
        assert result.decision is MatchDecision.MATCH
        assert result.scores[0].evaluation is RequirementEvaluation.VERIFIED_MATCH
        assert result.scores[0].similarity is None
        assert result.scores[0].candidate_field_path == "skills.proficient"
        assert '"Python"' in result.scores[0].reason

    def test_an_inferred_claim_matches_but_says_so(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                )
            ],
            a_candidate(claims=("Python",), inferred=True),
        )
        assert result.decision is MatchDecision.MATCH
        assert result.scores[0].evaluation is RequirementEvaluation.DERIVED_MATCH
        assert "inferred" in result.scores[0].reason

    def test_gate_claimed_rows_are_not_scored_again(self) -> None:
        result = evaluate_match(
            [
                a_requirement("3+ years required", min_years=3.0),
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                ),
            ],
            a_candidate(claims=("Python",), years=5.0),
            scorer=LexicalScorer(),
        )
        assert result.gate.status is HardGateStatus.PASS
        assert [score.requirement_text for score in result.scores] == ["Python"]
        assert result.decision is MatchDecision.MATCH

    def test_both_required_claims_present_is_a_match(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                ),
                a_requirement("SQL", kind=RequirementKind.DATABASE),
            ],
            a_candidate(claims=("Python", "SQL")),
        )
        assert result.decision is MatchDecision.MATCH
        assert all(
            score.evaluation is RequirementEvaluation.VERIFIED_MATCH
            for score in result.scores
        )


# ---------------------------------------------------------------------------
# Where only similarity can answer
# ---------------------------------------------------------------------------
class TestSimilarityDecides:
    def test_a_requirement_wrapping_a_claim_matches_semantically(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "Experience with PyTorch",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                )
            ],
            a_candidate(claims=("PyTorch",)),
            scorer=LexicalScorer(),
        )
        score = result.scores[0]
        assert score.evaluation is RequirementEvaluation.DERIVED_MATCH
        assert score.similarity == 1.0
        assert '"PyTorch"' in score.reason
        assert result.decision is MatchDecision.MATCH

    def test_a_barely_related_requirement_is_a_derived_miss(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "COBOL",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                )
            ],
            a_candidate(claims=("Python", "SQL")),
            scorer=LexicalScorer(),
        )
        score = result.scores[0]
        assert score.evaluation is RequirementEvaluation.DERIVED_MISMATCH
        assert score.similarity == 0.0
        # A derived miss on a stated must downgrades; it never hard-fails.
        assert result.decision is MatchDecision.PARTIAL_MATCH

    def test_a_close_but_unsettled_resemblance_goes_to_review(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "Python COBOL",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                )
            ],
            a_candidate(claims=("Python Rust",)),
            scorer=LexicalScorer(),
        )
        score = result.scores[0]
        assert score.evaluation is RequirementEvaluation.REVIEW_REQUIRED
        assert score.similarity == 0.5
        assert result.decision is MatchDecision.REVIEW_REQUIRED

    def test_without_a_scorer_an_unclaimed_row_is_unknown(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "PyTorch",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                )
            ],
            a_candidate(claims=("SQL",)),
            scorer=None,
        )
        score = result.scores[0]
        assert score.evaluation is RequirementEvaluation.UNKNOWN
        assert score.similarity is None
        assert "no scorer" in score.reason
        assert result.decision is MatchDecision.INSUFFICIENT_EVIDENCE

    def test_a_scorer_that_fails_leaves_the_row_unknown(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "PyTorch",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                )
            ],
            a_candidate(claims=("SQL",)),
            scorer=ThrowingScorer(),
        )
        assert result.scores[0].evaluation is RequirementEvaluation.UNKNOWN
        assert "scorer failed" in result.scores[0].reason
        assert result.decision is MatchDecision.INSUFFICIENT_EVIDENCE

    def test_empty_evidence_is_not_a_miss(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                )
            ],
            a_candidate(),
            scorer=LexicalScorer(),
        )
        assert result.scores[0].evaluation is RequirementEvaluation.UNKNOWN
        assert "no claims" in result.scores[0].reason
        assert result.decision is MatchDecision.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# Composition of the decision
# ---------------------------------------------------------------------------
class TestDecisionRules:
    def test_no_requirements_is_a_match(self) -> None:
        result = evaluate_match([], a_candidate())
        assert result.decision is MatchDecision.MATCH
        assert result.scores == []
        assert result.similarity_score is None
        assert result.gate.status is HardGateStatus.PASS

    def test_an_unmet_preference_downgrades_to_partial(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                ),
                a_requirement(
                    "Rust",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                    priority=RequirementPriority.PREFERRED,
                ),
            ],
            a_candidate(claims=("Python",)),
            scorer=LexicalScorer(),
        )
        assert result.decision is MatchDecision.PARTIAL_MATCH

    def test_a_row_with_no_stated_priority_never_changes_the_decision(
        self,
    ) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                ),
                a_requirement(
                    "COBOL",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                    priority=RequirementPriority.UNKNOWN,
                ),
            ],
            a_candidate(claims=("Python",)),
            scorer=LexicalScorer(),
        )
        assert result.decision is MatchDecision.MATCH
        assert len(result.scores) == 2

    def test_the_similarity_score_means_what_was_computed(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "Experience with PyTorch",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                ),
                a_requirement(
                    "COBOL",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                ),
            ],
            a_candidate(claims=("PyTorch",)),
            scorer=LexicalScorer(),
        )
        assert result.similarity_score == 0.5
        assert result.decision is MatchDecision.PARTIAL_MATCH

    def test_no_computed_similarity_means_no_similarity_score(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                )
            ],
            a_candidate(claims=("Python",)),
            scorer=LexicalScorer(),
        )
        assert result.similarity_score is None

    @pytest.mark.parametrize(
        ("decision", "positive", "human"),
        [
            (MatchDecision.MATCH, True, False),
            (MatchDecision.PARTIAL_MATCH, True, False),
            (MatchDecision.REVIEW_REQUIRED, False, True),
            (MatchDecision.INSUFFICIENT_EVIDENCE, False, True),
            (MatchDecision.HARD_MISMATCH, False, False),
        ],
    )
    def test_the_decision_carries_its_meaning(
        self, decision: MatchDecision, positive: bool, human: bool
    ) -> None:
        assert decision.is_positive is positive
        assert decision.requires_human is human


# ---------------------------------------------------------------------------
# Precedence with a real scorer in the room
# ---------------------------------------------------------------------------
class ScriptedScorer:
    """Answers with one fixed number, and can be told to fail on demand.

    The tests below care about *when* the scorer runs and *what its answer
    is allowed to change* - never about the arithmetic of a particular
    model, so one number and one failure switch say everything needed.
    """

    def __init__(self, *, value: float = 1.0, fails_on: str | None = None) -> None:
        self.value = value
        self.fails_on = fails_on
        self.calls: list[tuple[str, str]] = []

    def similarity(self, left: str, right: str) -> float:
        self.calls.append((left, right))
        if self.fails_on is not None and (
            self.fails_on in left or self.fails_on in right
        ):
            raise RuntimeError("provider hiccup")
        return self.value


class TestPrecedenceWithAScorer:
    def test_a_perfect_scorer_never_runs_after_a_gate_failure(self) -> None:
        scorer = ScriptedScorer(value=1.0)
        result = evaluate_match(
            [
                a_requirement("3+ years required", min_years=3.0),
                a_requirement("Python", kind=RequirementKind.PROGRAMMING_LANGUAGE),
            ],
            a_candidate(claims=("Python",), years=1.0),
            scorer=scorer,
        )
        # The veto stands, and nothing was even asked: a score computed
        # after a hard failure would be a score with no say.
        assert result.decision is MatchDecision.HARD_MISMATCH
        assert result.gate.status is HardGateStatus.HARD_MISMATCH
        assert result.scores == []
        assert scorer.calls == []

    def test_a_perfect_scorer_never_runs_when_the_gate_is_unknown(self) -> None:
        scorer = ScriptedScorer(value=1.0)
        result = evaluate_match(
            [a_requirement("3+ years required", min_years=3.0)],
            a_candidate(claims=("Python",)),
            scorer=scorer,
        )
        assert result.decision is MatchDecision.INSUFFICIENT_EVIDENCE
        assert result.scores == []
        assert scorer.calls == []

    def test_one_undecided_required_row_outweighs_a_perfect_one(self) -> None:
        scorer = ScriptedScorer(value=1.0, fails_on="SQL")
        result = evaluate_match(
            [
                a_requirement(
                    "Experience with PyTorch",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                ),
                a_requirement("SQL", kind=RequirementKind.PROGRAMMING_LANGUAGE),
            ],
            a_candidate(claims=("Python",)),
            scorer=scorer,
        )
        # One row scored perfectly, one row the scorer could not answer:
        # silence on a stated must is insufficiency, not a rescued match.
        assert result.scores[0].evaluation is RequirementEvaluation.DERIVED_MATCH
        assert result.scores[1].evaluation is RequirementEvaluation.UNKNOWN
        assert result.decision is MatchDecision.INSUFFICIENT_EVIDENCE
        assert result.similarity_score == 1.0

    def test_insufficient_evidence_outranks_a_review_row(self) -> None:
        scorer = ScriptedScorer(value=0.5, fails_on="SQL")
        result = evaluate_match(
            [
                a_requirement(
                    "Experience with PyTorch",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                ),
                a_requirement("SQL", kind=RequirementKind.PROGRAMMING_LANGUAGE),
            ],
            a_candidate(claims=("Python",)),
            scorer=scorer,
        )
        # A row waiting for review plus a row nobody could answer: the
        # missing evidence wins, because a reviewer cannot review silence.
        assert result.scores[0].evaluation is RequirementEvaluation.REVIEW_REQUIRED
        assert result.scores[1].evaluation is RequirementEvaluation.UNKNOWN
        assert result.decision is MatchDecision.INSUFFICIENT_EVIDENCE

    def test_a_perfect_scorer_decides_only_where_no_claim_does(self) -> None:
        scorer = ScriptedScorer(value=1.0)
        result = evaluate_match(
            [
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                ),
                a_requirement(
                    "Experience with PyTorch",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                ),
            ],
            a_candidate(claims=("Python",)),
            scorer=scorer,
        )
        # The exact claim never consults the scorer; only the open row
        # does - semantic input is one input, not a second opinion on
        # facts the profile already states.
        assert result.scores[0].evaluation is RequirementEvaluation.VERIFIED_MATCH
        assert result.scores[1].evaluation is RequirementEvaluation.DERIVED_MATCH
        assert result.decision is MatchDecision.MATCH
        assert [left for left, _ in scorer.calls] == ["Experience with PyTorch"]


# ---------------------------------------------------------------------------
# The models themselves
# ---------------------------------------------------------------------------
class TestModels:
    def test_an_unknown_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            RequirementScore(
                requirement_text="Python",
                kind=RequirementKind.OTHER,
                priority=RequirementPriority.REQUIRED,
                evaluation=RequirementEvaluation.UNKNOWN,
                reason="x",
                bogus=True,  # type: ignore[call-arg]
            )

    def test_a_similarity_outside_the_range_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            RequirementScore(
                requirement_text="Python",
                kind=RequirementKind.OTHER,
                priority=RequirementPriority.REQUIRED,
                evaluation=RequirementEvaluation.DERIVED_MATCH,
                reason="x",
                similarity=1.5,
            )

    def test_the_result_survives_a_round_trip(self) -> None:
        original = evaluate_match(
            [
                a_requirement("3+ years required", min_years=3.0),
                a_requirement(
                    "Experience with PyTorch",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                ),
            ],
            a_candidate(claims=("PyTorch",), years=5.0),
            scorer=LexicalScorer(),
        )
        assert MatchResult.model_validate(original.model_dump()) == original

    def test_positive_and_human_flags_follow_the_decision(self) -> None:
        result = evaluate_match(
            [
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                )
            ],
            a_candidate(claims=("Python",)),
        )
        assert result.is_positive is True
        assert result.requires_human is False
