"""Read-only discovery: listing pages and source adapters in, stored jobs
with provenance out.

Three contracts are checked here: a page (or adapter) yields normalised
jobs that carry where they came from; a blocked or unrecognisable page
comes back *typed* — status, reason, error code — instead of raising or
lying; and re-running the same page merges rather than duplicates. The
boundary itself — application actions refused — lives in
``test_job_records``; this file proves the service keeps to discovery
actions only, and that nothing in the discovery path touches a job page,
a browser, or a repository from inside ``jobs``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from assistant.job_service import JobService
from core.enums import (
    PageKind,
    RetrievalMethod,
    SourceAdapterStatus,
    SourceMode,
)
from jobs.models import JobStatus
from jobs.records import PROVENANCE_KEY, enforce_source_mode
from jobs.source import JobSource, SearchQuery, parse_listing
from profile.service import ProfileService

LISTING = "search_results.html"
EMPTY = "search_results_empty.html"
BLOCKED = "challenge.html"
UNRECOGNISED = "unrecognized.html"
MALFORMED = "malformed.html"

PAGE_URL = "https://www.linkedin.com/jobs/search/?keywords=engineer"


class FakeSource:
    """A JobSource over saved HTML: the live path with the browser removed."""

    name = "fake"

    def __init__(self, html: str, *, page_url: str = PAGE_URL, fail: bool = False):
        self._html = html
        self._page_url = page_url
        self._fail = fail
        self.queries: list[SearchQuery] = []
        self.fetch_calls: list[str] = []

    def search(self, query: SearchQuery):
        self.queries.append(query)
        if self._fail:
            raise ConnectionError("connection refused")
        return parse_listing(self._html, source=self.name, page_url=self._page_url)

    def fetch_job(self, url: str):
        self.fetch_calls.append(url)
        raise AssertionError("discovery must never fetch a job page")


class UnreachableSource(FakeSource):
    """Answers the protocol but is down whenever asked."""

    def __init__(self) -> None:
        super().__init__("", fail=True)


@pytest.fixture()
def profiles(tmp_path, db) -> ProfileService:
    service = ProfileService(db, storage_path=tmp_path / "candidate_profile.json")
    service.create_profile("primary", persist_json=True, actor="user")
    return service


@pytest.fixture()
def service(db, profiles) -> JobService:
    return JobService(db, profile_service=profiles, candidate_id="primary")


def page(fixtures_dir: Path, name: str) -> str:
    return (fixtures_dir / "html" / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Saved listing pages
# ---------------------------------------------------------------------------
class TestListingDiscovery:
    def test_a_saved_listing_page_stores_every_job_with_provenance(
        self, service, fixtures_dir
    ) -> None:
        outcome = service.discover_listing(
            page(fixtures_dir, LISTING), source="fixture", page_url=PAGE_URL
        )
        assert outcome.result.status is SourceAdapterStatus.OK
        assert outcome.stored_count == 3
        assert outcome.merged_count == 0
        assert [job.status for job in outcome.stored] == [JobStatus.DISCOVERED] * 3
        for job in outcome.stored:
            provenance = job.metadata[PROVENANCE_KEY]
            assert provenance["retrieval_method"] == RetrievalMethod.SAVED_PAGE.value
            assert provenance["retrieval_status"] == SourceAdapterStatus.OK.value
            assert provenance["source_url"] == PAGE_URL

    def test_provenance_survives_the_database_round_trip(
        self, service, fixtures_dir
    ) -> None:
        outcome = service.discover_listing(page(fixtures_dir, LISTING), source="fixture")
        stored_id = outcome.stored[0].id
        reloaded = service.get(stored_id)
        provenance = reloaded.metadata[PROVENANCE_KEY]
        assert provenance["source"] == "fixture"
        assert provenance["source_job_id"]
        assert provenance["retrieved_at"]

    def test_the_same_page_again_merges_instead_of_duplicating(
        self, service, fixtures_dir
    ) -> None:
        html = page(fixtures_dir, LISTING)
        first = service.discover_listing(html, source="fixture", page_url=PAGE_URL)
        second = service.discover_listing(html, source="fixture", page_url=PAGE_URL)
        assert first.stored_count == 3
        assert second.stored_count == 0
        assert second.merged_count == 3
        assert len(service.list_jobs()) == 3

    def test_an_empty_results_page_is_a_valid_answer(
        self, service, fixtures_dir
    ) -> None:
        outcome = service.discover_listing(page(fixtures_dir, EMPTY), source="fixture")
        assert outcome.result.status is SourceAdapterStatus.OK
        assert outcome.result.page_kind is PageKind.EMPTY
        assert outcome.result.error_code is None
        assert outcome.stored_count == 0
        assert service.list_jobs() == []

    def test_a_blocked_page_is_typed_and_stores_nothing(
        self, service, fixtures_dir
    ) -> None:
        outcome = service.discover_listing(page(fixtures_dir, BLOCKED), source="fixture")
        assert outcome.result.status is SourceAdapterStatus.BLOCKED
        assert outcome.result.error_code == "SOURCE_BLOCKED"
        assert outcome.result.reason
        assert outcome.stored_count == 0
        assert service.list_jobs() == []

    def test_an_unrecognised_page_reports_unsupported(
        self, service, fixtures_dir
    ) -> None:
        outcome = service.discover_listing(page(fixtures_dir, UNRECOGNISED), source="fixture")
        assert not outcome.result.ok
        assert outcome.result.error_code == "UNSUPPORTED_PAGE"
        assert outcome.result.reason
        assert service.list_jobs() == []

    def test_a_malformed_page_is_tolerated_not_raised_on(
        self, service, fixtures_dir
    ) -> None:
        # The parser repairs broken markup rather than giving up, so a
        # malformed capture may well yield a job; what must hold either way
        # is that nothing raises and whatever is stored carries provenance.
        outcome = service.discover_listing(page(fixtures_dir, MALFORMED), source="fixture")
        for job in outcome.stored:
            assert job.metadata[PROVENANCE_KEY]["retrieval_method"] == (
                RetrievalMethod.SAVED_PAGE.value
            )

    def test_a_partial_read_says_so(self, service) -> None:
        html = """
        <html><body><div class="jobs-search-results">
        <a href="/jobs/view/good-role-9001">Data Engineer</a>
        <a href="/jobs/view/apply-9002">Easy Apply</a>
        </div></body></html>
        """
        outcome = service.discover_listing(html, source="fixture", page_url=PAGE_URL)
        assert outcome.result.status is SourceAdapterStatus.PARTIAL
        assert outcome.result.error_code == "EXTRACTION_PARTIAL"
        assert outcome.stored_count == 1


# ---------------------------------------------------------------------------
# Source adapters (the live path, browser removed)
# ---------------------------------------------------------------------------
class TestAdapterDiscovery:
    def test_a_source_adapter_answers_and_stores(
        self, service, fixtures_dir
    ) -> None:
        source = FakeSource(page(fixtures_dir, LISTING))
        outcome = service.discover(source, SearchQuery(keywords="engineer"))
        assert outcome.result.status is SourceAdapterStatus.OK
        assert outcome.stored_count == 3
        assert outcome.result.source == "fake"
        assert len(source.queries) == 1
        for job in outcome.stored:
            provenance = job.metadata[PROVENANCE_KEY]
            assert provenance["retrieval_method"] == RetrievalMethod.BROWSER_FETCH.value
            assert provenance["retrieval_status"] == SourceAdapterStatus.OK.value

    def test_discovery_never_reads_a_single_job_page(
        self, service, fixtures_dir
    ) -> None:
        source = FakeSource(page(fixtures_dir, LISTING))
        service.discover(source, SearchQuery(keywords="engineer"))
        assert source.fetch_calls == []

    def test_a_source_that_cannot_be_reached_reports_a_typed_failure(
        self, service
    ) -> None:
        outcome = service.discover(UnreachableSource(), SearchQuery(keywords="engineer"))
        assert outcome.result.status is SourceAdapterStatus.FAILED
        assert outcome.result.error_code == "SOURCE_UNAVAILABLE"
        assert outcome.result.reason
        assert outcome.stored_count == 0
        assert service.list_jobs() == []

    def test_discovery_results_split_new_rows_from_merges(
        self, service, fixtures_dir
    ) -> None:
        html = page(fixtures_dir, LISTING)
        service.discover(FakeSource(html), SearchQuery(keywords="engineer"))
        second = service.discover(FakeSource(html), SearchQuery(keywords="engineer"))
        assert second.stored_count == 0
        assert second.merged_count == 3


# ---------------------------------------------------------------------------
# Boundary: discovery stays discovery
# ---------------------------------------------------------------------------
class TestDiscoveryBoundary:
    def test_the_service_starts_in_discovery_only_mode(self, service) -> None:
        assert service.source_mode is SourceMode.DISCOVERY_ONLY

    def test_application_actions_are_refused_from_the_service_mode(
        self, service
    ) -> None:
        from core.errors import ApplicationBoundaryError

        with pytest.raises(ApplicationBoundaryError):
            enforce_source_mode(service.source_mode, "SUBMIT")

    def test_the_discovery_modules_never_import_a_repository(self) -> None:
        source = Path("src/jobs/discovery.py").read_text(encoding="utf-8")
        assert "import database" not in source
        assert "from database" not in source
