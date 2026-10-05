"""JobService: the wiring between stored jobs, the profile, and jobs.*.

The service makes no decisions of its own, so these tests check wiring
behaviour only — the right repository, the right profile, the cache
actually reused — while every verdict still comes from the already-tested
``jobs`` package. The fixture posting wants five years and the synthetic
profile states three, so the gate's veto is the expected outcome, not a
coincidence.
"""

from __future__ import annotations

import pytest

from core.enums import FactStatus, MatchDecision, ReviewReason
from core.errors import JobNotFoundError
from core.evidence import Evidence
from core.enums import EvidenceSourceType
from jobs.candidate import CandidateEvidence
from jobs.models import Job, RequirementKind
from candidate_profile.service import ProfileService

FIXTURE_PAGE = "job_detail.html"
YEARS_FIELD = "experience.total_years_experience"


@pytest.fixture()
def profiles(tmp_path, db) -> ProfileService:
    """A profile seeded with the synthetic fixture's verified facts."""
    service = ProfileService(db, storage_path=tmp_path / "candidate_profile.json")
    service.create_profile("primary", persist_json=True, actor="user")
    service.update_fact(
        YEARS_FIELD,
        3,
        status=FactStatus.VERIFIED,
        source=EvidenceSourceType.RESUME,
        source_id="resume.txt",
        evidence=[
            Evidence(
                source_type=EvidenceSourceType.RESUME,
                source_id="resume.txt",
                text_excerpt="SYNTHETIC: 3 years",
            )
        ],
        candidate_id="primary",
        actor="user",
    )
    service.update_fact(
        "skills.proficient",
        ["Python", "SQL"],
        status=FactStatus.VERIFIED,
        source=EvidenceSourceType.USER_INPUT,
        source_id="profile",
        evidence=[
            Evidence(
                source_type=EvidenceSourceType.USER_INPUT,
                source_id="profile",
                text_excerpt="SYNTHETIC: Python, SQL",
            )
        ],
        candidate_id="primary",
        actor="user",
    )
    return service


@pytest.fixture()
def service(db, profiles):
    from assistant.job_service import JobService

    return JobService(db, profile_service=profiles, candidate_id="primary")


def fixture_page(fixtures_dir):
    return (fixtures_dir / "html" / FIXTURE_PAGE).read_text(encoding="utf-8")


def ingest(service, fixtures_dir) -> str:
    result = service.ingest_page(fixture_page(fixtures_dir), source="fixture")
    assert result.created
    assert result.page.usable
    return result.job.id


# ---------------------------------------------------------------------------
# Jobs in and out
# ---------------------------------------------------------------------------
class TestStoredJobs:
    def test_an_unknown_job_id_raises_rather_than_returning_none(self, service) -> None:
        with pytest.raises(JobNotFoundError):
            service.get("job-does-not-exist")

    def test_save_then_get_round_trips(self, service) -> None:
        job = Job(source="fixture", title="Data Engineer", company="Northwind")
        job_id, created = service.save(job)
        assert created is True
        loaded = service.get(job_id)
        assert loaded.title == "Data Engineer"
        assert [row.id for row in service.list_jobs()] == [job_id]

    def test_ingesting_the_same_page_twice_merges(self, service, fixtures_dir) -> None:
        first = service.ingest_page(fixture_page(fixtures_dir), source="fixture")
        second = service.ingest_page(fixture_page(fixtures_dir), source="fixture")
        assert first.created is True
        assert second.created is False
        assert second.job.id == first.job.id
        assert len(service.list_jobs()) == 1
        assert second.job.description_text

    def test_an_unusable_page_is_still_recorded(self, service) -> None:
        result = service.ingest_page("<html><body>nothing here</body></html>")
        assert result.page.usable is False
        assert result.job.description_text is None
        assert result.created is True


# ---------------------------------------------------------------------------
# Evidence from the real profile
# ---------------------------------------------------------------------------
class TestCandidateEvidence:
    def test_the_profile_becomes_matcher_evidence(self, service) -> None:
        evidence = service.evidence()
        assert evidence.years_of_experience == 3
        assert evidence.years_source is not None
        assert evidence.years_source.status is FactStatus.VERIFIED
        assert {claim.text for claim in evidence.claims} >= {"Python", "SQL"}

    def test_an_injected_provider_wins(self, db, profiles) -> None:
        from assistant.job_service import JobService

        stripped = CandidateEvidence()
        service = JobService(
            db,
            profile_service=profiles,
            candidate_id="primary",
            evidence_provider=lambda: stripped,
        )
        assert service.evidence() is stripped


# ---------------------------------------------------------------------------
# Analysis and matching through the service
# ---------------------------------------------------------------------------
class TestAnalysisAndMatching:
    def test_analyze_reuses_the_cache(self, service, fixtures_dir) -> None:
        job_id = ingest(service, fixtures_dir)
        first = service.analyze(job_id)
        second = service.analyze(job_id)
        assert first.cached is False
        assert second.cached is True
        assert [r.model_dump(exclude={"id"}) for r in second.requirements] == [
            r.model_dump(exclude={"id"}) for r in first.requirements
        ]
        assert any(r.min_years == 5.0 for r in first.requirements)
        assert any(
            r.kind is RequirementKind.PROGRAMMING_LANGUAGE for r in first.requirements
        )

    def test_match_hits_the_gate_before_any_scoring(self, service, fixtures_dir) -> None:
        job_id = ingest(service, fixtures_dir)
        outcome = service.match(job_id)
        assert outcome.cached is False
        assert outcome.result.decision is MatchDecision.HARD_MISMATCH
        assert outcome.result.gate.status.value == "HARD_MISMATCH"
        assert outcome.result.scores == []
        assert outcome.review_reasons == []

    def test_a_cached_match_survives_a_new_service_instance(
        self, service, fixtures_dir, db, profiles
    ) -> None:
        from assistant.job_service import JobService

        job_id = ingest(service, fixtures_dir)
        first = service.match(job_id)
        fresh = JobService(
            db,
            profile_service=profiles,
            candidate_id="primary",
        )
        second = fresh.match(job_id)
        assert second.cached is True
        assert second.result == first.result
        assert second.match_id == first.match_id


# ---------------------------------------------------------------------------
# Explanation
# ---------------------------------------------------------------------------
class TestExplain:
    def test_explaining_before_a_match_refuses_to_guess(
        self, service, fixtures_dir
    ) -> None:
        job_id = ingest(service, fixtures_dir)
        with pytest.raises(JobNotFoundError):
            service.explain(job_id)

    def test_explain_reads_the_stored_decision(self, service, fixtures_dir) -> None:
        job_id = ingest(service, fixtures_dir)
        service.match(job_id)
        explanation = service.explain(job_id)
        assert explanation.decision is MatchDecision.HARD_MISMATCH
        assert explanation.job_title == "Senior Machine Learning Engineer"
        assert explanation.rows
        report = explanation.render()
        assert "posting:" in report
        assert "candidate:" in report
        assert "5" in report  # the gate's reason names both sides


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------
class TestReviewQueue:
    def test_a_decided_job_never_queues(self, service, fixtures_dir) -> None:
        job_id = ingest(service, fixtures_dir)
        service.match(job_id)
        assert len(service.review_queue()) == 0

    def test_a_profile_without_years_queues_for_review(
        self, service, fixtures_dir, db, profiles
    ) -> None:
        from assistant.job_service import JobService

        job_id = ingest(service, fixtures_dir)
        no_years = CandidateEvidence.from_facts(
            [
                fact
                for fact in profiles.load_profile("primary").to_facts()
                if fact.field_path != YEARS_FIELD
            ]
        )
        quiet = JobService(
            db,
            profile_service=profiles,
            candidate_id="primary",
            evidence_provider=lambda: no_years,
        )
        outcome = quiet.match(job_id)
        assert outcome.result.decision is MatchDecision.INSUFFICIENT_EVIDENCE

        queue = service.review_queue()
        assert len(queue) == 1
        item = queue.items[0]
        assert item.job_id == job_id
        assert ReviewReason.ELIGIBILITY_UNKNOWN in item.reasons
