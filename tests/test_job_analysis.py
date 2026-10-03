"""The analysis cache: same inputs reuse the verdict, changed inputs do not.

Every "reuse" assertion here also asserts *what* was reused — a cache hit
that silently returned different requirements would pass a lazy test and
fail a real user. The store is the real repository against a temporary
database, because a fake store can only prove the code it was written
for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.enums import (
    AnalysisSource,
    FactStatus,
    MatchDecision,
    RequirementPriority,
    ReviewReason,
)
from core.hashing import sha256_text
from jobs.analysis import (
    ANALYZER,
    ANALYZER_VERSION,
    AnalysisStore,
    MatchOutcome,
    RequirementAnalysis,
    analyze_job,
    candidate_fingerprint,
    content_fingerprint,
    match_job,
    requirements_fingerprint,
    scorer_fingerprint,
)
from jobs.candidate import CandidateClaim, CandidateEvidence, FactRef
from jobs.models import Job, Requirement, RequirementKind
from jobs.requirements import extract_requirements

POSTING = (
    "<h3>Required qualifications</h3>"
    "<ul><li>3+ years of experience required</li>"
    "<li>Python</li></ul>"
)
OTHER_POSTING = "<h3>Requirements</h3><ul><li>SQL</li><li>Kubernetes</li></ul>"


def make_job(*, job_id: str = "job-a", description: str = POSTING) -> Job:
    return Job(
        id=job_id,
        title="Machine Learning Engineer",
        company="Northwind",
        canonical_url=f"https://jobs.example/{job_id}",
        description_text=description,
    )


def a_candidate(
    *,
    claims: tuple[str, ...] = ("Python",),
    years: float | None = None,
    sponsorship: bool | None = None,
):
    return CandidateEvidence(
        claims=[
            CandidateClaim(
                text=text,
                source=FactRef(
                    field_path="skills.proficient",
                    status=FactStatus.VERIFIED,
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


def counting_extractor(calls: list[str]):
    def extract(text: str, *, raw: str | None = None) -> list[Requirement]:
        calls.append(text)
        return extract_requirements(text, raw=raw)

    return extract


def without_ids(rows: list[Requirement]) -> list[dict]:
    """Requirement rows without their generated ids — the store assigns
    those, so freshly extracted rows and rows read back differ only there."""
    return [row.model_dump(exclude={"id"}) for row in rows]


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------
class TestFingerprints:
    def test_content_fingerprint_prefers_the_stored_hash(self) -> None:
        job = make_job()
        job.description_hash = "stored-hash"
        assert content_fingerprint(job) == "stored-hash"

    def test_content_fingerprint_hashes_the_text_when_no_hash(self) -> None:
        assert content_fingerprint(make_job()) == sha256_text(POSTING)
        assert content_fingerprint(make_job(description=OTHER_POSTING)) != (
            content_fingerprint(make_job())
        )

    def test_a_job_with_no_description_fingerprints_as_the_empty_string(
        self,
    ) -> None:
        job = Job(id="job-empty", title="Anything", company="Acme")
        assert content_fingerprint(job) == sha256_text("")

    @pytest.mark.parametrize(
        "override",
        [
            {"text": "SQL"},
            {"kind": RequirementKind.DATABASE},
            {"priority": RequirementPriority.PREFERRED},
            {"min_years": 2.0},
            {"ambiguous": True},
            {"confidence": 0.5},
        ],
    )
    def test_a_changed_requirement_changes_the_fingerprint(self, override: dict) -> None:
        base = Requirement(text="Python", priority=RequirementPriority.REQUIRED)
        changed = Requirement(
            **{"text": "Python", "priority": RequirementPriority.REQUIRED, **override}
        )
        assert requirements_fingerprint([base]) != requirements_fingerprint([changed])

    def test_requirement_order_is_part_of_the_fingerprint(self) -> None:
        python = Requirement(text="Python", priority=RequirementPriority.REQUIRED)
        sql = Requirement(text="SQL", priority=RequirementPriority.REQUIRED)
        assert requirements_fingerprint([python, sql]) != requirements_fingerprint(
            [sql, python]
        )

    def test_identical_requirements_fingerprint_identically(self) -> None:
        rows = extract_requirements(POSTING)
        assert requirements_fingerprint(rows) == requirements_fingerprint(
            [Requirement.model_validate(row.model_dump()) for row in rows]
        )

    @pytest.mark.parametrize(
        "override",
        [
            {"years": 7.0},
            {"sponsorship": True},
        ],
    )
    def test_changed_years_or_sponsorship_change_the_candidate_fingerprint(
        self, override: dict
    ) -> None:
        base = a_candidate()
        other = a_candidate(**override)
        assert candidate_fingerprint(base) != candidate_fingerprint(other)

    def test_a_changed_claim_changes_the_candidate_fingerprint(self) -> None:
        assert candidate_fingerprint(a_candidate(claims=("Python",))) != (
            candidate_fingerprint(a_candidate(claims=("Rust",)))
        )

    def test_a_claim_truth_status_is_part_of_the_fingerprint(self) -> None:
        verified = a_candidate(claims=("Python",))
        inferred = CandidateEvidence(
            claims=[
                CandidateClaim(
                    text="Python",
                    source=FactRef(
                        field_path="skills.proficient", status=FactStatus.INFERRED
                    ),
                )
            ]
        )
        assert candidate_fingerprint(verified) != candidate_fingerprint(inferred)

    def test_claim_order_is_part_of_the_fingerprint(self) -> None:
        assert candidate_fingerprint(a_candidate(claims=("Python", "SQL"))) != (
            candidate_fingerprint(a_candidate(claims=("SQL", "Python")))
        )

    def test_an_evidence_excerpt_is_not_part_of_the_fingerprint(self) -> None:
        from core.enums import EvidenceSourceType
        from core.evidence import Evidence

        with_excerpt = CandidateEvidence(
            claims=[
                CandidateClaim(
                    text="Python",
                    source=FactRef(
                        field_path="skills.proficient",
                        status=FactStatus.VERIFIED,
                        evidence=[
                            Evidence(
                                source_type=EvidenceSourceType.RESUME,
                                source_id="resume.txt",
                                text_excerpt="Five years of Python at Acme",
                            )
                        ],
                    ),
                )
            ]
        )
        without = a_candidate(claims=("Python",))
        assert candidate_fingerprint(with_excerpt) == candidate_fingerprint(without)


# ---------------------------------------------------------------------------
# Extraction cache
# ---------------------------------------------------------------------------
class TestExtractionCache:
    def test_the_first_run_records_and_the_second_reuses(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        calls: list[str] = []

        first = analyze_job(job, repo, extract=counting_extractor(calls))
        second = analyze_job(job, repo, extract=counting_extractor(calls))

        assert first.cached is False
        assert second.cached is True
        assert without_ids(second.requirements) == without_ids(first.requirements)
        assert second.analysis_id == first.analysis_id
        assert len(calls) == 1
        assert without_ids(repo.requirements(job.id)) == without_ids(first.requirements)
        assert len(repo.analyses(job.id)) == 1

    def test_a_changed_description_misses_and_replaces_the_rows(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job_v1 = make_job()
        repo.save(job_v1)
        first = analyze_job(job_v1, repo)

        job_v2 = make_job(description=OTHER_POSTING)
        second = analyze_job(job_v2, repo)

        assert second.cached is False
        assert second.content_hash != first.content_hash
        assert without_ids(repo.requirements(job_v1.id)) == without_ids(
            second.requirements
        )
        assert len(repo.analyses(job_v1.id)) == 2

    def test_an_empty_description_yields_empty_requirements_both_times(
        self, db
    ) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = Job(id="job-bare", title="Anything", company="Acme")
        repo.save(job)

        first = analyze_job(job, repo)
        second = analyze_job(job, repo)

        assert first.requirements == []
        assert first.cached is False
        assert second.cached is True
        assert second.requirements == []

    def test_the_recorded_analysis_carries_its_identity(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        outcome = analyze_job(
            job,
            repo,
            analysis_source=AnalysisSource.AI_GENERAL,
            ai_provider="ollama",
            ai_model="qwen2.5:7b",
            prompt_version="jd_extraction_v1",
        )
        row = repo.analyses(job.id)[0]
        assert row["analyzer"] == ANALYZER
        assert row["analyzer_version"] == ANALYZER_VERSION
        assert row["analysis_source"] == AnalysisSource.AI_GENERAL.value
        assert row["ai_model"] == "qwen2.5:7b"
        assert row["requirement_count"] == len(outcome.requirements)
        assert row["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# Match cache
# ---------------------------------------------------------------------------
class TestMatchCache:
    def test_the_first_match_records_and_the_second_reuses(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        requirements = extract_requirements(POSTING)
        evidence = a_candidate(years=5.0)

        first = match_job(job, requirements, evidence, repo, candidate_id="primary")
        second = match_job(job, requirements, evidence, repo, candidate_id="primary")

        assert first.cached is False
        assert second.cached is True
        assert second.result == first.result
        assert second.match_id == first.match_id
        rows = repo.matches(job_id=job.id)
        assert len(rows) == 1
        assert rows[0]["decision"] == first.result.decision.value

    def test_a_cached_hit_reconstructs_the_gate_and_the_scores(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        requirements = extract_requirements(POSTING)
        evidence = a_candidate(years=1.0)

        first = match_job(job, requirements, evidence, repo, candidate_id="primary")
        second = match_job(job, requirements, evidence, repo, candidate_id="primary")

        assert second.result.gate.status is first.result.gate.status
        assert [check.reason for check in second.result.gate.checks] == [
            check.reason for check in first.result.gate.checks
        ]
        assert first.result.decision is MatchDecision.HARD_MISMATCH
        assert second.result.scores == []
        assert first.result.gate.checks[0].requirement_index == 0

    def test_a_different_candidate_is_a_different_key(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        requirements = extract_requirements(POSTING)
        evidence = a_candidate(years=5.0)

        match_job(job, requirements, evidence, repo, candidate_id="primary")
        other = match_job(job, requirements, evidence, repo, candidate_id="other")

        assert other.cached is False
        assert len(repo.matches(job_id=job.id)) == 2

    def test_changed_requirements_change_the_match_key(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        evidence = a_candidate(years=5.0)

        match_job(job, extract_requirements(POSTING), evidence, repo, candidate_id="p")
        changed = match_job(
            job, extract_requirements(OTHER_POSTING), evidence, repo, candidate_id="p"
        )

        assert changed.cached is False

    def test_changed_candidate_evidence_changes_the_match_key(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        requirements = extract_requirements(POSTING)

        match_job(job, requirements, a_candidate(years=5.0), repo, candidate_id="p")
        changed = match_job(
            job, requirements, a_candidate(years=6.0), repo, candidate_id="p"
        )

        assert changed.cached is False

    def test_review_reasons_are_stored_and_replayed_from_cache(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        requirements = [
            Requirement(text="3+ years required", min_years=3.0, priority=RequirementPriority.REQUIRED)
        ]
        evidence = CandidateEvidence()

        first = match_job(job, requirements, evidence, repo, candidate_id="primary")
        second = match_job(job, requirements, evidence, repo, candidate_id="primary")

        assert first.review_reasons == [ReviewReason.ELIGIBILITY_UNKNOWN]
        assert second.cached is True
        assert second.review_reasons == [ReviewReason.ELIGIBILITY_UNKNOWN]
        row = repo.matches(job_id=job.id)[0]
        assert row["review_reasons"] == ["ELIGIBILITY_UNKNOWN"]

    def test_counts_cover_the_gate_rows_and_the_scored_rows(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        match_job(
            job,
            extract_requirements(POSTING),
            a_candidate(years=5.0),
            repo,
            candidate_id="primary",
        )
        row = repo.matches(job_id=job.id)[0]
        # One gate row (years matched) and one scored row (Python claimed).
        assert row["matched_count"] == 2
        assert row["mismatched_count"] == 0
        assert row["unknown_count"] == 0

    def test_the_stored_explanation_is_the_full_match_result(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        outcome = match_job(
            job,
            extract_requirements(POSTING),
            a_candidate(years=5.0),
            repo,
            candidate_id="primary",
        )
        row = repo.matches(job_id=job.id)[0]
        assert row["explanation"]["decision"] == outcome.result.decision.value
        assert row["explanation"]["gate"]["status"] == outcome.result.gate.status.value
        assert len(row["explanation"]["scores"]) == len(outcome.result.scores)

    def test_the_evidence_column_holds_the_candidate_lineage(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        match_job(
            job,
            extract_requirements(POSTING),
            a_candidate(years=5.0),
            repo,
            candidate_id="primary",
        )
        row = repo.matches(job_id=job.id)[0]
        paths = {item["field_path"] for item in row["evidence"]}
        assert "experience.total_years_experience" in paths
        assert "skills.proficient" in paths


# ---------------------------------------------------------------------------
# The scorer's half of the match cache key
# ---------------------------------------------------------------------------
class TestScorerCacheKey:
    def test_no_scorer_fingerprints_as_the_empty_key(self) -> None:
        assert scorer_fingerprint(None) == ""

    def test_the_lexical_scorer_fingerprints_as_its_id(self) -> None:
        from ai.embeddings import LexicalScorer

        assert scorer_fingerprint(LexicalScorer()) == "lexical:v1"

    def test_an_unnamed_scorer_falls_back_to_its_class(self) -> None:
        class Anonymous:
            def similarity(self, left: str, right: str) -> float:
                return 0.0

        fingerprint = scorer_fingerprint(Anonymous())
        assert fingerprint.endswith("Anonymous")
        assert "." in fingerprint

    def test_switching_scorers_rematches_instead_of_replaying(self, db) -> None:
        from ai.embeddings import LexicalScorer
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        requirements = extract_requirements(POSTING)
        evidence = a_candidate(years=5.0)

        plain = match_job(job, requirements, evidence, repo, candidate_id="primary")
        scored = match_job(
            job,
            requirements,
            evidence,
            repo,
            candidate_id="primary",
            scorer=LexicalScorer(),
        )

        # Different scorer, different key: the verdict is recomputed rather
        # than borrowed from a scorer that never computed it.
        assert plain.cached is False
        assert scored.cached is False
        assert plain.scorer_fingerprint == ""
        assert scored.scorer_fingerprint == "lexical:v1"
        assert len(repo.matches(job_id=job.id)) == 2

    def test_the_same_scorer_id_hits_the_cache_across_instances(self, db) -> None:
        from ai.embeddings import LexicalScorer
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        job = make_job()
        repo.save(job)
        requirements = extract_requirements(POSTING)
        evidence = a_candidate(years=5.0)

        first = match_job(
            job, requirements, evidence, repo, candidate_id="primary",
            scorer=LexicalScorer(),
        )
        second = match_job(
            job, requirements, evidence, repo, candidate_id="primary",
            scorer=LexicalScorer(),
        )

        assert first.cached is False
        assert second.cached is True
        assert second.scorer_fingerprint == "lexical:v1"
        assert len(repo.matches(job_id=job.id)) == 1


# ---------------------------------------------------------------------------
# The protocol and the layer it guards
# ---------------------------------------------------------------------------
class TestStoreProtocol:
    def test_the_repository_satisfies_the_protocol(self, db) -> None:
        from database.repositories.jobs import JobRepository

        assert isinstance(JobRepository(db), AnalysisStore)

    def test_a_bare_object_does_not(self) -> None:
        assert not isinstance(object(), AnalysisStore)

    def test_outcome_models_refuse_unknown_fields(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RequirementAnalysis(bogus=True)  # type: ignore[call-arg]


class TestLayerBoundary:
    def test_jobs_never_imports_database_browser_or_legacy(self, project_root: Path) -> None:
        forbidden = ("import database", "from database", "selenium", "from automation")
        offenders = []
        for path in sorted((project_root / "src" / "jobs").glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for needle in forbidden:
                if needle in source:
                    offenders.append(f"{path.name}: {needle}")
        assert offenders == []
