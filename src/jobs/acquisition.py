"""Capturing what a posting actually says.

Discovery proves a link exists; acquisition gets hold of the text behind it.
The two are separate because they fail differently: a listing page is usually
readable without an account, while a posting page may be collapsed behind a
control, gated behind a sign-in, already closed, or never have carried a
description at all. Each of those deserves a different answer from the one
before it, which is what :class:`core.enums.ExtractionStatus` encodes.

Three judgements happen here and nowhere else:

* :func:`parse_job_page` decides **what the page holds** — structured data, a
  description element, or neither.
* :func:`classify_description` decides **whether that is enough to reason
  about**, using thresholds from :class:`core.settings.ExtractionSettings`.
* :meth:`JobPage.apply_to` carries the result onto a stored job, filling
  blanks and never overwriting something already known.

No model is consulted. The description is a fact about a page; reading
requirements out of it is a later, separate step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from html import escape as escape_html
from typing import Any, Optional

from core.enums import ExtractionStatus, PageKind
from core.hashing import sha256_text
from core.logging_config import get_logger
from core.settings import ExtractionSettings
from jobs.models import Job
from jobs.normalizer import normalize_text
from jobs.source import (
    PageScan,
    description_block,
    detect_page_kind,
    fields_from_posting,
    json_ld_postings,
    scan_page,
)

__all__ = ["JobPage", "classify_description", "parse_job_page"]

log = get_logger(__name__)

#: A posting the source has already closed. Separate from a capture failure:
#: the description was readable, it simply is not worth anything now.
_EXPIRED_MARKERS = (
    "no longer accepting applications",
    "this job has expired",
    "job posting is no longer active",
    "this job is no longer active",
    "this position has been closed",
    "job has been filled",
    "posting has expired",
)

#: Fields a posting page can correct on a stored job. Description fields are
#: deliberately absent: they are governed by :meth:`JobPage.apply_to`, which
#: refuses to write an unusable capture.
_PAGE_FIELDS = (
    "external_job_id",
    "company",
    "title",
    "location",
    "workplace_type",
    "employment_type",
    "experience_level",
    "posted_at",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
)

#: Suffixes some sources append to a page title. Only ever applied to a
#: fallback title, never to structured data.
_TITLE_SUFFIXES = ("| linkedin", "- linkedin")


@dataclass(frozen=True)
class JobPage:
    """One capture of a posting page.

    Frozen because the result is a reading of a page at a moment in time:
    letting a caller edit it afterwards would make the recorded status a lie
    about the text next to it.
    """

    source: str
    page_url: str
    status: ExtractionStatus
    reason: Optional[str] = None
    description_text: str = ""
    description_raw: str = ""
    title: str = ""
    company: str = ""
    location: Optional[str] = None
    external_job_id: Optional[str] = None
    workplace_type: Optional[str] = None
    employment_type: Optional[str] = None
    experience_level: Optional[str] = None
    posted_at: Optional[datetime] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    salary_period: Optional[str] = None
    collapsed: bool = False

    @property
    def usable(self) -> bool:
        """Whether this capture may be used for requirement extraction."""
        return self.status.is_usable

    @property
    def content_hash(self) -> Optional[str]:
        """Hash of the captured text — the key an analysis is cached under."""
        if not self.description_text:
            return None
        return sha256_text(self.description_text)

    @property
    def description_length(self) -> int:
        return len(self.description_text)

    def apply_to(self, job: Job) -> Job:
        """A copy of ``job`` carrying what this page told us.

        Two rules, in order of importance:

        * A description is written only when this capture is usable. Keeping
          a forty-character stub would be worse than keeping none, because
          the next reader would believe the posting had been read.
        * Everything else fills a blank only. Discovery may already know the
          company, and neither source should lose a field to the other.

        The lifecycle is untouched: status belongs to the state machine, not
        to a parser.
        """
        updated = job.model_copy(deep=True)
        for name in _PAGE_FIELDS:
            if not getattr(updated, name) and getattr(self, name):
                setattr(updated, name, getattr(self, name))

        if self.usable and self.description_text:
            updated.description_raw = self.description_raw or updated.description_raw
            updated.description_text = self.description_text
            updated.description_hash = self.content_hash
        return updated


def classify_description(
    text: str,
    *,
    collapsed: bool = False,
    settings: Optional[ExtractionSettings] = None,
) -> tuple[ExtractionStatus, Optional[str]]:
    """Judge whether captured text is fit to reason about.

    The four outcomes are not a gradient. ``UNAVAILABLE`` means the source had
    nothing to give, ``FAILED`` means we tried and got something unusable,
    ``PARTIAL`` means a real but incomplete description, and ``COMPLETE``
    means the length rules were satisfied. A caller must be able to tell
    "retry later" from "give up" from "proceed carefully", so the reason says
    which threshold decided it.

    Args:
        text: The normalised description.
        collapsed: Whether the page held a control hiding more of it.
        settings: Thresholds; defaults to :class:`ExtractionSettings`.

    Returns:
        ``(status, reason)``. ``reason`` is ``None`` only for ``COMPLETE``.
    """
    rules = settings or ExtractionSettings()
    length = len(text.strip())

    if length == 0:
        return ExtractionStatus.UNAVAILABLE, "no description text was captured"
    if length < rules.partial_min_chars:
        return (
            ExtractionStatus.FAILED,
            f"description is {length} characters, below the "
            f"{rules.partial_min_chars} needed to be usable",
        )
    if collapsed:
        return (
            ExtractionStatus.PARTIAL,
            "the page hides part of the description behind a control",
        )
    if length < rules.complete_min_chars:
        return (
            ExtractionStatus.PARTIAL,
            f"description is {length} characters, below the "
            f"{rules.complete_min_chars} expected of a complete posting",
        )
    return ExtractionStatus.COMPLETE, None


def parse_job_page(
    html: str,
    *,
    source: str = "linkedin",
    page_url: str = "",
    settings: Optional[ExtractionSettings] = None,
) -> JobPage:
    """Read one posting page and judge the description it carried.

    Never raises on bad input: an unreadable page comes back with a status and
    a reason, because the caller's whole job is to record what happened.

    Args:
        html: Page source, exactly as received.
        source: Source key for the record.
        page_url: Where the page came from.
        settings: Classification thresholds.

    Returns:
        A :class:`JobPage`. ``status`` distinguishes a page that refused to
        show a description (``FAILED``, worth retrying later) from one that
        has none to give (``UNAVAILABLE``, not worth retrying).
    """
    rules = settings or ExtractionSettings()

    if not html or not html.strip():
        return JobPage(
            source=source,
            page_url=page_url,
            status=ExtractionStatus.FAILED,
            reason="empty response",
        )

    scan = scan_page(html)

    kind = detect_page_kind(
        title=scan.title,
        body_sample=scan.body_sample,
        job_count=0,
        has_listing_chrome=False,
    )
    if kind is PageKind.BLOCKED:
        return JobPage(
            source=source,
            page_url=page_url,
            status=ExtractionStatus.FAILED,
            reason="page asked for verification instead of the posting",
        )

    posting = _first_posting(scan)
    fields = fields_from_posting(posting, base_url=page_url) if posting else {}
    page_fields = _page_fields(fields)
    page_fields["title"] = fields.get("title") or _fallback_title(scan)

    if _is_expired(scan):
        return JobPage(
            source=source,
            page_url=page_url,
            status=ExtractionStatus.UNAVAILABLE,
            reason="posting is no longer open",
            **page_fields,
        )

    text, raw = _resolve_description(scan, fields)
    if not text:
        reason = (
            "description element covered the whole page"
            if scan.blocks
            else "page carried no description"
        )
        return JobPage(
            source=source,
            page_url=page_url,
            status=ExtractionStatus.UNAVAILABLE,
            reason=reason,
            **page_fields,
        )

    truncated = len(text) > rules.max_chars
    if truncated:
        text = text[: rules.max_chars]

    collapsed = bool(scan.collapse_controls)
    status, reason = classify_description(text, collapsed=collapsed, settings=rules)
    if truncated:
        reason = f"{reason}; truncated to {rules.max_chars} characters" if reason else (
            f"truncated to {rules.max_chars} characters"
        )
        if status is ExtractionStatus.COMPLETE:
            status = ExtractionStatus.PARTIAL

    log.info(
        "posting page read",
        extra={
            "extraction": {
                "source": source,
                "status": status.value,
                "length": len(text),
                "collapsed": collapsed,
            }
        },
    )
    return JobPage(
        source=source,
        page_url=page_url,
        status=status,
        reason=reason,
        description_text=text,
        description_raw=raw,
        collapsed=collapsed,
        **page_fields,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _first_posting(scan: PageScan) -> Optional[dict[str, Any]]:
    """The first JSON-LD posting on the page, if any."""
    for payload in scan.json_ld:
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            continue
        for posting in json_ld_postings(data):
            return posting
    return None


def _resolve_description(
    scan: PageScan, fields: dict[str, Any]
) -> tuple[str, str]:
    """``(text, raw)`` of the description, most authoritative source first.

    Structured data wins because it is written by the poster for machines and
    is therefore not subject to a "show more" control. A description element
    is next: real text, in the page, that a person would read.

    The element path rebuilds markup from the structure the scan recorded
    rather than handing over a flattened line, because the requirement
    extractor reads headings and list items — the difference between a
    "requirements" section and a "responsibilities" one is exactly what a
    single line of text would throw away.
    """
    if fields.get("description_text"):
        return fields["description_text"], fields.get("description_raw") or ""
    block = description_block(scan)
    if block:
        return block, _render_structure(scan) or block
    return "", ""


def _render_structure(scan: PageScan) -> str:
    """The description rebuilt as markup from its headings, items and paragraphs."""
    return "".join(
        f"<{tag}>{escape_html(text)}</{tag}>" for tag, text in scan.structure
    )


def _is_expired(scan: PageScan) -> bool:
    haystack = f"{scan.title} {scan.body_sample}".lower()
    return any(marker in haystack for marker in _EXPIRED_MARKERS)


def _fallback_title(scan: PageScan) -> str:
    """Page title when the posting carried no structured title.

    Used only to fill a blank: sources append their own name to a page title,
    and a stored job usually already has a better title from discovery.
    """
    metas = dict(scan.metas)
    for key in ("og:title", "twitter:title"):
        value = metas.get(key)
        if not value:
            continue
        cleaned = normalize_text(value)
        for suffix in _TITLE_SUFFIXES:
            if cleaned.lower().endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip(" |-")
        return cleaned
    return ""


def _page_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """The subset of structured fields a :class:`JobPage` can carry."""
    return {name: fields[name] for name in _PAGE_FIELDS if name in fields}
