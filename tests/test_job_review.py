"""Review queue: the doubt is named, never re-decided.

Each derivation test builds a real match through the real matcher — the
reasons have to come out of decisions the pipeline actually makes, not out
of hand-fed inputs. The queue tests then check membership: exactly the
decisions that require a human, and no more.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from core.enums import (
    FactStatus,
    MatchDecision,
    RequirementPriority,
    ReviewReason,
)
from jobs.candidate import CandidateClaim, CandidateEvidence, FactRef
from jobs.explain import explain_match
from jobs.matching import evaluate_match
from jobs.models import Job, Requirement, RequirementKind
from jobs.review import ReviewItem, ReviewQueue, derive_review_reasons

YEARS = Requirement(
    text="3+ years required", min_years=3.0, priority=RequirementPriority.REQUIRED
)
PYTHON = Requirement(
    text="Python",
    kind=RequirementKind.PROGRAMMING_LANGUAGE,
    priority=RequirementPriority.REQUIRED,
)
COBOL = Requirement(
    text="COBOL",
    kind=RequirementKind.PROGRAMMING_LANGUAGE,
    priority=RequirementPriority.REQUIRED,
)
MYSTERY = Requirement(text="Mystery requirement", priority=RequirementPriority.REQUIRED)
SECRET = Requirement(text="Secret requirement", priority=RequirementPriority.REQUIRED)
SPONSORSHIP = Requirement(
    text="Visa sponsorship handled case by case",
    kind=RequirementKind.SPONSORSHIP,
    priority=RequirementPriority.REQUIRED,
)


class FakeScorer:
    """A scorer with one opinion and one way to break."""

    def __init__(self, value: float = 0.6, *, fail_on: tuple[str, ...] = ()) -> None:
        self.value = value
        self.fail_on = set(fail_on)

    def similarity(self, left: str, right: str) -> float:
        if left in self.fail_on:
            raise RuntimeError("the scorer broke")
        return self.value


def a_candidate(*, claims: tuple[str, ...] = ("Python",), years: float | None = None):
    return CandidateEvidence(
        claims=[
            CandidateClaim(
                text=text,
                source=FactRef(
                    field_path="skills.proficient", status=FactStatus.VERIFIED
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
    )


def a_job(*, job_id: str = "job-r") -> Job:
    return Job(
        id=job_id,
        title="Data Engineer",
        company="Northwind",
        canonical_url=f"https://jobs.example/{job_id}",
    )


# ---------------------------------------------------------------------------
# Deriving reasons from a real decision
# ---------------------------------------------------------------------------
class TestDerivation:
    def test_a_clean_decision_names_nothing(self) -> None:
        requirements = [PYTHON]
        evidence = a_candidate()
        result = evaluate_match(requirements, evidence)
        assert result.decision is MatchDecision.MATCH
        assert derive_review_reasons(result) == []

    def test_a_hard_mismatch_names_nothing(self) -> None:
        requirements = [YEARS]
        evidence = a_candidate(years=1.0)
        result = evaluate_match(requirements, evidence)
        assert result.decision is MatchDecision.HARD_MISMATCH
        assert derive_review_reasons(result) == []

    def test_an_unknown_gate_names_eligibility_unknown(self) -> None:
        requirements = [YEARS]
        result = evaluate_match(requirements, CandidateEvidence())
        assert result.decision is MatchDecision.INSUFFICIENT_EVIDENCE
        assert derive_review_reasons(result) == [ReviewReason.ELIGIBILITY_UNKNOWN]

    def test_an_unreadable_sponsorship_row_names_the_ambiguity(self) -> None:
        requirements = [SPONSORSHIP]
        result = evaluate_match(requirements, CandidateEvidence())
        assert result.decision is MatchDecision.REVIEW_REQUIRED
        assert derive_review_reasons(result) == [
            ReviewReason.AMBIGUOUS_HARD_REQUIREMENT
        ]

    def test_an_unknown_required_score_names_insufficient_evidence(self) -> None:
        requirements = [PYTHON, COBOL]
        result = evaluate_match(requirements, a_candidate())
        assert result.decision is MatchDecision.INSUFFICIENT_EVIDENCE
        assert derive_review_reasons(result) == [ReviewReason.INSUFFICIENT_EVIDENCE]

    def test_a_review_band_row_names_low_ai_confidence(self) -> None:
        requirements = [COBOL]
        result = evaluate_match(
            requirements, a_candidate(), scorer=FakeScorer(value=0.6)
        )
        assert result.decision is MatchDecision.REVIEW_REQUIRED
        assert derive_review_reasons(result) == [ReviewReason.LOW_AI_CONFIDENCE]

    def test_a_low_mean_similarity_names_low_ai_confidence_too(self) -> None:
        requirements = [PYTHON, MYSTERY, SECRET]
        result = evaluate_match(
            requirements,
            a_candidate(),
            scorer=FakeScorer(value=0.3, fail_on=("Secret requirement",)),
        )
        assert result.decision is MatchDecision.INSUFFICIENT_EVIDENCE
        explanation = explain_match(result, requirements, a_candidate())
        assert explanation.similarity_score == pytest.approx(0.3)
        assert derive_review_reasons(result, explanation=explanation) == [
            ReviewReason.INSUFFICIENT_EVIDENCE,
            ReviewReason.LOW_AI_CONFIDENCE,
        ]

    def test_an_incomplete_extraction_is_named_beside_the_gate(self) -> None:
        requirements = [YEARS]
        result = evaluate_match(requirements, CandidateEvidence())
        reasons = derive_review_reasons(result, extraction_status="PARTIAL")
        assert reasons == [
            ReviewReason.ELIGIBILITY_UNKNOWN,
            ReviewReason.JD_EXTRACTION_INCOMPLETE,
        ]

    def test_the_job_status_carries_the_same_incomplete_signal(self) -> None:
        from jobs.models import JobStatus

        requirements = [YEARS]
        result = evaluate_match(requirements, CandidateEvidence())
        reasons = derive_review_reasons(result, job_status=JobStatus.JD_FAILED)
        assert ReviewReason.JD_EXTRACTION_INCOMPLETE in reasons

    def test_the_same_incomplete_signal_is_named_once(self) -> None:
        from jobs.models import JobStatus

        requirements = [YEARS]
        result = evaluate_match(requirements, CandidateEvidence())
        reasons = derive_review_reasons(
            result,
            extraction_status="PARTIAL",
            job_status=JobStatus.JD_PARTIAL,
        )
        assert reasons.count(ReviewReason.JD_EXTRACTION_INCOMPLETE) == 1

    def test_derivation_takes_no_scorer_failure_as_a_verdict(self) -> None:
        # A scorer that raises leaves rows UNKNOWN; the queue is named after
        # that uncertainty, not after the exception.
        requirements = [COBOL]
        result = evaluate_match(
            requirements, a_candidate(), scorer=FakeScorer(fail_on=("COBOL",))
        )
        assert result.decision is MatchDecision.INSUFFICIENT_EVIDENCE
        assert derive_review_reasons(result) == [ReviewReason.INSUFFICIENT_EVIDENCE]


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------
class TestReviewItem:
    def test_from_match_carries_identity_decision_and_report(self) -> None:
        job = a_job()
        requirements = [YEARS]
        result = evaluate_match(requirements, CandidateEvidence())
        explanation = explain_match(result, requirements, CandidateEvidence(), job=job)
        item = ReviewItem.from_match(job, result, explanation=explanation)
        assert item.job_id == "job-r"
        assert item.title == "Data Engineer"
        assert item.url == "https://jobs.example/job-r"
        assert item.decision is MatchDecision.INSUFFICIENT_EVIDENCE
        assert item.reasons == [ReviewReason.ELIGIBILITY_UNKNOWN]
        assert item.report is not None
        assert "INSUFFICIENT_EVIDENCE" in item.report

    def test_from_match_accepts_already_derived_reasons(self) -> None:
        job = a_job()
        requirements = [YEARS]
        result = evaluate_match(requirements, CandidateEvidence())
        item = ReviewItem.from_match(
            job, result, reasons=[ReviewReason.STATE_REQUIRES_HUMAN]
        )
        assert item.reasons == [ReviewReason.STATE_REQUIRES_HUMAN]

    def test_from_row_decodes_json_reasons(self) -> None:
        item = ReviewItem.from_row(
            {
                "id": "job-r",
                "title": "Data Engineer",
                "company": "Northwind",
                "canonical_url": "https://jobs.example/job-r",
                "status": "MATCHED",
                "decision": "INSUFFICIENT_EVIDENCE",
                "review_reasons": json.dumps(["ELIGIBILITY_UNKNOWN"]),
                "matched_at": "2026-10-01T00:00:00+00:00",
            }
        )
        assert item.reasons == [ReviewReason.ELIGIBILITY_UNKNOWN]
        assert item.report is None

    @pytest.mark.parametrize("raw", ["", "not json", None])
    def test_from_row_tolerates_absent_or_malformed_reasons(self, raw) -> None:
        item = ReviewItem.from_row(
            {"id": "job-r", "decision": "REVIEW_REQUIRED", "review_reasons": raw}
        )
        assert item.reasons == []

    def test_from_row_refuses_an_unknown_decision(self) -> None:
        with pytest.raises(ValueError):
            ReviewItem.from_row({"id": "job-r", "decision": "MAYBE"})

    def test_a_review_item_refuses_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            ReviewItem(  # type: ignore[call-arg]
                job_id="job-r",
                decision=MatchDecision.REVIEW_REQUIRED,
                bogus=True,
            )


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------
class TestReviewQueue:
    def test_from_matches_keeps_only_human_decisions(self) -> None:
        clean = evaluate_match([PYTHON], a_candidate())
        queued = evaluate_match([YEARS], CandidateEvidence())
        hard = evaluate_match([YEARS], a_candidate(years=1.0))
        queue = ReviewQueue.from_matches(
            [
                (a_job(job_id="job-clean"), clean, None),
                (a_job(job_id="job-queued"), queued, None),
                (a_job(job_id="job-hard"), hard, None),
            ]
        )
        assert queue.job_ids() == ["job-queued"]
        assert len(queue) == 1

    def test_from_rows_reads_the_repository_query(self, db) -> None:
        from database.repositories.jobs import JobRepository
        from core.enums import AnalysisSource, HardGateStatus

        repo = JobRepository(db)
        repo.save(a_job())
        repo.save_match(
            job_id="job-r",
            candidate_id="primary",
            decision=MatchDecision.INSUFFICIENT_EVIDENCE,
            hard_gate_status=HardGateStatus.UNKNOWN,
            analysis_source=AnalysisSource.JOB_DATA,
            requirements_fingerprint="fp-1",
            candidate_fingerprint="cfp-1",
            explanation={"decision": "INSUFFICIENT_EVIDENCE"},
            review_reasons=["ELIGIBILITY_UNKNOWN"],
        )
        assert len(repo.review_required()) == 1

        queue = ReviewQueue.from_rows(repo.review_required())
        assert [item.job_id for item in queue.items] == ["job-r"]
        assert queue.items[0].reasons == [ReviewReason.ELIGIBILITY_UNKNOWN]

    def test_a_decided_match_never_reaches_the_repository_queue(self, db) -> None:
        from database.repositories.jobs import JobRepository
        from core.enums import AnalysisSource, HardGateStatus

        repo = JobRepository(db)
        repo.save(a_job())
        repo.save_match(
            job_id="job-r",
            candidate_id="primary",
            decision=MatchDecision.MATCH,
            hard_gate_status=HardGateStatus.PASS,
            analysis_source=AnalysisSource.JOB_DATA,
            requirements_fingerprint="fp-1",
            candidate_fingerprint="cfp-1",
            explanation={"decision": "MATCH"},
        )
        assert repo.review_required() == []
        assert len(ReviewQueue.from_rows(repo.review_required())) == 0

    def test_counts_by_reason_and_only(self) -> None:
        first = ReviewItem(
            job_id="job-1",
            decision=MatchDecision.INSUFFICIENT_EVIDENCE,
            reasons=[ReviewReason.ELIGIBILITY_UNKNOWN, ReviewReason.JD_EXTRACTION_INCOMPLETE],
        )
        second = ReviewItem(
            job_id="job-2",
            decision=MatchDecision.REVIEW_REQUIRED,
            reasons=[ReviewReason.ELIGIBILITY_UNKNOWN],
        )
        queue = ReviewQueue(items=[first, second])
        assert queue.counts_by_reason() == {
            ReviewReason.ELIGIBILITY_UNKNOWN: 2,
            ReviewReason.JD_EXTRACTION_INCOMPLETE: 1,
        }
        assert [item.job_id for item in queue.only(ReviewReason.ELIGIBILITY_UNKNOWN)] == [
            "job-1",
            "job-2",
        ]
        assert queue.only(ReviewReason.LOW_AI_CONFIDENCE) == []

    def test_an_empty_queue_is_falsey_and_counted(self) -> None:
        queue = ReviewQueue()
        assert len(queue) == 0
        assert queue.job_ids() == []
        assert queue.counts_by_reason() == {}
