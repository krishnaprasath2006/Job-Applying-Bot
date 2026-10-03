"""Discovery: turning a listing page into job stubs.

Every test here reads a saved fixture. Nothing in this file opens a browser,
reaches the network or mentions real credentials — that is the point of the
split between :mod:`jobs.source` (HTML in, jobs out) and ``automation``
(fetching), and these tests are what prove it holds.

The fixtures are deliberately shaped like a real results page, including the
navigation links and pagination that a naive parser would turn into phantom
jobs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.enums import PageKind, SourceAdapterStatus
from jobs.source import (
    JobSource,
    ListingResult,
    SearchQuery,
    detect_page_kind,
    html_to_text,
    job_link_id,
    parse_listing,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "html"
PAGE_URL = "https://www.linkedin.com/jobs/search/?keywords=machine%20learning"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def parse(name: str, *, page_url: str = PAGE_URL) -> ListingResult:
    return parse_listing(load(name), source="linkedin", page_url=page_url)


# ---------------------------------------------------------------------------
# A results page
# ---------------------------------------------------------------------------
class TestResultsPage:
    def test_every_posting_on_the_page_is_read(self) -> None:
        result = parse("search_results.html")
        assert result.page_kind is PageKind.RESULTS
        assert result.status is SourceAdapterStatus.OK
        assert [job.title for job in result.jobs] == [
            "Senior Machine Learning Engineer",
            "Machine Learning Engineer",
            "AI Engineer, Recommendations",
        ]

    def test_fields_come_from_the_card_markup(self) -> None:
        jobs = {job.external_job_id: job for job in parse("search_results.html").jobs}
        second = jobs["4000000002"]
        assert second.company == "Contoso Ltd"
        assert second.location == "Remote"
        assert second.source == "linkedin"
        assert second.status.value == "DISCOVERED"

    def test_navigation_links_never_become_jobs(self) -> None:
        result = parse("search_results.html")
        # Three cards, three postings — the header links to /jobs/, /company/
        # and /feed/ are not postings and are not counted as such.
        assert len(result.jobs) == 3
        assert result.links_seen == 3
        titles = {job.title.lower() for job in result.jobs}
        assert "jobs" not in titles
        assert "northwind analytics" not in titles

    def test_json_ld_and_card_merge_into_one_job(self) -> None:
        result = parse("search_results.html")
        first = result.jobs[0]
        # The structured data supplies the description; the card confirms the
        # location and the relative date, and neither is lost.
        assert first.description_text and "SYNTHETIC POSTING" in first.description_text
        assert "<p>" not in first.description_text
        assert first.company == "Northwind Analytics Pvt Ltd"
        assert first.metadata["found_by"] == "json-ld"
        assert first.metadata["posted_text"] == "3 days ago"
        assert first.posted_at is not None

    def test_relative_links_are_resolved_against_the_page(self) -> None:
        for job in parse("search_results.html").jobs:
            assert job.url.startswith("https://www.linkedin.com/jobs/view/")
            assert job.metadata["page_url"] == PAGE_URL

    def test_tracking_parameters_are_not_part_of_the_canonical_url(self) -> None:
        first = parse("search_results.html").jobs[0]
        assert first.canonical_url is not None
        assert "refId" not in first.canonical_url
        assert "trackingId" not in first.canonical_url
        assert first.canonical_url.endswith("4000000001")

    def test_a_next_page_link_is_exposed_for_the_crawler(self) -> None:
        result = parse("search_results.html")
        assert result.has_more
        assert result.next_url == (
            "https://www.linkedin.com/jobs/search/?keywords=machine%20learning&start=25"
        )

    def test_posting_ids_are_read_from_the_path(self) -> None:
        ids = [job.external_job_id for job in parse("search_results.html").jobs]
        assert ids == ["4000000001", "4000000002", "4000000003"]


# ---------------------------------------------------------------------------
# Pages that are not result lists
# ---------------------------------------------------------------------------
class TestEmptyPage:
    def test_an_empty_result_set_is_an_answer_not_a_failure(self) -> None:
        result = parse("search_results_empty.html")
        assert result.page_kind is PageKind.EMPTY
        assert result.status is SourceAdapterStatus.OK
        assert result.ok is True
        assert result.jobs == ()
        assert result.reason is None

    def test_an_empty_page_has_no_next_link(self) -> None:
        assert parse("search_results_empty.html").has_more is False


class TestBlockedPage:
    def test_a_verification_wall_is_reported_as_blocked(self) -> None:
        result = parse("challenge.html")
        assert result.page_kind is PageKind.BLOCKED
        assert result.status is SourceAdapterStatus.BLOCKED
        assert result.ok is False
        assert result.jobs == ()

    def test_the_reason_says_what_happened(self) -> None:
        assert "verification" in (parse("challenge.html").reason or "")

    def test_a_blocked_page_never_reports_success(self) -> None:
        assert ListingResult(
            source="linkedin", page_kind=PageKind.BLOCKED
        ).ok is False


class TestUnreadablePage:
    def test_a_page_that_is_neither_results_nor_empty_is_unreadable(self) -> None:
        result = parse("unrecognized.html")
        assert result.page_kind is PageKind.UNKNOWN
        assert result.status is SourceAdapterStatus.FAILED
        assert result.ok is False
        assert result.jobs == ()
        assert result.reason

    def test_an_empty_response_is_unreadable_rather_than_empty(self) -> None:
        result = parse_listing("", source="linkedin", page_url=PAGE_URL)
        assert result.page_kind is PageKind.UNKNOWN
        assert result.reason == "empty response"

    def test_whitespace_only_is_also_unreadable(self) -> None:
        result = parse_listing("   \n\t  ", source="linkedin")
        assert result.page_kind is PageKind.UNKNOWN


# ---------------------------------------------------------------------------
# Fragile markup
# ---------------------------------------------------------------------------
class TestLinksOnlyPage:
    def test_postings_are_read_even_without_card_markup(self) -> None:
        result = parse("results_without_cards.html")
        assert result.page_kind is PageKind.RESULTS
        assert [job.title for job in result.jobs] == [
            "Backend Engineer",
            "Data Engineer",
            "Unnumbered Role",
        ]

    def test_a_posting_without_an_id_keeps_its_url_identity(self) -> None:
        unnumbered = parse("results_without_cards.html").jobs[2]
        assert unnumbered.external_job_id is None
        assert unnumbered.canonical_url is not None

    def test_ids_in_the_query_string_count_too(self) -> None:
        by_title = {job.title: job for job in parse("results_without_cards.html").jobs}
        assert by_title["Data Engineer"].external_job_id == "4000000012"

    def test_a_link_that_is_not_a_posting_is_not_counted(self) -> None:
        result = parse("results_without_cards.html")
        assert len(result.jobs) == 3
        assert result.links_seen == 3


class TestMalformedPage:
    def test_broken_nesting_is_repaired_rather_than_rejected(self) -> None:
        result = parse("malformed.html")
        assert result.page_kind is PageKind.RESULTS
        assert len(result.jobs) == 1

    def test_the_repaired_job_still_carries_its_fields(self) -> None:
        job = parse("malformed.html").jobs[0]
        assert job.external_job_id == "4000000021"
        assert job.title == "Nested badly"
        assert job.company == "Umbrella Corp"
        assert job.location == "Chicago, IL"


# ---------------------------------------------------------------------------
# Unreadable links
# ---------------------------------------------------------------------------
ACTION_CARD_PAGE = """
<html><head><title>results</title></head><body>
<div class="jobs-search-results">
  <div class="jobs-search-results__list-item">
    <a class="base-card__full-link" href="/jobs/view/4000000031">Real Role</a>
    <h3 class="base-search-card__title">Real Role</h3>
    <h4 class="base-search-card__subtitle">Acme GmbH</h4>
  </div>
  <div class="jobs-search-results__list-item">
    <a class="base-card__full-link" href="/jobs/view/4000000032">Easy Apply</a>
  </div>
</div>
</body></html>
"""


class TestUnreadableLinks:
    def test_a_control_labelled_link_is_skipped_rather_than_stored(self) -> None:
        result = parse_listing(ACTION_CARD_PAGE, source="linkedin", page_url=PAGE_URL)
        assert [job.title for job in result.jobs] == ["Real Role"]
        assert result.links_skipped == 1

    def test_a_partial_read_says_so_instead_of_reporting_success(self) -> None:
        result = parse_listing(ACTION_CARD_PAGE, source="linkedin", page_url=PAGE_URL)
        assert result.status is SourceAdapterStatus.PARTIAL
        assert result.ok is True
        assert result.page_kind is PageKind.RESULTS


# ---------------------------------------------------------------------------
# Page classification
# ---------------------------------------------------------------------------
class TestPageClassification:
    def test_blocked_wins_over_every_other_reading(self) -> None:
        kind = detect_page_kind(
            title="Security Verification",
            body_sample="complete the captcha to continue. sorry, no results",
            job_count=0,
        )
        assert kind is PageKind.BLOCKED

    def test_results_wins_over_stale_markers(self) -> None:
        kind = detect_page_kind(
            title="jobs",
            body_sample="this page mentions no results in its script comments",
            job_count=4,
        )
        assert kind is PageKind.RESULTS

    def test_empty_markers_mean_an_empty_result_set(self) -> None:
        assert (
            detect_page_kind(
                title="x", body_sample="Sorry, we could not find any jobs", job_count=0
            )
            is PageKind.EMPTY
        )

    def test_listing_chrome_alone_is_enough_for_empty(self) -> None:
        assert (
            detect_page_kind(
                title="x", body_sample="nothing here", job_count=0, has_listing_chrome=True
            )
            is PageKind.EMPTY
        )

    def test_anything_else_is_unknown(self) -> None:
        assert (
            detect_page_kind(title="Careers", body_sample="we are hiring", job_count=0)
            is PageKind.UNKNOWN
        )

    def test_only_a_definite_answer_is_usable(self) -> None:
        assert PageKind.RESULTS.usable is True
        assert PageKind.EMPTY.usable is True
        assert PageKind.BLOCKED.usable is False
        assert PageKind.UNKNOWN.usable is False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
class TestJobLinkId:
    def test_id_at_the_end_of_the_path(self) -> None:
        assert job_link_id("/jobs/view/4000123456") == "4000123456"

    def test_id_after_a_slug(self) -> None:
        assert job_link_id("/jobs/view/senior-engineer-4000123456?ref=x") == "4000123456"

    def test_id_in_the_query_string(self) -> None:
        assert job_link_id("/jobs/search/?currentJobId=4000123456&ref=x") == "4000123456"

    def test_no_id_is_reported_as_absent_rather_than_invented(self) -> None:
        assert job_link_id("/jobs/view/short-id") == ""
        assert job_link_id("/jobs/search/?q=python") == ""
        assert job_link_id("") == ""


class TestHtmlToText:
    def test_tags_are_removed(self) -> None:
        assert html_to_text("<p>Build <b>models</b></p>") == "Build models"

    def test_entities_are_decoded(self) -> None:
        assert html_to_text("Python &amp; SQL &ndash; daily") == "Python & SQL - daily"

    def test_whitespace_is_collapsed(self) -> None:
        assert html_to_text("<li>  one\n  </li> <li>two</li>") == "one two"

    def test_empty_input_is_empty_text(self) -> None:
        assert html_to_text(None) == ""
        assert html_to_text("") == ""


class TestSearchQuery:
    def test_blank_keywords_are_refused(self) -> None:
        with pytest.raises(ValueError, match="keywords"):
            SearchQuery(keywords="   ")

    def test_the_page_offset_is_derived_not_sent(self) -> None:
        first = SearchQuery(keywords="python", page=1, results_per_page=25)
        third = SearchQuery(keywords="python", page=3, results_per_page=25)
        assert first.start_offset == 0
        assert third.start_offset == 50

    def test_a_query_may_be_built_from_settings(self) -> None:
        from core.settings import JobSearchSettings

        query = SearchQuery.from_settings(
            JobSearchSettings(keywords=["ML Engineer", "Other"], locations=["India"])
        )
        assert query.keywords == "ML Engineer"
        assert query.location == "India"

    def test_the_source_is_normalised(self) -> None:
        assert SearchQuery(keywords="python", source="LinkedIn").source == "linkedin"

    def test_results_per_page_stays_in_a_sane_range(self) -> None:
        with pytest.raises(ValueError):
            SearchQuery(keywords="python", results_per_page=0)
        with pytest.raises(ValueError):
            SearchQuery(keywords="python", results_per_page=101)


# ---------------------------------------------------------------------------
# The source protocol
# ---------------------------------------------------------------------------
class TestJobSourceProtocol:
    def test_a_fixture_backed_source_satisfies_the_protocol(self) -> None:
        from jobs.acquisition import JobPage, parse_job_page

        class FixtureSource:
            name = "fixture"

            def search(self, query: SearchQuery) -> ListingResult:
                return parse_listing(load("search_results.html"), source=self.name)

            def fetch_job(self, url: str) -> JobPage:
                return parse_job_page(
                    load("job_detail.html"), source=self.name, page_url=url
                )

        assert isinstance(FixtureSource(), JobSource)

    def test_a_source_that_cannot_read_postings_is_not_a_source(self) -> None:
        class SearchOnly:
            name = "search-only"

            def search(self, query: SearchQuery) -> ListingResult:
                return parse_listing(load("search_results.html"), source=self.name)

        assert not isinstance(SearchOnly(), JobSource)

    def test_the_linkedin_source_satisfies_the_protocol(self) -> None:
        from automation.linkedin_source import LinkedInSource

        assert isinstance(LinkedInSource(), JobSource)


class TestLinkedInSource:
    """URL construction and fetch injection, still without a browser."""

    @staticmethod
    def source(**kwargs):
        from automation.linkedin_source import LinkedInSource

        html = kwargs.pop("html", None)
        if html is None:
            html = load("search_results.html")
        return LinkedInSource(fetch=lambda url: html, **kwargs)

    @staticmethod
    def query(**kwargs) -> SearchQuery:
        kwargs.setdefault("keywords", "Machine Learning")
        return SearchQuery(**kwargs)

    def test_the_search_url_carries_the_keywords(self) -> None:
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.source().build_search_url(self.query(location="India")))
        assert parsed.path == "/jobs/search/"
        query = parse_qs(parsed.query)
        assert query["keywords"] == ["Machine Learning"]
        assert query["location"] == ["India"]

    def test_filters_become_platform_parameters(self) -> None:
        from urllib.parse import parse_qs, urlparse

        url = self.source().build_search_url(
            self.query(remote_only=True, easy_apply_only=True)
        )
        query = parse_qs(urlparse(url).query)
        assert query["f_WT"] == ["3"]  # workplace type: remote
        assert query["f_AL"] == ["1"]  # easy apply only

    def test_the_result_offset_is_sent_not_the_page_number(self) -> None:
        from urllib.parse import parse_qs, urlparse

        url = self.source().build_search_url(self.query(page=3, results_per_page=25))
        assert parse_qs(urlparse(url).query)["start"] == ["50"]
        assert "page" not in parse_qs(urlparse(url).query)

    def test_a_first_page_omits_the_offset(self) -> None:
        from urllib.parse import parse_qs, urlparse

        url = self.source().build_search_url(self.query(page=1))
        assert "start" not in parse_qs(urlparse(url).query)

    def test_search_returns_jobs_parsed_from_the_fetched_page(self) -> None:
        result = self.source().search(self.query())
        assert result.page_kind is PageKind.RESULTS
        assert len(result.jobs) == 3

    def test_every_job_remembers_which_page_it_came_from(self) -> None:
        source = self.source()
        result = source.search(self.query())
        for job in result.jobs:
            assert job.metadata["page_url"] == source.build_search_url(self.query())

    def test_a_fetch_failure_is_a_result_not_an_exception(self) -> None:
        from automation.linkedin_source import LinkedInSource

        def explode(url: str) -> str:
            raise TimeoutError("driver never answered")

        result = LinkedInSource(fetch=explode).search(self.query())
        assert result.jobs == ()
        assert result.page_kind is PageKind.UNKNOWN
        assert "TimeoutError" in (result.reason or "")

    def test_blocked_html_passes_through_as_blocked(self) -> None:
        from automation.linkedin_source import LinkedInSource

        source = LinkedInSource(fetch=lambda url: load("challenge.html"))
        result = source.search(self.query())
        assert result.page_kind is PageKind.BLOCKED
        assert result.status is SourceAdapterStatus.BLOCKED


# ---------------------------------------------------------------------------
# The boundary between the domain and the browser
# ---------------------------------------------------------------------------
class TestLayerBoundary:
    def test_src_never_imports_the_automation_package(self, project_root: Path) -> None:
        """The dependency is one-way, or the browser is back in the domain."""
        import re

        pattern = re.compile(r"^\s*(?:from|import)\s+automation\b", re.MULTILINE)
        offenders = [
            str(path.relative_to(project_root))
            for path in sorted((project_root / "src").rglob("*.py"))
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        assert offenders == []

    def test_automation_reads_pages_through_the_domain_parser(self, project_root: Path) -> None:
        text = (project_root / "automation" / "linkedin_source.py").read_text(encoding="utf-8")
        assert "from jobs.source import" in text


# ---------------------------------------------------------------------------
# Integration with persistence
# ---------------------------------------------------------------------------
class TestDiscoveryAndPersistence:
    def test_rerunning_discovery_does_not_duplicate_jobs(self, db) -> None:
        from database.repositories.jobs import JobRepository

        repo = JobRepository(db)
        for page_url in (PAGE_URL, PAGE_URL + "&start=0"):
            for job in parse("search_results.html", page_url=page_url).jobs:
                repo.save(job)

        assert db.count("jobs") == 3
        counts = repo.count_by_status()
        assert counts == {"DISCOVERED": 3}

    def test_parsed_jobs_start_the_lifecycle_at_discovered(self, db) -> None:
        from database.repositories.jobs import JobRepository
        from jobs.models import JobStatus

        repo = JobRepository(db)
        job = parse("search_results.html").jobs[0]
        job_id, created = repo.save(job)
        assert created is True
        assert repo.load(job_id).status is JobStatus.DISCOVERED
        assert len(repo.state_events(job_id)) == 1
