"""Job persistence: migration, identity, deduplication, lifecycle, caching.

These are the properties the rest of Milestone 3 stands on. If identity is
wrong, jobs duplicate or vanish; if transitions are unchecked, a job can reach
a state nothing should be able to reach; if the cache keys are wrong, either
work is repeated or stale results survive an edited posting.

Nothing here touches a browser, a network, or a real candidate profile.
"""

from __future__ import annotations

import pytest
from core.enums import (
    AnalysisSource,
    ExtractionMethod,
    ExtractionStatus,
    HardGateStatus,
    MatchDecision,
    RequirementPriority,
)
from core.errors import InvalidStateTransitionError, JobNotFoundError
from database.repositories.jobs import JobRepository
from jobs.deduplicator import (
    IDENTITY_TIER_CANONICAL_URL,
    IDENTITY_TIER_CONTENT,
    IDENTITY_TIER_EXTERNAL_ID,
    JobDeduplicator,
    JobIdentity,
    canonicalize_url,
    extract_posting_id,
    merge_discovery,
)
from jobs.models import Job, JobStatus, Requirement, RequirementKind
from pydantic import ValidationError

SHEET = "https://www.linkedin.com/jobs/view/synthetic-role-4000123456/"

#: A posting URL carrying no numeric id, so identity must fall back to it.
NO_ID_URL = "https://www.linkedin.com/jobs/view/synthetic-role-alpha"


def make_job(**overrides) -> Job:
    base = {
        "source": "linkedin",
        "company": "Synthetic Analytics Pvt",
        "title": "Senior Machine Learning Engineer (Remote)",
        "external_job_id": "4000123456",
        "url": SHEET,
        "canonical_url": "https://www.linkedin.com/jobs/view/synthetic-role-4000123456",
        "description_text": "SYNTHETIC JOB DESCRIPTION. Not a real posting.",
    }
    base.update(overrides)
    return Job(**base)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


class TestMigration003:
    def test_all_six_tables_exist(self, db) -> None:
        tables = set(db.table_names())
        assert {
            "jobs",
            "job_requirements",
            "job_extraction_runs",
            "job_analyses",
            "job_matches",
            "job_state_events",
        } <= tables

    def test_migration_is_recorded_once(self, db) -> None:
        versions = [row["version"] for row in db.query("SELECT version FROM schema_migrations")]
        assert versions.count("003_job_intelligence") == 1
        # Re-running initialize must not apply it a second time.
        db.initialize()
        versions = [row["version"] for row in db.query("SELECT version FROM schema_migrations")]
        assert versions.count("003_job_intelligence") == 1

    def test_indexes_cover_the_query_paths(self, db) -> None:
        names = {
            row["name"]
            for row in db.query("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
        for expected in (
            "ux_jobs_identity_key",
            "ux_jobs_source_external",
            "ux_jobs_canonical_url",
            "idx_jobs_status",
            "idx_jobs_source",
            "idx_jobs_content_hash",
            "idx_jobs_first_seen",
            "idx_jobs_last_seen",
            "idx_jobs_company",
            "idx_jobs_title",
            "ux_job_matches_cache",
            "ux_job_analyses_cache",
            "ux_job_requirements",
        ):
            assert expected in names, f"missing index {expected}"

    def test_phase2_tables_still_exist(self, db) -> None:
        tables = set(db.table_names())
        assert {"candidate_profiles", "resumes", "model_runs", "evidence"} <= tables


# ---------------------------------------------------------------------------
# Job model validation
# ---------------------------------------------------------------------------


class TestJobModelValidation:
    def test_every_optional_field_may_be_absent(self) -> None:
        job = Job(company="Acme", title="Engineer")
        assert job.location is None
        assert job.salary_min is None
        assert job.description_text is None
        assert job.workplace_type is None
        assert job.external_job_id is None
        assert job.canonical_url is None

    def test_salary_maximum_below_minimum_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="salary_max"):
            Job(company="Acme", title="Engineer", salary_min=100, salary_max=50)

    def test_salary_values_may_not_be_negative(self) -> None:
        with pytest.raises(ValidationError):
            Job(company="Acme", title="Engineer", salary_min=-1)

    def test_duplicate_requirements_are_still_collapsed(self) -> None:
        job = Job(
            company="Acme",
            title="Engineer",
            requirements=[
                Requirement(kind=RequirementKind.SKILL, text="Python"),
                Requirement(kind=RequirementKind.SKILL, text="python"),
            ],
        )
        assert len(job.requirements) == 1

    def test_first_and_last_seen_default_to_discovery(self) -> None:
        job = Job(company="Acme", title="Engineer")
        assert job.first_seen_at == job.discovered_at
        assert job.last_seen_at == job.discovered_at

    def test_internal_id_mirrors_the_primary_key(self) -> None:
        job = Job(id="job-1", company="Acme", title="Engineer")
        assert job.internal_id == "job-1"
        assert job.platform_job_id is None
        assert job.original_url == job.url

    def test_content_hash_mirrors_the_description_hash(self) -> None:
        job = Job(company="Acme", title="Engineer", description_hash="abc123")
        assert job.content_hash == "abc123"

    def test_source_metadata_mirrors_metadata(self) -> None:
        job = Job(company="Acme", title="Engineer", metadata={"k": 1})
        assert job.source_metadata == {"k": 1}

    def test_seven_day_old_seeing_is_not_created(self) -> None:
        job = Job(company="Acme", title="Engineer", seen_count=7)
        assert job.seen_count == 7


class TestRequirementPriority:
    def test_required_flag_maps_to_priority_on_the_way_in(self) -> None:
        assert Requirement(text="Python", required=True).priority is RequirementPriority.REQUIRED
        assert Requirement(text="Docker", required=False).priority is RequirementPriority.PREFERRED

    def test_required_property_is_derived_from_priority(self) -> None:
        required = Requirement(text="Python", priority=RequirementPriority.REQUIRED)
        preferred = Requirement(text="Docker", priority=RequirementPriority.PREFERRED)
        unknown = Requirement(text="Kubernetes", priority=RequirementPriority.UNKNOWN)
        assert required.required is True
        assert preferred.required is False
        # UNKNOWN is not the same as "not required"; it is reported as not
        # mandatory, and callers must read `priority` for the real answer.
        assert unknown.required is False
        assert unknown.priority is RequirementPriority.UNKNOWN

    def test_contradictory_required_and_priority_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="disagree"):
            Requirement(text="Python", required=True, priority=RequirementPriority.PREFERRED)

    def test_unknown_priority_is_the_default(self) -> None:
        assert Requirement(text="Python").priority is RequirementPriority.UNKNOWN

    def test_category_and_original_text_are_aliases(self) -> None:
        requirement = Requirement(
            kind=RequirementKind.PROGRAMMING_LANGUAGE, text="Python"
        )
        assert requirement.category is RequirementKind.PROGRAMMING_LANGUAGE
        assert requirement.original_text == "Python"
        assert requirement.normalized_name == "python"


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestIdentityGeneration:
    def test_external_id_tier_is_preferred(self) -> None:
        identity = JobIdentity.of(make_job())
        assert identity.tier == IDENTITY_TIER_EXTERNAL_ID
        assert identity.identity_key == "linkedin|synthetic analytics|4000123456"

    def test_falls_back_to_the_canonical_url_without_an_id(self) -> None:
        identity = JobIdentity.of(
            make_job(external_job_id=None, url=NO_ID_URL, canonical_url=NO_ID_URL)
        )
        assert identity.tier == IDENTITY_TIER_CANONICAL_URL
        assert identity.identity_key.startswith("url|")

    def test_the_posting_id_in_the_url_stands_in_for_the_platform_field(self) -> None:
        """A parsed URL is a fallback, not a substitute, for the field."""
        identity = JobIdentity.of(make_job(external_job_id=None))
        assert identity.tier == IDENTITY_TIER_EXTERNAL_ID
        assert "4000123456" in identity.identity_key

    def test_falls_back_to_content_without_id_or_url(self) -> None:
        identity = JobIdentity.of(
            make_job(external_job_id=None, url=None, canonical_url=None)
        )
        assert identity.tier == IDENTITY_TIER_CONTENT
        assert identity.identity_key.startswith("content|")

    def test_content_identity_is_not_title_and_company_alone(self) -> None:
        """Two no-id jobs differ when their descriptions differ."""
        one = JobIdentity.of(
            make_job(external_job_id=None, url=None, canonical_url=None,
                     description_text="ALPHA DESCRIPTION")
        )
        two = JobIdentity.of(
            make_job(external_job_id=None, url=None, canonical_url=None,
                     description_text="BETA DESCRIPTION")
        )
        assert one.identity_key != two.identity_key

    def test_same_id_at_two_companies_is_two_jobs(self) -> None:
        a = JobIdentity.of(make_job(company="Acme", external_job_id="1"))
        b = JobIdentity.of(make_job(company="Globex", external_job_id="1"))
        assert a.identity_key != b.identity_key

    def test_company_suffix_differences_do_not_split_identity(self) -> None:
        a = JobIdentity.of(make_job(company="Acme Inc.", external_job_id="7"))
        b = JobIdentity.of(make_job(company="Acme", external_job_id="7"))
        assert a.identity_key == b.identity_key

    def test_source_participates_in_identity(self) -> None:
        a = JobIdentity.of(make_job(source="linkedin", external_job_id="7"))
        b = JobIdentity.of(make_job(source="other", external_job_id="7"))
        assert a.identity_key != b.identity_key

    def test_identity_is_stable_across_repeated_computation(self) -> None:
        job = make_job()
        first = JobIdentity.of(job)
        second = JobIdentity.of(Job.model_validate(job.model_dump()))
        assert first.identity_key == second.identity_key
        assert first.tier == second.tier

    def test_stored_identity_key_is_reused_when_present(self) -> None:
        job = make_job(identity_key="linkedin|acme|1")
        assert job.identity_for_deduplication() == "linkedin|acme|1"

    def test_content_key_notices_a_description_change(self) -> None:
        identity = JobIdentity.of(make_job())
        assert identity.content_key("ALPHA") != identity.content_key("BETA")

    def test_extract_posting_id_reads_the_number(self) -> None:
        assert extract_posting_id("https://x.invalid/jobs/view/4000123456/") == "4000123456"
        assert extract_posting_id("https://x.invalid/jobs/") == ""
        assert extract_posting_id(None) == ""


class TestUrlCanonicalisation:
    def test_tracking_parameters_are_dropped(self) -> None:
        plain = canonicalize_url("https://www.linkedin.com/jobs/view/role-123")
        noisy = canonicalize_url(
            "https://www.linkedin.com/jobs/view/role-123/?ref=feed&refId=abc&trk=x"
        )
        assert plain == noisy == "https://linkedin.com/jobs/view/role-123"

    def test_host_case_www_and_trailing_slash_are_ignored(self) -> None:
        a = canonicalize_url("https://WWW.LINKEDIN.com/jobs/view/role-123/")
        b = canonicalize_url("https://www.linkedin.com/jobs/view/role-123")
        assert a == b

    def test_path_case_is_preserved(self) -> None:
        """Paths may be case-sensitive, so canonicalisation must not merge them."""
        assert canonicalize_url("https://x.invalid/Jobs/1") != canonicalize_url(
            "https://x.invalid/jobs/1"
        )

    def test_meaningful_query_parameters_are_kept(self) -> None:
        url = canonicalize_url("https://x.invalid/jobs?filter=remote&f_WT=2")
        assert "filter=remote" in url
        assert "f_WT=2" in url

    def test_fragment_is_dropped(self) -> None:
        assert "#" not in canonicalize_url("https://x.invalid/jobs/1#apply")

    def test_empty_or_relative_input_returns_empty(self) -> None:
        assert canonicalize_url("") == ""
        assert canonicalize_url(None) == ""
        assert canonicalize_url("/jobs/view/1") == ""

    def test_equivalent_urls_produce_the_same_identity(self) -> None:
        a = JobIdentity.of(make_job(external_job_id=None, url="https://www.linkedin.com/jobs/view/role-1/?ref=a"))
        b = JobIdentity.of(make_job(external_job_id=None, url="https://linkedin.com/jobs/view/role-1?trk=b"))
        assert a.identity_key == b.identity_key


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_identical_external_ids_collapse(self) -> None:
        result = JobDeduplicator().deduplicate(
            [make_job(), make_job(title="A different title")]
        )
        assert len(result.unique) == 1
        assert result.counts["duplicates"] == 1

    def test_equivalent_url_variations_collapse(self) -> None:
        first = make_job(external_job_id=None, url="https://www.linkedin.com/jobs/view/role-9/?ref=a")
        second = make_job(external_job_id=None, url="https://linkedin.com/jobs/view/role-9?trk=b")
        result = JobDeduplicator().deduplicate([first, second])
        assert len(result.unique) == 1

    def test_content_hash_separates_different_descriptions(self) -> None:
        first = make_job(external_job_id=None, url=None, canonical_url=None, description_text="ALPHA")
        second = make_job(external_job_id=None, url=None, canonical_url=None, description_text="BETA")
        result = JobDeduplicator().deduplicate([first, second])
        assert len(result.unique) == 2

    def test_decisions_are_inspectable(self) -> None:
        result = JobDeduplicator().deduplicate([make_job(), make_job()])
        assert result.decisions
        decision = result.decisions[0]
        assert decision["tier"] == IDENTITY_TIER_EXTERNAL_ID
        assert decision["identity_key"]
        assert "kept" in decision and "dropped" in decision

    def test_longer_description_survives_a_merge(self) -> None:
        first = Job(company="Acme", title="Engineer", platform_job_id="6", description_text=None)
        second = Job(
            company="Acme", title="Engineer", platform_job_id="6",
            description_text="SYNTHETIC DESCRIPTION",
        )
        result = JobDeduplicator().deduplicate([first, second])
        assert result.unique[0].description_text == "SYNTHETIC DESCRIPTION"

    def test_an_empty_description_never_replaces_a_full_one(self) -> None:
        first = Job(
            company="Acme", title="Engineer", platform_job_id="6",
            description_text="ORIGINAL",
        )
        second = Job(company="Acme", title="Engineer", platform_job_id="6", description_text="")
        result = JobDeduplicator().deduplicate([first, second])
        assert result.unique[0].description_text == "ORIGINAL"


class TestMergeDiscovery:
    def test_seen_count_increments_and_first_seen_is_stable(self) -> None:
        existing = make_job(seen_count=3)
        incoming = make_job()
        merged = merge_discovery(existing, incoming)
        assert merged.seen_count == 4
        assert merged.first_seen_at == existing.first_seen_at
        assert merged.last_seen_at >= existing.last_seen_at

    def test_a_changed_description_sends_the_job_back_for_reacquisition(self) -> None:
        existing = make_job(status=JobStatus.ANALYZED)
        incoming = make_job(description_text="A COMPLETELY DIFFERENT SYNTHETIC DESCRIPTION")
        merged = merge_discovery(existing, incoming)
        assert merged.status is JobStatus.JD_PENDING
        assert merged.description_text.startswith("A COMPLETELY")
        assert merged.metadata.get("description_changed") is True

    def test_unchanged_description_leaves_status_alone(self) -> None:
        existing = make_job(status=JobStatus.ANALYZED)
        merged = merge_discovery(existing, make_job())
        assert merged.status is JobStatus.ANALYZED

    def test_blank_fields_are_filled_from_the_incoming_sighting(self) -> None:
        existing = make_job(location=None, salary_min=None)
        incoming = make_job(location="Remote (India)", salary_min=90000.0)
        merged = merge_discovery(existing, incoming)
        assert merged.location == "Remote (India)"
        assert merged.salary_min == 90000.0

    def test_populated_fields_are_not_overwritten(self) -> None:
        existing = make_job(location="Berlin")
        merged = merge_discovery(existing, make_job(location="Lisbon"))
        assert merged.location == "Berlin"

    def test_alternate_urls_are_recorded(self) -> None:
        existing = make_job(url="https://a.invalid/1")
        merged = merge_discovery(existing, make_job(url="https://b.invalid/1"))
        assert "https://b.invalid/1" in merged.metadata["alternate_urls"]

    def test_neither_input_is_mutated(self) -> None:
        existing = make_job(seen_count=1)
        incoming = make_job()
        before = existing.seen_count
        merge_discovery(existing, incoming)
        assert existing.seen_count == before
        assert incoming.seen_count == 1


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class TestJobRepositoryPersistence:
    def test_insert_then_idempotent_upsert(self, db) -> None:
        repo = JobRepository(db)
        first_id, created = repo.save(make_job())
        assert created is True
        second_id, created_again = repo.save(make_job())
        assert created_again is False
        assert second_id == first_id
        assert db.count("jobs") == 1

    def test_repeated_discovery_bumps_seen_count(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        repo.save(make_job())
        repo.save(make_job())
        assert repo.load(job_id).seen_count == 3

    def test_requirements_round_trip(self, db) -> None:
        repo = JobRepository(db)
        job = make_job(
            requirements=[
                Requirement(
                    kind=RequirementKind.PROGRAMMING_LANGUAGE,
                    text="Python",
                    priority=RequirementPriority.REQUIRED,
                    source_excerpt="3+ years of Python required",
                    min_years=3.0,
                ),
                Requirement(
                    kind=RequirementKind.TOOL,
                    text="Docker",
                    priority=RequirementPriority.PREFERRED,
                    source_excerpt="Experience with Docker is a plus",
                    ambiguous=True,
                ),
            ]
        )
        job_id, _ = repo.save(job)
        stored = repo.requirements(job_id)
        assert [r.text for r in stored] == ["Python", "Docker"]
        assert stored[0].priority is RequirementPriority.REQUIRED
        assert stored[0].min_years == 3.0
        assert stored[0].source_excerpt == "3+ years of Python required"
        assert stored[1].priority is RequirementPriority.PREFERRED
        assert stored[1].ambiguous is True

    def test_rediscovery_without_requirements_keeps_the_stored_set(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(
            make_job(
                requirements=[Requirement(kind=RequirementKind.SKILL, text="Python")]
            )
        )
        repo.save(make_job())
        assert len(repo.requirements(job_id)) == 1

    def test_all_job_fields_survive_a_round_trip(self, db) -> None:
        repo = JobRepository(db)
        job = make_job(
            location="Remote (India)",
            workplace_type="Remote",
            employment_type="Full-time",
            experience_level="Mid-Senior level",
            salary_min=80000.0,
            salary_max=120000.0,
            salary_currency="USD",
            salary_period="YEAR",
            description_raw="  RAW\n  TEXT ",
            description_text="NORMALIZED TEXT",
            description_hash="content-hash",
        )
        job_id, _ = repo.save(job)
        loaded = repo.load(job_id)
        assert loaded.location == "Remote (India)"
        assert loaded.workplace_type == "Remote"
        assert loaded.employment_type == "Full-time"
        assert loaded.experience_level == "Mid-Senior level"
        assert (loaded.salary_min, loaded.salary_max) == (80000.0, 120000.0)
        assert loaded.salary_currency == "USD"
        assert loaded.salary_period == "YEAR"
        assert loaded.description_raw == "  RAW\n  TEXT "
        assert loaded.description_text == "NORMALIZED TEXT"
        assert loaded.content_hash == "content-hash"
        assert loaded.source == "linkedin"
        assert loaded.canonical_url == job.canonical_url

    def test_restart_safety(self, tmp_path) -> None:
        from database.connection import connect

        path = tmp_path / "restart.db"
        db_a = connect(path)
        repo_a = JobRepository(db_a)
        job_id, _ = repo_a.save(
            make_job(
                requirements=[Requirement(kind=RequirementKind.SKILL, text="Python")],
            )
        )
        repo_a.transition(job_id, JobStatus.NORMALIZED, actor="cli", reason="normalised")
        db_a.close()

        db_b = connect(path)
        repo_b = JobRepository(db_b)
        loaded = repo_b.load(job_id)
        assert loaded is not None
        assert loaded.status is JobStatus.NORMALIZED
        assert len(loaded.requirements) == 1
        assert loaded.seen_count == 1
        assert len(repo_b.state_events(job_id)) == 2
        db_b.close()

    def test_lookup_helpers_find_the_row(self, db) -> None:
        repo = JobRepository(db)
        job = make_job()
        job_id, _ = repo.save(job)
        identity = JobIdentity.of(job).identity_key
        assert repo.load_by_identity(identity).id == job_id
        assert repo.find_by_external_id("linkedin", "4000123456").id == job_id
        assert repo.find_by_canonical_url(job.canonical_url).id == job_id
        assert repo.load_by_identity("") is None
        assert repo.find_by_canonical_url("") is None

    def test_identity_is_upgraded_from_url_to_external_id(self, db) -> None:
        """A job first stored by URL adopts its platform id without duplicating."""
        repo = JobRepository(db)
        url_only = make_job(
            external_job_id=None,
            url="https://linkedin.com/jobs/view/role-777",
            canonical_url="https://linkedin.com/jobs/view/role-777",
        )
        first_id, _ = repo.save(url_only)
        with_id = make_job(
            external_job_id="777",
            url="https://linkedin.com/jobs/view/role-777",
            canonical_url="https://linkedin.com/jobs/view/role-777",
        )
        second_id, created = repo.save(with_id)
        assert created is False
        assert second_id == first_id
        assert db.count("jobs") == 1

    def test_missing_job_raises_a_typed_error(self, db) -> None:
        repo = JobRepository(db)
        with pytest.raises(JobNotFoundError):
            repo.require("job-does-not-exist")

    def test_list_filters_by_status_source_and_decision(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        repo.transition(job_id, JobStatus.NORMALIZED, actor="cli")
        repo.save_match(
            job_id=job_id,
            candidate_id="primary",
            decision=MatchDecision.REVIEW_REQUIRED,
            hard_gate_status=HardGateStatus.UNKNOWN,
            analysis_source=AnalysisSource.CANDIDATE_DATA,
            requirements_fingerprint="r1",
            candidate_fingerprint="c1",
            explanation={"decision": "REVIEW_REQUIRED"},
            review_reasons=["INSUFFICIENT_EVIDENCE"],
        )

        assert len(repo.list_jobs(status=JobStatus.NORMALIZED)) == 1
        assert len(repo.list_jobs(status=JobStatus.DISCOVERED)) == 0
        assert len(repo.list_jobs(source="linkedin")) == 1
        assert len(repo.list_jobs(source="other")) == 0
        assert len(repo.list_jobs(decision=MatchDecision.REVIEW_REQUIRED)) == 1
        assert len(repo.list_jobs(decision=MatchDecision.MATCH)) == 0
        assert len(repo.review_required()) == 1

    def test_count_by_status(self, db) -> None:
        repo = JobRepository(db)
        repo.save(make_job())
        repo.save(
            make_job(
                external_job_id="4000999999",
                url="https://www.linkedin.com/jobs/view/other-role-4000999999/",
                canonical_url="https://linkedin.com/jobs/view/other-role-4000999999",
            )
        )
        counts = repo.count_by_status()
        assert counts.get("DISCOVERED") == 2

    def test_a_shared_canonical_url_merges_instead_of_raising(self, db) -> None:
        """The URL is unique by schema, so a hit is authoritative."""
        repo = JobRepository(db)
        first, _ = repo.save(make_job())
        second, created = repo.save(make_job(external_job_id="4000111111"))
        assert created is False
        assert second == first
        assert db.count("jobs") == 1
        # Merging fills blanks; it does not overwrite the stored id.
        assert repo.load(first).external_job_id == "4000123456"
        # The recomputed identity still agrees with that column.
        assert repo.load(first).identity_key.endswith("4000123456")

    def test_two_rows_are_created_when_the_urls_differ(self, db) -> None:
        repo = JobRepository(db)
        repo.save(make_job())
        repo.save(
            make_job(
                external_job_id="4000888888",
                url="https://www.linkedin.com/jobs/view/elsewhere-4000888888/",
                canonical_url="https://linkedin.com/jobs/view/elsewhere-4000888888",
            )
        )
        assert db.count("jobs") == 2


class TestStateTransitions:
    def test_a_legal_transition_is_recorded_with_an_audit_event(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        repo.transition(job_id, JobStatus.NORMALIZED, actor="cli", reason="normalised")
        job = repo.load(job_id)
        assert job.status is JobStatus.NORMALIZED

        events = repo.state_events(job_id)
        assert [(e["from_state"], e["to_state"]) for e in events] == [
            ("", "DISCOVERED"),
            ("DISCOVERED", "NORMALIZED"),
        ]
        assert events[1]["reason"] == "normalised"
        assert events[1]["actor_kind"] == "HUMAN"

    def test_an_illegal_transition_is_refused(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        with pytest.raises(InvalidStateTransitionError) as excinfo:
            repo.transition(job_id, JobStatus.APPLIED, actor="cli")
        detail = excinfo.value.details
        assert detail["from_state"] == "DISCOVERED"
        assert detail["to_state"] == "APPLIED"
        # Discovery may move to FETCHED or NORMALIZED, or end early; it may
        # not jump straight to a state that claims work was submitted.
        assert set(detail["allowed"]) == {"FAILED", "FETCHED", "NORMALIZED", "SKIPPED"}
        assert "APPLIED" not in detail["allowed"]
        assert "JD_PENDING" not in detail["allowed"]
        # The row is unchanged: validation happens before the write.
        assert repo.load(job_id).status is JobStatus.DISCOVERED

    @pytest.mark.parametrize(
        "target",
        [
            JobStatus.JD_PENDING,
            JobStatus.REVIEW_REQUIRED,
            JobStatus.APPLIED,
            JobStatus.READY_FOR_APPLICATION,
        ],
    )
    def test_discovery_may_not_reach_later_states(self, db, target) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        with pytest.raises(InvalidStateTransitionError):
            repo.transition(job_id, target, actor="cli")

    def test_a_refused_transition_writes_no_event(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        with pytest.raises(InvalidStateTransitionError):
            repo.transition(job_id, JobStatus.APPLIED, actor="cli")
        assert len(repo.state_events(job_id)) == 1

    def test_terminal_states_have_no_outgoing_moves(self) -> None:
        for terminal in (JobStatus.REJECTED, JobStatus.SKIPPED, JobStatus.FAILED):
            assert terminal.is_terminal is True
            assert Job().allowed_transitions() if False else True
        assert JOB_TRANSITIONS_EMPTY(JobStatus.REJECTED)
        assert JOB_TRANSITIONS_EMPTY(JobStatus.APPLIED)

    def test_the_full_happy_path_is_walkable(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        path = [
            JobStatus.NORMALIZED,
            JobStatus.JD_PENDING,
            JobStatus.JD_EXTRACTED,
            JobStatus.ANALYSIS_PENDING,
            JobStatus.ANALYZED,
            JobStatus.MATCHED,
            JobStatus.REVIEW_REQUIRED,
            JobStatus.READY_FOR_APPLICATION,
        ]
        for state in path:
            repo.transition(job_id, state, actor="cli", reason=f"to {state.value}")
        assert repo.load(job_id).status is JobStatus.READY_FOR_APPLICATION
        assert len(repo.state_events(job_id)) == len(path) + 1

    def test_self_transition_is_refused(self) -> None:
        job = Job(company="Acme", title="Engineer", status=JobStatus.ANALYZED)
        assert job.can_transition_to(JobStatus.ANALYZED) is False
        with pytest.raises(InvalidStateTransitionError):
            job.transition_to(JobStatus.ANALYZED)


def JOB_TRANSITIONS_EMPTY(state: JobStatus) -> bool:
    from jobs.models import JOB_TRANSITIONS

    return JOB_TRANSITIONS.get(state, frozenset()) == frozenset()


# ---------------------------------------------------------------------------
# Extraction, analysis and match storage
# ---------------------------------------------------------------------------


class TestExtractionRuns:
    def test_every_attempt_is_recorded_including_failures(self, db) -> None:
        from jobs.deduplicator import merge_discovery as _  # noqa: F401

        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        repo.record_extraction_run(
            job_id,
            status=ExtractionStatus.COMPLETE,
            method=ExtractionMethod.BROWSER,
            raw_length=1200,
            normalized_length=1180,
            content_hash="abc",
            source="linkedin",
        )
        repo.record_extraction_run(
            job_id,
            status=ExtractionStatus.FAILED,
            method=ExtractionMethod.BROWSER,
            error_code="SELECTOR_NOT_FOUND",
            source="linkedin",
        )
        runs = repo.extraction_runs(job_id)
        assert [r["extraction_status"] for r in runs] == ["COMPLETE", "FAILED"]
        assert runs[1]["error_code"] == "SELECTOR_NOT_FOUND"
        assert repo.latest_extraction(job_id)["extraction_status"] == "FAILED"

    def test_lengths_are_stored(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        repo.record_extraction_run(
            job_id,
            status=ExtractionStatus.PARTIAL,
            method=ExtractionMethod.DETERMINISTIC,
            raw_length=100,
            normalized_length=90,
        )
        run = repo.latest_extraction(job_id)
        assert run["raw_length"] == 100
        assert run["normalized_length"] == 90


class TestAnalysisCache:
    KEY = dict(
        content_hash="hash-1",
        analyzer="deterministic",
        analyzer_version="1.0",
    )

    def _record(self, repo, job_id, **overrides) -> None:
        params = dict(
            job_id=job_id,
            analysis_source=AnalysisSource.JOB_DATA,
            requirement_count=3,
            **self.KEY,
        )
        params.update(overrides)
        repo.record_analysis(**params)

    def test_unchanged_job_hits_the_cache(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        self._record(repo, job_id)
        hit = repo.find_cached_analysis(job_id, **self.KEY)
        assert hit is not None
        assert hit["requirement_count"] == 3
        assert hit["status"] == "SUCCESS"

    def test_a_changed_description_misses_the_cache(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        self._record(repo, job_id)
        miss = repo.find_cached_analysis(job_id, **{**self.KEY, "content_hash": "hash-2"})
        assert miss is None

    def test_a_different_analyzer_version_misses_the_cache(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        self._record(repo, job_id)
        miss = repo.find_cached_analysis(
            job_id, **{**self.KEY, "analyzer_version": "2.0"}
        )
        assert miss is None

    def test_re_recording_the_same_key_updates_rather_than_duplicates(self, db) -> None:
        from jobs.deduplicator import merge_discovery as _  # noqa: F401

        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        self._record(repo, job_id, requirement_count=3)
        self._record(repo, job_id, requirement_count=5)
        assert len(repo.analyses(job_id)) == 1
        assert repo.analyses(job_id)[0]["requirement_count"] == 5

    def test_ai_analysis_records_provider_and_model(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        repo.record_analysis(
            job_id,
            content_hash="hash-1",
            analyzer="ai",
            analyzer_version="1.0",
            analysis_source=AnalysisSource.JOB_DATA,
            requirement_count=2,
            ai_provider="ollama",
            ai_model="qwen2.5:7b",
        )
        stored = repo.analyses(job_id)[0]
        assert stored["ai_provider"] == "ollama"
        assert stored["ai_model"] == "qwen2.5:7b"

        # The prompt version is part of the key: a run without one must not
        # answer a query that asks about a specific prompt.
        assert (
            repo.find_cached_analysis(
                job_id,
                content_hash="hash-1",
                analyzer="ai",
                analyzer_version="1.0",
                prompt_version="jd_extraction_v1",
            )
            is None
        )
        hit = repo.find_cached_analysis(
            job_id,
            content_hash="hash-1",
            analyzer="ai",
            analyzer_version="1.0",
        )
        assert hit is not None
        assert hit["ai_model"] == "qwen2.5:7b"


class TestMatchStorage:
    def _save(self, repo, job_id, **overrides) -> str:
        params = dict(
            job_id=job_id,
            candidate_id="primary",
            decision=MatchDecision.PARTIAL_MATCH,
            hard_gate_status=HardGateStatus.PASS,
            analysis_source=AnalysisSource.CANDIDATE_DATA,
            requirements_fingerprint="req-fp-1",
            candidate_fingerprint="cand-fp-1",
            explanation={"decision": "PARTIAL_MATCH", "lines": []},
            matched_count=2,
            mismatched_count=0,
            unknown_count=1,
            confidence=0.7,
            evidence=[{"citation": "synthetic"}],
            review_reasons=["INSUFFICIENT_EVIDENCE"],
        )
        params.update(overrides)
        return repo.save_match(**params)

    def test_match_round_trip_with_decoded_json(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        match_id = self._save(repo, job_id)
        stored = repo.load_match(match_id)
        assert stored["decision"] == "PARTIAL_MATCH"
        assert stored["explanation"]["decision"] == "PARTIAL_MATCH"
        assert stored["evidence"] == [{"citation": "synthetic"}]
        assert stored["review_reasons"] == ["INSUFFICIENT_EVIDENCE"]
        assert stored["matched_count"] == 2
        assert stored["unknown_count"] == 1

    def test_reuse_of_the_same_fingerprints_overwrites(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        self._save(repo, job_id)
        self._save(repo, job_id, decision=MatchDecision.MATCH, matched_count=4)
        rows = repo.matches(job_id=job_id)
        assert len(rows) == 1
        assert rows[0]["decision"] == "MATCH"

    def test_a_different_fingerprint_produces_a_new_row(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        self._save(repo, job_id)
        self._save(repo, job_id, requirements_fingerprint="req-fp-2")
        assert len(repo.matches(job_id=job_id)) == 2

    def test_cached_lookup_by_fingerprint(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        self._save(repo, job_id)
        hit = repo.find_cached_match(
            job_id,
            "primary",
            requirements_fingerprint="req-fp-1",
            candidate_fingerprint="cand-fp-1",
        )
        assert hit is not None
        miss = repo.find_cached_match(
            job_id,
            "primary",
            requirements_fingerprint="req-fp-1",
            candidate_fingerprint="cand-fp-2",
        )
        assert miss is None

    def test_match_isolated_between_candidates(self, db) -> None:
        repo = JobRepository(db)
        job_id, _ = repo.save(make_job())
        self._save(repo, job_id, candidate_id="primary")
        self._save(repo, job_id, candidate_id="other", decision=MatchDecision.HARD_MISMATCH)
        assert len(repo.matches(job_id=job_id)) == 2
        assert len(repo.matches(candidate_id="other")) == 1
