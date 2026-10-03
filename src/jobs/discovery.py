"""Read-only discovery: turning a source (or a saved listing page) into
normalised, provenance-carrying jobs.

Discovery is a deliberate half-pipeline. It fetches or parses, normalises,
and stops — persistence is the caller's job, application execution is
nobody's job in this milestone. The stop is enforced twice: this module
never imports a repository, and every entry point calls
:func:`~jobs.records.enforce_source_mode` first, so an application action
wired in later fails closed here rather than reaching a live platform.

Two entry points, one shape of output:

* :func:`discover` — a source adapter (``JobSource``) answers a
  ``SearchQuery`` with a listing page.
* :func:`discover_listing` — the same, from listing HTML already in
  hand (a saved fixture, a capture). No adapter, no I/O.

Both return a :class:`DiscoveryResult`: the normalised jobs plus the
*typed* outcome — page kind, adapter status, and a reason when the page
was blocked, empty, or unparseable. A page that yields zero jobs is a
valid answer with a reason, not an exception; a blocked page is a typed
failure with its error code. Neither is ever silent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Sequence

from core.enums import (
    PageKind,
    RetrievalMethod,
    SourceAdapterStatus,
    SourceMode,
)
from core.hashing import utc_now
from core.logging_config import get_logger
from jobs.models import Job
from jobs.records import JobNormalizer, RetrievalInfo, enforce_source_mode
from jobs.source import JobSource, ListingResult, SearchQuery, parse_listing

__all__ = [
    "DISCOVERY_ERROR_CODES",
    "DiscoveryResult",
    "discover",
    "discover_listing",
]

log = get_logger(__name__)

#: Stable machine-readable acquisition failure codes. Typed, never prose,
#: so callers branch on them and tests assert on them without string
#: matching against human sentences.
DISCOVERY_ERROR_CODES = {
    "SOURCE_UNAVAILABLE",   # the source could not be reached at all
    "JOB_NOT_FOUND",        # a specific posting is gone or never existed
    "JD_NOT_FOUND",         # page fetched, description absent
    "PAGE_TIMEOUT",         # the page did not load in time
    "EXTRACTION_PARTIAL",   # something usable, but clearly incomplete
    "SOURCE_BLOCKED",       # CAPTCHA / login wall / anti-bot page
    "UNSUPPORTED_PAGE",     # recognised as not-a-listing/not-a-job page
    "INVALID_JOB",          # structurally unusable posting data
}


@dataclass(frozen=True)
class DiscoveryResult:
    """One discovery attempt, normalised and typed.

    Attributes:
        jobs: Normalised jobs with provenance attached, in document order.
        source: The source key the page was parsed under.
        page_url: Where the listing came from.
        page_kind: What the page turned out to be.
        status: Adapter status (``OK``/``PARTIAL``/``FAILED``/...).
        reason: Human-readable explanation when status is not ``OK``.
        error_code: One of :data:`DISCOVERY_ERROR_CODES` when the attempt
            failed, else ``None``.
        retrieval: The provenance of this attempt, attached to every job.
        links_seen: Links the parser examined (diagnostics).
        links_skipped: Links discarded as non-job links (diagnostics).
        next_url: Pagination pointer when the page had more results.
    """

    jobs: tuple[Job, ...]
    source: str
    page_url: str
    page_kind: PageKind
    status: SourceAdapterStatus
    reason: Optional[str] = None
    error_code: Optional[str] = None
    retrieval: RetrievalInfo = field(default_factory=RetrievalInfo)
    links_seen: int = 0
    links_skipped: int = 0
    next_url: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status.is_success

    @property
    def count(self) -> int:
        return len(self.jobs)

    @property
    def has_more(self) -> bool:
        return bool(self.next_url)

    def summary(self) -> dict[str, Any]:
        """JSON-safe one-liner for CLI output and structured logs."""
        return {
            "source": self.source,
            "page_url": self.page_url,
            "page_kind": self.page_kind.value,
            "status": self.status.value,
            "reason": self.reason,
            "error_code": self.error_code,
            "jobs": self.count,
            "links_seen": self.links_seen,
            "links_skipped": self.links_skipped,
            "has_more": self.has_more,
        }


def discover(
    source: JobSource,
    query: SearchQuery,
    *,
    mode: SourceMode = SourceMode.DISCOVERY_ONLY,
    now: Optional[datetime] = None,
) -> DiscoveryResult:
    """Run one read-only search against a source adapter.

    The adapter does the fetching; this function owns normalisation,
    provenance, and the typed outcome. Adapter exceptions are converted
    to a failed :class:`DiscoveryResult` (error code
    ``SOURCE_UNAVAILABLE``) rather than propagating raw — a source being
    down is an outcome discovery reports, not a crash.

    Raises:
        ApplicationBoundaryError: If ``mode`` does not permit discovery
            (fail closed before any adapter is called).
    """
    enforce_source_mode(mode, "DISCOVER")
    attempted_at = now or utc_now()
    try:
        listing = source.search(query)
    except Exception as exc:  # noqa: BLE001 - converted to a typed outcome
        log.warning(
            "source search failed",
            extra={"discovery": {"source": source.name, "error": type(exc).__name__}},
        )
        retrieval = RetrievalInfo(
            retrieved_at=attempted_at,
            method=RetrievalMethod.BROWSER_FETCH,
            status=SourceAdapterStatus.FAILED,
            source_url="",
            detail=type(exc).__name__,
        )
        return DiscoveryResult(
            jobs=(),
            source=source.name,
            page_url="",
            page_kind=PageKind.UNKNOWN,
            status=SourceAdapterStatus.FAILED,
            reason=f"source search failed: {exc}",
            error_code=_code_for_exception(exc),
            retrieval=retrieval,
        )
    return _from_listing(
        listing,
        retrieved_at=attempted_at,
        method=RetrievalMethod.BROWSER_FETCH,
    )


def discover_listing(
    html: str,
    *,
    source: str = "local",
    page_url: str = "",
    source_path: str = "",
    mode: SourceMode = SourceMode.DISCOVERY_ONLY,
    now: Optional[datetime] = None,
) -> DiscoveryResult:
    """Parse listing HTML already in hand — saved fixture, prior capture.

    No adapter, no I/O, no network. Byte-for-byte the same normalisation
    and provenance path as :func:`discover`, so a fixture-tested pipeline
    and a live one cannot diverge.

    Args:
        html: The page source.
        source: Source key recorded on every job.
        page_url: The listing's URL, when known. Preferred in provenance:
            it says which page this was.
        source_path: The file the bytes were read from, when local.
            Recorded when no URL is known, so a saved capture's origin is
            never left blank.
    """
    enforce_source_mode(mode, "DISCOVER")
    listing = parse_listing(html, source=source, page_url=page_url)
    return _from_listing(
        listing,
        retrieved_at=now or utc_now(),
        method=RetrievalMethod.SAVED_PAGE,
        source_path=source_path,
    )


def _from_listing(
    listing: ListingResult,
    *,
    retrieved_at: datetime,
    method: RetrievalMethod,
    source_path: str = "",
) -> DiscoveryResult:
    status = listing.status
    error_code: Optional[str] = None
    if listing.page_kind is PageKind.BLOCKED:
        error_code = "SOURCE_BLOCKED"
    elif listing.page_kind is PageKind.UNKNOWN and not listing.jobs:
        error_code = "UNSUPPORTED_PAGE"
    elif status is SourceAdapterStatus.PARTIAL:
        error_code = "EXTRACTION_PARTIAL"

    retrieval = RetrievalInfo(
        retrieved_at=retrieved_at,
        method=method,
        status=status,
        source_url=listing.page_url or source_path,
        detail=listing.reason,
    )
    # Listing stubs come out of the parser with identity already assigned;
    # attaching provenance is their path into the normalisation contract.
    jobs = tuple(
        JobNormalizer.attach_provenance(job, retrieval)
        for job in listing.jobs
    )
    log.info(
        "discovery completed",
        extra={
            "discovery": {
                "status": status.value,
                "page_kind": listing.page_kind.value,
                "jobs": len(jobs),
                "error_code": error_code,
            }
        },
    )
    return DiscoveryResult(
        jobs=jobs,
        source=listing.source,
        page_url=listing.page_url,
        page_kind=listing.page_kind,
        status=status,
        reason=listing.reason,
        error_code=error_code,
        retrieval=retrieval,
        links_seen=listing.links_seen,
        links_skipped=listing.links_skipped,
        next_url=listing.next_url,
    )


def _code_for_exception(exc: BaseException) -> str:
    """Map an adapter exception to a stable acquisition error code."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timed out" in text:
        return "PAGE_TIMEOUT"
    if "block" in text or "captcha" in text or "challenge" in text:
        return "SOURCE_BLOCKED"
    if "not found" in text or "404" in text:
        return "JOB_NOT_FOUND"
    if "unavailable" in text or "connection" in text or "refused" in text:
        return "SOURCE_UNAVAILABLE"
    return "SOURCE_UNAVAILABLE"
