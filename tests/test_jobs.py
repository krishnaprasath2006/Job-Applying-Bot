"""Job vocabulary, normalisation, and deduplication.

Phase 2 fetches no jobs. What matters here is that the identity rules and the
grounding rules are settled and tested before any browser work exists, because
both are expensive to get wrong later: a bad identity rule silently drops
postings, and an ungrounded requirement quietly becomes a fabricated fact about
the candidate.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.enums import AnalysisSource
from jobs.deduplicator import (
    DeduplicationResult,
    JobDeduplicator,
    JobIdentity,
    extract_posting_id,
)
from jobs.models import Job, JobStatus, Requirement, RequirementKind
from jobs.normalizer import (
    normalize_company,
    normalize_skill,
    normalize_text,
    normalize_title,
    slugify,
)


def make_job(**overrides) -> Job:
    base = {
        "company": "Synthetic Analytics Pvt",
        "title": "Senior Machine Learning Engineer (Remote)",
        "platform_job_id": "4000123456",
        "url": "https://example.invalid/jobs/view/4000123456/",
        "description_text": "SYNTHETIC JOB DESCRIPTION. Not a real posting.",
    }
    base.update(overrides)
    return Job(**base)


class TestNormalizeText:
    def test_whitespace_is_collapsed(self) -> None:
        assert normalize_text("  a \n\t b  ") == "a b"

    def test_none_becomes_empty(self) -> None:
        assert normalize_text(None) == ""

    def test_smart_quotes_and_dashes_are_folded(self) -> None:
        assert normalize_text("it\u2019s a \u2013 test") == "it's a - test"

    def test_unicode_compatibility_forms_compare_equal(self) -> None:
        assert normalize_text("ﬁle") == normalize_text("file")


class TestNormalizeTitle:
    def test_seniority_and_remote_are_stripped(self) -> None:
        assert normalize_title("Senior Machine Learning Engineer (Remote)") == "machine learning engineer"

    def test_a_plain_title_is_unchanged_apart_from_case(self) -> None:
        assert normalize_title("Data Analyst") == "data analyst"

    def test_level_range_noise_is_stripped(self) -> None:
        assert normalize_title("Engineer (L4-L5)") == "engineer"

    def test_a_title_that_is_only_noise_is_refused(self) -> None:
        # Better a loud failure than an empty key that merges every posting.
        with pytest.raises(ValueError):
            normalize_title("Remote")
        with pytest.raises(ValueError):
            normalize_title("   ")


class TestNormalizeCompany:
    def test_legal_suffixes_are_dropped(self) -> None:
        assert normalize_company("Acme Inc.") == normalize_company("Acme")

    def test_case_and_spacing_do_not_matter(self) -> None:
        assert normalize_company("  SYNTHETIC  Analytics  ") == "synthetic analytics"


class TestNormalizeSkill:
    def test_aliases_map_to_canonical_forms(self) -> None:
        assert normalize_skill("Postgres") == "postgresql"
        assert normalize_skill("k8s") == "kubernetes"
        assert normalize_skill("CI/CD") == "ci/cd"

    def test_an_unknown_skill_is_left_alone_rather_than_guessed(self) -> None:
        # Forcing an unmapped name onto the nearest known skill would invent a
        # match the employer never asked for.
        assert normalize_skill("Some Framework Nobody Mapped") == "some framework nobody mapped"

    def test_blank_input_is_empty(self) -> None:
        assert normalize_skill("   ") == ""


class TestSlugify:
    def test_spaces_and_punctuation_collapse_to_dashes(self) -> None:
        assert slugify("Machine Learning / AI!") == "machine-learning-ai"

    def test_edge_dashes_are_trimmed(self) -> None:
        assert slugify("  --hello world--  ") == "hello-world"


class TestRequirement:
    def test_text_is_required(self) -> None:
        with pytest.raises(ValidationError):
            Requirement(text="   ")

    def test_normalization_defaults_to_lower_case_text(self) -> None:
        assert Requirement(text="  Python  ").normalized == "python"

    def test_explicit_normalization_is_kept(self) -> None:
        assert Requirement(text="Python", normalized="python3").normalized == "python3"

    def test_an_ungrounded_requirement_cannot_be_scored(self) -> None:
        requirement = Requirement(
            text="Expert in Rust", analysis_source=AnalysisSource.AI_GENERAL, confidence=0.9
        )
        assert requirement.is_grounded is False
        with pytest.raises(ValueError):
            requirement.assert_grounded()

    def test_a_description_requirement_is_grounded(self) -> None:
        requirement = Requirement(text="3+ years of Python", kind=RequirementKind.EXPERIENCE)
        assert requirement.is_grounded is True
        requirement.assert_grounded()

    def test_years_outside_the_plausible_range_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            Requirement(text="Experience", min_years=61)
        with pytest.raises(ValidationError):
            Requirement(text="Experience", min_years=-1)

    def test_unknown_fields_are_refused(self) -> None:
        with pytest.raises(ValidationError):
            Requirement(text="Python", invented_field="anything")


class TestJob:
    def test_duplicate_requirements_are_collapsed(self) -> None:
        job = Job(
            company="Acme",
            title="Engineer",
            requirements=[
                Requirement(text="Python", kind=RequirementKind.SKILL),
                Requirement(text="python ", kind=RequirementKind.SKILL),
                Requirement(text="Python", kind=RequirementKind.TOOL),
            ],
        )
        # Same kind plus same text is the same requirement; a different kind is
        # a different statement and stays.
        assert len(job.requirements) == 2

    def test_grounded_and_ungrounded_requirements_are_separable(self) -> None:
        job = Job(
            company="Acme",
            title="Engineer",
            requirements=[
                Requirement(text="Python"),
                Requirement(text="Rust", analysis_source=AnalysisSource.AI_GENERAL),
            ],
        )
        assert [r.text for r in job.grounded_requirements()] == ["Python"]
        assert [r.text for r in job.ungrounded_requirements()] == ["Rust"]

    def test_terminal_statuses_are_terminal(self) -> None:
        assert JobStatus.APPLIED.is_terminal is True
        assert JobStatus.SKIPPED.is_terminal is True
        assert JobStatus.FAILED.is_terminal is True
        assert JobStatus.DISCOVERED.is_terminal is False

    def test_a_job_starts_as_discovered(self) -> None:
        assert Job(company="Acme", title="Engineer").status is JobStatus.DISCOVERED


class TestPostingIdExtraction:
    def test_the_numeric_id_is_extracted_from_a_url(self) -> None:
        assert extract_posting_id("https://example.invalid/jobs/view/4000123456/") == "4000123456"

    def test_a_company_prefixed_url_is_handled(self) -> None:
        url = "https://example.invalid/jobs/view/synthetic-analytics-4000123456"
        assert extract_posting_id(url) == "4000123456"

    def test_a_url_without_an_id_yields_nothing_rather_than_a_guess(self) -> None:
        assert extract_posting_id("https://example.invalid/jobs/view/engineering") == ""
        assert extract_posting_id(None) == ""

    def test_an_explicit_platform_id_wins_over_the_url(self) -> None:
        job = make_job(platform_job_id="999", url="https://example.invalid/jobs/view/4000123456/")
        assert JobIdentity.of(job).posting_id == "999"


class TestJobIdentity:
    def test_identity_is_company_plus_posting_id(self) -> None:
        identity = JobIdentity.of(make_job())
        assert identity.identity_key.startswith("synthetic analytics|4000123456")

    def test_title_is_informational_and_not_part_of_identity(self) -> None:
        a = JobIdentity.of(make_job(title="Senior ML Engineer"))
        b = JobIdentity.of(make_job(title="ML Engineer"))
        assert a.identity_key == b.identity_key
        assert a.title == b.title

    def test_the_same_title_at_two_companies_is_two_jobs(self) -> None:
        a = JobIdentity.of(make_job(company="Acme", platform_job_id="1"))
        b = JobIdentity.of(make_job(company="Globex", platform_job_id="1"))
        assert a.identity_key != b.identity_key

    def test_company_suffix_differences_do_not_split_identity(self) -> None:
        a = JobIdentity.of(make_job(company="Acme Inc.", platform_job_id="7"))
        b = JobIdentity.of(make_job(company="Acme", platform_job_id="7"))
        assert a.identity_key == b.identity_key

    def test_an_unnormalizable_title_does_not_break_identity(self) -> None:
        identity = JobIdentity.of(make_job(title="Remote", platform_job_id=""))
        assert identity.identity_key

    def test_content_key_notices_a_description_change(self) -> None:
        identity = JobIdentity.of(make_job())
        before = identity.content_key("SYNTHETIC ORIGINAL DESCRIPTION")
        after = identity.content_key("SYNTHETIC REVISED DESCRIPTION")
        assert before != after

    def test_content_key_ignores_insignificant_whitespace_changes(self) -> None:
        identity = JobIdentity.of(make_job())
        assert identity.content_key("a  b") == identity.content_key("a\n b")


class TestDeduplicator:
    def test_reposted_jobs_collapse_into_one(self) -> None:
        jobs = [
            make_job(platform_job_id="4000123456", title="Senior ML Engineer"),
            make_job(platform_job_id="4000123456", title="ML Engineer"),
        ]
        result = JobDeduplicator().deduplicate(jobs)
        assert len(result.unique) == 1
        assert result.removed_count == 1

    def test_different_postings_are_all_kept(self) -> None:
        jobs = [
            make_job(platform_job_id="1"),
            make_job(platform_job_id="2"),
            make_job(company="Globex", platform_job_id="1"),
        ]
        result = JobDeduplicator().deduplicate(jobs)
        assert len(result.unique) == 3
        assert result.duplicates == {}

    def test_a_collapsed_posting_is_recorded_not_discarded_silently(self) -> None:
        jobs = [make_job(platform_job_id="5"), make_job(platform_job_id="5", url="https://example.invalid/jobs/view/5-repost")]
        result = JobDeduplicator().deduplicate(jobs)
        recorded = result.unique[0].metadata["duplicate_postings"]
        assert len(recorded) == 1

    def test_a_kept_posting_without_a_description_can_absorb_one(self) -> None:
        first = make_job(platform_job_id="6", description_text=None)
        second = make_job(platform_job_id="6", description_text="SYNTHETIC DESCRIPTION")
        result = JobDeduplicator().deduplicate([first, second])
        assert result.unique[0].description_text == "SYNTHETIC DESCRIPTION"

    def test_an_existing_description_is_not_overwritten(self) -> None:
        first = make_job(platform_job_id="8", description_text="ORIGINAL")
        second = make_job(platform_job_id="8", description_text="REPLACEMENT")
        result = JobDeduplicator().deduplicate([first, second])
        assert result.unique[0].description_text == "ORIGINAL"

    def test_metadata_merging_can_be_switched_off(self) -> None:
        jobs = [make_job(platform_job_id="9"), make_job(platform_job_id="9")]
        result = JobDeduplicator(merge_metadata=False).deduplicate(jobs)
        assert "duplicate_postings" not in result.unique[0].metadata
        assert len(result.unique) == 1

    def test_counts_describe_the_input(self) -> None:
        jobs = [make_job(platform_job_id="1"), make_job(platform_job_id="1"), make_job(platform_job_id="2")]
        result = JobDeduplicator().deduplicate(jobs)
        assert result.counts == {"input": 3, "unique": 2, "duplicates": 1}

    def test_an_empty_batch_is_handled(self) -> None:
        result = JobDeduplicator().deduplicate([])
        assert isinstance(result, DeduplicationResult)
        assert result.unique == [] and result.removed_count == 0

    def test_is_duplicate_compares_normalised_identity(self) -> None:
        existing = [make_job(company="Acme Inc.", platform_job_id="3")]
        assert JobDeduplicator().is_duplicate(make_job(company="Acme", platform_job_id="3"), existing)
        assert not JobDeduplicator().is_duplicate(make_job(company="Acme", platform_job_id="4"), existing)

    def test_grouping_by_company_uses_the_normalised_name(self) -> None:
        jobs = [make_job(company="Acme Inc."), make_job(company="Acme"), make_job(company="Globex LLC")]
        grouped = JobDeduplicator().group_by_company(jobs)
        assert set(grouped) == {"acme", "globex"}
        assert len(grouped["acme"]) == 2
