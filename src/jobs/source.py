"""Where jobs come from, and how a listing page becomes job stubs.

The boundary between this module and ``automation/`` is the point of the
design:

* **Here** is everything that decides *what a job is* — recognising a results
  page, pulling cards and JSON-LD apart, normalising the fields, building
  ``Job`` stubs. Every function takes a string, so it is exercised against
  saved fixtures with no browser, no network and no credentials.
* **``automation/``** (outside ``src``) is everything that *fetches* HTML,
  which is the layer that needs a browser and therefore Selenium. It
  implements :class:`JobSource` and hands its pages to :func:`parse_listing`.

``src`` never imports ``automation``: the dependency points one way, so the
browser stack can be replaced, stubbed out or refused entirely without
touching the domain.

Parsing is deliberately tolerant rather than selector-exact. A listing page
from any source is recognised by the shape of its links (``/jobs/view/...``)
and by JSON-LD ``JobPosting`` blocks, so a markup refresh on one platform
degrades to fewer fields instead of an empty result set.
"""

from __future__ import annotations

import html as html_entities
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import (
    TYPE_CHECKING,
    Any,
    Iterable,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)
from urllib.parse import parse_qs, urljoin, urlparse

from pydantic import BaseModel, Field, field_validator

from core.enums import PageKind, SourceAdapterStatus
from core.hashing import parse_iso_datetime, sha256_text
from core.logging_config import get_logger
from jobs.deduplicator import canonicalize_url, extract_posting_id
from jobs.models import Job, JobStatus
from jobs.normalizer import normalize_text

if TYPE_CHECKING:  # pragma: no cover - type checking only, and importing it
    # at runtime would be a cycle: acquisition imports this module.
    from jobs.acquisition import JobPage

__all__ = [
    "JobSource",
    "ListingResult",
    "PageScan",
    "SearchQuery",
    "description_block",
    "detect_page_kind",
    "fields_from_posting",
    "html_to_text",
    "job_link_id",
    "json_ld_postings",
    "parse_listing",
    "scan_page",
]

log = get_logger(__name__)

#: A link that points at a posting, in any of the shapes sources use.
_JOB_HREF_RE = re.compile(r"/jobs/view/|\bcurrentJobId=", re.IGNORECASE)

#: Base used to make a relative posting link absolute when the caller could
#: not supply the page it came from.
_DEFAULT_BASE_URLS = {"linkedin": "https://www.linkedin.com"}

#: Marker phrases for a page that refused to show results. Checked against
#: visible text only — scripts are excluded while scanning, because a JS
#: bundle mentions "captcha" without the page being one.
_BLOCKED_MARKERS = (
    "captcha",
    "unusual traffic",
    "security check",
    "verify you are human",
    "verify you are a human",
    "are you a robot",
    "pardon our interruption",
    "please verify you are a human",
    "checking your browser",
    "attention required",
    "sign in to continue",
)

#: Marker phrases for a legitimate empty result set.
_EMPTY_MARKERS = (
    "no results",
    "0 results",
    "no jobs found",
    "no matching jobs",
    "couldn't find any jobs",
    "could not find any jobs",
    "did not match any jobs",
    "try adjusting your search",
)

#: Class-name fragments that mean "this element is a result card".
_CARD_CLASS_HINTS = (
    "jobs-search-results__list-item",
    "job-card",
    "result-card",
    "artdeco-base-card",
    "base-card",
    "job-search-card",
)

#: Class-name fragments that mean "this page lists results" even when empty.
_CHROME_CLASS_HINTS = (
    "jobs-search-results",
    "reusable-search",
    "jobs-unified-search-results",
    "job-results",
)

#: Class and id fragments that hold a job description on a posting page.
#: Ordered most specific first: a page that has ``description__text`` inside
#: ``content`` must give us the inner one, because the outer element is the
#: page rather than the role.
_DESCRIPTION_HINTS = (
    "description__text",
    "jobs-description",
    "job-details-jobs-unified-top-card__job-description",
    "jobs-box__html-description",
    "show-more-less-text",
    "job-description",
    "about-the-job",
    "about-the-role",
    "job-details",
    "description",
    "summary",
    "content",
)

#: Elements whose boundaries carry meaning inside a description: a heading
#: starts a section and a list item is one claim. Recorded as the description
#: is scanned, so a page captured from a description element — rather than
#: from structured data — still reads back as sections and items.
_STRUCTURE_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "li", "p"})

#: Visible text of a control that hides more of the description. Its presence
#: means the captured text is deliberately shorter than the page holds.
_COLLAPSE_CONTROL_TEXT = frozenset(
    {"show more", "see more", "more", "read more", "expand", "show full description"}
)
_COLLAPSE_CLASS_HINTS = ("show-more", "show more", "expand", "toggle", "collapse")

#: Elements whose text is the whole page rather than its content. A block at
#: least this large a share of the visible text is a wrapper, and choosing it
#: would hand the navigation and the footer to the requirement extractor.
_WRAPPER_SHARE_LIMIT = 0.95

#: Elements with no end tag. They must not be pushed onto the open-element
#: stack, or they would never be popped.
_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})

#: How much visible text to keep for page classification.
_BODY_SAMPLE_LIMIT = 8000

#: Segments whose class suggests the field they hold. First match wins, so
#: the more specific hint comes first.
_TITLE_CLASS_HINTS = ("search-card__title", "job-card__title", "card__title", "title")
_COMPANY_CLASS_HINTS = ("search-card__subtitle", "company", "employer", "subtitle")
_LOCATION_CLASS_HINTS = ("search-card__meta", "location", "workplace", "job-location")
_DATE_CLASS_HINTS = ("posted", "date", "age")

#: Anchor text that names a control rather than a job. A card whose only
#: readable text is one of these tells us where a posting is but not what it
#: is, and a stored job called "Easy Apply" would poison every later
#: comparison. Such a link is counted as skipped, not dropped silently.
_ACTION_LABELS = frozenset(
    {
        "apply",
        "apply now",
        "easy apply",
        "share",
        "save",
        "saved",
        "sign in",
        "see more",
        "learn more",
        "more",
        "view",
        "details",
    }
)


@dataclass(frozen=True)
class _RawLink:
    """An anchor that points at a posting, before any card context."""

    href: str
    text: str


@dataclass
class _Frame:
    """One open element while scanning."""

    tag: str
    attrs: dict[str, str]
    text: list[str] = field(default_factory=list)
    is_card: bool = False
    links: list[_RawLink] = field(default_factory=list)
    segments: list[tuple[str, str, str]] = field(default_factory=list)
    #: Index into the structure log at the moment this element opened. A
    #: structural element that closes over its children's entries replaces
    #: them, so ``<li><p>x</p> more</li>`` is read as one item rather than two.
    structure_start: int = -1


@dataclass(frozen=True)
class _Card:
    """A finished result card: its posting links and its labelled parts."""

    links: tuple[_RawLink, ...]
    segments: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class PageScan:
    """Everything the scanner saw in one page."""

    title: str
    body_sample: str
    json_ld: tuple[str, ...]
    cards: tuple[_Card, ...]
    loose_links: tuple[_RawLink, ...]
    next_href: Optional[str]
    has_listing_chrome: bool
    blocks: tuple[tuple[str, str], ...] = ()
    #: Headings, list items and paragraphs of the description, in document
    #: order: ``description_raw`` when a page carried no structured data.
    structure: tuple[tuple[str, str], ...] = ()
    collapse_controls: tuple[str, ...] = ()
    metas: tuple[tuple[str, str], ...] = ()
    #: Total visible characters on the page, uncapped. Used to tell a content
    #: block from the wrapper that contains the whole page.
    visible_length: int = 0


# ---------------------------------------------------------------------------
# Public value types
# ---------------------------------------------------------------------------
class SearchQuery(BaseModel):
    """One request to a job source.

    Deliberately platform-neutral: it says *what* to look for, never *how* to
    ask for it. URL construction belongs to the source that implements
    :class:`JobSource`.
    """

    keywords: str
    location: str = ""
    remote_only: bool = False
    easy_apply_only: bool = False
    results_per_page: int = Field(default=25, ge=1, le=100)
    page: int = Field(default=1, ge=1)
    source: str = "linkedin"

    @field_validator("keywords")
    @classmethod
    def _keywords_must_mean_something(cls, value: str) -> str:
        cleaned = normalize_text(value)
        if not cleaned:
            raise ValueError("keywords must not be blank")
        return cleaned

    @field_validator("source")
    @classmethod
    def _source_must_be_named(cls, value: str) -> str:
        cleaned = normalize_text(value).lower()
        if not cleaned:
            raise ValueError("source must not be blank")
        return cleaned

    @property
    def start_offset(self) -> int:
        """Result index this page starts at, for offset-style pagination."""
        return (self.page - 1) * self.results_per_page

    @classmethod
    def from_settings(
        cls,
        settings: Any,
        *,
        keyword: Optional[str] = None,
        location: Optional[str] = None,
        page: int = 1,
        source: str = "linkedin",
    ) -> "SearchQuery":
        """Build a query from :class:`core.settings.JobSearchSettings`.

        The parameter is typed loosely on purpose: discovery should not have
        to import the settings module to describe what it wants.
        """
        keywords = keyword or (settings.keywords[0] if settings.keywords else "")
        return cls(
            keywords=keywords,
            location=location or (settings.locations[0] if settings.locations else ""),
            remote_only=bool(getattr(settings, "remote_only", False)),
            easy_apply_only=bool(getattr(settings, "easy_apply_only", False)),
            results_per_page=int(getattr(settings, "results_per_page", 25)),
            page=page,
            source=source,
        )


@dataclass(frozen=True)
class ListingResult:
    """What one fetch of a listing page produced.

    A blocked page is an answer, not a crash: it is returned with
    ``page_kind = BLOCKED`` and an empty job list so the caller can stop and
    tell a human rather than retrying into the same wall.
    """

    source: str
    page_kind: PageKind
    jobs: tuple[Job, ...] = ()
    page_url: str = ""
    next_url: Optional[str] = None
    reason: Optional[str] = None
    links_seen: int = 0
    links_skipped: int = 0

    @property
    def status(self) -> SourceAdapterStatus:
        """Typed outcome of this attempt, for logging and the audit trail."""
        if self.page_kind is PageKind.BLOCKED:
            return SourceAdapterStatus.BLOCKED
        if self.page_kind is PageKind.UNKNOWN:
            return SourceAdapterStatus.FAILED
        if self.links_skipped and self.jobs:
            # Some links could not be read as jobs. That is a partial read,
            # and it is worth saying so rather than reporting plain success.
            return SourceAdapterStatus.PARTIAL
        return SourceAdapterStatus.OK

    @property
    def ok(self) -> bool:
        """Whether the page gave a usable answer (including "no jobs")."""
        return self.status in (SourceAdapterStatus.OK, SourceAdapterStatus.PARTIAL)

    @property
    def has_more(self) -> bool:
        return self.next_url is not None

    def job_urls(self) -> list[str]:
        """Absolute posting URLs, in the order they appeared."""
        return [job.url for job in self.jobs if job.url]


@runtime_checkable
class JobSource(Protocol):
    """What the assistant needs from a place jobs are listed.

    Two capabilities, because discovery without acquisition is a list of
    links: search finds postings, and ``fetch_job`` reads one.

    Implemented by ``automation`` (browser-backed) and by tests (fixtures).
    ``src`` only ever sees this shape, which is what keeps Selenium out of the
    domain layer.
    """

    name: str

    def search(self, query: SearchQuery) -> ListingResult:
        """Run one search and return what the listing page contained."""
        ...  # pragma: no cover - protocol declaration

    def fetch_job(self, url: str) -> "JobPage":
        """Read one posting page and report the description it carried."""
        ...  # pragma: no cover - protocol declaration


# ---------------------------------------------------------------------------
# HTML scanning
# ---------------------------------------------------------------------------
class _ListingScanner(HTMLParser):
    """Single pass over a listing page.

    Collects posting anchors, result cards with their labelled segments,
    JSON-LD blocks, the page title, a sample of visible text, and any explicit
    "next" link. Nesting is followed with a stack and repaired rather than
    trusted: real pages are not well-formed, and a parser that gives up on the
    first misplaced tag would return nothing at all.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []
        self.json_ld: list[str] = []
        self.cards: list[_Card] = []
        self.loose_links: list[_RawLink] = []
        self.blocks: list[tuple[str, str]] = []
        self.structure: list[tuple[str, str]] = []
        self.collapse_controls: list[str] = []
        self.metas: list[tuple[str, str]] = []
        self.next_href: Optional[str] = None
        self.has_listing_chrome = False
        self._body_len = 0
        self._visible_len = 0
        self._stack: list[_Frame] = []
        self._capture: Optional[str] = None
        self._capture_tag: Optional[str] = None

    # -- capture control ---------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attributes = {key: (value or "") for key, value in attrs}
        classes = attributes.get("class", "")

        if tag in _VOID_TAGS:
            # Void elements never get an end tag, so pushing a frame for one
            # would leave it open forever and swallow the text that follows.
            if tag == "meta":
                key = attributes.get("property") or attributes.get("name") or ""
                content = attributes.get("content") or ""
                if key and content:
                    self.metas.append((key, content))
            return

        if tag in ("script", "style"):
            if tag == "script" and "ld+json" in attributes.get("type", "").lower():
                self._capture, self._capture_tag = "jsonld", tag
            else:
                self._capture, self._capture_tag = "skip", tag
            self._stack.append(self._new_frame(tag, attributes))
            return

        if tag == "title":
            self._capture, self._capture_tag = "title", tag

        if tag == "a":
            self._remember_next(attributes)

        if any(hint in classes for hint in _CHROME_CLASS_HINTS):
            self.has_listing_chrome = True

        self._stack.append(
            self._new_frame(tag, attributes, is_card=_looks_like_card(classes))
        )

    def _new_frame(
        self, tag: str, attrs: dict[str, str], *, is_card: bool = False
    ) -> _Frame:
        frame = _Frame(tag=tag, attrs=attrs, is_card=is_card)
        frame.structure_start = len(self.structure)
        return frame

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        # A self-closing tag has no content to propagate, but may still be a
        # link worth recording.
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._capture_tag == tag:
            self._capture = None
            self._capture_tag = None

        index = next(
            (i for i in range(len(self._stack) - 1, -1, -1) if self._stack[i].tag == tag),
            None,
        )
        if index is None:
            return
        closing = self._stack[index:]
        del self._stack[index:]
        for frame in reversed(closing):
            self._close(frame)

    def handle_data(self, data: str) -> None:
        if self._capture == "jsonld":
            self.json_ld.append(data)
            return
        if self._capture == "skip":
            return
        if self._capture == "title":
            self.title_parts.append(data)
            return
        if not data:
            return
        if self._stack:
            # Whitespace-only runs are kept so that adjacent words do not
            # fuse into one; ``normalize_text`` collapses them at close.
            self._stack[-1].text.append(data)
        visible = data.strip()
        if visible:
            self._visible_len += len(visible)
            if self._body_len < _BODY_SAMPLE_LIMIT:
                self.body_parts.append(visible)
                self._body_len += len(visible)

    # -- closing -----------------------------------------------------------
    def _close(self, frame: _Frame) -> None:
        text = normalize_text("".join(frame.text))

        if self._stack:
            # Text belongs to the parent too, so a card ends up holding the
            # full text of everything inside it.
            self._stack[-1].text.extend(frame.text)

        if frame.tag == "a":
            href = frame.attrs.get("href", "")
            if _is_job_href(href):
                # Recorded even with no text: an anchor with an empty label is
                # still a posting link, and counting it is what lets a card
                # made only of such links be reported as skipped rather than
                # silently vanishing.
                link = _RawLink(href=href, text=text)
                self.loose_links.append(link)
                for ancestor in reversed(self._stack):
                    if ancestor.is_card:
                        ancestor.links.append(link)
                        break

        classes = frame.attrs.get("class", "")
        if text:
            hint = f"{classes} {frame.attrs.get('id', '')}".lower()
            if any(needle in hint for needle in _DESCRIPTION_HINTS):
                self.blocks.append((hint.strip(), text))
            if frame.tag in ("button", "a"):
                label = text.strip(" .\u2026").lower()
                if label in _COLLAPSE_CONTROL_TEXT or any(
                    needle in hint for needle in _COLLAPSE_CLASS_HINTS
                ):
                    self.collapse_controls.append(text)

        if text and frame.tag in _STRUCTURE_TAGS and self._in_description(frame):
            # Structural entries made while this element was open are its
            # children, and one list item is a truer unit than the paragraphs
            # inside it — so they are superseded rather than kept alongside.
            if frame.structure_start >= 0:
                del self.structure[frame.structure_start:]
            self.structure.append((frame.tag, text))

        for ancestor in reversed(self._stack):
            if ancestor.is_card:
                ancestor.segments.append((frame.tag, classes, text))
                break

        if frame.is_card and frame.links:
            self.cards.append(
                _Card(links=tuple(frame.links), segments=tuple(frame.segments))
            )

    def _in_description(self, frame: _Frame) -> bool:
        """Whether this element sits inside the element holding the description."""
        for candidate in (frame, *reversed(self._stack)):
            hint = (
                f"{candidate.attrs.get('class', '')} {candidate.attrs.get('id', '')}"
            ).lower()
            if any(needle in hint for needle in _DESCRIPTION_HINTS):
                return True
        return False

    def _remember_next(self, attrs: dict[str, str]) -> None:
        if self.next_href:
            return
        href = attrs.get("href", "")
        if not href:
            return
        rel = attrs.get("rel", "").lower().split()
        classes = attrs.get("class", "").lower()
        label = attrs.get("aria-label", "").lower()
        if "next" in rel or label in ("next", "go to next page"):
            self.next_href = href
        elif "pagination" in classes and "next" in classes:
            self.next_href = href


def _looks_like_card(classes: str) -> bool:
    return bool(classes) and any(hint in classes for hint in _CARD_CLASS_HINTS)


def _is_job_href(href: str) -> bool:
    return bool(href) and bool(_JOB_HREF_RE.search(href))


def scan_page(html: str) -> PageScan:
    scanner = _ListingScanner()
    scanner.feed(html)
    scanner.close()
    return PageScan(
        title=normalize_text("".join(scanner.title_parts)),
        body_sample=normalize_text(" ".join(scanner.body_parts))[:_BODY_SAMPLE_LIMIT],
        json_ld=tuple(scanner.json_ld),
        cards=tuple(scanner.cards),
        loose_links=tuple(scanner.loose_links),
        next_href=scanner.next_href,
        has_listing_chrome=scanner.has_listing_chrome,
        blocks=tuple(scanner.blocks),
        structure=tuple(scanner.structure),
        collapse_controls=tuple(scanner.collapse_controls),
        metas=tuple(scanner.metas),
        visible_length=scanner._visible_len,
    )


# ---------------------------------------------------------------------------
# Page classification
# ---------------------------------------------------------------------------
def detect_page_kind(
    *,
    title: str,
    body_sample: str,
    job_count: int,
    has_listing_chrome: bool = False,
) -> PageKind:
    """Decide what kind of page this is before trusting anything on it.

    Order matters: a challenge page can mention "no results" in its markup,
    and an empty result set never mentions CAPTCHA, so blocked is checked
    first and the empty markers only once no jobs were found.
    """
    haystack = f"{title}\n{body_sample}".lower()
    if any(marker in haystack for marker in _BLOCKED_MARKERS):
        return PageKind.BLOCKED
    if job_count:
        return PageKind.RESULTS
    if any(marker in haystack for marker in _EMPTY_MARKERS) or has_listing_chrome:
        return PageKind.EMPTY
    return PageKind.UNKNOWN


def job_link_id(href: str) -> str:
    """Posting id carried by a link, or an empty string.

    Sources put the id in the path (``/jobs/view/role-4001234567``) or in the
    query (``?currentJobId=4001234567``); both are accepted, and neither is
    invented when absent.
    """
    if not href:
        return ""
    found = extract_posting_id(href)
    if found:
        return found
    query = parse_qs(urlparse(href).query)
    for key in ("currentJobId", "currentjobid"):
        values = query.get(key)
        if values and values[0].isdigit():
            return values[0]
    return ""


def html_to_text(markup: str | None) -> str:
    """Visible text of an HTML fragment, whitespace folded.

    Used for JSON-LD descriptions and for the job description body alike:
    both arrive as markup and neither should reach the requirement extractor
    with its tags still attached.
    """
    if not markup:
        return ""
    without_tags = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.I | re.S)
    without_tags = re.sub(r"<[^>]+>", " ", without_tags)
    return normalize_text(html_entities.unescape(without_tags))


def description_block(scan: PageScan) -> Optional[str]:
    """Text of the element that most specifically holds the description.

    Hints are tried from most specific to least, so a page whose wrapper is a
    generic ``content`` div still yields the ``description__text`` inside it.

    A block accounting for nearly all the visible text is rejected as the
    wrapper itself. Choosing it would hand the navigation and the footer to
    the requirement extractor, which is worse than reporting that the
    description could not be isolated: wrong requirements are silent, a
    missing one is visible.
    """
    if not scan.blocks:
        return None
    total = scan.visible_length
    for hint in _DESCRIPTION_HINTS:
        for text in sorted(
            (text for label, text in scan.blocks if hint in label),
            key=len,
            reverse=True,
        ):
            if total and len(text) >= _WRAPPER_SHARE_LIMIT * total:
                continue
            return text
    return None


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
def parse_listing(
    html: str,
    *,
    source: str = "linkedin",
    page_url: str = "",
) -> ListingResult:
    """Turn one listing page into job stubs.

    JSON-LD is read first because it is authoritative about structure; cards
    are read second and fill in whatever JSON-LD omitted. The two are merged
    by identity, so a page carrying both does not produce duplicate jobs.

    Args:
        html: The page source, exactly as received.
        source: Source key stored on every job built from this page.
        page_url: The URL the page came from, used to resolve relative links
            and to describe where a job was found.

    Returns:
        A :class:`ListingResult` whose ``page_kind`` says what the page was.
        Never raises on malformed input: an unreadable page comes back as
        ``PageKind.UNKNOWN`` with a reason.
    """
    if not html or not html.strip():
        return ListingResult(
            source=source,
            page_kind=PageKind.UNKNOWN,
            page_url=page_url,
            reason="empty response",
        )

    try:
        scan = scan_page(html)
    except Exception as exc:  # noqa: BLE001 - a parser failure is data, not a crash
        log.warning(
            "listing page could not be scanned",
            extra={"discovery": {"source": source, "error": type(exc).__name__}},
        )
        return ListingResult(
            source=source,
            page_kind=PageKind.UNKNOWN,
            page_url=page_url,
            reason=f"scan failed: {type(exc).__name__}",
        )

    base_url = page_url or _DEFAULT_BASE_URLS.get(source, "")
    jobs, skipped = _collect_jobs(scan, source=source, page_url=page_url, base_url=base_url)

    kind = detect_page_kind(
        title=scan.title,
        body_sample=scan.body_sample,
        job_count=len(jobs),
        has_listing_chrome=scan.has_listing_chrome,
    )
    next_url = _resolve_next(scan.next_href, base_url)
    # Every posting anchor, whether or not it sat inside a card.
    link_count = len(scan.loose_links)

    reason: Optional[str] = None
    if kind is PageKind.BLOCKED:
        reason = "page asked for verification instead of results"
    elif kind is PageKind.UNKNOWN:
        reason = "page matched no known results or empty state"

    log.info(
        "listing parsed",
        extra={
            "discovery": {
                "source": source,
                "page_kind": kind.value,
                "jobs": len(jobs),
                "links_seen": link_count,
                "links_skipped": skipped,
            }
        },
    )
    return ListingResult(
        source=source,
        page_kind=kind,
        jobs=tuple(jobs),
        page_url=page_url,
        next_url=next_url,
        reason=reason,
        links_seen=link_count,
        links_skipped=skipped,
    )


def _resolve_next(href: Optional[str], base_url: str) -> Optional[str]:
    if not href:
        return None
    return urljoin(base_url, href) if base_url else href


def _collect_jobs(
    scan: PageScan,
    *,
    source: str,
    page_url: str,
    base_url: str,
) -> tuple[list[Job], int]:
    """Build jobs from JSON-LD and cards, merged by identity.

    Returns the jobs and the number of links that could not be read as a job.
    """
    collected: dict[str, Job] = {}
    order: list[str] = []
    skipped = 0

    def add(job: Optional[Job]) -> None:
        if job is None:
            return
        key = _merge_key(job)
        existing = collected.get(key)
        if existing is None:
            collected[key] = job
            order.append(key)
        else:
            collected[key] = _fill_gaps(existing, job)

    for payload in _json_ld_jobs(scan.json_ld, source=source, base_url=base_url, page_url=page_url):
        add(payload)

    seen_cards: set[str] = set()
    for card in scan.cards:
        job = _job_from_card(card, source=source, base_url=base_url, page_url=page_url)
        if job is None:
            skipped += 1
            continue
        card_key = job.canonical_url or job.url or job.title
        if card_key in seen_cards:
            continue
        seen_cards.add(card_key)
        add(job)

    for link in scan.loose_links:
        if any(link in card.links for card in scan.cards):
            continue  # already represented by its card
        job = _job_from_link(link, source=source, base_url=base_url, page_url=page_url)
        if job is None:
            skipped += 1
            continue
        add(job)

    return [collected[key] for key in order], skipped


def _merge_key(job: Job) -> str:
    """Within-page identity for one posting.

    The platform id is preferred over the full identity key here, because two
    descriptions of the same posting — one from JSON-LD, one from its card —
    can disagree about the company spelling while agreeing on the id. The
    merge exists to keep both halves, so the key must not split them.
    """
    if job.external_job_id:
        return f"id:{job.source}|{job.external_job_id}"
    if job.canonical_url:
        return f"url:{job.canonical_url}"
    if job.url:
        return f"url:{canonicalize_url(job.url) or job.url}"
    return f"text:{normalize_text(job.title).lower()}|{normalize_text(job.company).lower()}"


def _fill_gaps(existing: Job, incoming: Job) -> Job:
    """Keep the richer job, taking any field only one of them knows.

    JSON-LD arrives first, so this mostly means a card correcting a spelling
    or supplying a link the structured data lacked.
    """
    merged = existing.model_copy(deep=True)
    for name in (
        "external_job_id",
        "company",
        "title",
        "location",
        "url",
        "canonical_url",
        "workplace_type",
        "employment_type",
        "experience_level",
        "posted_at",
        "description_raw",
        "description_text",
        "description_hash",
    ):
        if not getattr(merged, name) and getattr(incoming, name):
            setattr(merged, name, getattr(incoming, name))
    if len(incoming.description_text or "") > len(merged.description_text or ""):
        merged.description_raw = incoming.description_raw or merged.description_raw
        merged.description_text = incoming.description_text
        merged.description_hash = incoming.description_hash
    # Keep anything only the other source knew: a structured date and a
    # relative "3 days ago" from the card are both worth having.
    for key, value in incoming.metadata.items():
        merged.metadata.setdefault(key, value)
    return merged


# ---------------------------------------------------------------------------
# Structured data
# ---------------------------------------------------------------------------
def _json_ld_jobs(
    payloads: Sequence[str],
    *,
    source: str,
    base_url: str,
    page_url: str,
) -> list[Job]:
    jobs: list[Job] = []
    for raw in payloads:
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in json_ld_postings(data):
            job = _job_from_posting(item, source=source, base_url=base_url, page_url=page_url)
            if job is not None:
                jobs.append(job)
    return jobs


def json_ld_postings(data: Any) -> list[dict[str, Any]]:
    """Flatten whatever JSON-LD shape arrived into candidate postings."""
    candidates: list[Any] = []
    if isinstance(data, list):
        candidates.extend(data)
    elif isinstance(data, dict):
        graph = data.get("@graph")
        candidates.extend(graph if isinstance(graph, list) else [data])
    else:
        return []

    postings: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        declared = item.get("@type", "")
        types = declared if isinstance(declared, list) else [declared]
        if any(str(t).lower() == "jobposting" for t in types):
            postings.append(item)
    return postings


def fields_from_posting(item: dict[str, Any], *, base_url: str = "") -> dict[str, Any]:
    """Every job field a JSON-LD ``JobPosting`` carries.

    Shared by discovery (which builds a stub from a listing page) and by
    acquisition (which enriches a stored job from the posting page), so the
    two can never disagree about what the structured data means.

    Returns an empty dict when the posting has no title: a job without a
    title is not a job, and the caller should treat the block as unreadable.
    """
    title = normalize_text(str(item.get("title") or ""))
    if not title:
        return {}

    url = normalize_text(str(item.get("url") or ""))
    absolute = urljoin(base_url, url) if url else ""
    description_raw = str(item.get("description") or "") or None
    description_text = html_to_text(description_raw) if description_raw else None
    salary_min, salary_max, salary_currency, salary_period = _salary_of(item)

    return {
        "external_job_id": _posting_id(item, absolute) or None,
        "company": normalize_text(str(_company_of(item) or "")),
        "title": title,
        "location": _location_of(item),
        "url": absolute or None,
        "canonical_url": canonicalize_url(absolute) or None,
        "workplace_type": _workplace_of(item),
        "employment_type": _employment_type_of(item),
        "posted_at": parse_iso_datetime(item.get("datePosted")),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "salary_period": salary_period,
        "description_raw": description_raw,
        "description_text": description_text,
        "description_hash": sha256_text(description_text) if description_text else None,
    }


def _job_from_posting(
    item: dict[str, Any],
    *,
    source: str,
    base_url: str,
    page_url: str,
) -> Optional[Job]:
    fields = fields_from_posting(item, base_url=base_url)
    if not fields:
        return None

    posted = normalize_text(str(item.get("datePosted") or ""))
    return Job(
        source=source,
        metadata={
            "page_url": page_url,
            "found_by": "json-ld",
            **({"posted_text": posted} if posted and parse_iso_datetime(posted) is None else {}),
        },
        **fields,
    )


def _salary_of(
    item: dict[str, Any],
) -> tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    """``(min, max, currency, period)`` from a JSON-LD ``baseSalary``.

    A range whose ends disagree is dropped rather than corrected: silently
    swapping an employer's contradictory numbers would present a salary they
    never advertised.
    """
    salary = item.get("baseSalary")
    if not isinstance(salary, dict):
        return None, None, None, None
    currency = normalize_text(str(salary.get("currency") or "")).upper() or None

    value = salary.get("value")
    if isinstance(value, (int, float)):
        amount = float(value)
        return amount, amount, currency, None
    if not isinstance(value, dict):
        return None, None, currency, None

    def _number(*keys: str) -> Optional[float]:
        for key in keys:
            raw = value.get(key)
            if isinstance(raw, (int, float)):
                return float(raw)
        return None

    low = _number("minValue", "value")
    high = _number("maxValue", "value")
    if low is not None and high is not None and low > high:
        return None, None, currency, None
    period = normalize_text(str(value.get("unitText") or "")).upper() or None
    return low, high, currency, period


def _employment_type_of(item: dict[str, Any]) -> Optional[str]:
    """``FULL_TIME`` becomes the label a person would write."""
    declared = item.get("employmentType")
    if isinstance(declared, list):
        declared = declared[0] if declared else None
    if not declared:
        return None
    text = normalize_text(str(declared)).replace("_", "-").lower()
    return text.title() if text else None


def _company_of(item: dict[str, Any]) -> str:
    organization = item.get("hiringOrganization")
    if isinstance(organization, dict):
        return str(organization.get("name") or "")
    if isinstance(organization, str):
        return organization
    return ""


def _location_of(item: dict[str, Any]) -> Optional[str]:
    if str(item.get("jobLocationType") or "").upper() == "TELECOMMUTE":
        return "Remote"
    location = item.get("jobLocation")
    if isinstance(location, list):
        location = location[0] if location else None
    if isinstance(location, str):
        return normalize_text(location) or None
    if not isinstance(location, dict):
        return None
    address = location.get("address", location)
    if isinstance(address, str):
        return normalize_text(address) or None
    if not isinstance(address, dict):
        return None
    parts = [
        str(address.get(key) or "")
        for key in ("addressLocality", "addressRegion", "addressCountry")
    ]
    joined = normalize_text(", ".join(part for part in parts if part))
    return joined or None


def _workplace_of(item: dict[str, Any]) -> Optional[str]:
    if str(item.get("jobLocationType") or "").upper() == "TELECOMMUTE":
        return "Remote"
    return None


def _posting_id(item: dict[str, Any], url: str) -> str:
    identifier = item.get("identifier")
    if isinstance(identifier, dict):
        value = str(identifier.get("value") or "")
        if value.isdigit():
            return value
    elif isinstance(identifier, str) and identifier.isdigit():
        return identifier
    return job_link_id(url)


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------
def _job_from_card(
    card: _Card,
    *,
    source: str,
    base_url: str,
    page_url: str,
) -> Optional[Job]:
    link = _best_link(card.links)
    if link is None:
        return None

    title = _segment_for(card, _TITLE_CLASS_HINTS) or link.text
    title = normalize_text(title)
    if not _title_is_usable(title):
        return None

    absolute = urljoin(base_url, link.href) if base_url else link.href
    company = normalize_text(_segment_for(card, _COMPANY_CLASS_HINTS) or "")
    location = normalize_text(_segment_for(card, _LOCATION_CLASS_HINTS) or "") or None
    posted_text = normalize_text(_segment_for(card, _DATE_CLASS_HINTS) or "")
    external_id = job_link_id(absolute)

    metadata: dict[str, Any] = {"page_url": page_url, "found_by": "listing-card"}
    if company:
        metadata["company_text"] = company
    if posted_text:
        metadata["posted_text"] = posted_text

    return Job(
        source=source,
        external_job_id=external_id or None,
        company=company,
        title=title,
        location=location,
        url=absolute or None,
        canonical_url=canonicalize_url(absolute) or None,
        posted_at=parse_iso_datetime(posted_text),
        metadata=metadata,
    )


def _job_from_link(
    link: _RawLink,
    *,
    source: str,
    base_url: str,
    page_url: str,
) -> Optional[Job]:
    """A posting link with no card around it.

    Such a page still tells us the title, the URL and usually the id; the
    company is simply unknown, which the identity rules tolerate by falling
    back to the URL rather than dropping the job.
    """
    title = normalize_text(link.text)
    if not _title_is_usable(title):
        return None
    absolute = urljoin(base_url, link.href) if base_url else link.href
    return Job(
        source=source,
        external_job_id=job_link_id(absolute) or None,
        title=title,
        url=absolute or None,
        canonical_url=canonicalize_url(absolute) or None,
        metadata={"page_url": page_url, "found_by": "listing-link"},
    )


def _best_link(links: Sequence[_RawLink]) -> Optional[_RawLink]:
    """The link whose text reads best as a job title."""
    usable = [link for link in links if normalize_text(link.text)]
    if not usable:
        return None
    # The longest text is the title anchor; a logo link's text is empty or a
    # company name repeated from elsewhere in the card.
    return max(usable, key=lambda link: len(normalize_text(link.text)))


def _title_is_usable(title: str) -> bool:
    """Does this text name a job, or a control on the page?"""
    cleaned = normalize_text(title).strip(" .·|,-\u2013\u2014").lower()
    return bool(cleaned) and cleaned not in _ACTION_LABELS


def _segment_for(card: _Card, hints: Iterable[str]) -> str:
    """Text of the first segment whose class names the field it holds."""
    lowered = tuple(hint.lower() for hint in hints)
    for hint in lowered:
        for _tag, classes, text in card.segments:
            if hint in classes.lower() and text:
                return text
    return ""
