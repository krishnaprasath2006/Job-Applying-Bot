"""Ingestion through a source adapter: one fetch, one verdict.

The contract under test: a source answers ``fetch_job``, the page's own
extraction verdict becomes both ``extraction_status`` and the retrieval
status in provenance, and a job first seen in a listing merges onto the
same row with provenance following whichever sighting supplied the text.
Typed failures propagate (the caller sees the code), application actions
never reach the adapter, and no parser moves the lifecycle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from assistant.job_service import JobService
from core.enums import RetrievalMethod, SourceAdapterStatus, SourceMode
from core.errors import ApplicationBoundaryError, SourceAcquisitionError
from jobs.acquisition import parse_job_page
from jobs.models import Job, JobStatus
from jobs.records import PROVENANCE_KEY
from jobs.source import SearchQuery
from candidate_profile.service import ProfileService

PAGE_URL = "https://www.linkedin.com/jobs/view/4000000021"

#: Fixture page -> (extraction status, expected retrieval status).
VERDICTS = [
    ("job_detail.html", "COMPLETE", SourceAdapterStatus.OK),
    ("job_detail_collapsed.html", "PARTIAL", SourceAdapterStatus.PARTIAL),
    ("job_detail_tiny.html", "FAILED", SourceAdapterStatus.FAILED),
    ("job_detail_expired.html", "UNAVAILABLE", SourceAdapterStatus.UNAVAILABLE),
]


class FakeSource:
    """A JobSource that fetches saved pages and refuses to search."""

    name = "fake"

    def __init__(self, html: str, *, page_url: str = PAGE_URL):
        self._html = html
        self._page_url = page_url
        self.search_calls = 0

    def search(self, query: SearchQuery):
        self.search_calls += 1
        raise AssertionError("ingestion must never run a search")

    def fetch_job(self, url: str):
        return parse_job_page(self._html, source=self.name, page_url=url)


class BrokenSource(FakeSource):
    def fetch_job(self, url: str):
        raise SourceAcquisitionError("posting is gone", error_code="JOB_NOT_FOUND")


@pytest.fixture()
def profiles(tmp_path, db) -> ProfileService:
    service = ProfileService(db, storage_path=tmp_path / "candidate_profile.json")
    service.create_profile("primary", persist_json=True, actor="user")
    return service


@pytest.fixture()
def service(db, profiles) -> JobService:
    return JobService(db, profile_service=profiles, candidate_id="primary")


def fixture_html(fixtures_dir: Path, name: str) -> str:
    return (fixtures_dir / "html" / name).read_text(encoding="utf-8")


class TestIngestionProvenance:
    @pytest.mark.parametrize(
        "name,extraction,retrieval", VERDICTS, ids=[v[0] for v in VERDICTS]
    )
    def test_the_pages_verdict_becomes_both_statuses(
        self, service, fixtures_dir, name: str, extraction: str, retrieval
    ) -> None:
        source = FakeSource(fixture_html(fixtures_dir, name))
        result = service.ingest_from_source(source, PAGE_URL)
        assert result.created is True
        assert result.job.metadata["extraction_status"] == extraction
        provenance = result.job.metadata[PROVENANCE_KEY]
        assert provenance["retrieval_method"] == RetrievalMethod.BROWSER_FETCH.value
        assert provenance["retrieval_status"] == retrieval.value
        assert provenance["source_url"] == PAGE_URL

    def test_a_usable_page_stores_its_description(self, service, fixtures_dir) -> None:
        source = FakeSource(fixture_html(fixtures_dir, "job_detail.html"))
        result = service.ingest_from_source(source, PAGE_URL)
        assert result.page.usable
        assert result.job.description_text
        assert result.job.canonical_url
        assert source.search_calls == 0

    def test_a_failed_capture_still_records_the_attempt(
        self, service, fixtures_dir
    ) -> None:
        source = FakeSource(fixture_html(fixtures_dir, "job_detail_tiny.html"))
        result = service.ingest_from_source(source, PAGE_URL)
        assert result.created is True
        assert result.job.metadata["extraction_status"] == "FAILED"
        assert not result.job.description_text
        assert result.job.metadata[PROVENANCE_KEY]["retrieval_status"] == "FAILED"
        assert result.job.metadata[PROVENANCE_KEY]["detail"]

    def test_no_parser_moves_the_lifecycle(self, service, fixtures_dir) -> None:
        source = FakeSource(fixture_html(fixtures_dir, "job_detail.html"))
        result = service.ingest_from_source(source, PAGE_URL)
        assert result.job.status is JobStatus.DISCOVERED


class TestMergeWithDiscovery:
    def test_a_fetch_fills_in_the_listing_stub_on_the_same_row(
        self, service, fixtures_dir
    ) -> None:
        listing = """
        <html><body><div class="jobs-search-results">
        <a href="/jobs/view/senior-engineer-90010001">Senior Engineer</a>
        </div></body></html>
        """
        detail = """
        <html><head><title>Senior Engineer</title>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "JobPosting",
         "title": "Senior Engineer",
         "url": "https://www.linkedin.com/jobs/view/senior-engineer-90010001",
         "description": "<p>""" + ("We need a senior engineer with Python. " * 20) + """</p>"}
        </script></head><body></body></html>
        """
        discovered = service.discover_listing(listing, source="fake")
        stub_id = discovered.stored[0].id

        result = service.ingest_from_source(
            FakeSource(detail, page_url=""), "https://www.linkedin.com/jobs/view/senior-engineer-90010001"
        )
        assert result.created is False
        assert result.job.id == stub_id
        assert result.job.description_text
        # Provenance followed the text: the fetch supplied it, so the fetch
        # is now the origin of record.
        provenance = result.job.metadata[PROVENANCE_KEY]
        assert provenance["retrieval_method"] == RetrievalMethod.BROWSER_FETCH.value
        assert provenance["retrieval_status"] == SourceAdapterStatus.OK.value

    def test_a_second_sighting_keeps_the_original_when_the_text_stands(
        self, service, fixtures_dir
    ) -> None:
        detail = fixture_html(fixtures_dir, "job_detail.html")
        first = service.ingest_from_source(FakeSource(detail), PAGE_URL)
        second = service.ingest_from_source(
            FakeSource(fixture_html(fixtures_dir, "job_detail_stub.html")), PAGE_URL
        )
        assert second.created is False
        assert second.job.id == first.job.id
        assert second.job.description_text == first.job.description_text
        provenance = second.job.metadata[PROVENANCE_KEY]
        assert provenance["retrieval_status"] == SourceAdapterStatus.OK.value


class TestTypedFailures:
    def test_a_typed_fetch_failure_propagates_with_its_code(
        self, service, fixtures_dir
    ) -> None:
        source = BrokenSource(fixture_html(fixtures_dir, "job_detail.html"))
        with pytest.raises(SourceAcquisitionError) as exc:
            service.ingest_from_source(source, PAGE_URL)
        assert exc.value.details.get("error_code") == "JOB_NOT_FOUND"


class TestBoundary:
    def test_fetch_is_a_discovery_action_and_submit_is_not(self, service) -> None:
        from jobs.records import enforce_source_mode

        assert service.source_mode is SourceMode.DISCOVERY_ONLY
        enforce_source_mode(service.source_mode, "FETCH")  # permitted
        with pytest.raises(ApplicationBoundaryError):
            enforce_source_mode(service.source_mode, "SUBMIT")
