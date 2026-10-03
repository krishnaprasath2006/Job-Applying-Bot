"""The browser: start a driver, load a page, read its HTML.

The only module in the project that imports Selenium, which is what lets
``src`` stay importable — and testable — on a machine with no browser
installed. Everything above this layer asks for HTML as a string.

This layer **reads pages**. It does not log in, does not fill forms, does not
click submission controls and does not accept offers. Discovery only needs
what a logged-out visitor can see, and keeping the capability out of the
reader is what stops "just fetch the listing" from quietly growing into
"just apply".

Failures are raised as :class:`core.errors.SourceAcquisitionError` so a
caller can report a typed reason instead of a Selenium stack trace.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from core.errors import ConfigurationError, SourceAcquisitionError
from core.logging_config import get_logger

log = get_logger(__name__)

__all__ = ["Browser", "SUPPORTED_BROWSERS", "build_driver", "fetch_html"]

#: Drivers this module knows how to start.
SUPPORTED_BROWSERS = ("chrome", "edge", "firefox")


def build_driver(
    *,
    browser: str = "edge",
    headless: bool = False,
    page_load_timeout_seconds: float = 45.0,
) -> Any:
    """Create a Selenium driver for ``browser``.

    Args:
        browser: One of :data:`SUPPORTED_BROWSERS`.
        headless: Run without a visible window.
        page_load_timeout_seconds: How long a page may take to load.

    Returns:
        A started WebDriver.

    Raises:
        ConfigurationError: If the browser is not supported or its driver
            cannot be started.
    """
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException

    chosen = (browser or "").lower().strip()
    if chosen not in SUPPORTED_BROWSERS:
        raise ConfigurationError(
            "unsupported browser for job discovery",
            browser=browser,
            supported=list(SUPPORTED_BROWSERS),
        )

    if chosen == "chrome":
        from selenium.webdriver.chrome.options import Options

        options = Options()
        if headless:
            options.add_argument("--headless=new")
        factory = webdriver.Chrome
    elif chosen == "firefox":
        from selenium.webdriver.firefox.options import Options

        options = Options()
        if headless:
            options.add_argument("-headless")
        factory = webdriver.Firefox
    else:
        from selenium.webdriver.edge.options import Options

        options = Options()
        if headless:
            options.add_argument("--headless=new")
        factory = webdriver.Edge

    options.add_argument("--disable-notifications")
    options.add_argument("--no-default-browser-check")

    try:
        driver = factory(options=options)
    except WebDriverException as exc:  # pragma: no cover - needs a real browser
        raise SourceAcquisitionError(
            "browser driver could not be started",
            browser=chosen,
            error_code="DRIVER_START_FAILED",
            cause=type(exc).__name__,
        ) from exc

    driver.set_page_load_timeout(page_load_timeout_seconds)
    return driver


class Browser:
    """A page reader backed by one driver.

    Reusable across many pages: starting a browser is expensive, and a search
    walks several pages before it stops.

    Args:
        browser: One of :data:`SUPPORTED_BROWSERS`.
        headless: Run without a visible window.
        page_load_timeout_seconds: Per-page load budget.
        driver: An existing driver, for callers that already have one. When
            supplied, :meth:`quit` leaves it to the owner.
    """

    def __init__(
        self,
        *,
        browser: str = "edge",
        headless: bool = False,
        page_load_timeout_seconds: float = 45.0,
        driver: Any = None,
    ) -> None:
        self.browser = browser
        self.headless = headless
        self.page_load_timeout_seconds = page_load_timeout_seconds
        self._driver = driver
        self._owns_driver = driver is None

    # -- lifecycle ---------------------------------------------------------
    @property
    def driver(self) -> Any:
        """The live driver, started on first use."""
        if self._driver is None:
            self._driver = build_driver(
                browser=self.browser,
                headless=self.headless,
                page_load_timeout_seconds=self.page_load_timeout_seconds,
            )
        return self._driver

    def quit(self) -> None:
        """Stop the driver if this browser owns it."""
        if self._driver is None or not self._owns_driver:
            self._driver = None
            return
        try:
            self._driver.quit()
        except Exception as exc:  # noqa: BLE001 - quitting must never mask a result
            log.debug("driver quit failed", extra={"browser": {"error": type(exc).__name__}})
        finally:
            self._driver = None

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.quit()

    # -- reading -----------------------------------------------------------
    def html(self, url: str, *, settle_seconds: float = 0.0) -> str:
        """Load ``url`` and return the page's HTML source.

        Waits for the document to finish loading before reading, because
        ``page_source`` taken mid-load is a partial page and a partial page
        parsed as a listing silently looks like "few results".

        Args:
            url: Page to load.
            settle_seconds: Extra pause after load, for pages that hydrate
                their results client-side. Zero by default: waiting without a
                reason is how a crawler becomes slow.

        Returns:
            The rendered HTML.

        Raises:
            SourceAcquisitionError: If the page could not be loaded at all.
        """
        from selenium.common.exceptions import TimeoutException, WebDriverException

        driver = self.driver
        try:
            driver.get(url)
            self._wait_for_document(driver)
            if settle_seconds > 0:
                time.sleep(settle_seconds)
            return driver.page_source
        except (TimeoutException, WebDriverException) as exc:
            raise SourceAcquisitionError(
                "page could not be loaded",
                url=url,
                error_code="PAGE_LOAD_FAILED",
                cause=type(exc).__name__,
            ) from exc

    @staticmethod
    def _wait_for_document(driver: Any) -> None:
        from selenium.webdriver.support.ui import WebDriverWait

        WebDriverWait(driver, 30).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )


def fetch_html(
    url: str,
    *,
    browser: str = "edge",
    headless: bool = False,
    page_load_timeout_seconds: float = 45.0,
    settle_seconds: float = 0.0,
) -> str:
    """Load one page with a throwaway browser and return its HTML.

    Convenient for a single fetch; use :class:`Browser` directly when walking
    several pages, so the browser is started once.
    """
    with Browser(
        browser=browser,
        headless=headless,
        page_load_timeout_seconds=page_load_timeout_seconds,
    ) as session:
        return session.html(url, settle_seconds=settle_seconds)
