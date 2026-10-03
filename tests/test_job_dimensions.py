"""The eleven-dimension report: all eleven speak, and none of them lie.

The report is checked against the phase-7 rules directly: every dimension
present with a non-empty explanation, scores bounded or honestly absent,
``NOT_SCORED`` kept distinct from ``0.0``, hard blockers carried through
even when a scorer would say otherwise, and two builds of the same inputs
producing identical bytes.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.enums import (
    DimensionStatus,
    EvidenceSourceType,
    FactStatus,
    HardGateStatus,
    MatchDecision,
    RequirementPriority,
)
from core.evidence import Evidence
from jobs.candidate import CandidateClaim, CandidateEvidence, FactRef
from jobs.dimensions import DIMENSIONS, DimensionResult, MatchReport, build_report
from jobs.matching import evaluate_match
from jobs.models import Job, Requirement, RequirementKind
from test_job_matching import ScriptedScorer


def a_job(**overrides: object) -> Job:
    return Job(**overrides)  # type: ignore[arg-type]


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


def a_claim(
    text: str,
    *,
    field_path: str = "skills.proficient",
    with_excerpt: bool = True,
    status: FactStatus = FactStatus.VERIFIED,
) -> CandidateClaim:
    excerpts = (
        [
            Evidence(
                source_type=EvidenceSourceType.RESUME,
                source_id="resume.txt",
                text_excerpt=text,
            )
        ]
        if with_excerpt
        else []
    )
    return CandidateClaim(
        text=text,
        source=FactRef(field_path=field_path, status=status, evidence=excerpts),
    )


def a_candidate(
    *,
    claims: tuple[CandidateClaim, ...] = (),
    years: float | None = None,
    sponsorship: bool | None = None,
) -> CandidateEvidence:
    return CandidateEvidence(
        claims=list(claims),
        years_of_experience=years,
        years_source=(
            FactRef(field_path="experience.total_years_experience", status=FactStatus.VERIFIED)
            if years is not None
            else None
        ),
        requires_sponsorship=sponsorship,
        sponsorship_source=(
            FactRef(field_path="authorization.requires_sponsorship", status=FactStatus.VERIFIED)
            if sponsorship is not None
            else None
        ),
    )


def a_report(
    requirements: list[Requirement],
    evidence: CandidateEvidence,
    job: Job | None = None,
    *,
    scorer: object = None,
) -> MatchReport:
    result = evaluate_match(requirements, evidence, scorer=scorer)  # type: ignore[arg-type]
    return build_report(job or a_job(), requirements, evidence, result)


class TestTheEleven:
    def test_all_eleven_dimensions_arrive_in_spec_order(self) -> None:
        report = a_report([], a_candidate())
        assert list(report.dimension_scores) == list(DIMENSIONS)
        assert len(report.dimension_scores) == 11

    def test_every_dimension_explains_itself(self) -> None:
        report = a_report(
            [
                a_requirement(
                    "Python",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                    priority=RequirementPriority.PREFERRED,
                )
            ],
            a_candidate(claims=(a_claim("Python"),)),
        )
        for name in DIMENSIONS:
            dimension = report.dimension_scores[name]
            assert dimension.explanation.strip(), name
            assert isinstance(dimension.status, DimensionStatus)

    def test_every_score_is_bounded_or_not_scored(self) -> None:
        report = a_report(
            [
                a_requirement("Python", kind=RequirementKind.PROGRAMMING_LANGUAGE),
                a_requirement("SQL", kind=RequirementKind.DATABASE),
                a_requirement("Rust", kind=RequirementKind.PROGRAMMING_LANGUAGE),
            ],
            a_candidate(claims=(a_claim("Python"),)),
            scorer=ScriptedScorer(value=0.4),
        )
        for name in DIMENSIONS:
            score = report.dimension_scores[name].score
            assert score is None or 0.0 <= score <= 1.0, name
        assert report.overall_match is None or 0.0 <= report.overall_match <= 1.0

    def test_the_explanations_line_up_with_the_dimensions(self) -> None:
        report = a_report([], a_candidate())
        assert len(report.explanations) == len(DIMENSIONS)
        for name, explanation in zip(DIMENSIONS, report.explanations):
            assert explanation == report.dimension_scores[name].explanation


class TestNotScoredIsNotZero:
    def test_a_silent_profile_scores_nothing_rather_than_zero(self) -> None:
        report = a_report(
            [a_requirement("Python", kind=RequirementKind.PROGRAMMING_LANGUAGE)],
            a_candidate(),
            scorer=ScriptedScorer(value=1.0),
        )
        # Claims exist to compare against? No: the profile is empty, and an
        # empty profile is unknown, not a perfect anti-match.
        coverage = report.dimension_scores["resume_evidence_coverage"]
        assert coverage.status is DimensionStatus.UNKNOWN
        assert coverage.score is None

    def test_a_posting_that_states_nothing_is_not_applicable(self) -> None:
        report = a_report([], a_candidate(claims=(a_claim("Python"),)))
        for name in (
            "skill_match",
            "experience_match",
            "education_match",
            "must_have_match",
            "nice_to_have_match",
            "authorization_match",
            "domain_match",
        ):
            dimension = report.dimension_scores[name]
            assert dimension.status is DimensionStatus.NOT_APPLICABLE, name
            assert dimension.score is None, name

    def test_overall_is_none_when_nothing_could_be_scored(self) -> None:
        report = a_report([], a_candidate())
        assert report.overall_match is None
        assert report.alarms == []

    def test_measured_and_missing_scores_zero_and_the_all_zero_alarm_rings(
        self,
    ) -> None:
        # A posting asking for a skill the profile cannot answer, scored
        # by a resemblence of zero, and a profile whose claims carry no
        # excerpts: everything measured is 0.
        report = a_report(
            [a_requirement("Kubernetes", kind=RequirementKind.CLOUD)],
            a_candidate(claims=(a_claim("Python", with_excerpt=False),)),
            scorer=ScriptedScorer(value=0.0),
        )
        assert report.dimension_scores["skill_match"].score == 0.0
        assert report.dimension_scores["skill_match"].status is DimensionStatus.WEAK
        assert report.overall_match == 0.0
        assert report.alarms, "an all-zero report must raise its alarm"


class TestBlockersTravel:
    def test_a_hard_blocker_survives_a_perfect_scorer(self) -> None:
        requirements = [
            a_requirement("3+ years required", min_years=3.0),
            a_requirement("Python", kind=RequirementKind.PROGRAMMING_LANGUAGE),
        ]
        evidence = a_candidate(
            claims=(a_claim("Python"),),
            years=1.0,
        )
        report = a_report(requirements, evidence, scorer=ScriptedScorer(value=1.0))

        # The scorer would have said 1.0 to everything; the gate vetoed
        # before it could speak, and the report says so.
        assert report.decision is MatchDecision.HARD_MISMATCH
        assert report.gate_status is HardGateStatus.HARD_MISMATCH
        assert report.hard_blockers
        assert any("years" in blocker for blocker in report.hard_blockers)
        # The gated years row still answers the experience dimension.
        experience = report.dimension_scores["experience_match"]
        assert experience.score == 0.0
        assert experience.status is DimensionStatus.WEAK

    def test_blockers_are_empty_when_the_gate_passes(self) -> None:
        report = a_report(
            [a_requirement("Python", kind=RequirementKind.PROGRAMMING_LANGUAGE)],
            a_candidate(claims=(a_claim("Python"),)),
        )
        assert report.decision is MatchDecision.MATCH
        assert report.hard_blockers == []


class TestTheFieldDimensions:
    def test_location_compares_the_posting_field_against_profile_evidence(
        self,
    ) -> None:
        claims = (a_claim("Austin, TX", field_path="location.current_city"),)
        agreeing = a_report([], a_candidate(claims=claims), a_job(location="Austin"))
        assert agreeing.dimension_scores["location_match"].score == 1.0

        disagreeing = a_report([], a_candidate(claims=claims), a_job(location="Berlin"))
        assert disagreeing.dimension_scores["location_match"].score == 0.0

    def test_location_stays_honest_when_either_side_is_silent(self) -> None:
        loud_profile = a_report(
            [], a_candidate(claims=(a_claim("Austin", field_path="location.current_city"),))
        )
        assert loud_profile.dimension_scores["location_match"].status is (
            DimensionStatus.UNKNOWN
        )

        silent_both = a_report([], a_candidate())
        assert silent_both.dimension_scores["location_match"].status is (
            DimensionStatus.NOT_APPLICABLE
        )
        assert silent_both.dimension_scores["location_match"].score is None

    def test_workplace_compares_arrangement_words(self) -> None:
        remote = a_candidate(
            claims=(a_claim("remote", field_path="preferences.remote_preference"),)
        )
        agreeing = a_report([], remote, a_job(workplace_type="REMOTE"))
        assert agreeing.dimension_scores["workplace_match"].score == 1.0

        onsite = a_report([], remote, a_job(workplace_type="ON_SITE"))
        assert onsite.dimension_scores["workplace_match"].score == 0.0

    def test_seniority_admits_the_profile_says_nothing(self) -> None:
        report = a_report([], a_candidate(), a_job(experience_level="Senior"))
        seniority = report.dimension_scores["seniority_match"]
        assert seniority.status is DimensionStatus.UNKNOWN
        assert seniority.score is None
        assert "no seniority fact" in seniority.explanation

        unstated = a_report([], a_candidate())
        assert unstated.dimension_scores["seniority_match"].status is (
            DimensionStatus.NOT_APPLICABLE
        )


class TestResumeEvidenceCoverage:
    def test_coverage_counts_claims_backed_by_a_verbatim_excerpt(self) -> None:
        backed = a_candidate(
            claims=(
                a_claim("Python"),
                a_claim("SQL", with_excerpt=False),
            )
        )
        report = a_report([], backed)
        coverage = report.dimension_scores["resume_evidence_coverage"]
        assert coverage.score == 0.5
        assert coverage.status is DimensionStatus.PARTIAL
        assert "1 of 2" in coverage.explanation

    def test_coverage_without_claims_is_unknown(self) -> None:
        report = a_report([], a_candidate())
        coverage = report.dimension_scores["resume_evidence_coverage"]
        assert coverage.status is DimensionStatus.UNKNOWN
        assert coverage.score is None


class TestComposition:
    def test_matched_missing_and_uncertain_lists_name_the_rows(self) -> None:
        report = a_report(
            [
                a_requirement("Python", kind=RequirementKind.PROGRAMMING_LANGUAGE),
                a_requirement("SQL", kind=RequirementKind.DATABASE),
            ],
            a_candidate(claims=(a_claim("Python"),)),
            scorer=ScriptedScorer(value=0.2, fails_on="SQL"),
        )
        assert report.matched_requirements == ["Python"]
        assert report.uncertain_requirements == ["SQL"]
        assert report.missing_requirements == []

    def test_one_hit_and_one_miss_compose_a_partial(self) -> None:
        report = a_report(
            [
                a_requirement("Python", kind=RequirementKind.PROGRAMMING_LANGUAGE),
                a_requirement("COBOL", kind=RequirementKind.PROGRAMMING_LANGUAGE),
            ],
            a_candidate(claims=(a_claim("Python"),)),
            scorer=ScriptedScorer(value=0.0),
        )
        skill = report.dimension_scores["skill_match"]
        assert skill.score == 0.5
        assert skill.status is DimensionStatus.PARTIAL

    def test_must_and_nice_split_by_priority(self) -> None:
        report = a_report(
            [
                a_requirement("Python", kind=RequirementKind.PROGRAMMING_LANGUAGE),
                a_requirement(
                    "Rust",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                    priority=RequirementPriority.PREFERRED,
                ),
            ],
            a_candidate(claims=(a_claim("Python"),)),
            scorer=ScriptedScorer(value=0.0),
        )
        assert report.dimension_scores["must_have_match"].score == 1.0
        assert report.dimension_scores["nice_to_have_match"].score == 0.0

    def test_the_report_names_its_grounding(self) -> None:
        report = a_report(
            [a_requirement("Python", kind=RequirementKind.PROGRAMMING_LANGUAGE)],
            a_candidate(claims=(a_claim("Python"),)),
        )
        assert report.grounded_in == sorted(report.grounded_in)
        assert "job_description" in report.grounded_in
        assert "skills.proficient" in report.grounded_in
        assert "posting" in report.evidence_source
        assert "profile" in report.evidence_source

    def test_similarity_is_named_only_when_it_participated(self) -> None:
        claims_only = a_report(
            [a_requirement("Python", kind=RequirementKind.PROGRAMMING_LANGUAGE)],
            a_candidate(claims=(a_claim("Python"),)),
        )
        assert "similarity" not in claims_only.evidence_source

        with_scorer = a_report(
            [
                a_requirement(
                    "Experience with PyTorch",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                )
            ],
            a_candidate(claims=(a_claim("Python"),)),
            scorer=ScriptedScorer(value=1.0),
        )
        assert "similarity" in with_scorer.evidence_source


class TestDeterminismAndBounds:
    def test_two_builds_of_the_same_inputs_are_identical(self) -> None:
        requirements = [
            a_requirement("Python", kind=RequirementKind.PROGRAMMING_LANGUAGE),
            a_requirement("3+ years required", min_years=3.0),
            a_requirement(
                "Remote",
                kind=RequirementKind.WORKPLACE_TYPE,
                priority=RequirementPriority.PREFERRED,
            ),
        ]
        evidence = a_candidate(claims=(a_claim("Python"),), years=5.0)
        job = a_job(location="Austin", workplace_type="REMOTE")
        first = a_report(requirements, evidence, job, scorer=ScriptedScorer(value=0.6))
        second = a_report(requirements, evidence, job, scorer=ScriptedScorer(value=0.6))
        assert first.model_dump() == second.model_dump()

    def test_a_score_above_one_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            DimensionResult(
                status=DimensionStatus.STRONG,
                score=1.1,
                explanation="impossible",
            )

    def test_a_report_is_json_round_trippable(self) -> None:
        report = a_report(
            [a_requirement("Python", kind=RequirementKind.PROGRAMMING_LANGUAGE)],
            a_candidate(claims=(a_claim("Python"),)),
        )
        assert MatchReport.model_validate(report.model_dump(mode="json")) == report

    def test_an_empty_posting_with_an_empty_profile_is_a_clean_match(
        self,
    ) -> None:
        result = evaluate_match([], a_candidate())
        report = build_report(a_job(), [], a_candidate(), result)
        assert report.decision is MatchDecision.MATCH
        assert report.overall_match is None
        assert report.hard_blockers == []
        assert report.alarms == []
