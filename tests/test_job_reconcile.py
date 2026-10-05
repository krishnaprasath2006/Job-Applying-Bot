"""The cross-check: two extractions, one verdict on whether they agreed.

Every conflict here comes from real ``Requirement`` rows - or, in the
service tests, from the real extractor and a real (fake-provider) model
reading of the same stored posting - because the point of a conflict is
that a human can trace it back to what each side actually produced.

The promotion rule is tested against the real matcher: the report must
turn a verdict that would have decided alone into a review, and must
never soften one that already required a human or was vetoed by the
gate.
"""

from __future__ import annotations

from typing import Optional

import pytest

from core.enums import MatchDecision, RequirementPriority, ReviewReason
from jobs.analysis import match_job
from jobs.hard_gate import evaluate_hard_gate
from jobs.matching import MatchResult, evaluate_match
from jobs.models import Requirement, RequirementKind
from jobs.reconcile import (
    RECONCILIATION_KEY,
    ConflictIssue,
    apply_conflicts,
    conflict_count,
    reconcile,
)
from jobs.requirements import extract_requirements
from jobs.review import derive_review_reasons
from test_job_analysis import POSTING, a_candidate, make_job
from test_job_interpret import FakeProvider

from assistant.job_service import JobService
from candidate_profile.service import ProfileService

# A description long enough to be usable (> 150 chars) whose prose the
# deterministic extractor reads differently from the model: the model
# claims a bare "Python" row the rules never produce as such.
AI_DESCRIPTION = (
    "We are hiring a data engineer. You will build reliable data pipelines "
    "in Python and SQL, own them in production, and mentor teammates across "
    "the platform as the team grows."
)
AI_PAGE = (
    "<html><head><title>Data Engineer</title></head><body>"
    "<h1 class=\"top-card-layout__title\">Data Engineer</h1>"
    '<div class="description__text"> <p>'
    + AI_DESCRIPTION
    + "</p> </div></body></html>"
)
AI_PAYLOAD = {
    "requirements": [
        {
            "text": "Python",
            "category": "SKILL",
            "priority": "REQUIRED",
            "evidence": "Python",
            "confidence": 0.95,
        }
    ]
}


def req(
    text: str,
    *,
    kind: RequirementKind = RequirementKind.SKILL,
    priority: RequirementPriority = RequirementPriority.REQUIRED,
    min_years: Optional[float] = None,
) -> Requirement:
    return Requirement(text=text, kind=kind, priority=priority, min_years=min_years)


# ---------------------------------------------------------------------------
# reconcile()
# ---------------------------------------------------------------------------


class TestReconcile:
    def test_identical_extractions_produce_no_conflicts(self) -> None:
        rows = [req("Python"), req("SQL")]
        report = reconcile(rows, [req("Python"), req("SQL")])

        assert report.conflicts == []
        assert report.conflict_count == 0
        assert report.has_conflicts is False
        assert report.deterministic_count == 2
        assert report.ai_count == 2

    def test_differing_years_on_a_paired_row_is_a_years_conflict(self) -> None:
        report = reconcile(
            [req("5+ years experience", kind=RequirementKind.EXPERIENCE, min_years=5.0)],
            [req("5+ years experience", kind=RequirementKind.EXPERIENCE, min_years=3.0)],
        )

        assert report.conflict_count == 1
        conflict = report.conflicts[0]
        assert conflict.issue is ConflictIssue.YEARS_DISAGREE
        assert conflict.deterministic_years == 5.0
        assert conflict.ai_years == 3.0
        assert conflict.kind == RequirementKind.EXPERIENCE.value

    def test_one_side_dropping_the_years_still_disagrees(self) -> None:
        report = reconcile(
            [req("Experience required", kind=RequirementKind.EXPERIENCE, min_years=5.0)],
            [req("Experience required", kind=RequirementKind.EXPERIENCE)],
        )

        assert report.conflict_count == 1
        assert report.conflicts[0].issue is ConflictIssue.YEARS_DISAGREE
        assert report.conflicts[0].ai_years is None

    def test_a_priority_flip_involving_required_is_a_conflict(self) -> None:
        report = reconcile(
            [req("Python", priority=RequirementPriority.REQUIRED)],
            [req("Python", priority=RequirementPriority.PREFERRED)],
        )

        assert report.conflict_count == 1
        assert report.conflicts[0].issue is ConflictIssue.PRIORITY_DISAGREE

    def test_two_non_required_priorities_are_not_a_conflict(self) -> None:
        report = reconcile(
            [req("Kubernetes", priority=RequirementPriority.PREFERRED)],
            [req("Kubernetes", priority=RequirementPriority.UNKNOWN)],
        )

        assert report.conflicts == []

    def test_a_required_row_only_one_side_found_is_a_presence_conflict(self) -> None:
        report = reconcile(
            [req("Python"), req("SQL")],
            [req("Python")],
        )

        assert report.conflict_count == 1
        conflict = report.conflicts[0]
        assert conflict.issue is ConflictIssue.PRESENCE_DISAGREE
        assert conflict.deterministic_text == "SQL"
        assert conflict.ai_text == ""

    def test_an_unpaired_non_required_row_is_not_a_conflict(self) -> None:
        report = reconcile(
            [
                req("Python"),
                req("Kubernetes", priority=RequirementPriority.PREFERRED),
            ],
            [req("Python")],
        )

        assert report.conflicts == []

    def test_rows_pair_across_different_wordings_within_a_kind(self) -> None:
        report = reconcile(
            [req("5 years Python experience", min_years=5.0)],
            [req("Python experience for 3 years", min_years=3.0)],
        )

        assert report.conflict_count == 1
        assert report.conflicts[0].issue is ConflictIssue.YEARS_DISAGREE

    def test_rows_of_different_kinds_never_pair(self) -> None:
        report = reconcile(
            [
                req(
                    "Python pipelines",
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                    priority=RequirementPriority.UNKNOWN,
                )
            ],
            [req("Python", kind=RequirementKind.SKILL)],
        )

        # The unknown-priority row is detail, not a contradiction; only
        # the model's REQUIRED row stands alone.
        assert report.conflict_count == 1
        assert report.conflicts[0].issue is ConflictIssue.PRESENCE_DISAGREE
        assert report.conflicts[0].ai_text == "Python"

    def test_an_empty_side_reports_only_its_required_rows(self) -> None:
        report = reconcile(
            [],
            [req("Python"), req("Kubernetes", priority=RequirementPriority.PREFERRED)],
        )

        assert report.conflict_count == 1
        assert report.conflicts[0].deterministic_text == ""
        assert report.deterministic_count == 0
        assert report.ai_count == 2

    def test_a_pair_reports_at_most_one_issue(self) -> None:
        report = reconcile(
            [
                req(
                    "5+ years required",
                    kind=RequirementKind.EXPERIENCE,
                    priority=RequirementPriority.REQUIRED,
                    min_years=5.0,
                )
            ],
            [
                req(
                    "5+ years required",
                    kind=RequirementKind.EXPERIENCE,
                    priority=RequirementPriority.PREFERRED,
                    min_years=3.0,
                )
            ],
        )

        # Years outrank priority: one disagreement, one conflict.
        assert report.conflict_count == 1
        assert report.conflicts[0].issue is ConflictIssue.YEARS_DISAGREE


# ---------------------------------------------------------------------------
# Metadata round trip
# ---------------------------------------------------------------------------


class TestMetadataRoundTrip:
    def test_to_metadata_carries_the_counts_and_the_issues(self) -> None:
        report = reconcile(
            [req("Python"), req("SQL")],
            [req("Python")],
        )
        block = report.to_metadata()

        assert block["conflicts"] == report.conflict_count
        assert block["deterministic"] == 2
        assert block["ai"] == 1
        assert len(block["issues"]) == 1
        assert block["issues"][0]["issue"] == "PRESENCE_DISAGREE"

    def test_conflict_count_reads_what_to_metadata_wrote(self) -> None:
        block = reconcile([req("Python")], []).to_metadata()

        assert conflict_count({RECONCILIATION_KEY: block}) == 1

    @pytest.mark.parametrize(
        "metadata",
        [
            None,
            {},
            {RECONCILIATION_KEY: None},
            {RECONCILIATION_KEY: "not a block"},
            {RECONCILIATION_KEY: {}},
            {RECONCILIATION_KEY: {"conflicts": "two"}},
            {RECONCILIATION_KEY: {"conflicts": True}},
        ],
    )
    def test_absent_or_unreadable_metadata_reads_as_zero(
        self, metadata
    ) -> None:
        assert conflict_count(metadata) == 0

    def test_the_summary_names_both_sides(self) -> None:
        agree = reconcile([req("Python")], [req("Python")])
        clash = reconcile([req("Python")], [])

        assert "agreed" in agree.summary()
        assert "1 conflict" in clash.summary()

    def test_the_report_preserves_both_row_sets_in_full(self) -> None:
        deterministic = [
            Requirement(
                text="Python",
                priority=RequirementPriority.REQUIRED,
                source_excerpt="Must know Python",
                min_years=None,
            ),
            req("SQL"),
        ]
        ai = [req("Python")]

        block = reconcile(deterministic, ai).to_metadata()

        det_rows = block["deterministic_rows"]
        ai_rows = block["ai_rows"]
        assert [row["text"] for row in det_rows] == ["Python", "SQL"]
        assert [row["text"] for row in ai_rows] == ["Python"]
        # Excerpts and priorities survive the JSON round trip, so the
        # preserved reading can still be audited against the posting.
        assert det_rows[0]["source_excerpt"] == "Must know Python"
        assert det_rows[0]["priority"] == "REQUIRED"
        assert det_rows[1]["kind"] == RequirementKind.SKILL.value


# ---------------------------------------------------------------------------
# apply_conflicts()
# ---------------------------------------------------------------------------


class TestApplyConflicts:
    @pytest.mark.parametrize(
        ("decision", "expected"),
        [
            (MatchDecision.MATCH, MatchDecision.REVIEW_REQUIRED),
            (MatchDecision.PARTIAL_MATCH, MatchDecision.REVIEW_REQUIRED),
            (MatchDecision.HARD_MISMATCH, MatchDecision.HARD_MISMATCH),
            (MatchDecision.INSUFFICIENT_EVIDENCE, MatchDecision.INSUFFICIENT_EVIDENCE),
            (MatchDecision.REVIEW_REQUIRED, MatchDecision.REVIEW_REQUIRED),
        ],
    )
    def test_only_a_deciding_verdict_is_promoted(
        self, decision: MatchDecision, expected: MatchDecision
    ) -> None:
        result = MatchResult(
            decision=decision, gate=evaluate_hard_gate([], a_candidate())
        )

        assert apply_conflicts(result, 1).decision is expected

    def test_zero_conflicts_return_the_original_untouched(self) -> None:
        match = evaluate_match([req("Python")], a_candidate(claims=("Python",)))

        assert apply_conflicts(match, 0) is match

    def test_a_real_match_is_promoted_without_rewriting_the_original(self) -> None:
        match = evaluate_match([req("Python")], a_candidate(claims=("Python",)))
        assert match.decision is MatchDecision.MATCH

        promoted = apply_conflicts(match, 2)

        assert promoted.decision is MatchDecision.REVIEW_REQUIRED
        assert match.decision is MatchDecision.MATCH


# ---------------------------------------------------------------------------
# derive_review_reasons(conflicts=...)
# ---------------------------------------------------------------------------


class TestConflictReason:
    def test_a_promoted_verdict_carries_the_conflict_reason(self) -> None:
        match = evaluate_match([req("Python")], a_candidate(claims=("Python",)))
        promoted = apply_conflicts(match, 1)

        assert derive_review_reasons(promoted, conflicts=1) == [
            ReviewReason.EXTRACTION_CONFLICT
        ]

    def test_zero_conflicts_name_no_reason(self) -> None:
        match = evaluate_match([req("Python")], a_candidate(claims=("Python",)))
        promoted = apply_conflicts(match, 1)

        assert derive_review_reasons(promoted, conflicts=0) == []

    def test_an_undecided_verdict_gets_no_reasons_even_with_conflicts(self) -> None:
        # Promotion and reason travel together, upstream in match_job;
        # deriving reasons over a verdict that still says MATCH would
        # queue nothing anyway (membership is requires_human).
        match = evaluate_match([req("Python")], a_candidate(claims=("Python",)))

        assert derive_review_reasons(match, conflicts=3) == []


# ---------------------------------------------------------------------------
# match_job(): conflicts reach the stored verdict
# ---------------------------------------------------------------------------


class TestMatchJobConflicts:
    def test_conflicts_promote_and_store_the_reason(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        requirements = extract_requirements(POSTING)
        evidence = a_candidate(years=5.0)

        outcome = match_job(
            job,
            requirements,
            evidence,
            repo,
            candidate_id="primary",
            conflicts=1,
        )

        assert outcome.result.decision is MatchDecision.REVIEW_REQUIRED
        assert outcome.review_reasons == [ReviewReason.EXTRACTION_CONFLICT]
        rows = repo.matches(job_id=job.id)
        assert rows[0]["decision"] == "REVIEW_REQUIRED"
        assert rows[0]["review_reasons"] == ["EXTRACTION_CONFLICT"]
        assert rows[0]["explanation"]["decision"] == "REVIEW_REQUIRED"

    def test_a_cached_hit_replays_the_promoted_verdict(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        requirements = extract_requirements(POSTING)
        evidence = a_candidate(years=5.0)

        first = match_job(
            job, requirements, evidence, repo, candidate_id="primary", conflicts=1
        )
        second = match_job(
            job, requirements, evidence, repo, candidate_id="primary", conflicts=1
        )

        assert second.cached is True
        assert second.result == first.result
        assert second.review_reasons == first.review_reasons

    def test_zero_conflicts_store_the_plain_verdict(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        requirements = extract_requirements(POSTING)
        evidence = a_candidate(years=5.0)

        outcome = match_job(job, requirements, evidence, repo, candidate_id="primary")

        assert outcome.result.decision is MatchDecision.MATCH
        assert outcome.review_reasons == []
        rows = repo.matches(job_id=job.id)
        assert rows[0]["review_reasons"] == []

    def test_a_gate_veto_is_not_softened_by_conflicts(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        requirements = extract_requirements(POSTING)
        evidence = a_candidate(claims=("COBOL",), years=0.0)

        outcome = match_job(
            job,
            requirements,
            evidence,
            repo,
            candidate_id="primary",
            conflicts=4,
        )

        assert outcome.result.decision is MatchDecision.HARD_MISMATCH
        assert outcome.review_reasons == []


# ---------------------------------------------------------------------------
# Service: the report is written with its rows, and rides the match
# ---------------------------------------------------------------------------


@pytest.fixture()
def profiles(tmp_path, db) -> ProfileService:
    service = ProfileService(db, storage_path=tmp_path / "candidate_profile.json")
    service.create_profile("primary", persist_json=True, actor="user")
    return service


@pytest.fixture()
def ai_service(db, profiles) -> JobService:
    return JobService(
        db,
        profile_service=profiles,
        candidate_id="primary",
        evidence_provider=lambda: a_candidate(claims=("Python",)),
    )


def ingest_ai_page(service: JobService, *, job_id: str = "ai-1") -> str:
    result = service.ingest_page(
        AI_PAGE, page_url=f"https://www.linkedin.com/jobs/view/4000000{job_id}"
    )
    assert result.job.description_text
    return result.job.id


class TestServiceReconciliation:
    def test_ai_analysis_records_the_cross_check_on_the_job(self, ai_service) -> None:
        job_id = ingest_ai_page(ai_service)
        seen_before = ai_service.get(job_id).seen_count

        analysis = ai_service.analyze(
            job_id, ai=True, provider=FakeProvider(payload=AI_PAYLOAD)
        )

        assert analysis.ai_fallback is False
        job = ai_service.get(job_id)
        block = job.metadata[RECONCILIATION_KEY]
        assert block["conflicts"] >= 1
        assert conflict_count(job.metadata) == block["conflicts"]
        # Neither reading overwrote the other: the deterministic rows are
        # preserved whole, and so are the model's (as the stored rows).
        expected_det = extract_requirements(
            job.description_text or "", raw=job.description_raw or None
        )
        assert expected_det, "the fixture description must yield requirements"
        assert [row["text"] for row in block["deterministic_rows"]] == [
            row.text for row in expected_det
        ]
        assert [row["text"] for row in block["ai_rows"]] == ["Python"]
        stored = ai_service.repository.requirements(job_id)
        assert [row.text for row in stored] == ["Python"]
        # Written through the metadata column, not through save():
        assert job.seen_count == seen_before
        # ...and it is really in the database, not just the read model.
        fresh = ai_service.repository.load(job_id)
        assert conflict_count(fresh.metadata) >= 1

    def test_match_promotes_and_queues_a_contradicted_job(self, ai_service) -> None:
        job_id = ingest_ai_page(ai_service)
        ai_service.analyze(
            job_id, ai=True, provider=FakeProvider(payload=AI_PAYLOAD)
        )

        outcome = ai_service.match(job_id)

        assert outcome.result.decision is MatchDecision.REVIEW_REQUIRED
        assert ReviewReason.EXTRACTION_CONFLICT in outcome.review_reasons
        assert job_id in ai_service.review_queue().job_ids()

    def test_a_match_keeps_the_models_rows(self, ai_service) -> None:
        job_id = ingest_ai_page(ai_service)
        ai_service.analyze(
            job_id, ai=True, provider=FakeProvider(payload=AI_PAYLOAD)
        )

        ai_service.match(job_id)

        rows = ai_service.repository.requirements(job_id)
        assert [row.text for row in rows] == ["Python"]

    def test_deterministic_reanalysis_clears_the_report(self, ai_service) -> None:
        job_id = ingest_ai_page(ai_service)
        ai_service.analyze(
            job_id, ai=True, provider=FakeProvider(payload=AI_PAYLOAD)
        )
        assert conflict_count(ai_service.get(job_id).metadata) >= 1

        ai_service.analyze(job_id)

        job = ai_service.get(job_id)
        assert RECONCILIATION_KEY not in job.metadata
        outcome = ai_service.match(job_id)
        assert outcome.result.decision is MatchDecision.MATCH
        assert ReviewReason.EXTRACTION_CONFLICT not in outcome.review_reasons

    def test_matching_a_never_analysed_job_analyses_it_first(self, ai_service) -> None:
        job_id = ingest_ai_page(ai_service)

        outcome = ai_service.match(job_id)

        assert outcome.cached is False
        assert outcome.result.decision is MatchDecision.MATCH
        assert outcome.review_reasons == []
        assert ai_service.repository.requirements(job_id)

    def test_patch_metadata_on_an_unknown_job_reports_failure(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)

        assert (
            repo.patch_metadata("no-such-job", {RECONCILIATION_KEY: {"conflicts": 1}})
            is False
        )
