"""Job deduplication.

The same job appears more than once: LinkedIn reposts it, a search returns it
on two pages, the crawler is restarted mid-run. This module decides when two
rows describe one posting, and every decision it makes is inspectable.

Identity is chosen from the most stable identifier the source actually
provides, in this order:

1. ``source + company + external_job_id`` — a platform id, disambiguated by
   employer so an id collision across sources can never merge two companies.
2. The **canonical** URL — two addresses for the same posting normalise to one.
3. A deterministic content identity — company, title and the description hash,
   used only when the source gives neither an id nor a URL.

Title plus company on its own is never the identity: ``"Software Engineer"``
exists at every company, and the same company runs several roles with the same
title. When no better identifier exists, the content hash is required to
participate, so the decision is at least anchored in what the posting said.

Each key records which tier produced it (``identity_tier``), so a duplicate
decision can be re-read from stored data instead of being re-derived from
memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from core.hashing import sha256_text
from jobs.models import Job, JobStatus
from jobs.normalizer import normalize_company, normalize_title, normalize_text
from jobs.records import PROVENANCE_KEY

__all__ = [
    "JobIdentity",
    "DeduplicationResult",
    "JobDeduplicator",
    "JOB_ID_RE",
    "IDENTITY_TIER_EXTERNAL_ID",
    "IDENTITY_TIER_CANONICAL_URL",
    "IDENTITY_TIER_CONTENT",
    "canonicalize_url",
    "extract_posting_id",
    "merge_discovery",
]

#: LinkedIn numeric job id in a posting URL.
JOB_ID_RE = re.compile(r"/jobs/view/(?:.*?-)?(\d{6,})")

IDENTITY_TIER_EXTERNAL_ID = "external_id"
IDENTITY_TIER_CANONICAL_URL = "canonical_url"
IDENTITY_TIER_CONTENT = "content"


@dataclass(frozen=True)
class JobIdentity:
    """The identity of a job posting.

    Attributes:
        company: Normalised company name.
        posting_id: The employer's own id, from the URL or platform.
        title: Normalised title. Informational only; not part of identity on
            its own.
        identity_key: Composite key used for grouping.
        tier: Which strategy produced ``identity_key``. One of
            ``external_id``, ``canonical_url`` or ``content``.
        source: The adapter that produced the job, empty when unset.
    """

    company: str
    posting_id: str
    title: str
    identity_key: str
    tier: str = IDENTITY_TIER_EXTERNAL_ID
    source: str = ""

    @classmethod
    def of(cls, job: "Job") -> "JobIdentity":
        """Build an identity from a job.

        The posting id is taken from ``external_job_id`` first and only then
        scraped out of the URL, because a parsed URL is a fallback and a
        platform field is a fact.
        """
        company = normalize_company(job.company)
        source = (job.source or "").strip().lower()
        posting_id = (
            (job.external_job_id or "").strip()
            or extract_posting_id(job.canonical_url or job.url)
        )
        title = _safe_title(job.title)

        if posting_id:
            # Tier 1. Empty segments are dropped so the key stays readable and
            # a job discovered without a source still groups with itself.
            parts = [part for part in (source, company, posting_id) if part]
            return cls(
                company=company,
                posting_id=posting_id,
                title=title,
                identity_key="|".join(parts),
                tier=IDENTITY_TIER_EXTERNAL_ID,
                source=source,
            )

        canonical = canonicalize_url(job.canonical_url or job.url)
        if canonical:
            return cls(
                company=company,
                posting_id="",
                title=title,
                identity_key=f"url|{canonical}",
                tier=IDENTITY_TIER_CANONICAL_URL,
                source=source,
            )

        # Tier 3. The content hash is what keeps this from being a
        # title-plus-company key: two postings only collapse here when they
        # also say the same thing.
        content = sha256_text(normalize_text(job.description_text))
        parts = [part for part in (source, company, title) if part]
        parts.append(content)
        return cls(
            company=company,
            posting_id="",
            title=title,
            identity_key="content|" + "|".join(parts),
            tier=IDENTITY_TIER_CONTENT,
            source=source,
        )

    def content_key(self, description: str | None = None) -> str:
        """Hash of identity plus description, for change detection.

        The description is an explicit argument because ``JobIdentity`` carries
        only the identity fields: hashing an empty string here would make the
        method blind to exactly the change it exists to detect.
        """
        return sha256_text(f"{self.identity_key}|{normalize_text(description)}")


def _safe_title(title: str | None) -> str:
    try:
        return normalize_title(title)
    except ValueError:
        return normalize_text(title).lower()


def extract_posting_id(url: str | None) -> str:
    """Pull the numeric posting id out of a job URL.

    Returns an empty string when no id is present rather than guessing.
    """
    if not url:
        return ""
    match = JOB_ID_RE.search(url)
    return match.group(1) if match else ""


#: Query parameters that identify the *visit*, not the posting.
_TRACKING_PARAMS = {
    "ref",
    "refId",
    "ref_id",
    "trackingId",
    "trackingid",
    "trk",
    "trkInfo",
    "position",
    "pageNum",
    "geoId",
    "keywords",
    "f_AL",
    "start",
    "currentJobId",
}
def canonicalize_url(url: str | None) -> str:
    """Reduce a posting URL to the form that identifies the posting.

    Deterministic and conservative: the host is lower-cased, a trailing slash
    is dropped, the fragment is removed, and known tracking parameters are
    dropped. Path segments and every other query parameter are preserved,
    because a job id can legitimately live in either.

    An empty or unparsable URL returns ``""`` rather than a partially
    normalised string, so callers fall through to the next identity tier.
    """
    if not url or not str(url).strip():
        return ""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    raw = str(url).strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""

    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")

    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in _TRACKING_PARAMS
    ]
    kept.sort()
    query = urlencode(kept, doseq=True)
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


@dataclass
class DeduplicationResult:
    """Outcome of deduplicating a batch.

    Attributes:
        unique: The first occurrence of each identity.
        duplicates: Later occurrences, mapped to the identity they collapsed
            into.
        counts: Useful summary numbers.
        decisions: One inspectable record per duplicate, stating which tier
            matched and which row was kept.
    """

    unique: list[Job] = field(default_factory=list)
    duplicates: dict[str, list[Job]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)

    @property
    def removed_count(self) -> int:
        return sum(len(v) for v in self.duplicates.values())


class JobDeduplicator:
    """Collapses repeated postings.

    Usage::

        result = JobDeduplicator().deduplicate(jobs)
        for job in result.unique:
            ...
    """

    def __init__(self, *, merge_metadata: bool = True) -> None:
        """
        Args:
            merge_metadata: Fold metadata from collapsed duplicates into the
                kept job, recording where each value came from.
        """
        self.merge_metadata = merge_metadata

    def deduplicate(self, jobs: Iterable[Job]) -> DeduplicationResult:
        """Group jobs by identity, keeping the first occurrence."""
        unique: list[Job] = []
        seen: dict[str, int] = {}
        duplicates: dict[str, list[Job]] = {}
        decisions: list[dict] = []

        for job in jobs:
            identity = JobIdentity.of(job)
            if identity.identity_key not in seen:
                seen[identity.identity_key] = len(unique)
                unique.append(job)
                continue

            duplicates.setdefault(identity.identity_key, []).append(job)
            target = unique[seen[identity.identity_key]]
            decisions.append(
                {
                    "identity_key": identity.identity_key,
                    "tier": identity.tier,
                    "kept": target.url or target.external_job_id or target.title,
                    "dropped": job.url or job.external_job_id or job.title,
                    "reason": "same identity as an earlier row in this batch",
                }
            )
            if self.merge_metadata:
                target.metadata.setdefault("duplicate_postings", []).append(
                    {
                        "url": job.url,
                        "title": job.title,
                        "status": job.status.value,
                        "description_hash": job.description_hash,
                        "identity_tier": identity.tier,
                    }
                )
                if not target.description_text and job.description_text:
                    target.description_text = job.description_text
                    target.description_hash = job.description_hash

        return DeduplicationResult(
            unique=unique,
            duplicates=duplicates,
            counts={
                "input": len(unique) + sum(len(v) for v in duplicates.values()),
                "unique": len(unique),
                "duplicates": sum(len(v) for v in duplicates.values()),
            },
            decisions=decisions,
        )

    def is_duplicate(self, candidate: Job, existing: Iterable[Job]) -> bool:
        """Whether ``candidate`` matches any of ``existing``."""
        target = JobIdentity.of(candidate).identity_key
        return any(JobIdentity.of(job).identity_key == target for job in existing)

    def group_by_company(self, jobs: Iterable[Job]) -> dict[str, list[Job]]:
        """Group jobs by normalised company name."""
        grouped: dict[str, list[Job]] = {}
        for job in jobs:
            grouped.setdefault(normalize_company(job.company), []).append(job)
        return grouped


#: Statuses from which a changed description sends a job back for re-acquisition.
_REACQUIRE_FROM = frozenset(
    {
        JobStatus.NORMALIZED,
        JobStatus.JD_PENDING,
        JobStatus.JD_EXTRACTED,
        JobStatus.JD_PARTIAL,
        JobStatus.JD_FAILED,
        JobStatus.ANALYSIS_PENDING,
        JobStatus.ANALYZED,
        JobStatus.MATCHED,
        JobStatus.REVIEW_REQUIRED,
    }
)


def _looks_truncated(original: str, candidate: str) -> bool:
    """Is ``candidate`` a partial capture of ``original``?

    Two different things shorten a description: an extractor that gave up
    halfway down the page, and an employer who genuinely rewrote the posting.
    They are told apart by shape — a truncated capture *starts with* what is
    already stored, a rewrite does not. Only then is the new text discarded in
    favour of the longer one.

    A candidate too short to judge is treated as partial: adopting a fragment
    would destroy the fuller description, while keeping it merely delays a
    re-extraction that the next complete capture would settle.
    """
    if len(candidate) >= len(original):
        return False
    head = candidate.strip()[:160]
    if len(head) < 40:
        return True
    return original.strip().startswith(head)


def merge_discovery(existing: Job, incoming: Job, *, now=None) -> Job:
    """Merge a re-discovered job into the stored one.

    Restart safety lives here. The rules are deliberately conservative:

    * ``first_seen_at`` never moves, ``last_seen_at`` always does, and
      ``seen_count`` increments — so "seen N times" is a fact, not a guess.
    * A blank field is filled; a populated field is never overwritten by a
      different populated value. Losing a description because a later crawl
      returned an empty one would destroy the more useful data.
    * A **changed** description is the exception: the new text wins, and the
      job is sent back to ``JD_PENDING`` so requirements are re-extracted
      instead of the old ones silently continuing to describe new content.
      A capture that merely stops early is not a change
      (:func:`_looks_truncated`) and never overwrites the fuller text.
    * Provenance travels with the data it describes: when this sighting
      supplied the text now stored, its origin replaces the older block;
      when the stored text stands, so does the origin that produced it.
    * The lifecycle status is otherwise left alone. State changes belong to
      the state machine, not to a merge.

    Args:
        existing: The stored job.
        incoming: The freshly discovered sighting.
        now: Clock override, so a caller can pin time. Defaults to the
            incoming sighting's own timestamps.

    Returns:
        A new :class:`Job`; neither input is mutated.
    """
    identity = JobIdentity.of(existing)
    merged = existing.model_copy(deep=True)

    # One more sighting of an already-stored job.
    merged.seen_count = existing.seen_count + 1
    merged.last_seen_at = now or incoming.last_seen_at or incoming.discovered_at
    if incoming.first_seen_at and (
        merged.first_seen_at is None or incoming.first_seen_at < merged.first_seen_at
    ):
        merged.first_seen_at = incoming.first_seen_at

    description_changed = False
    if incoming.description_text and incoming.description_text != existing.description_text:
        if not existing.description_text or not _looks_truncated(
            existing.description_text, incoming.description_text
        ):
            merged.description_raw = incoming.description_raw or merged.description_raw
            merged.description_text = incoming.description_text
            merged.description_hash = incoming.description_hash
            description_changed = True

    for name in (
        "source",
        "canonical_url",
        "url",
        "location",
        "workplace_type",
        "employment_type",
        "experience_level",
        "salary_min",
        "salary_max",
        "salary_currency",
        "salary_period",
        "posted_at",
        "external_job_id",
    ):
        if getattr(merged, name) in (None, "") and getattr(incoming, name) not in (None, ""):
            setattr(merged, name, getattr(incoming, name))

    if not merged.identity_key:
        merged.identity_key = identity.identity_key

    if incoming.url and incoming.url != existing.url:
        alternates = merged.metadata.setdefault("alternate_urls", [])
        if incoming.url not in alternates:
            alternates.append(incoming.url)

    incoming_provenance = incoming.metadata.get(PROVENANCE_KEY)
    if incoming_provenance and (
        description_changed or PROVENANCE_KEY not in existing.metadata
    ):
        merged.metadata[PROVENANCE_KEY] = incoming_provenance

    if description_changed and merged.status in _REACQUIRE_FROM:
        merged.status = JobStatus.JD_PENDING
        merged.metadata["description_changed"] = True

    return merged
