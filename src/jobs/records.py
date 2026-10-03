"""Source-neutral job records and their normalisation into stored jobs.

Everything a source adapter learns about a posting passes through here
before it becomes a :class:`~jobs.models.Job`. The record is the raw,
attributed snapshot — what the source said, when it said it, and how the
words reached us — while the normalised job is the single internal shape
the rest of the system understands. One normalisation path means a saved
file, a parsed listing, and a browser fetch cannot produce three different
job models for the same posting.

Provenance is not decoration. Every normalised job carries a
``provenance`` block in its metadata::

    source            where the posting came from ("linkedin", "local", ...)
    source_job_id     the platform's own identifier, when it exposed one
    source_url        the exact URL the bytes came from
    retrieved_at      when the bytes reached this system
    retrieval_method  how: saved page, listing parse, browser fetch
    retrieval_status  how the acquisition went, as a SourceAdapterStatus
    detail            optional human-readable note (never credentials)

That block is what lets a later reader reconstruct where a verdict came
from without trusting any single log line, and it is deliberately stored
as data rather than prose.

This module is pure: no I/O, no browser, no network, no repository.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.enums import (
    ExtractionStatus,
    RetrievalMethod,
    SourceAdapterStatus,
    SourceMode,
)
from core.errors import ApplicationBoundaryError
from core.hashing import utc_now
from jobs.models import Job, JobStatus

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from jobs.acquisition import JobPage

__all__ = [
    "PROVENANCE_KEY",
    "RetrievalInfo",
    "SourceJobRecord",
    "JobNormalizer",
    "enforce_source_mode",
]

#: Metadata key under which provenance is stored on a Job.
PROVENANCE_KEY = "provenance"


class RetrievalInfo(BaseModel):
    """Where, when, and how the bytes of one posting reached the system.

    Attributes:
        retrieved_at: UTC moment of acquisition.
        method: How the bytes arrived.
        status: How the acquisition went.
        source_url: The exact URL or path the bytes came from.
        detail: Optional note such as a typed error code. Must never
            contain credentials, cookies, or session state.
    """

    model_config = ConfigDict(extra="forbid")

    retrieved_at: datetime = Field(default_factory=utc_now)
    method: RetrievalMethod = RetrievalMethod.UNKNOWN
    status: SourceAdapterStatus = SourceAdapterStatus.OK
    source_url: str = ""
    detail: Optional[str] = None

    @model_validator(mode="after")
    def _no_credentials(self) -> "RetrievalInfo":
        """Refuse obvious secrets rather than persisting them.

        Provenance is stored forever; a URL with inline credentials or a
        cookie-looking detail string should never get that far.
        """
        lowered = f"{self.source_url} {self.detail or ''}".lower()
        for marker in ("password=", "pwd=", "sessionid=", "li_at=", "apikey="):
            if marker in lowered:
                raise ValueError(
                    "retrieval detail must not carry credentials or session data"
                )
        return self

    @classmethod
    def from_extraction(
        cls,
        *,
        extraction: "ExtractionStatus",
        method: RetrievalMethod,
        source_url: str = "",
        detail: Optional[str] = None,
        retrieved_at: Optional[datetime] = None,
    ) -> "RetrievalInfo":
        """Provenance for one capture, given its extraction verdict.

        The extraction outcome *is* the acquisition outcome: the bytes
        arrived, and what that arrival yielded is what the extractor
        judged. A capture that gave nothing usable is recorded as a failed
        retrieval, never as a quiet success with an empty description.
        """
        return cls(
            retrieved_at=retrieved_at or utc_now(),
            method=method,
            status=_RETRIEVAL_FOR_EXTRACTION.get(extraction, SourceAdapterStatus.FAILED),
            source_url=source_url,
            detail=detail,
        )

    @classmethod
    def from_page(cls, page: "JobPage", *, retrieved_at: Optional[datetime] = None) -> "RetrievalInfo":
        """Provenance for one acquired posting page."""
        return cls.from_extraction(
            extraction=page.status,
            method=RetrievalMethod.BROWSER_FETCH,
            source_url=page.page_url,
            detail=page.reason,
            retrieved_at=retrieved_at,
        )


#: Extraction verdict to acquisition status, so provenance answers "how did
#: this go" in one vocabulary. Both enums describe the same attempt: the
#: bytes were fetched, and the judgement of what they held is the result.
_RETRIEVAL_FOR_EXTRACTION: dict[ExtractionStatus, SourceAdapterStatus] = {
    ExtractionStatus.COMPLETE: SourceAdapterStatus.OK,
    ExtractionStatus.PARTIAL: SourceAdapterStatus.PARTIAL,
    ExtractionStatus.FAILED: SourceAdapterStatus.FAILED,
    ExtractionStatus.UNAVAILABLE: SourceAdapterStatus.UNAVAILABLE,
}


class SourceJobRecord(BaseModel):
    """One posting as a source reported it, before normalisation.

    Every field is optional except the source key, because sources differ
    in what they expose: a listing card has a title and a URL but no
    description; a fetched page has a description but may lack the
    company. The record holds what was actually seen; the normalizer
    decides what that means.
    """

    model_config = ConfigDict(extra="forbid")

    source: str
    source_job_id: Optional[str] = None
    url: str = ""
    canonical_url: Optional[str] = None
    title: str = ""
    company: str = ""
    location: Optional[str] = None
    workplace_type: Optional[str] = None
    employment_type: Optional[str] = None
    experience_level: Optional[str] = None
    posted_at: Optional[datetime] = None
    description_raw: str = ""
    description_text: str = ""
    retrieval: RetrievalInfo = Field(default_factory=RetrievalInfo)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_description(self) -> bool:
        return bool(self.description_text.strip())

    @property
    def is_usable(self) -> bool:
        """A record can become a job when it can be identified."""
        return bool(self.title.strip())


class JobNormalizer:
    """Turns :class:`SourceJobRecord` instances into stored-shape jobs.

    The normalizer is stateless and deterministic: the same record always
    produces the same job (modulo the discovery timestamp), which is what
    makes deduplication across sources possible.

    Args:
        mode: The source mode the pipeline runs in. Discovery-only mode
            is enforced here as well as at the service layer, so even a
            direct call cannot skip the boundary check.
    """

    def __init__(self, *, mode: SourceMode = SourceMode.DISCOVERY_ONLY) -> None:
        self.mode = mode

    def normalize(self, record: SourceJobRecord) -> Job:
        """Normalise one record into a :class:`Job`.

        Status starts at ``NORMALIZED`` when a description came with the
        record and at ``DISCOVERED`` otherwise — honest bookkeeping: the
        pipeline has the identity either way, but only one of them has
        text to analyse.

        Raises:
            ApplicationBoundaryError: If invoked while the pipeline is
                configured for a mode that forbids this action (currently
                no mode permits application execution, so this guards the
                boundary rather than gating a supported flow).
            ValueError: If the record cannot be identified (no title).
        """
        enforce_source_mode(self.mode, "NORMALIZE")
        if not record.is_usable:
            raise ValueError(
                f"source record from {record.source!r} has no title to normalise"
            )

        status = (
            JobStatus.NORMALIZED
            if record.has_description
            else JobStatus.DISCOVERED
        )
        provenance = self.provenance_for(record)
        metadata = dict(record.metadata)
        metadata[PROVENANCE_KEY] = provenance
        if record.has_description:
            metadata.setdefault(
                "extraction_status", "COMPLETE" if len(record.description_text) >= 400 else "PARTIAL"
            )

        return Job(
            source=record.source,
            external_job_id=record.source_job_id or None,
            title=record.title,
            company=record.company,
            location=record.location,
            url=record.url or None,
            canonical_url=record.canonical_url or record.url or None,
            workplace_type=record.workplace_type,
            employment_type=record.employment_type,
            experience_level=record.experience_level,
            posted_at=record.posted_at,
            description_raw=record.description_raw or record.description_text,
            description_text=record.description_text or None,
            status=status,
            metadata=metadata,
        )

    @staticmethod
    def provenance_for(record: SourceJobRecord) -> dict[str, Any]:
        """The provenance block for one record, JSON-safe and stable."""
        return {
            "source": record.source,
            "source_job_id": record.source_job_id,
            "source_url": record.retrieval.source_url or record.url or None,
            "retrieved_at": record.retrieval.retrieved_at.isoformat(),
            "retrieval_method": record.retrieval.method.value,
            "retrieval_status": record.retrieval.status.value,
            "detail": record.retrieval.detail,
        }

    @staticmethod
    def attach_provenance(job: Job, retrieval: RetrievalInfo) -> Job:
        """Merge a retrieval's provenance into an already-built job.

        Listings come out of the page parser as job stubs rather than as
        records, so this is their path to the same provenance contract.
        The job's own status and identity are left exactly as the parser
        set them — provenance says where bytes came from, never what the
        pipeline decided.
        """
        metadata = dict(job.metadata)
        metadata[PROVENANCE_KEY] = {
            "source": job.source or None,
            "source_job_id": job.external_job_id,
            "source_url": retrieval.source_url or job.canonical_url or job.url or None,
            "retrieved_at": retrieval.retrieved_at.isoformat(),
            "retrieval_method": retrieval.method.value,
            "retrieval_status": retrieval.status.value,
            "detail": retrieval.detail,
        }
        return job.model_copy(update={"metadata": metadata})


#: Actions the read-only discovery pipeline may perform.
_DISCOVERY_ACTIONS = frozenset(
    {"DISCOVER", "FETCH", "PARSE", "NORMALIZE", "PERSIST", "READ", "ANALYZE", "MATCH"}
)

#: Actions that touch a live platform's application flow. None are
#: permitted in any mode this milestone defines.
_APPLICATION_ACTIONS = frozenset(
    {
        "APPLY",
        "SUBMIT",
        "SUBMIT_APPLICATION",
        "FILL_FORM",
        "ACCEPT_DECLARATION",
        "UPLOAD_RESUME",
        "CLICK_SUBMIT",
    }
)


def enforce_source_mode(mode: SourceMode, action: str) -> None:
    """Fail closed when an action exceeds what ``mode`` permits.

    Two rules, both refusals by default:

    * application-execution actions are never permitted — no mode in this
      milestone allows them, so they raise before the action is even
      interpreted;
    * anything outside the read-only discovery allowlist raises too, so a
      typo or an unrecognised action cannot slip through as "probably
      fine".

    Raises:
        ApplicationBoundaryError: If the action is not permitted in this
            mode. The default is refusal.
    """
    key = action.upper()
    if key in _APPLICATION_ACTIONS or mode is not SourceMode.DISCOVERY_ONLY:
        raise ApplicationBoundaryError(
            f"action {action!r} is not permitted in source mode {mode.value}",
            mode=mode.value,
            action=action,
        )
    if key not in _DISCOVERY_ACTIONS:
        raise ApplicationBoundaryError(
            f"unrecognised source action {action!r}; only read-only "
            f"discovery actions are allowed in {mode.value}",
            mode=mode.value,
            action=action,
        )
