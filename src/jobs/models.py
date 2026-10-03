"""Job and requirement models.

Phase 2 settled the vocabulary; Milestone 3 makes it usable. Every job field
here tolerates absence, because a posting rarely exposes salary, workplace
type, or experience level, and a model that required them would reject real
data rather than record it as unknown.

Two rules carry most of the weight:

1. **A requirement is grounded or it is not.** A requirement read from the job
   description is ``JOB_DATA``; one a model produced from its own knowledge is
   ``AI_GENERAL`` and must never be scored against a candidate as though it
   came from the employer.
2. **Priority is tri-state.** ``REQUIRED``, ``PREFERRED`` and ``UNKNOWN`` are
   different answers. Collapsing ``UNKNOWN`` into ``PREFERRED`` would quietly
   inflate every match score, and collapsing it into ``REQUIRED`` would reject
   jobs for a requirement the employer never stated.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from core.enums import (
    AnalysisSource,
    EvidenceSourceType,
    ExtractionMethod,
    RequirementPriority,
)
from core.errors import InvalidStateTransitionError
from core.evidence import Evidence
from core.hashing import utc_now

__all__ = [
    "JobStatus",
    "JOB_TRANSITIONS",
    "RequirementKind",
    "Requirement",
    "Job",
]


class JobStatus(str, Enum):
    """Lifecycle of a tracked job.

    Extended in Milestone 3 with the acquisition and analysis states the
    job-intelligence pipeline needs. ``APPLYING`` and ``APPLIED`` are kept
    because they already existed and something may read them, but **no code in
    this milestone can reach them**: there is no path that starts an
    application.

    ``JD_*`` states describe job-description acquisition, which is deliberately
    separate from analysis: a job can hold a complete description and still be
    unanalysed, and a job with no description must not be analysed as though it
    had one.
    """

    DISCOVERED = "DISCOVERED"
    FETCHED = "FETCHED"
    NORMALIZED = "NORMALIZED"
    JD_PENDING = "JD_PENDING"
    JD_EXTRACTED = "JD_EXTRACTED"
    JD_PARTIAL = "JD_PARTIAL"
    JD_FAILED = "JD_FAILED"
    ANALYSIS_PENDING = "ANALYSIS_PENDING"
    ANALYZED = "ANALYZED"
    MATCHED = "MATCHED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    READY_FOR_APPLICATION = "READY_FOR_APPLICATION"
    APPLYING = "APPLYING"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        """No further transition is expected from this state."""
        return self in (
            JobStatus.APPLIED,
            JobStatus.REJECTED,
            JobStatus.SKIPPED,
            JobStatus.FAILED,
        )

    @property
    def has_description(self) -> bool:
        """Whether job-description acquisition has produced something usable."""
        return self in (JobStatus.JD_EXTRACTED, JobStatus.JD_PARTIAL)

    @property
    def is_analysable(self) -> bool:
        """Whether requirement extraction may run on this job."""
        return self.has_description or self is JobStatus.ANALYSIS_PENDING


#: Explicit adjacency matrix. A transition that is not listed here is invalid
#: and raises; there is no default "allow everything" path, because an
#: accidental jump to ``APPLIED`` is exactly the failure this table exists to
#: make impossible.
JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.DISCOVERED: frozenset(
        {JobStatus.FETCHED, JobStatus.NORMALIZED, JobStatus.SKIPPED, JobStatus.FAILED}
    ),
    JobStatus.FETCHED: frozenset(
        {JobStatus.NORMALIZED, JobStatus.SKIPPED, JobStatus.FAILED}
    ),
    JobStatus.NORMALIZED: frozenset(
        {JobStatus.JD_PENDING, JobStatus.SKIPPED, JobStatus.FAILED}
    ),
    JobStatus.JD_PENDING: frozenset(
        {
            JobStatus.JD_EXTRACTED,
            JobStatus.JD_PARTIAL,
            JobStatus.JD_FAILED,
            JobStatus.SKIPPED,
            JobStatus.FAILED,
        }
    ),
    JobStatus.JD_EXTRACTED: frozenset(
        {JobStatus.ANALYSIS_PENDING, JobStatus.JD_PENDING, JobStatus.SKIPPED, JobStatus.FAILED}
    ),
    JobStatus.JD_PARTIAL: frozenset(
        {
            JobStatus.ANALYSIS_PENDING,
            JobStatus.JD_PENDING,
            JobStatus.REVIEW_REQUIRED,
            JobStatus.SKIPPED,
            JobStatus.FAILED,
        }
    ),
    # A failed acquisition may be retried: the next attempt starts again from
    # JD_PENDING rather than pretending the description arrived.
    JobStatus.JD_FAILED: frozenset(
        {JobStatus.JD_PENDING, JobStatus.SKIPPED, JobStatus.FAILED}
    ),
    JobStatus.ANALYSIS_PENDING: frozenset(
        {
            JobStatus.ANALYZED,
            JobStatus.JD_PENDING,
            JobStatus.REVIEW_REQUIRED,
            JobStatus.SKIPPED,
            JobStatus.FAILED,
        }
    ),
    JobStatus.ANALYZED: frozenset(
        {
            JobStatus.MATCHED,
            JobStatus.JD_PENDING,
            JobStatus.REVIEW_REQUIRED,
            JobStatus.REJECTED,
            JobStatus.SKIPPED,
            JobStatus.FAILED,
        }
    ),
    JobStatus.MATCHED: frozenset(
        {
            JobStatus.REVIEW_REQUIRED,
            JobStatus.JD_PENDING,
            JobStatus.READY_FOR_APPLICATION,
            JobStatus.REJECTED,
            JobStatus.SKIPPED,
        }
    ),
    # A human can send a reviewed job back for re-analysis, which is how a
    # corrected requirement set re-enters the pipeline.
    JobStatus.REVIEW_REQUIRED: frozenset(
        {
            JobStatus.ANALYSIS_PENDING,
            JobStatus.JD_PENDING,
            JobStatus.MATCHED,
            JobStatus.READY_FOR_APPLICATION,
            JobStatus.REJECTED,
            JobStatus.SKIPPED,
            JobStatus.FAILED,
        }
    ),
    JobStatus.READY_FOR_APPLICATION: frozenset(
        {JobStatus.REJECTED, JobStatus.SKIPPED, JobStatus.REVIEW_REQUIRED}
    ),
    # Legacy application states, unreachable in this milestone.
    JobStatus.APPLYING: frozenset({JobStatus.APPLIED, JobStatus.FAILED}),
    JobStatus.APPLIED: frozenset(),
    JobStatus.REJECTED: frozenset(),
    JobStatus.SKIPPED: frozenset(),
    JobStatus.FAILED: frozenset(),
}


class RequirementKind(str, Enum):
    """What kind of thing a requirement is.

    A superset of the Phase 2 vocabulary: the original members are unchanged so
    existing readers keep working, and the added members cover the categories
    the requirement extractor actually distinguishes. ``category`` is an alias
    for ``kind`` for callers that prefer the milestone's terminology.
    """

    # Phase 2 members.
    SKILL = "SKILL"
    TOOL = "TOOL"
    CERTIFICATION = "CERTIFICATION"
    EDUCATION = "EDUCATION"
    EXPERIENCE = "EXPERIENCE"
    SOFT_SKILL = "SOFT_SKILL"
    LOCATION = "LOCATION"
    COMPENSATION = "COMPENSATION"
    AUTHORIZATION = "AUTHORIZATION"
    OTHER = "OTHER"
    # Milestone 3 members.
    TECHNOLOGY = "TECHNOLOGY"
    PROGRAMMING_LANGUAGE = "PROGRAMMING_LANGUAGE"
    FRAMEWORK = "FRAMEWORK"
    DATABASE = "DATABASE"
    CLOUD = "CLOUD"
    YEARS_OF_EXPERIENCE = "YEARS_OF_EXPERIENCE"
    WORKPLACE_TYPE = "WORKPLACE_TYPE"
    EMPLOYMENT_TYPE = "EMPLOYMENT_TYPE"
    SPONSORSHIP = "SPONSORSHIP"
    LANGUAGE = "LANGUAGE"
    DOMAIN = "DOMAIN"


class Requirement(BaseModel):
    """One thing a job asks for.

    Attributes:
        kind: What sort of requirement this is. Read it as ``category`` when
            following the milestone terminology.
        text: The requirement as stated by the job description.
        normalized: Lower-cased comparison form. Never inferred; if the job did
            not state a value, this is ``None``.
        priority: ``REQUIRED``, ``PREFERRED``, or ``UNKNOWN`` when the posting
            does not say. This, not ``required``, is the stored truth.
        ambiguous: The extractor could not decide how to read this line. An
            ambiguous requirement is never allowed to fail a candidate on its
            own; it routes to review.
        min_years: Minimum years requested, if stated.
        source_excerpt: The exact text this requirement was read from, kept
            verbatim so a human can check the classification.
        extraction_source: Whether a deterministic rule or a model produced
            this row.
        evidence: Where the requirement came from.
        analysis_source: ``JOB_DATA`` when read from the description,
            ``AI_GENERAL`` when produced from model knowledge.
        confidence: How confident the extractor was, in ``[0, 1]``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    kind: RequirementKind = RequirementKind.OTHER
    text: str
    normalized: Optional[str] = None
    priority: RequirementPriority = RequirementPriority.UNKNOWN
    ambiguous: bool = False
    min_years: Optional[float] = Field(default=None, ge=0.0, le=60.0)
    source_excerpt: Optional[str] = None
    extraction_source: ExtractionMethod = ExtractionMethod.DETERMINISTIC
    evidence: list[Evidence] = Field(default_factory=list)
    analysis_source: AnalysisSource = AnalysisSource.JOB_DATA
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="before")
    @classmethod
    def _accept_required_flag(cls, data: Any) -> Any:
        """Accept the Phase 2 ``required=`` keyword without keeping two truths.

        ``required`` used to be a field. Keeping it alongside ``priority``
        would allow ``required=True, priority=PREFERRED``, a contradiction that
        nothing would ever notice. The legacy keyword is therefore translated
        on the way in, and a genuine conflict between the two is rejected.
        """
        if not isinstance(data, dict) or "required" not in data:
            return data
        payload = dict(data)
        declared = payload.pop("required")
        if "priority" not in payload:
            payload["priority"] = (
                RequirementPriority.REQUIRED if declared else RequirementPriority.PREFERRED
            )
        else:
            priority = RequirementPriority(payload["priority"])
            if priority.is_mandatory != bool(declared):
                raise ValueError(
                    "required and priority disagree: "
                    f"required={declared!r} priority={priority.value!r}"
                )
        return payload

    @field_validator("text")
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("a requirement must have non-empty text")
        return cleaned

    def model_post_init(self, __context: Any) -> None:
        if self.normalized is None:
            self.normalized = self.text.lower().strip()

    # -- compatibility and terminology --------------------------------------
    @property
    def category(self) -> RequirementKind:
        """Milestone 3 name for :attr:`kind`."""
        return self.kind

    @property
    def normalized_name(self) -> Optional[str]:
        """Milestone 3 name for :attr:`normalized`."""
        return self.normalized

    @property
    def original_text(self) -> str:
        """Milestone 3 name for :attr:`text`."""
        return self.text

    @property
    def required(self) -> bool:
        """Whether the posting marked this mandatory.

        Derived from ``priority`` so there is exactly one stored truth. An
        ``UNKNOWN`` priority reports ``False``; callers that care must read
        ``priority`` rather than treating "not stated as required" as "not
        required".
        """
        return self.priority.is_mandatory

    @property
    def is_grounded(self) -> bool:
        """Only a requirement read from the job description may be scored."""
        return self.analysis_source is AnalysisSource.JOB_DATA

    @property
    def is_deterministic(self) -> bool:
        """Whether a rule, rather than a model, produced this row."""
        return self.extraction_source is ExtractionMethod.DETERMINISTIC

    def assert_grounded(self) -> None:
        """Raise unless the requirement came from the job description.

        Raises:
            ValueError: If the requirement is ungrounded.
        """
        if not self.is_grounded:
            raise ValueError(
                "requirement was not read from a job description and must not "
                f"be scored against a candidate (source={self.analysis_source.value})"
            )


class Job(BaseModel):
    """A job posting.

    Identity is ``source`` plus ``external_job_id`` (or, failing that, the
    canonical URL, or failing that a content identity) â€” never title plus
    company alone. ``url`` is the address the source handed over and is kept
    unmodified; ``canonical_url`` is the normalised comparison form.

    Every optional field may be ``None``. A posting without a salary, without
    a workplace type, or without a description is normal, and the pipeline
    records that as absence rather than inventing a value.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    source: str = ""
    external_job_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("external_job_id", "platform_job_id"),
    )
    company: str = ""
    title: str = ""
    location: Optional[str] = None
    canonical_url: Optional[str] = None
    url: Optional[str] = None
    workplace_type: Optional[str] = None
    employment_type: Optional[str] = None
    experience_level: Optional[str] = None
    salary_min: Optional[float] = Field(default=None, ge=0.0)
    salary_max: Optional[float] = Field(default=None, ge=0.0)
    salary_currency: Optional[str] = None
    salary_period: Optional[str] = None
    description_raw: Optional[str] = None
    description_text: Optional[str] = None
    description_hash: Optional[str] = None
    identity_key: Optional[str] = None
    status: JobStatus = JobStatus.DISCOVERED
    posted_at: Optional[datetime] = None
    discovered_at: datetime = Field(default_factory=utc_now)
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    seen_count: int = Field(default=1, ge=1)
    requirements: list[Requirement] = Field(default_factory=list)
    analysis_source: AnalysisSource = AnalysisSource.JOB_DATA
    metadata: dict[str, Any] = Field(default_factory=dict)

    # -- construction --------------------------------------------------------
    @model_validator(mode="after")
    def _dedupe_requirements(self) -> "Job":
        seen: set[tuple[str, str]] = set()
        unique: list[Requirement] = []
        for requirement in self.requirements:
            key = (requirement.kind.value, requirement.normalized or requirement.text.lower())
            if key in seen:
                continue
            seen.add(key)
            unique.append(requirement)
        self.requirements = unique
        return self

    @model_validator(mode="after")
    def _stamp_first_seen(self) -> "Job":
        """First and last seen default to the discovery moment.

        Leaving them ``None`` would make "never seen since" indistinguishable
        from "seen at discovery", which is what the restart-recovery queries
        rely on.
        """
        if self.first_seen_at is None:
            self.first_seen_at = self.discovered_at
        if self.last_seen_at is None:
            self.last_seen_at = self.discovered_at
        return self

    @model_validator(mode="after")
    def _validate_salary_range(self) -> "Job":
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            raise ValueError(
                f"salary_max ({self.salary_max}) is below salary_min ({self.salary_min})"
            )
        return self

    # -- terminology and compatibility --------------------------------------
    @property
    def internal_id(self) -> str:
        """The assistant's own identifier for this job (``id``)."""
        return self.id

    @property
    def platform_job_id(self) -> Optional[str]:
        """Phase 2 name for :attr:`external_job_id`."""
        return self.external_job_id

    @property
    def original_url(self) -> Optional[str]:
        """The URL exactly as the source provided it (``url``)."""
        return self.url

    @property
    def description_normalized(self) -> Optional[str]:
        """Whitespace-normalised description (``description_text``)."""
        return self.description_text

    @property
    def content_hash(self) -> Optional[str]:
        """Hash of the job description content, for change detection."""
        return self.description_hash

    @property
    def source_metadata(self) -> dict[str, Any]:
        """Milestone 3 name for :attr:`metadata`."""
        return self.metadata

    # -- behaviour -----------------------------------------------------------
    def transition_to(self, target: JobStatus, *, reason: str = "") -> "Job":
        """Return a copy in ``target``, or raise if the move is illegal.

        The transition table is explicit so that a bug cannot walk a job from
        ``DISCOVERED`` to ``APPLIED`` by chaining plausible-looking steps.

        Raises:
            InvalidStateTransitionError: If the transition is not permitted.
        """
        if not self.can_transition_to(target):
            allowed = sorted(s.value for s in JOB_TRANSITIONS.get(self.status, frozenset()))
            raise InvalidStateTransitionError(
                f"cannot move a job from {self.status.value} to {target.value}",
                from_state=self.status.value,
                to_state=target.value,
                allowed=allowed,
                reason=reason,
            )
        return self.model_copy(update={"status": target})

    def can_transition_to(self, target: JobStatus) -> bool:
        """Whether the transition table permits ``target`` from here."""
        if target is self.status:
            # A self-transition is a no-op, not a legal state change.
            return False
        return target in JOB_TRANSITIONS.get(self.status, frozenset())

    def allowed_transitions(self) -> list[JobStatus]:
        """Every state this job may move to next, in a stable order."""
        return sorted(JOB_TRANSITIONS.get(self.status, frozenset()), key=lambda s: s.value)

    def grounded_requirements(self) -> list[Requirement]:
        """Only requirements actually read from the job description."""
        return [r for r in self.requirements if r.is_grounded]

    def ungrounded_requirements(self) -> list[Requirement]:
        """Requirements that came from model knowledge, not the posting."""
        return [r for r in self.requirements if not r.is_grounded]

    def required_requirements(self) -> list[Requirement]:
        """Requirements the posting marked mandatory."""
        return [r for r in self.requirements if r.priority.is_mandatory]

    def identity_for_deduplication(self) -> str:
        """The identity key, computed if it has not been stored yet.

        Kept as a method rather than a property so callers cannot confuse the
        stored key with the computed one; the stored ``identity_key`` is what
        the database indexes.
        """
        if self.identity_key:
            return self.identity_key
        from jobs.deduplicator import JobIdentity

        return JobIdentity.of(self).identity_key

    def has_description(self) -> bool:
        return bool((self.description_text or "").strip())

    def describe_description(self) -> dict[str, Any]:
        """Length facts about the captured description, used by quality rules."""
        raw = self.description_raw or ""
        text = self.description_text or ""
        return {
            "has_raw": bool(raw.strip()),
            "has_text": bool(text.strip()),
            "raw_length": len(raw),
            "normalized_length": len(text),
            "content_hash": self.description_hash,
        }
