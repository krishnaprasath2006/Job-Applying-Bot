"""LinkedIn as a job source: search URLs in, listing HTML out.

Implements :class:`jobs.source.JobSource` for the one platform the assistant
supports today. URL construction lives here rather than in ``src`` because it
is a property of the platform, not of the domain: a source that answered
"where are jobs listed" differently should require no change to job
parsing, identity or matching.

Fetching is injected. Tests pass a callable that returns saved HTML and
therefore never start a browser, never touch the network and never need
credentials; production passes nothing and gets the Selenium-backed reader
from :mod:`automation.browser`, imported lazily so that importing this module
stays free of Selenium.

Parameter names (``f_WT`` for workplace type, ``f_AL`` for Easy Apply,
``start`` for the result offset) are the platform's public search vocabulary.
They are asserted against fixtures here, not against the live site — the test
suite never reaches LinkedIn.
"""

from __future__ import annotations

from typing import Callable, Optional
from urllib.parse import urlencode

from core.enums import ExtractionStatus, PageKind
from core.logging_config import get_logger
from core.settings import ExtractionSettings
from jobs.acquisition import JobPage, parse_job_page
from jobs.source import ListingResult, SearchQuery, parse_listing

log = get_logger(__name__)

__all__ = ["LinkedInSource"]

#: Placeholder kept out of tests: only the host matters for resolving links.
LINKEDIN_BASE_URL = "https://www.linkedin.com"


class LinkedInSource:
    """Browser-backed LinkedIn job search.

    Args:
        fetch: Callable returning the HTML of a page. Defaults to the
            Selenium reader; supply one in tests.
        base_url: Host used to resolve relative links in returned pages.
        settle_seconds: Extra wait after a page loads, for results that are
            rendered client-side.
        browser / headless: Passed to the browser when fetching is left to it.
        extraction_settings: Thresholds for judging a captured description.
    """

    name = "linkedin"

    def __init__(
        self,
        *,
        fetch: Optional[Callable[[str], str]] = None,
        base_url: str = LINKEDIN_BASE_URL,
        settle_seconds: float = 0.0,
        browser: str = "edge",
        headless: bool = False,
        extraction_settings: Optional[ExtractionSettings] = None,
    ) -> None:
        self._fetch = fetch
        self.base_url = base_url.rstrip("/")
        self.settle_seconds = settle_seconds
        self.browser = browser
        self.headless = headless
        self.extraction_settings = extraction_settings or ExtractionSettings()

    # -- JobSource ---------------------------------------------------------
    def build_search_url(self, query: SearchQuery) -> str:
        """Absolute search URL for ``query``.

        The offset rather than the page number is sent, because the platform
        pages by result index: page 3 of 25 starts at result 50.
        """
        params: list[tuple[str, str]] = [("keywords", query.keywords)]
        if query.location:
            params.append(("location", query.location))
        if query.start_offset:
            params.append(("start", str(query.start_offset)))
        if query.remote_only:
            params.append(("f_WT", "3"))
        if query.easy_apply_only:
            params.append(("f_AL", "1"))
        return f"{self.base_url}/jobs/search/?{urlencode(params)}"

    def search(self, query: SearchQuery) -> ListingResult:
        """Run one search and return what the results page contained."""
        url = self.build_search_url(query)
        return self.fetch_page(url)

    def fetch_page(self, url: str) -> ListingResult:
        """Read one listing page, whatever its shape turns out to be.

        A blocked or unreadable page is returned, not raised: the caller needs
        the reason in order to stop and tell a human, and a raised error here
        would be indistinguishable from a transient failure worth retrying.
        """
        try:
            html = self._read(url)
        except Exception as exc:  # noqa: BLE001 - reported as a typed result
            log.warning(
                "listing could not be read",
                extra={"discovery": {"source": self.name, "error": type(exc).__name__}},
            )
            return ListingResult(
                source=self.name,
                page_kind=PageKind.UNKNOWN,
                page_url=url,
                reason=f"{type(exc).__name__}: {exc}"[:200],
            )
        return parse_listing(html, source=self.name, page_url=url)

    def fetch_job(self, url: str) -> JobPage:
        """Read one posting page: the description, and how good a capture it was.

        A read failure is reported as ``ExtractionStatus.FAILED`` with the
        reason attached, so a driver that timed out is distinguishable from a
        posting that has no description — the first is worth retrying and the
        second is not.
        """
        try:
            html = self._read(url)
        except Exception as exc:  # noqa: BLE001 - reported as a typed result
            log.warning(
                "posting page could not be read",
                extra={"extraction": {"source": self.name, "error": type(exc).__name__}},
            )
            return JobPage(
                source=self.name,
                page_url=url,
                status=ExtractionStatus.FAILED,
                reason=f"{type(exc).__name__}: {exc}"[:200],
            )
        return parse_job_page(
            html,
            source=self.name,
            page_url=url,
            settings=self.extraction_settings,
        )

    # -- internals ---------------------------------------------------------
    def _read(self, url: str) -> str:
        if self._fetch is not None:
            return self._fetch(url)
        # Imported here, not at module scope: reading saved pages must not
        # require Selenium to be importable at all.
        from automation.browser import fetch_html

        return fetch_html(
            url,
            browser=self.browser,
            headless=self.headless,
            settle_seconds=self.settle_seconds,
        )
