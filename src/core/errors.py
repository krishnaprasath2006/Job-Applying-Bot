"""Domain exceptions.

Every layer raises a specific subclass of :class:`AssistantError` so callers
can branch on failure kind instead of parsing strings. There is intentionally
no broad ``except Exception: pass`` anywhere in this package: an important
failure must be observable, either by propagating or by being wrapped in one
of these with a cause attached.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AssistantError",
    "ConfigurationError",
    "ProfileValidationError",
    "ProfileNotFoundError",
    "ProfilePersistenceError",
    "ResumeParseError",
    "ResumeValidationError",
    "DuplicateResumeError",
    "ResumeNotFoundError",
    "DatabaseError",
    "MigrationError",
    "AIProviderError",
    "ProviderUnavailableError",
    "ProviderTimeoutError",
    "ModelNotFoundError",
    "MissingEvidenceError",
    "SafetyViolationError",
    "SubmissionBlockedError",
    "ImmutableFactError",
    "InvalidStateTransitionError",
    "ApplicationBoundaryError",
    "JobNotFoundError",
    "SourceAcquisitionError",
    "JobExtractionError",
    "RequirementExtractionError",
    "AIResponseValidationError",
    "UnsupportedClaimError",
]


class AssistantError(Exception):
    """Base class for every error this package raises.

    Args:
        message: Human-readable description, safe to log.
        details: Structured context for debugging. Must never contain
            secrets, passwords, cookies, or full resume text.
    """

    def __init__(self, message: str, **details: Any) -> None:
        self.message = message
        self.details: dict[str, Any] = details
        super().__init__(message)

    def __str__(self) -> str:
        if not self.details:
            return self.message
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.details.items()))
        return f"{self.message} ({rendered})"


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
class ConfigurationError(AssistantError):
    """Configuration is missing, malformed, or internally inconsistent."""


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------
class ProfileValidationError(AssistantError):
    """A profile failed validation.

    Note that a validator *reports* problems; it does not repair them. This
    exception exists to let a caller choose to reject a profile outright, not
    to imply that anything was silently fixed.
    """

    def __init__(self, message: str, issues: Any = None, **details: Any) -> None:
        super().__init__(message, **details)
        self.issues = list(issues or [])


class ProfileNotFoundError(AssistantError):
    """No candidate profile exists yet."""


class ProfilePersistenceError(AssistantError):
    """A profile could not be read from or written to storage."""


# --------------------------------------------------------------------------
# Resumes
# --------------------------------------------------------------------------
class ResumeParseError(AssistantError):
    """A resume could not be parsed into text."""


class ResumeValidationError(AssistantError):
    """A file is not an acceptable resume."""


class DuplicateResumeError(AssistantError):
    """This exact file content has already been ingested.

    Carries ``resume_id`` of the original so a caller can attach a new
    filename to the existing document instead of creating a copy.
    """

    def __init__(self, message: str, file_hash: str, resume_id: str | None = None) -> None:
        super().__init__(message, file_hash=file_hash, resume_id=resume_id)
        self.file_hash = file_hash
        self.resume_id = resume_id


class ResumeNotFoundError(AssistantError):
    """No resume with the given id or hash exists."""


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
class DatabaseError(AssistantError):
    """A database operation failed."""


class MigrationError(AssistantError):
    """A migration could not be applied."""


# --------------------------------------------------------------------------
# AI
# --------------------------------------------------------------------------
class AIProviderError(AssistantError):
    """Base class for AI provider failures."""


class ProviderUnavailableError(AIProviderError):
    """The provider is not reachable.

    This is what gets raised when Ollama is not running. The important part is
    what the provider does *not* do: it does not fall back to another
    provider, and it does not fabricate output. An unavailable model yields a
    clean error so the caller can fall back to ``UNKNOWN`` explicitly.
    """


class ProviderTimeoutError(AIProviderError):
    """The provider did not respond within the configured timeout."""


class ModelNotFoundError(AIProviderError):
    """The configured model name is not available on the provider."""


class AIResponseValidationError(AIProviderError):
    """A model's structured response failed schema validation.

    Raised for malformed JSON, unknown enum values, missing required
    fields, evidence excerpts that are absent or do not come from the
    stored JD, and requirement indexes that point nowhere. The caller
    falls back to deterministic analysis — the raw JD stays authoritative
    and a bad response never reaches the matcher.
    """


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------
class MissingEvidenceError(AssistantError):
    """A value was used without the evidence required to trust it.

    Raised when something tries to treat a fact as application-safe while it
    is ``UNKNOWN`` or ``INFERRED``, or while it carries no source at all.
    """


# --------------------------------------------------------------------------
# Safety
# --------------------------------------------------------------------------
class SafetyViolationError(AssistantError):
    """An operation was blocked by a safety policy."""


class SubmissionBlockedError(SafetyViolationError):
    """Real submission was attempted while safety settings forbade it.

    Phase 2 never submits anything, so this is reachable only from tests that
    exercise the guards deliberately.
    """


class ImmutableFactError(SafetyViolationError):
    """AI output tried to mutate verified candidate facts.

    Encodes the global domain rule: AI may suggest, extract, classify, draft,
    and analyse, but a change to a ``VERIFIED`` fact requires explicit human
    action or a trusted deterministic source.
    """


class ApplicationBoundaryError(SafetyViolationError):
    """Code on the discovery side of the line reached for application mode.

    Discovery is read-only by construction: the source pipeline normalises
    and stores jobs and stops there. If any call tries to cross into
    application execution — submitting, filling a form, accepting a
    declaration — this error is raised *before* the action is interpreted.
    Failing closed means the default is refusal, so a wiring mistake is a
    loud typed error rather than a quiet real-world side effect.
    """


# --------------------------------------------------------------------------
# Job intelligence
# --------------------------------------------------------------------------
class InvalidStateTransitionError(AssistantError):
    """A job was asked to move to a state its transition table forbids.

    Carries ``from_state``, ``to_state`` and the moves that *are* allowed, so
    the caller learns what the machine permits rather than only what it
    refused.
    """


class JobNotFoundError(AssistantError):
    """A referenced job id has no row."""


class JobExtractionError(AssistantError):
    """Job-description extraction produced nothing usable.

    Carries a stable ``error_code`` and the deterministic status the caller
    should record, so a missing description is never written down as a
    success.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "EXTRACTION_FAILED",
        **details: Any,
    ) -> None:
        self.error_code = error_code
        super().__init__(message, error_code=error_code, **details)


class SourceAcquisitionError(AssistantError):
    """A source adapter could not deliver the data it was asked for.

    Args:
        message: What failed.
        error_code: Stable machine-readable code such as ``TIMEOUT``,
            ``SELECTOR_NOT_FOUND`` or ``NETWORK_ERROR``. Never prose, so a
            caller can branch on it.
        **details: Structured context, redacted before logging.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "ACQUISITION_FAILED",
        **details: Any,
    ) -> None:
        self.error_code = error_code
        super().__init__(message, error_code=error_code, **details)


class RequirementExtractionError(AssistantError):
    """Structured requirement extraction could not be completed.

    Raised instead of returning an empty list, because "the posting asks for
    nothing" and "extraction broke" must not look alike to the matcher.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "REQUIREMENT_EXTRACTION_FAILED",
        **details: Any,
    ) -> None:
        self.error_code = error_code
        super().__init__(message, error_code=error_code, **details)


class UnsupportedClaimError(AssistantError):
    """AI output asserted something the candidate's evidence does not support.

    Encodes the hallucination guard: a model may interpret, classify, summarise
    and compare, but it may not originate a candidate fact. Output that tries
    is rejected rather than downgraded, so it can never reach a match result.
    """
