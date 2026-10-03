"""Domain enumerations shared across every layer.

These values are deliberately closed sets. A ``str`` free-for-all in the
database would let a typo such as ``"verified"`` silently become a fact
state nobody can reason about, so the vocabulary is fixed here and
validated by Pydantic at every boundary.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "FactStatus",
    "EvidenceSourceType",
    "AnalysisSource",
    "FieldType",
    "RiskLevel",
    "ResumeStatus",
    "ResumeFileType",
    "SectionType",
    "DocumentType",
    "ModelRunStatus",
    "ModelRunTask",
    "ValidationSeverity",
    "ValidationCode",
    "RequirementPriority",
    "ExtractionStatus",
    "ExtractionMethod",
    "RequirementEvaluation",
    "HardGateStatus",
    "MatchDecision",
    "ReviewReason",
    "SourceAdapterStatus",
    "PageKind",
    "SourceMode",
    "RetrievalMethod",
    "ReviewStatus",
    "ReviewSeverity",
    "DimensionStatus",
    "ResumeRelevanceDecision",
]


class _StrEnum(str, Enum):
    """Enum whose members compare equal to their string value.

    Keeping ``str`` in the bases means these serialise cleanly to JSON and
    to SQLite columns without a custom encoder.

    ``_missing_`` accepts case and separator variations of an existing
    member's value (``"verified"``, ``"VERIFIED"``, ``"in inferred"``), so
    hand-written JSON and CLI arguments are forgiving. It never invents a
    member: an unrecognised value still raises, which keeps every enum closed.
    """

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)

    @classmethod
    def _missing_(cls, value: object) -> "_StrEnum | None":
        if not isinstance(value, str):
            return None
        wanted = value.strip().replace("-", " ").replace("_", " ")
        wanted = "".join(ch for ch in wanted if not ch.isspace()).casefold()
        if not wanted:
            return None
        for member in cls:
            candidate = str(member.value).replace("-", " ").replace("_", " ")
            candidate = "".join(ch for ch in candidate if not ch.isspace()).casefold()
            if candidate == wanted:
                return member
        return None


class FactStatus(_StrEnum):
    """Truth state of a single candidate fact.

    ``VERIFIED``
        Confirmed by the candidate or by a deterministic source the
        candidate has accepted. Only this state may be used to fill a
        real application form.
    ``UNKNOWN``
        No value is known. This is the *correct* default and is not a
        defect. An empty profile is a valid profile.
    ``INFERRED``
        Produced by deterministic parsing (a resume parser guessing a
        date range) or proposed by AI. Never application-safe on its own
        and never promoted to ``VERIFIED`` without explicit human action.
    """

    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"
    INFERRED = "INFERRED"

    @property
    def is_application_safe(self) -> bool:
        """Only verified facts may be used in a real application form."""
        return self is FactStatus.VERIFIED


class EvidenceSourceType(_StrEnum):
    """Where a piece of information originally came from."""

    RESUME = "RESUME"
    PROFILE = "PROFILE"
    USER_INPUT = "USER_INPUT"
    JOB_DESCRIPTION = "JOB_DESCRIPTION"
    VERIFIED_ANSWER = "VERIFIED_ANSWER"
    SYSTEM = "SYSTEM"


class AnalysisSource(_StrEnum):
    """How an artefact was actually derived.

    Adopted from the reference research (``GPT-Jobhunter``), which records
    whether an analysis was grounded in retrieved data or in general model
    knowledge. Recording this is what stops a model from passing general
    knowledge off as a fact about the candidate or the job.
    """

    JOB_DATA = "JOB_DATA"
    CANDIDATE_DATA = "CANDIDATE_DATA"
    USER_PROVIDED = "USER_PROVIDED"
    AI_GENERAL = "AI_GENERAL"


class FieldType(_StrEnum):
    """Semantic type of a candidate fact, used for validation rules."""

    TEXT = "TEXT"
    EMAIL = "EMAIL"
    URL = "URL"
    PHONE = "PHONE"
    DATE = "DATE"
    DATE_RANGE = "DATE_RANGE"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    LIST = "LIST"


class RiskLevel(_StrEnum):
    """How dangerous it would be to answer a question wrongly.

    Used later to decide which answers need extra scrutiny before a real
    submission. A low-risk answer and a work-authorisation answer are not
    the same kind of risk.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ResumeStatus(_StrEnum):
    """Lifecycle of an ingested resume."""

    STORED = "STORED"
    PARSED = "PARSED"
    PARSE_FAILED = "PARSE_FAILED"
    DUPLICATE = "DUPLICATE"
    INVALID = "INVALID"


class ResumeFileType(_StrEnum):
    """Supported resume container formats."""

    PDF = "PDF"
    DOCX = "DOCX"
    TXT = "TXT"
    MD = "MD"
    UNKNOWN = "UNKNOWN"


class SectionType(_StrEnum):
    """Structured sections extracted from a resume."""

    SUMMARY = "SUMMARY"
    EDUCATION = "EDUCATION"
    EXPERIENCE = "EXPERIENCE"
    SKILLS = "SKILLS"
    PROJECTS = "PROJECTS"
    CERTIFICATIONS = "CERTIFICATIONS"
    ACHIEVEMENTS = "ACHIEVEMENTS"
    LINKS = "LINKS"
    CONTACT = "CONTACT"


class DocumentType(_StrEnum):
    """Anything the evidence model can point at."""

    RESUME = "RESUME"
    PROFILE = "PROFILE"
    JOB_DESCRIPTION = "JOB_DESCRIPTION"
    ANSWER = "ANSWER"
    OTHER = "OTHER"


class ModelRunStatus(_StrEnum):
    """Outcome of a single AI call."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class ModelRunTask(_StrEnum):
    """What an AI call was for.

    Recorded so later phases can audit which model produced which
    artefact, and so a prompt change can be compared like-for-like.
    """

    EXTRACT = "EXTRACT"
    CLASSIFY = "CLASSIFY"
    MATCH = "MATCH"
    GENERATE_TEXT = "GENERATE_TEXT"
    ANSWER_QUESTION = "ANSWER_QUESTION"
    SUMMARIZE = "SUMMARIZE"
    EMBED = "EMBED"


class ValidationSeverity(_StrEnum):
    """How much a validation finding matters."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class ValidationCode(_StrEnum):
    """Stable identifiers for every validation rule.

    Codes are part of the contract: tests assert on them and later phases
    may branch on them, so they must not be renamed casually.
    """

    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    UNKNOWN_VALUE_FOR_REQUIRED_FIELD = "UNKNOWN_VALUE_FOR_REQUIRED_FIELD"
    INVALID_TYPE = "INVALID_TYPE"
    UNSUPPORTED_STATUS = "UNSUPPORTED_STATUS"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    UNKNOWN_WITH_VALUE = "UNKNOWN_WITH_VALUE"
    VALUE_WITHOUT_EVIDENCE = "VALUE_WITHOUT_EVIDENCE"
    MALFORMED_EMAIL = "MALFORMED_EMAIL"
    INVALID_URL = "INVALID_URL"
    INVALID_PHONE = "INVALID_PHONE"
    INVALID_DATE = "INVALID_DATE"
    IMPOSSIBLE_DATE_RANGE = "IMPOSSIBLE_DATE_RANGE"
    DATE_IN_FUTURE = "DATE_IN_FUTURE"
    DUPLICATE_SKILL = "DUPLICATE_SKILL"
    INCONSISTENT_EXPERIENCE_DURATION = "INCONSISTENT_EXPERIENCE_DURATION"
    OVERLAPPING_JOBS = "OVERLAPPING_JOBS"
    FUTURE_EXPERIENCE = "FUTURE_EXPERIENCE"
    CONTRADICTORY_VALUES = "CONTRADICTORY_VALUES"
    INFERRED_MARKED_VERIFIED = "INFERRED_MARKED_VERIFIED"
    IMPLAUSIBLE_GPA = "IMPLAUSIBLE_GPA"
    IMPLAUSIBLE_YEARS_OF_EXPERIENCE = "IMPLAUSIBLE_YEARS_OF_EXPERIENCE"
    EMPTY_SECTION = "EMPTY_SECTION"


class RequirementPriority(_StrEnum):
    """Whether a posting needs something, wants it, or does not say.

    ``UNKNOWN`` is a real state, not a placeholder. A job description that
    lists a skill under no heading at all is genuinely unclear about whether
    the skill is mandatory, and recording it as ``PREFERRED`` would be a
    guess in the direction that quietly inflates every match score.
    """

    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    UNKNOWN = "UNKNOWN"

    @property
    def is_mandatory(self) -> bool:
        return self is RequirementPriority.REQUIRED


class ExtractionStatus(_StrEnum):
    """Outcome of acquiring a job description.

    ``COMPLETE``
        A description of plausible length was captured and normalised.
    ``PARTIAL``
        Something was captured, but deterministic rules say it is short,
        truncated, or missing a section the page clearly has.
    ``FAILED``
        Extraction was attempted and produced nothing usable.
    ``UNAVAILABLE``
        Extraction was not attempted: the source had no description to give
        (an expired posting, a stub listing). Distinct from ``FAILED``
        because retrying will not help without new input.
    """

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"

    @property
    def is_usable(self) -> bool:
        """Whether the captured text may be used for requirement extraction."""
        return self in (ExtractionStatus.COMPLETE, ExtractionStatus.PARTIAL)

    @property
    def is_failure(self) -> bool:
        return self in (ExtractionStatus.FAILED, ExtractionStatus.UNAVAILABLE)


class ExtractionMethod(_StrEnum):
    """How a value was obtained.

    Recorded on every captured artefact so a later reader can tell a
    deterministic parse from a model's interpretation without trusting a
    comment.
    """

    DETERMINISTIC = "DETERMINISTIC"
    AI = "AI"
    BROWSER = "BROWSER"
    HUMAN = "HUMAN"
    NONE = "NONE"


class RequirementEvaluation(_StrEnum):
    """How one job requirement stands against the candidate's evidence.

    The four-way split is the point: ``VERIFIED_MISMATCH`` means the evidence
    says no, ``UNKNOWN`` means there is no evidence either way, and the two
    must never be collapsed. ``DERIVED_*`` values are computed from other
    facts rather than read directly, so they are honest but weaker.
    """

    VERIFIED_MATCH = "VERIFIED_MATCH"
    VERIFIED_MISMATCH = "VERIFIED_MISMATCH"
    DERIVED_MATCH = "DERIVED_MATCH"
    DERIVED_MISMATCH = "DERIVED_MISMATCH"
    UNKNOWN = "UNKNOWN"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

    @property
    def is_match(self) -> bool:
        return self in (RequirementEvaluation.VERIFIED_MATCH, RequirementEvaluation.DERIVED_MATCH)

    @property
    def is_mismatch(self) -> bool:
        return self in (
            RequirementEvaluation.VERIFIED_MISMATCH,
            RequirementEvaluation.DERIVED_MISMATCH,
        )

    @property
    def is_uncertain(self) -> bool:
        return self in (RequirementEvaluation.UNKNOWN, RequirementEvaluation.REVIEW_REQUIRED)


class HardGateStatus(_StrEnum):
    """Result of the deterministic gate that runs before any scoring.

    A high semantic similarity cannot move this to ``PASS``: the gate only
    ever looks at evidence.
    """

    PASS = "PASS"
    HARD_MISMATCH = "HARD_MISMATCH"
    UNKNOWN = "UNKNOWN"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

    @property
    def blocks_match(self) -> bool:
        """True when this status must prevent a ``MATCH`` decision."""
        return self in (HardGateStatus.HARD_MISMATCH, HardGateStatus.UNKNOWN)


class MatchDecision(_StrEnum):
    """Top-level verdict for one job/candidate pair.

    Every value is derived from published rules, never chosen by a model.
    """

    MATCH = "MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    HARD_MISMATCH = "HARD_MISMATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

    @property
    def is_positive(self) -> bool:
        return self in (MatchDecision.MATCH, MatchDecision.PARTIAL_MATCH)

    @property
    def requires_human(self) -> bool:
        return self in (MatchDecision.REVIEW_REQUIRED, MatchDecision.INSUFFICIENT_EVIDENCE)


class ReviewReason(_StrEnum):
    """Why a job was routed to a human instead of being decided."""

    AMBIGUOUS_HARD_REQUIREMENT = "AMBIGUOUS_HARD_REQUIREMENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    EXTRACTION_CONFLICT = "EXTRACTION_CONFLICT"
    JD_EXTRACTION_INCOMPLETE = "JD_EXTRACTION_INCOMPLETE"
    ELIGIBILITY_UNKNOWN = "ELIGIBILITY_UNKNOWN"
    LOW_AI_CONFIDENCE = "LOW_AI_CONFIDENCE"
    STATE_REQUIRES_HUMAN = "STATE_REQUIRES_HUMAN"


class SourceAdapterStatus(_StrEnum):
    """Typed outcome of one acquisition attempt.

    Discovery is allowed to fail; it is not allowed to fail silently. Every
    attempt returns one of these, and a non-``OK`` status is logged with the
    error code that explains it.
    """

    OK = "OK"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"

    @property
    def is_success(self) -> bool:
        return self in (SourceAdapterStatus.OK, SourceAdapterStatus.PARTIAL)


class PageKind(_StrEnum):
    """What a fetched listing page turned out to be.

    Told apart before anything is parsed from it, because the right response
    to a CAPTCHA wall and the right response to an empty result set are not
    the same: one is a reason to stop and tell a human, the other is a normal
    answer.
    """

    RESULTS = "RESULTS"
    EMPTY = "EMPTY"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"

    @property
    def usable(self) -> bool:
        """True when the page gave a definite answer about the listing."""
        return self in (PageKind.RESULTS, PageKind.EMPTY)


class SourceMode(_StrEnum):
    """What a source adapter is allowed to do in this milestone.

    ``DISCOVERY_ONLY``
        Read listings and job pages, normalise them, persist them. The
        adapter may fetch, parse, and store — and nothing else. Discovery
        never transitions into application mode: the boundary is a typed
        error, not a convention, because a convention is only as good as
        the one call site that forgets it.

    Any future mode that would permit writes to a live platform must be
    added here explicitly, and the safety invariants must be revisited
    before it can be selected.
    """

    DISCOVERY_ONLY = "DISCOVERY_ONLY"

    @property
    def allows_application(self) -> bool:
        """No mode in this milestone permits application execution."""
        return False


class RetrievalMethod(_StrEnum):
    """How the bytes of a job page reached the system."""

    SAVED_PAGE = "SAVED_PAGE"          # a file handed to us locally
    LISTING_PARSE = "LISTING_PARSE"    # parsed out of a saved/live listing page
    BROWSER_FETCH = "BROWSER_FETCH"    # read-only fetch through automation/
    UNKNOWN = "UNKNOWN"


class ReviewStatus(_StrEnum):
    """Lifecycle of one human-review item.

    ``OPEN``
        Waiting for a human. The default; nothing is decided without one.
    ``RESOLVED``
        A human looked at it and closed it. Recording the closure, not the
        verdict — this enum never claims *what* the human decided.
    ``DISMISSED``
        A human closed it as not worth acting on. Kept distinct from
        ``RESOLVED`` so "handled" and "overridden" never blur together.
    """

    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ReviewSeverity(_StrEnum):
    """How much a review item matters, for queue ordering only.

    Severity orders the queue; it never suppresses an item. Every open item
    is shown regardless of severity.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DimensionStatus(_StrEnum):
    """Verdict of one match-report dimension.

    ``NOT_APPLICABLE``
        The posting says nothing this dimension could be measured against.
        Distinct from ``UNKNOWN``: no education requirement is not an
        unknown education requirement.
    """

    STRONG = "STRONG"
    PARTIAL = "PARTIAL"
    WEAK = "WEAK"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ResumeRelevanceDecision(_StrEnum):
    """Outcome of resume-to-job relevance."""

    RECOMMENDED = "RECOMMENDED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
