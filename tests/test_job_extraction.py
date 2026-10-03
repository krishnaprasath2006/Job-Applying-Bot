"""Acquisition: what a posting says, and how good a capture of it we got.

Every page read here is a saved fixture. Nothing in this file opens a browser,
reaches the network or touches a real posting — which is the point of the split
under test: :func:`jobs.acquisition.parse_job_page` takes a string, so ``src``
can reason about a job description without knowing how the HTML arrived, and
``automation`` only has to produce one.

Two rules are pinned down here because everything downstream depends on them:

* an unusable capture never becomes a job's description, and
* a capture never overwrites a field discovery already filled in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.enums import ExtractionMethod, ExtractionStatus
from core.hashing import sha256_text
from core.settings import ExtractionSettings
from jobs.acquisition import JobPage, classify_description, parse_job_page
from jobs.models import Job, JobStatus
from pydantic import ValidationError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "html"
PAGE_URL = "https://www.linkedin.com/jobs/view/senior-machine-learning-engineer-4000000001"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def parse(name: str, **overrides) -> JobPage:
    return parse_job_page(load(name), source="linkedin", page_url=PAGE_URL, **overrides)


def discovered_job(**overrides) -> Job:
    base = {
        "source": "linkedin",
        "company": "Northwind Analytics Pvt Ltd",
        "title": "Senior Machine Learning Engineer",
        "url": PAGE_URL,
    }
    base.update(overrides)
    return Job(**base)


# ---------------------------------------------------------------------------
# Judging a captured description
# ---------------------------------------------------------------------------
class TestClassifyDescription:
    def test_nothing_captured_is_unavailable(self) -> None:
        status, reason = classify_description("")
        assert status is ExtractionStatus.UNAVAILABLE
        assert reason == "no description text was captured"

    def test_whitespace_alone_is_unavailable(self) -> None:
        status, _ = classify_description("   \n\t  ")
        assert status is ExtractionStatus.UNAVAILABLE

    def test_a_stub_is_a_failure_that_names_its_length(self) -> None:
        text = "We are hiring. Please apply."
        status, reason = classify_description(text)
        assert status is ExtractionStatus.FAILED
        assert f"{len(text)} characters" in reason
        assert "150" in reason

    def test_length_decides_before_collapse_does(self) -> None:
        status, reason = classify_description("Too short.", collapsed=True)
        assert status is ExtractionStatus.FAILED
        assert "control" not in reason

    def test_a_description_below_the_complete_threshold_is_partial(self) -> None:
        status, reason = classify_description("x" * 200)
        assert status is ExtractionStatus.PARTIAL
        assert "400" in reason
        assert "complete" in reason

    def test_a_collapse_makes_any_length_partial(self) -> None:
        status, reason = classify_description("x" * 600, collapsed=True)
        assert status is ExtractionStatus.PARTIAL
        assert "control" in reason

    def test_a_long_description_is_complete_and_gives_no_reason(self) -> None:
        status, reason = classify_description("x" * 600)
        assert status is ExtractionStatus.COMPLETE
        assert reason is None

    def test_thresholds_come_from_settings_when_supplied(self) -> None:
        rules = ExtractionSettings(partial_min_chars=50, complete_min_chars=100)
        status, reason = classify_description("x" * 150, settings=rules)
        assert status is ExtractionStatus.COMPLETE
        assert reason is None

    def test_a_raised_partial_threshold_turns_text_into_a_failure(self) -> None:
        rules = ExtractionSettings(partial_min_chars=300, complete_min_chars=400)
        status, reason = classify_description("x" * 200, settings=rules)
        assert status is ExtractionStatus.FAILED
        assert "300" in reason

    def test_a_reason_exists_exactly_when_the_status_is_not_complete(self) -> None:
        for text in ("", "x", "x" * 100, "x" * 600):
            for collapsed in (False, True):
                status, reason = classify_description(text, collapsed=collapsed)
                assert (reason is None) is (status is ExtractionStatus.COMPLETE)

    def test_thresholds_must_be_ordered(self) -> None:
        with pytest.raises(ValidationError):
            ExtractionSettings(partial_min_chars=400, complete_min_chars=400)
        with pytest.raises(ValidationError):
            ExtractionSettings(partial_min_chars=500, complete_min_chars=400)

    def test_the_defaults_are_the_advertised_thresholds(self) -> None:
        rules = ExtractionSettings()
        assert rules.partial_min_chars == 150
        assert rules.complete_min_chars == 400


# ---------------------------------------------------------------------------
# Reading a posting page
# ---------------------------------------------------------------------------
class TestParseJobPage:
    def test_structured_data_wins_over_the_element_on_the_same_page(self) -> None:
        page = parse("job_detail.html")
        assert page.status is ExtractionStatus.COMPLETE
        assert page.reason is None
        assert page.description_text.startswith("SYNTHETIC POSTING.")
        assert "element fallback" not in page.description_text
        assert "<p>" in page.description_raw

    def test_the_structured_fields_are_read(self) -> None:
        page = parse("job_detail.html")
        assert page.title == "Senior Machine Learning Engineer"
        assert page.company == "Northwind Analytics Pvt Ltd"
        assert page.location == "Bengaluru, IN"
        assert page.external_job_id == "4000000001"
        assert page.employment_type == "Full-Time"
        assert page.salary_min == 120000.0
        assert page.salary_max == 160000.0
        assert page.salary_currency == "USD"
        assert page.salary_period == "YEAR"
        assert page.posted_at is not None
        assert page.posted_at.year == 2026

    def test_without_structured_data_the_element_is_used(self) -> None:
        page = parse("job_detail_element.html")
        assert page.status is ExtractionStatus.COMPLETE
        assert "Site Reliability Engineer to keep a synthetic platform" in (
            page.description_text
        )
        assert page.external_job_id is None
        assert page.company == ""

    def test_an_element_capture_keeps_the_structure_it_was_read_from(self) -> None:
        # The description element has no structured data to borrow, so the
        # headings and items are rebuilt as markup: without them the
        # difference between "what we look for" and "what you will do" is
        # lost the moment the text is flattened onto one line.
        page = parse("job_detail_element.html")
        assert page.description_raw != page.description_text
        assert "<h3>What we look for</h3>" in page.description_raw
        assert "<li>" in page.description_raw
        assert page.description_text.startswith("SYNTHETIC POSTING.")

    def test_a_fallback_title_loses_the_source_suffix(self) -> None:
        page = parse("job_detail_element.html")
        assert page.title == "Site Reliability Engineer at Tailspin"

    def test_a_description_hidden_behind_a_control_is_partial(self) -> None:
        page = parse("job_detail_collapsed.html")
        assert page.status is ExtractionStatus.PARTIAL
        assert page.collapsed is True
        assert "control" in page.reason
        assert page.description_text.strip()

    def test_an_expired_posting_is_unavailable_rather_than_a_failure(self) -> None:
        page = parse("job_detail_expired.html")
        assert page.status is ExtractionStatus.UNAVAILABLE
        assert page.reason == "posting is no longer open"
        assert page.description_text == ""
        assert page.usable is False
        assert page.title == "Data Engineer at Globex BV"

    def test_a_verification_challenge_is_a_failure(self) -> None:
        page = parse("job_detail_blocked.html")
        assert page.status is ExtractionStatus.FAILED
        assert "verification" in page.reason
        assert page.description_text == ""

    def test_a_posting_published_without_a_description_is_unavailable(self) -> None:
        page = parse("job_detail_stub.html")
        assert page.status is ExtractionStatus.UNAVAILABLE
        assert page.reason == "page carried no description"
        assert page.usable is False

    def test_a_description_that_is_too_short_fails_with_the_numbers(self) -> None:
        page = parse("job_detail_tiny.html")
        assert page.status is ExtractionStatus.FAILED
        assert "47 characters" in page.reason
        assert "150" in page.reason

    def test_an_empty_response_is_reported_rather_than_raised(self) -> None:
        for html in ("", "   ", "\n\t  "):
            page = parse_job_page(html, source="linkedin", page_url=PAGE_URL)
            assert page.status is ExtractionStatus.FAILED
            assert page.reason == "empty response"

    def test_thresholds_are_passed_through_from_settings(self) -> None:
        # The same element is a complete description under the default rules
        # and only a partial one for a source expected to write longer postings.
        assert parse("job_detail_element.html").status is ExtractionStatus.COMPLETE
        rules = ExtractionSettings(complete_min_chars=1000)
        page = parse("job_detail_element.html", settings=rules)
        assert page.status is ExtractionStatus.PARTIAL
        assert "1000" in page.reason

    def test_an_overlong_capture_is_truncated_and_marked_partial(self) -> None:
        rules = ExtractionSettings(max_chars=1000)
        page = parse("job_detail_long.html", settings=rules)
        assert page.description_length == 1000
        assert page.status is ExtractionStatus.PARTIAL
        assert "truncated to 1000" in page.reason

    def test_a_description_that_is_the_whole_page_is_not_trusted(self) -> None:
        html = (
            "<html><head><title>Odd posting</title></head><body>"
            '<div class="description__text"><p>'
            + "word " * 200
            + "</p></div></body></html>"
        )
        page = parse_job_page(html, source="linkedin", page_url=PAGE_URL)
        assert page.status is ExtractionStatus.UNAVAILABLE
        assert page.reason == "description element covered the whole page"

    def test_unreadable_structured_data_does_not_break_the_page(self) -> None:
        html = load("job_detail_element.html").replace(
            '<meta charset="utf-8">',
            '<meta charset="utf-8"><script type="application/ld+json">{not json</script>',
        )
        page = parse_job_page(html, source="linkedin", page_url=PAGE_URL)
        assert page.status is ExtractionStatus.COMPLETE
        assert "Site Reliability" in page.description_text

    def test_the_source_and_page_url_are_recorded(self) -> None:
        page = parse_job_page(
            load("job_detail.html"),
            source="fixture",
            page_url="https://example.test/jobs/view/1",
        )
        assert page.source == "fixture"
        assert page.page_url == "https://example.test/jobs/view/1"

    @pytest.mark.parametrize(
        ("fixture", "usable"),
        [
            ("job_detail.html", True),
            ("job_detail_element.html", True),
            ("job_detail_collapsed.html", True),
            ("job_detail_blocked.html", False),
            ("job_detail_stub.html", False),
            ("job_detail_tiny.html", False),
            ("job_detail_expired.html", False),
        ],
    )
    def test_a_capture_is_usable_only_when_it_carried_text(
        self, fixture: str, usable: bool
    ) -> None:
        assert parse(fixture).usable is usable, fixture

    def test_the_content_hash_follows_the_captured_text(self) -> None:
        page = parse("job_detail.html")
        assert page.content_hash == sha256_text(page.description_text)
        assert parse("job_detail_stub.html").content_hash is None

    def test_the_length_property_matches_the_text(self) -> None:
        page = parse("job_detail.html")
        assert page.description_length == len(page.description_text)


# ---------------------------------------------------------------------------
# Carrying a capture onto a stored job
# ---------------------------------------------------------------------------
class TestApplyToStoredJob:
    def test_a_usable_capture_writes_the_description(self) -> None:
        job = parse("job_detail.html").apply_to(discovered_job())
        assert job.description_text.startswith("SYNTHETIC POSTING.")
        assert job.description_raw
        assert job.description_hash == sha256_text(job.description_text)

    @pytest.mark.parametrize(
        "fixture",
        [
            "job_detail_blocked.html",
            "job_detail_stub.html",
            "job_detail_tiny.html",
            "job_detail_expired.html",
        ],
    )
    def test_an_unusable_capture_writes_no_description(self, fixture: str) -> None:
        job = parse(fixture).apply_to(discovered_job())
        assert job.description_text is None, fixture
        assert job.description_hash is None, fixture

    def test_the_original_job_is_untouched(self) -> None:
        job = discovered_job()
        parse("job_detail.html").apply_to(job)
        assert job.description_text is None

    def test_a_field_discovery_already_knew_is_not_overwritten(self) -> None:
        job = discovered_job(location="Berlin", salary_min=10.0, salary_max=20.0)
        page = JobPage(
            source="linkedin",
            page_url=PAGE_URL,
            status=ExtractionStatus.COMPLETE,
            company="Some Other Name",
            title="Some Other Title",
            location="Munich",
            salary_min=999.0,
            salary_max=999.0,
            description_text="x" * 500,
        )
        merged = page.apply_to(job)
        assert merged.company == "Northwind Analytics Pvt Ltd"
        assert merged.title == "Senior Machine Learning Engineer"
        assert merged.location == "Berlin"
        assert merged.salary_min == 10.0
        assert merged.salary_max == 20.0

    def test_a_blank_field_is_filled_in(self) -> None:
        job = discovered_job()
        page = JobPage(
            source="linkedin",
            page_url=PAGE_URL,
            status=ExtractionStatus.COMPLETE,
            employment_type="Full-Time",
            location="Lisbon",
            description_text="x" * 500,
        )
        merged = page.apply_to(job)
        assert merged.employment_type == "Full-Time"
        assert merged.location == "Lisbon"

    def test_a_failed_capture_still_contributes_what_it_learned(self) -> None:
        job = Job(source="linkedin")
        job = parse("job_detail_tiny.html").apply_to(job)
        assert job.title == "Short posting at Initech"
        assert job.description_text is None
        assert job.description_hash is None

    @pytest.mark.parametrize("status", [JobStatus.DISCOVERED, JobStatus.JD_PENDING])
    def test_a_parser_never_moves_the_lifecycle(self, status: JobStatus) -> None:
        job = discovered_job(status=status)
        assert parse("job_detail.html").apply_to(job).status is status
        assert parse("job_detail_blocked.html").apply_to(job).status is status

    def test_a_partial_capture_is_still_carried_over(self) -> None:
        job = parse("job_detail_collapsed.html").apply_to(discovered_job())
        assert job.description_text is not None
        assert job.description_text.strip()


# ---------------------------------------------------------------------------
# The lifecycle, end to end over the database
# ---------------------------------------------------------------------------
class TestExtractionLifecycle:
    @staticmethod
    def _repo(db):
        from database.repositories.jobs import JobRepository

        return JobRepository(db)

    def test_a_readable_posting_runs_from_discovered_to_extracted(self, db) -> None:
        repo = self._repo(db)
        job_id, created = repo.save(discovered_job())
        assert created is True

        repo.transition(job_id, JobStatus.FETCHED, actor="test", reason="page read")
        page = parse("job_detail.html")
        repo.save(page.apply_to(repo.require(job_id)), actor="test")
        repo.transition(job_id, JobStatus.NORMALIZED, actor="test")
        repo.transition(job_id, JobStatus.JD_PENDING, actor="test")
        repo.transition(job_id, JobStatus.JD_EXTRACTED, actor="test")
        repo.record_extraction_run(
            job_id,
            status=page.status,
            method=ExtractionMethod.DETERMINISTIC,
            raw_length=len(page.description_raw),
            normalized_length=page.description_length,
            content_hash=page.content_hash,
            source=page.source,
        )

        stored = repo.require(job_id)
        assert stored.status is JobStatus.JD_EXTRACTED
        assert stored.description_text.startswith("SYNTHETIC POSTING.")
        assert stored.description_hash == page.content_hash

        run = repo.latest_extraction(job_id)
        assert run["extraction_status"] == "COMPLETE"
        assert run["content_hash"] == stored.description_hash
        assert run["raw_length"] >= run["normalized_length"]

        events = repo.state_events(job_id)
        assert [event["to_state"] for event in events] == [
            "DISCOVERED",
            "FETCHED",
            "NORMALIZED",
            "JD_PENDING",
            "JD_EXTRACTED",
        ]

    def test_a_blocked_posting_ends_the_capture_as_a_failure(self, db) -> None:
        repo = self._repo(db)
        job_id, _ = repo.save(discovered_job())
        repo.transition(job_id, JobStatus.FETCHED, actor="test")
        page = parse("job_detail_blocked.html")
        repo.save(page.apply_to(repo.require(job_id)), actor="test")
        repo.transition(job_id, JobStatus.NORMALIZED, actor="test")
        repo.transition(job_id, JobStatus.JD_PENDING, actor="test")
        repo.transition(job_id, JobStatus.JD_FAILED, actor="test", reason=page.reason)
        repo.record_extraction_run(
            job_id,
            status=page.status,
            method=ExtractionMethod.DETERMINISTIC,
            content_hash=page.content_hash,
            source=page.source,
            error_code="blocked",
            detail={"reason": page.reason},
        )

        stored = repo.require(job_id)
        assert stored.status is JobStatus.JD_FAILED
        assert stored.description_text is None

        run = repo.latest_extraction(job_id)
        assert run["extraction_status"] == "FAILED"
        assert run["error_code"] == "blocked"
        assert run["content_hash"] is None
        assert json.loads(run["detail"])["reason"] == page.reason

    def test_a_second_capture_puts_a_job_back_to_being_read(self, db) -> None:
        repo = self._repo(db)
        job_id, _ = repo.save(discovered_job())
        repo.transition(job_id, JobStatus.FETCHED, actor="test")
        repo.transition(job_id, JobStatus.NORMALIZED, actor="test")
        repo.transition(job_id, JobStatus.JD_PENDING, actor="test")
        repo.transition(job_id, JobStatus.JD_EXTRACTED, actor="test")

        repo.transition(job_id, JobStatus.JD_PENDING, actor="test", reason="re-scan")
        assert repo.require(job_id).status is JobStatus.JD_PENDING

    def test_the_description_written_by_a_capture_survives_being_saved(self, db) -> None:
        repo = self._repo(db)
        job_id, _ = repo.save(discovered_job())
        page = parse("job_detail.html")
        repo.save(page.apply_to(repo.require(job_id)), actor="test")

        # Saving the job again, as later steps do, must not lose the capture.
        stored = repo.require(job_id)
        repo.save(stored, actor="test")
        reloaded = repo.require(job_id)
        assert reloaded.description_text == stored.description_text
        assert reloaded.description_hash == stored.description_hash

    def test_an_unusable_capture_leaves_the_job_without_a_description(self, db) -> None:
        repo = self._repo(db)
        job_id, _ = repo.save(discovered_job())
        page = parse("job_detail_stub.html")
        repo.save(page.apply_to(repo.require(job_id)), actor="test")

        stored = repo.require(job_id)
        assert stored.description_text is None
        assert stored.title == "Senior Machine Learning Engineer"
