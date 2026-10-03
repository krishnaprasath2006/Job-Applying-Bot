"""The hard gate: one year against a stated three must fail, every time.

The gate is judged on what it refuses to do as much as what it decides: a
preference cannot fail a candidate, a missing skill is not evidence of
absence, and a profile that says nothing yields ``UNKNOWN`` — never a pass.
The headline case is the first test below: the posting asks for three years,
the profile states one, and no rule anywhere lets that come back green.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.enums import (
    EvidenceSourceType,
    FactStatus,
    HardGateStatus,
    RequirementEvaluation,
    RequirementPriority,
)
from core.evidence import Evidence, Fact
from jobs.candidate import CandidateEvidence, FactRef
from jobs.hard_gate import GateCheck, HardGateResult, evaluate_hard_gate
from jobs.models import Requirement, RequirementKind
from jobs.requirements import extract_requirements


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
    years: float | None = None, sponsorship: bool | None = None
) -> CandidateEvidence:
    return CandidateEvidence(
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


# ---------------------------------------------------------------------------
# Years
# ---------------------------------------------------------------------------
class TestYearsGate:
    def test_one_year_against_stated_three_is_a_hard_mismatch(self) -> None:
        result = evaluate_hard_gate(
            [a_requirement("3+ years of experience required", min_years=3.0)],
            a_candidate(years=1.0),
        )
        assert result.status is HardGateStatus.HARD_MISMATCH
        assert len(result.checks) == 1
        check = result.checks[0]
        assert check.evaluation is RequirementEvaluation.DERIVED_MISMATCH
        assert check.evaluation.is_mismatch
        assert "3" in check.reason and "1" in check.reason
        assert check.candidate_field_path == "experience.total_years_experience"

    @pytest.mark.parametrize("years", [3.0, 5.0, 40.0])
    def test_meeting_the_minimum_passes(self, years: float) -> None:
        result = evaluate_hard_gate(
            [a_requirement("3+ years of experience required", min_years=3.0)],
            a_candidate(years=years),
        )
        assert result.status is HardGateStatus.PASS
        assert result.checks[0].evaluation is RequirementEvaluation.DERIVED_MATCH

    def test_years_the_profile_does_not_state_are_unknown_not_a_pass(self) -> None:
        result = evaluate_hard_gate(
            [a_requirement("3+ years of experience required", min_years=3.0)],
            a_candidate(),
        )
        assert result.status is HardGateStatus.UNKNOWN
        assert result.checks[0].evaluation is RequirementEvaluation.UNKNOWN
        assert result.blocks is True
        assert result.checks[0].candidate_field_path is None

    def test_a_preference_cannot_fail_a_candidate(self) -> None:
        result = evaluate_hard_gate(
            [
                a_requirement(
                    "5+ years preferred",
                    priority=RequirementPriority.PREFERRED,
                    min_years=5.0,
                )
            ],
            a_candidate(years=1.0),
        )
        assert result.status is HardGateStatus.PASS
        assert result.checks == []

    def test_an_unstated_priority_does_not_gate(self) -> None:
        result = evaluate_hard_gate(
            [
                a_requirement(
                    "3+ years",
                    priority=RequirementPriority.UNKNOWN,
                    min_years=3.0,
                )
            ],
            a_candidate(years=1.0),
        )
        assert result.status is HardGateStatus.PASS
        assert result.checks == []

    def test_a_per_skill_minimum_is_still_bounded_by_total_years(self) -> None:
        # One total year cannot hide three years of any single skill: the
        # total is an upper bound, so failing it is sound whatever the row's
        # category.
        result = evaluate_hard_gate(
            [
                a_requirement(
                    "3+ years of Python development",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                    min_years=3.0,
                )
            ],
            a_candidate(years=1.0),
        )
        assert result.status is HardGateStatus.HARD_MISMATCH


# ---------------------------------------------------------------------------
# Sponsorship
# ---------------------------------------------------------------------------
class TestSponsorshipGate:
    _NO_SPONSORSHIP = a_requirement(
        "No sponsorship available",
        kind=RequirementKind.SPONSORSHIP,
        priority=RequirementPriority.REQUIRED,
    )

    def test_a_posting_that_does_not_sponsor_fails_a_candidate_who_needs_it(
        self,
    ) -> None:
        result = evaluate_hard_gate([self._NO_SPONSORSHIP], a_candidate(sponsorship=True))
        assert result.status is HardGateStatus.HARD_MISMATCH
        check = result.checks[0]
        assert check.evaluation is RequirementEvaluation.VERIFIED_MISMATCH
        assert check.candidate_field_path == "authorization.requires_sponsorship"
        assert "does not sponsor" in check.reason

    def test_a_candidate_who_needs_no_sponsorship_passes(self) -> None:
        result = evaluate_hard_gate(
            [self._NO_SPONSORSHIP], a_candidate(sponsorship=False)
        )
        assert result.status is HardGateStatus.PASS
        assert result.checks[0].evaluation is RequirementEvaluation.VERIFIED_MATCH

    def test_an_unsaid_sponsorship_answer_is_unknown(self) -> None:
        result = evaluate_hard_gate([self._NO_SPONSORSHIP], a_candidate())
        assert result.status is HardGateStatus.UNKNOWN
        assert result.checks[0].evaluation is RequirementEvaluation.UNKNOWN

    def test_a_posting_that_sponsors_cannot_disqualify_anyone(self) -> None:
        result = evaluate_hard_gate(
            [
                a_requirement(
                    "Sponsorship available",
                    kind=RequirementKind.SPONSORSHIP,
                )
            ],
            a_candidate(sponsorship=True),
        )
        assert result.status is HardGateStatus.PASS
        assert result.checks == []

    def test_the_phrasing_that_contains_both_readings_is_read_as_forbidding(
        self,
    ) -> None:
        # "No sponsorship available" also contains "sponsorship available";
        # the forbidding phrases are asked first and must win.
        result = evaluate_hard_gate(
            [
                a_requirement(
                    "No sponsorship available",
                    kind=RequirementKind.SPONSORSHIP,
                )
            ],
            a_candidate(sponsorship=True),
        )
        assert result.status is HardGateStatus.HARD_MISMATCH

    def test_a_direction_that_cannot_be_read_goes_to_a_human(self) -> None:
        result = evaluate_hard_gate(
            [
                a_requirement(
                    "Sponsorship case by case",
                    kind=RequirementKind.SPONSORSHIP,
                )
            ],
            a_candidate(),
        )
        assert result.status is HardGateStatus.REVIEW_REQUIRED
        assert result.checks[0].evaluation is RequirementEvaluation.REVIEW_REQUIRED
        assert result.blocks is False

    def test_a_sponsorship_row_that_never_says_the_word_is_also_unreadable(
        self,
    ) -> None:
        result = evaluate_hard_gate(
            [
                a_requirement(
                    "Work authorization handled case by case",
                    kind=RequirementKind.SPONSORSHIP,
                )
            ],
            a_candidate(),
        )
        assert result.status is HardGateStatus.REVIEW_REQUIRED

    def test_a_preferred_sponsorship_row_does_not_gate(self) -> None:
        result = evaluate_hard_gate(
            [
                a_requirement(
                    "No sponsorship available",
                    kind=RequirementKind.SPONSORSHIP,
                    priority=RequirementPriority.PREFERRED,
                )
            ],
            a_candidate(sponsorship=True),
        )
        assert result.status is HardGateStatus.PASS
        assert result.checks == []


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------
class TestComposition:
    def test_a_definitive_failure_outranks_an_unreadable_one(self) -> None:
        result = evaluate_hard_gate(
            [
                a_requirement("3+ years required", min_years=3.0),
                a_requirement(
                    "Sponsorship case by case",
                    kind=RequirementKind.SPONSORSHIP,
                ),
            ],
            a_candidate(years=1.0),
        )
        assert result.status is HardGateStatus.HARD_MISMATCH

    def test_unknown_outranks_review(self) -> None:
        result = evaluate_hard_gate(
            [
                a_requirement("3+ years required", min_years=3.0),
                a_requirement(
                    "Sponsorship case by case",
                    kind=RequirementKind.SPONSORSHIP,
                ),
            ],
            a_candidate(),
        )
        assert result.status is HardGateStatus.UNKNOWN

    def test_review_outranks_a_clean_board(self) -> None:
        result = evaluate_hard_gate(
            [
                a_requirement("3+ years required", min_years=3.0),
                a_requirement(
                    "Sponsorship case by case",
                    kind=RequirementKind.SPONSORSHIP,
                ),
            ],
            a_candidate(years=5.0),
        )
        assert result.status is HardGateStatus.REVIEW_REQUIRED

    def test_no_requirements_means_nothing_can_fail(self) -> None:
        result = evaluate_hard_gate([], a_candidate())
        assert result.status is HardGateStatus.PASS
        assert result.checks == []

    def test_only_required_rows_reach_the_checks(self) -> None:
        result = evaluate_hard_gate(
            [
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                    priority=RequirementPriority.PREFERRED,
                ),
                a_requirement("3+ years required", min_years=3.0),
            ],
            a_candidate(years=5.0),
        )
        assert [check.requirement_text for check in result.checks] == [
            "3+ years required"
        ]

    @pytest.mark.parametrize(
        ("status", "blocks"),
        [
            (HardGateStatus.HARD_MISMATCH, True),
            (HardGateStatus.UNKNOWN, True),
            (HardGateStatus.REVIEW_REQUIRED, False),
            (HardGateStatus.PASS, False),
        ],
    )
    def test_the_block_rule_comes_from_the_status(
        self, status: HardGateStatus, blocks: bool
    ) -> None:
        assert HardGateResult(status=status).blocks is blocks


# ---------------------------------------------------------------------------
# What never gates
# ---------------------------------------------------------------------------
class TestWhatNeverGates:
    def test_a_missing_required_skill_is_not_a_hard_mismatch(self) -> None:
        # The profile does not mention Rust. That is an absence of a claim,
        # not a claim of absence, and scoring — not the gate — weighs it.
        result = evaluate_hard_gate(
            [
                a_requirement(
                    "Rust",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                )
            ],
            a_candidate(years=5.0),
        )
        assert result.status is HardGateStatus.PASS
        assert result.checks == []

    def test_an_unmet_education_row_is_not_gated_either(self) -> None:
        result = evaluate_hard_gate(
            [
                a_requirement(
                    "Master's degree required",
                    kind=RequirementKind.EDUCATION,
                )
            ],
            a_candidate(years=5.0),
        )
        assert result.status is HardGateStatus.PASS
        assert result.checks == []


# ---------------------------------------------------------------------------
# End to end with the extractor
# ---------------------------------------------------------------------------
class TestWithTheExtractor:
    def test_a_posted_minimum_and_a_short_cv_disagree_in_the_gate(self) -> None:
        posting = (
            "<h3>Required qualifications</h3>"
            "<ul><li>3+ years of experience required</li></ul>"
        )
        requirements = extract_requirements(posting)
        assert requirements
        assert requirements[0].min_years == 3.0
        assert requirements[0].priority is RequirementPriority.REQUIRED

        facts = [
            Fact(
                field_path="experience.total_years_experience",
                value=1,
                status=FactStatus.VERIFIED,
                evidence=[
                    Evidence(
                        source_type=EvidenceSourceType.RESUME,
                        source_id="resume.txt",
                        text_excerpt="1 year of experience",
                    )
                ],
            )
        ]
        result = evaluate_hard_gate(
            requirements, CandidateEvidence.from_facts(facts)
        )
        assert result.status is HardGateStatus.HARD_MISMATCH
        assert result.mismatches

    def test_a_posted_sponsorship_rule_and_a_needing_candidate_disagree(self) -> None:
        posting = (
            "<h3>Required qualifications</h3>"
            "<ul><li>No sponsorship available</li></ul>"
        )
        requirements = extract_requirements(posting)
        assert requirements
        assert requirements[0].kind is RequirementKind.SPONSORSHIP

        result = evaluate_hard_gate(
            requirements,
            CandidateEvidence(
                requires_sponsorship=True,
                sponsorship_source=FactRef(
                    field_path="authorization.requires_sponsorship",
                    status=FactStatus.VERIFIED,
                ),
            ),
        )
        assert result.status is HardGateStatus.HARD_MISMATCH


# ---------------------------------------------------------------------------
# The models themselves
# ---------------------------------------------------------------------------
class TestModels:
    def test_an_unknown_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            GateCheck(
                requirement_text="3+ years",
                kind=RequirementKind.OTHER,
                priority=RequirementPriority.REQUIRED,
                evaluation=RequirementEvaluation.UNKNOWN,
                reason="x",
                bogus=True,  # type: ignore[call-arg]
            )

    def test_the_result_survives_a_round_trip(self) -> None:
        original = evaluate_hard_gate(
            [
                a_requirement("3+ years required", min_years=3.0),
                a_requirement(
                    "Sponsorship case by case",
                    kind=RequirementKind.SPONSORSHIP,
                ),
            ],
            a_candidate(years=1.0),
        )
        assert HardGateResult.model_validate(original.model_dump()) == original

    def test_mismatches_and_uncertain_partition_the_checks(self) -> None:
        result = evaluate_hard_gate(
            [
                a_requirement("3+ years required", min_years=3.0),
                a_requirement("5+ years required", min_years=5.0),
            ],
            a_candidate(years=1.0),
        )
        assert len(result.mismatches) == 2
        assert result.uncertain == []
