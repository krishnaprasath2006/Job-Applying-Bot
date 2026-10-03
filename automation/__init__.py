"""Browser-backed access to job sources.

This package sits outside ``src`` on purpose. It is the layer that needs a
browser and therefore Selenium, and the domain layer must be able to run —
and to be tested — with no browser, no network and no credentials at all.

The dependency points one way: ``automation`` imports ``src`` (for
:class:`jobs.source.SearchQuery`, :func:`jobs.source.parse_listing` and the
:class:`jobs.source.JobSource` protocol it implements). ``src`` never imports
``automation``.
"""

from __future__ import annotations

__all__ = ["Browser", "LinkedInSource", "fetch_html"]


def __getattr__(name: str):
    """Expose the two entry points without importing Selenium up front.

    ``from automation import LinkedInSource`` works, while plain
    ``import automation`` stays free of Selenium so that environments which
    only parse saved pages never load the browser stack.
    """
    if name == "LinkedInSource":
        from automation.linkedin_source import LinkedInSource

        return LinkedInSource
    if name == "Browser":
        from automation.browser import Browser

        return Browser
    if name == "fetch_html":
        from automation.browser import fetch_html

        return fetch_html
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
