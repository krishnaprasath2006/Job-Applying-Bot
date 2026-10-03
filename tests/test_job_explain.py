"""Explainability: the audit record behind one decision.

Every assertion here is about lineage a human could follow — the excerpt
the posting was read from, the profile field that answered, the evidence
under it — and about the one thing an explanation must never do: fill in a
row nothing evaluated as though something had.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.enums import (
    AnalysisSource,
    EvidenceSourceType,
    ExtractionMethod,
    FactStatus,
    MatchDecision,
    RequirementEvaluation,
    RequirementPriority,
)
from core.evidence import Evidence, Fact
from jobs.candidate import CandidateClaim, CandidateEvidence, FactRef
from jobs.explain import (
    MatchExplanation,
    RowExplanation,
    explain_match,
)
from jobs.matching import evaluate_match
from jobs.models import Job, Requirement, RequirementKind
from jobs.requirements import extract_requirements


def a_candidate(*, claims: tuple[str, ...] = (), years: float | None = None):
    return CandidateEvidence(
        claims=[
            CandidateClaim(
                text=text,
                source=FactRef(
                    field_path="skills.proficient",
                    status=FactStatus.VERIFIED,
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
                evidence=[
                    Evidence(
                        source_type=EvidenceSourceType.RESUME,
                        source_id="resume.txt",
                        text_excerpt=f"{years:g} years",
                    )
                ],
            )
            if years is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# One row per requirement
# ---------------------------------------------------------------------------
class TestRows:
    def test_every_requirement_gets_a_row_in_document_order(self) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3>"
            "<ul><li>3+ years of experience required</li>"
            "<li>Python</li><li>SQL</li></ul>"
        )
        result = evaluate_match(
            requirements, a_candidate(claims=("Python", "SQL"), years=5.0)
        )
        explanation = explain_match(result, requirements, a_candidate(
            claims=("Python", "SQL"), years=5.0
        ))
        assert [row.index for row in explanation.rows] == [0, 1, 2]
        assert [row.requirement_text for row in explanation.rows] == [
            requirement.text for requirement in requirements
        ]

    def test_a_gate_row_is_explained_from_the_gate(self) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3>"
            "<ul><li>3+ years of experience required</li></ul>"
        )
        evidence = CandidateEvidence.from_facts(
            [
                Fact(
                    field_path="experience.total_years_experience",
                    value=1,
                    status=FactStatus.VERIFIED,
                    evidence=[
                        Evidence(
                            source_type=EvidenceSourceType.RESUME,
                            source_id="resume.txt",
                            text_excerpt="1 year",
                        )
                    ],
                )
            ]
        )
        result = evaluate_match(requirements, evidence)
        row = explain_match(result, requirements, evidence).rows[0]
        assert row.evaluation is RequirementEvaluation.DERIVED_MISMATCH
        assert "3" in row.reason and "1" in row.reason
        assert row.similarity is None
        assert row.candidate is not None
        assert row.candidate.field_path == "experience.total_years_experience"
        assert row.candidate.evidence[0].text_excerpt == "1 year"

    def test_a_scored_row_is_explained_from_the_score(self) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3><ul><li>Python</li></ul>"
        )
        evidence = a_candidate(claims=("Python",))
        result = evaluate_match(requirements, evidence)
        row = explain_match(result, requirements, evidence).rows[0]
        assert row.evaluation is RequirementEvaluation.VERIFIED_MATCH
        assert '"Python"' in row.reason
        assert row.candidate is not None
        assert row.candidate.field_path == "skills.proficient"
        assert row.candidate.evidence[0].text_excerpt == "Python"

    def test_a_similarity_row_carries_its_number(self) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3>"
            "<ul><li>Experience with PyTorch</li></ul>"
        )
        from ai.embeddings import LexicalScorer

        evidence = a_candidate(claims=("PyTorch",))
        result = evaluate_match(requirements, evidence, scorer=LexicalScorer())
        row = explain_match(result, requirements, evidence).rows[0]
        assert row.evaluation is RequirementEvaluation.DERIVED_MATCH
        assert row.similarity == 1.0

    def test_a_row_the_gate_read_as_already_satisfied_says_what_happened(
        self,
    ) -> None:
        # A sponsorship row the posting offers is gated by is_gated but
        # never checked; the explanation must not borrow an evaluation.
        requirements = [
            Requirement(
                text="Sponsorship available",
                kind=RequirementKind.SPONSORSHIP,
                priority=RequirementPriority.REQUIRED,
            )
        ]
        evidence = a_candidate()
        result = evaluate_match(requirements, evidence)
        row = explain_match(result, requirements, evidence).rows[0]
        assert result.gate.status.value == "PASS"
        assert row.evaluation is None
        assert "offers" in row.reason

    def test_rows_a_veto_reached_before_scoring_say_so(self) -> None:
        requirements = [
            Requirement(
                text="3+ years required",
                min_years=3.0,
                priority=RequirementPriority.REQUIRED,
            ),
            Requirement(
                text="Python",
                kind=RequirementKind.PROGRAMMING_LANGUAGE,
                priority=RequirementPriority.REQUIRED,
            ),
        ]
        evidence = a_candidate(claims=("Python",), years=1.0)
        result = evaluate_match(requirements, evidence)
        explanation = explain_match(result, requirements, evidence)
        assert explanation.decision is MatchDecision.HARD_MISMATCH
        gate_row, unscored_row = explanation.rows
        assert gate_row.evaluation is RequirementEvaluation.DERIVED_MISMATCH
        assert unscored_row.evaluation is None
        assert "gate decided" in unscored_row.reason
        assert unscored_row.candidate is None


# ---------------------------------------------------------------------------
# The posting side
# ---------------------------------------------------------------------------
class TestPostingLineage:
    def test_an_extracted_row_names_its_method_excerpt_and_confidence(
        self,
    ) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3><ul><li>Python</li></ul>"
        )
        evidence = a_candidate(claims=("Python",))
        result = evaluate_match(requirements, evidence)
        posting = explain_match(result, requirements, evidence).rows[0].posting
        assert posting.method is ExtractionMethod.DETERMINISTIC
        assert posting.analysis_source is AnalysisSource.JOB_DATA
        assert posting.excerpt == requirements[0].text
        assert posting.confidence == pytest.approx(0.9)

    def test_a_row_read_by_a_model_says_so(self) -> None:
        requirements = [
            Requirement(
                text="Python",
                kind=RequirementKind.PROGRAMMING_LANGUAGE,
                extraction_source=ExtractionMethod.AI,
                analysis_source=AnalysisSource.AI_GENERAL,
                confidence=0.7,
                source_excerpt="must know Python",
            )
        ]
        evidence = a_candidate(claims=("Python",))
        result = evaluate_match(requirements, evidence)
        posting = explain_match(result, requirements, evidence).rows[0].posting
        assert posting.method is ExtractionMethod.AI
        assert posting.analysis_source is AnalysisSource.AI_GENERAL
        assert posting.confidence == pytest.approx(0.7)
        assert posting.excerpt == "must know Python"


# ---------------------------------------------------------------------------
# The candidate side
# ---------------------------------------------------------------------------
class TestCandidateLineage:
    def test_an_inferred_status_is_shown_not_hidden(self) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3><ul><li>Python</li></ul>"
        )
        evidence = CandidateEvidence(
            claims=[
                CandidateClaim(
                    text="Python",
                    source=FactRef(
                        field_path="skills.proficient",
                        status=FactStatus.INFERRED,
                    ),
                )
            ]
        )
        result = evaluate_match(requirements, evidence)
        row = explain_match(result, requirements, evidence).rows[0]
        assert row.candidate is not None
        assert row.candidate.status is FactStatus.INFERRED

    def test_a_gate_row_still_points_at_the_fact_it_used(self) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3>"
            "<ul><li>3+ years of experience required</li></ul>"
        )
        evidence = a_candidate(years=5.0)
        result = evaluate_match(requirements, evidence)
        row = explain_match(result, requirements, evidence).rows[0]
        assert row.evaluation is not None
        # The gate answered, and its answer still points at the fact.
        assert row.candidate is not None
        assert row.candidate.field_path == "experience.total_years_experience"

    def test_an_unevaluated_row_carries_no_candidate_pointer(self) -> None:
        requirements = [
            Requirement(
                text="3+ years required",
                min_years=3.0,
                priority=RequirementPriority.REQUIRED,
            ),
            Requirement(
                text="COBOL",
                kind=RequirementKind.PROGRAMMING_LANGUAGE,
                priority=RequirementPriority.REQUIRED,
            ),
        ]
        evidence = a_candidate(years=1.0)
        result = evaluate_match(requirements, evidence)
        explanation = explain_match(result, requirements, evidence)
        assert explanation.rows[1].evaluation is None
        assert explanation.rows[1].candidate is None


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
class TestIdentity:
    def test_a_job_stamps_the_report(self) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3><ul><li>Python</li></ul>"
        )
        evidence = a_candidate(claims=("Python",))
        result = evaluate_match(requirements, evidence)
        job = Job(id="job-1", title="Machine Learning Engineer", company="Northwind")
        explanation = explain_match(
            result, requirements, evidence, job=job
        )
        assert explanation.job_id == "job-1"
        assert explanation.job_title == "Machine Learning Engineer"
        assert explanation.job_company == "Northwind"

    def test_without_a_job_the_identity_stays_empty(self) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3><ul><li>Python</li></ul>"
        )
        evidence = a_candidate(claims=("Python",))
        result = evaluate_match(requirements, evidence)
        explanation = explain_match(result, requirements, evidence)
        assert explanation.job_title is None


# ---------------------------------------------------------------------------
# The rendered report
# ---------------------------------------------------------------------------
class TestRender:
    def test_the_report_names_the_decision_and_the_gate(self) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3>"
            "<ul><li>3+ years of experience required</li></ul>"
        )
        evidence = a_candidate(years=1.0)
        result = evaluate_match(requirements, evidence)
        explanation = explain_match(result, requirements, evidence)
        report = explanation.render()
        assert "HARD_MISMATCH" in report
        assert "gate: HARD_MISMATCH" in report

    def test_the_report_shows_each_row_with_both_sides(self) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3><ul><li>Python</li></ul>"
        )
        evidence = a_candidate(claims=("Python",))
        result = evaluate_match(requirements, evidence)
        report = explain_match(result, requirements, evidence).render()
        assert "Python" in report
        assert "posting:" in report
        assert "skills.proficient" in report
        assert "why:" in report

    def test_an_unevaluated_row_is_spelled_out(self) -> None:
        requirements = [
            Requirement(
                text="3+ years required",
                min_years=3.0,
                priority=RequirementPriority.REQUIRED,
            ),
            Requirement(text="Anything else", priority=RequirementPriority.REQUIRED),
        ]
        evidence = a_candidate(years=1.0)
        result = evaluate_match(requirements, evidence)
        report = explain_match(result, requirements, evidence).render()
        assert "NOT EVALUATED" in report

    def test_a_long_excerpt_is_truncated_not_dropped(self) -> None:
        requirements = [
            Requirement(
                text="Python",
                kind=RequirementKind.PROGRAMMING_LANGUAGE,
                priority=RequirementPriority.REQUIRED,
                source_excerpt="x" * 300,
            )
        ]
        evidence = a_candidate(claims=("Python",))
        result = evaluate_match(requirements, evidence)
        report = explain_match(result, requirements, evidence).render()
        assert "x" * 300 not in report
        assert "..." in report


# ---------------------------------------------------------------------------
# Filtering and models
# ---------------------------------------------------------------------------
class TestHelpersAndModels:
    def test_rows_with_filters_by_evaluation(self) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3>"
            "<ul><li>3+ years of experience required</li><li>Python</li></ul>"
        )
        evidence = a_candidate(claims=("Python",), years=1.0)
        result = evaluate_match(requirements, evidence)
        explanation = explain_match(result, requirements, evidence)
        failed = explanation.rows_with(RequirementEvaluation.DERIVED_MISMATCH)
        assert [row.index for row in failed] == [0]
        assert [row.index for row in explanation.undecided_rows] == [1]

    def test_undecided_rows_are_the_unevaluated_ones(self) -> None:
        requirements = [
            Requirement(
                text="3+ years required",
                min_years=3.0,
                priority=RequirementPriority.REQUIRED,
            ),
            Requirement(
                text="Python",
                kind=RequirementKind.PROGRAMMING_LANGUAGE,
                priority=RequirementPriority.REQUIRED,
            ),
        ]
        evidence = a_candidate(claims=("Python",), years=1.0)
        result = evaluate_match(requirements, evidence)
        explanation = explain_match(result, requirements, evidence)
        assert [row.index for row in explanation.undecided_rows] == [1]

    def test_the_explanation_survives_a_round_trip(self) -> None:
        requirements = extract_requirements(
            "<h3>Required qualifications</h3>"
            "<ul><li>3+ years of experience required</li><li>Python</li></ul>"
        )
        evidence = a_candidate(claims=("Python",), years=1.0)
        result = evaluate_match(requirements, evidence)
        original = explain_match(result, requirements, evidence)
        assert MatchExplanation.model_validate(original.model_dump()) == original

    def test_an_unknown_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            RowExplanation(  # type: ignore[call-arg]
                index=0,
                requirement_text="Python",
                kind=RequirementKind.OTHER,
                priority=RequirementPriority.REQUIRED,
                reason="x",
                posting=None,
                bogus=True,
            )
