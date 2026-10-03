"""Typed configuration.

Every setting is declared once, here, with a type and a default. Nothing in
the assistant reads ``os.environ`` directly and no credential is ever given a
default value. The seven categories mirror the Phase 2 specification:
application, AI, database, browser, job search, safety, logging.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.enums import SourceMode
from core.errors import ConfigurationError

__all__ = [
    "ApplicationSettings",
    "AISettings",
    "DatabaseSettings",
    "BrowserSettings",
    "JobSearchSettings",
    "SafetySettings",
    "LoggingSettings",
    "ApiSettings",
    "AssistantSettings",
    "load_settings",
]

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f"}


class _Base(BaseModel):
    """Common config behaviour: reject unknown keys, coerce booleans loosely."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @field_validator("*", mode="before")
    @classmethod
    def _loose_bool(cls, value: Any) -> Any:
        """Accept ``1/0``, ``yes/no``, ``on/off`` from ``.env`` files."""
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in _TRUE:
                return True
            if lowered in _FALSE:
                return False
        return value


# --------------------------------------------------------------------------
# Safety - the most important block. Defaults are the safe ones.
# --------------------------------------------------------------------------
class SafetySettings(_Base):
    """Safety switches. Every default here is the conservative choice.

    These values are load-time only. There is deliberately no environment
    variable, CLI flag, or legacy variable that can raise them, and
    :meth:`assert_phase2_invariants` refuses to start if a Phase 2
    configuration would permit a real submission.
    """

    model_config = ConfigDict(extra="forbid")

    safe_mode: bool = Field(default=True, description="Master switch for safe operation.")
    dry_run: bool = Field(default=True, description="Never perform a real submission.")
    require_human_approval: bool = Field(
        default=True, description="A human must confirm before any submission."
    )

    allow_browser_navigation: bool = Field(default=False)
    allow_form_filling: bool = Field(default=False)
    allow_file_upload: bool = Field(default=False)
    allow_final_submission: bool = Field(default=False)

    max_applications_per_run: int = Field(default=5, ge=1, le=100)
    confirm_before_each_application: bool = Field(default=True)
    block_on_captcha: bool = Field(default=True)
    block_on_mfa: bool = Field(default=True)
    record_screenshots: bool = Field(default=False)

    @model_validator(mode="after")
    def _submission_needs_human_gates(self) -> "SafetySettings":
        """A submission may never be enabled without its human guard.

        The three conditions mirror what :class:`safety.policies.SafetyPolicy`
        checks at the moment of submission, so a configuration that validates
        here is one the policy could actually permit later. They previously
        required ``safe_mode`` to be *on*, which contradicted the policy's own
        requirement that it be off, making a permitted submission impossible to
        configure.
        """
        if self.allow_final_submission:
            if self.safe_mode or self.dry_run or not self.require_human_approval:
                raise ValueError(
                    "allow_final_submission cannot be true while safe_mode is on, "
                    "dry_run is on, or human approval is not required"
                )
        return self

    def assert_phase2_invariants(self) -> None:
        """Raise if this configuration would allow real submission.

        Phase 2 has no submission code at all. This guard exists so that the
        invariant is asserted on every startup rather than assumed, and so a
        future phase inherits a checked baseline instead of an unchecked one.

        Raises:
            ConfigurationError: If any Phase 2 safety invariant is violated.
        """
        violations: list[str] = []
        if not self.safe_mode:
            violations.append("safe_mode must be true in Phase 2")
        if not self.dry_run:
            violations.append("dry_run must be true in Phase 2")
        if not self.require_human_approval:
            violations.append("require_human_approval must be true in Phase 2")
        if self.allow_final_submission:
            violations.append("allow_final_submission must be false in Phase 2")
        if self.allow_form_filling:
            violations.append("allow_form_filling must be false in Phase 2")
        if violations:
            raise ConfigurationError(
                "unsafe safety configuration", violations="; ".join(violations)
            )

    @property
    def submission_possible(self) -> bool:
        return bool(
            self.allow_final_submission
            and not self.dry_run
            and not self.safe_mode is False
            and self.require_human_approval
        )


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------
class ApplicationSettings(_Base):
    """Assistant identity and file locations."""

    name: str = "AI Job Assistant"
    candidate_id: str = "primary"
    paths_root: Optional[Path] = None
    profile_dir: Optional[Path] = None
    resume_dir: Optional[Path] = None
    log_dir: Optional[Path] = None


# --------------------------------------------------------------------------
# AI
# --------------------------------------------------------------------------
class AISettings(_Base):
    """AI provider selection.

    ``provider`` and ``model`` are configuration, not code. Business logic
    never names a model, so switching from ``qwen2.5:7b`` to something else
    is an ``.env`` edit rather than a refactor.
    """

    provider: str = Field(default="ollama", description="Provider key from ai.registry.")
    model: str = Field(default="qwen2.5:7b", description="Provider-specific model name.")
    base_url: str = "http://localhost:11434"
    api_key: Optional[SecretStr] = Field(
        default=None,
        description="Only for non-local providers. Never log or serialise.",
    )
    embedding_model: Optional[str] = None
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    timeout_seconds: float = Field(default=60.0, gt=0.0, le=600.0)
    connect_timeout_seconds: float = Field(default=3.0, gt=0.0, le=120.0)
    max_retries: int = Field(default=0, ge=0, le=5, description="Phase 2 default is no retry.")
    json_mode: bool = True

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def has_api_key(self) -> bool:
        return self.api_key is not None and bool(self.api_key.get_secret_value())

    def secret_values(self) -> list[str]:
        """Values that must be registered with the log redactor."""
        values: list[str] = []
        if self.has_api_key:
            values.append(self.api_key.get_secret_value())  # type: ignore[union-attr]
        return values


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
class DatabaseSettings(_Base):
    """SQLite location and connection behaviour."""

    path: Optional[Path] = None
    echo: bool = False
    busy_timeout_seconds: float = Field(default=5.0, gt=0.0, le=60.0)
    enable_wal: bool = True
    enable_foreign_keys: bool = True


# --------------------------------------------------------------------------
# Browser
# --------------------------------------------------------------------------
class BrowserSettings(_Base):
    """Browser preferences for the future execution layer.

    Phase 2 never constructs a driver. These exist so the execution layer can
    be added later without inventing configuration.
    """

    browser: Literal["chrome", "edge", "firefox"] = "edge"
    headless: bool = False
    page_load_timeout_seconds: float = Field(default=45.0, gt=0.0)
    download_dir: Optional[Path] = None


# --------------------------------------------------------------------------
# Job search
# --------------------------------------------------------------------------
class JobSearchSettings(_Base):
    """Default search criteria.

    Mirrors the intent of the legacy ``config.py`` search terms without
    importing them, so the two cannot drift into disagreement silently.
    """

    keywords: list[str] = Field(default_factory=lambda: ["AI Engineer", "Machine Learning Engineer"])
    locations: list[str] = Field(default_factory=lambda: ["India"])
    remote_only: bool = False
    easy_apply_only: bool = True
    results_per_page: int = Field(default=10, ge=1, le=100)
    company_blacklist: list[str] = Field(default_factory=list)

    @field_validator("company_blacklist", mode="before")
    @classmethod
    def _clean_blacklist(cls, value: Any) -> Any:
        """Trim entries and refuse blanks.

        A blacklist entry of whitespace never matches a real company name, so
        it is a silent no-op. Rejecting it is louder and cheaper than shipping
        a rule that appears to work and does not.
        """
        if not isinstance(value, (list, tuple, set)):
            return value
        cleaned = []
        for item in value:
            text = str(item).strip()
            if not text:
                raise ValueError("company_blacklist entries must not be blank")
            cleaned.append(text)
        return cleaned
    years_of_experience_min: int = Field(default=0, ge=0, le=50)
    exclude_keywords: list[str] = Field(default_factory=list)
    source_mode: SourceMode = Field(
        default=SourceMode.DISCOVERY_ONLY,
        description=(
            "What source adapters may do. DISCOVERY_ONLY is the only mode "
            "this milestone defines: read, normalise, persist — never apply."
        ),
    )


# --------------------------------------------------------------------------
# Job description acquisition
# --------------------------------------------------------------------------
class ExtractionSettings(_Base):
    """How a captured job description is judged.

    The thresholds are configuration rather than constants because "short
    enough to be incomplete" is a claim about the source, and different
    platforms publish differently sized postings. Every classification records
    which threshold decided it, so a setting can be tuned without guessing
    what the previous value did.
    """

    complete_min_chars: int = Field(
        default=400,
        ge=50,
        le=100_000,
        description="At or above this many characters a description counts as complete.",
    )
    partial_min_chars: int = Field(
        default=150,
        ge=1,
        le=100_000,
        description="Below this a description is unusable rather than merely short.",
    )
    max_chars: int = Field(
        default=100_000,
        ge=1_000,
        le=2_000_000,
        description="Stored description is truncated here, to bound database rows.",
    )

    @field_validator("partial_min_chars")
    @classmethod
    def _partial_below_complete(cls, value: Any, info: Any) -> Any:
        """Refuse a configuration where "too short" is longer than "complete"."""
        complete = info.data.get("complete_min_chars")
        if complete is not None and value >= complete:
            raise ValueError("partial_min_chars must be below complete_min_chars")
        return value


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
class LoggingSettings(_Base):
    """Structured logging behaviour."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["json", "text", "silent"] = "json"
    to_file: bool = True
    max_bytes: int = Field(default=5_000_000, gt=0)
    backup_count: int = Field(default=3, ge=0)
    log_resume_bodies: bool = Field(
        default=False,
        description="Master switch for logging text extracted from resumes.",
    )


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
class ApiSettings(_Base):
    """Local-first HTTP surface settings for the FastAPI boundary.

    The bind address defaults to loopback. Exposing this service on a network
    interface is a deliberate act (``host="0.0.0.0"``), never an accident, and
    CORS origins are listed explicitly because a wildcard plus credentials
    would let any page drive the assistant.
    """

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
    )
    cors_allow_credentials: bool = False
    cors_allow_methods: list[str] = Field(default_factory=lambda: ["GET", "POST", "OPTIONS"])
    cors_allow_headers: list[str] = Field(default_factory=lambda: ["Content-Type", "Accept"])
    docs_enabled: bool = True

    @field_validator("cors_origins", "cors_allow_methods", "cors_allow_headers", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        """Accept a JSON list or a comma-separated list from the environment.

        ``pydantic-settings`` parses a complex field from a JSON document, which
        makes a plain ``ASSISTANT_API__CORS_ORIGINS=a,b`` silently fail. Both
        spellings are common in ``.env`` files, so both are accepted.
        """
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                return value
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    @field_validator("host")
    @classmethod
    def _require_host(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("api host must not be empty")
        return cleaned


# --------------------------------------------------------------------------
# Root
# --------------------------------------------------------------------------
class AssistantSettings(BaseSettings):
    """Aggregate settings object, populated from ``.env`` and the environment.

    Env prefix is ``ASSISTANT_`` for grouped categories, but flat variables
    used by the legacy bot (``DRY_RUN``, ``LINKEDIN_PASSWORD``) are honoured
    as aliases so both systems share one source of truth.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ASSISTANT_",
        # Double underscore separates a section from its field, so
        # ASSISTANT_SAFETY__DRY_RUN=false configures safety.dry_run. Without
        # this delimiter the nested namespace documented above silently does
        # nothing and every setting keeps its default.
        env_nested_delimiter="__",
        extra="ignore",
        populate_by_name=True,
        protected_namespaces=(),
    )

    application: ApplicationSettings = Field(default_factory=ApplicationSettings)
    ai: AISettings = Field(default_factory=AISettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    job_search: JobSearchSettings = Field(default_factory=JobSearchSettings)
    extraction: ExtractionSettings = Field(default_factory=ExtractionSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)

    # Legacy aliases. Present so the assistant and the old bot cannot
    # disagree about dry-run status. Each accepts both the namespaced form and
    # the historical bare name, because the legacy bot still reads the bare
    # name from .env and a single source of truth has to serve both.
    legacy_dry_run: bool = Field(
        default=True,
        validation_alias=AliasChoices("ASSISTANT_DRY_RUN", "DRY_RUN"),
        alias="DRY_RUN",
    )
    linkedin_username: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "ASSISTANT_LINKEDIN_USERNAME", "LINKEDIN_USERNAME", "LINKEDIN_EMAIL"
        ),
        alias="LINKEDIN_USERNAME",
    )
    linkedin_password: Optional[SecretStr] = Field(
        default=None,
        validation_alias=AliasChoices("ASSISTANT_LINKEDIN_PASSWORD", "LINKEDIN_PASSWORD"),
        alias="LINKEDIN_PASSWORD",
    )

    @property
    def has_linkedin_credentials(self) -> bool:
        return bool(self.linkedin_username and self.linkedin_password)

    def secret_values(self) -> list[str]:
        """Every secret that must be scrubbed from logs."""
        values = list(self.ai.secret_values())
        if self.linkedin_password is not None:
            secret = self.linkedin_password.get_secret_value()
            if secret:
                values.append(secret)
        return values

    def assert_consistent(self) -> None:
        """Check cross-settings consistency.

        Raises:
            ConfigurationError: If the legacy dry-run flag and the typed
                safety flag disagree, a Phase 2 invariant is violated, or
                the source mode would let discovery reach application
                execution.
        """
        if self.legacy_dry_run != self.safety.dry_run:
            raise ConfigurationError(
                "dry_run mismatch between legacy config and assistant safety settings",
                legacy_dry_run=self.legacy_dry_run,
                assistant_dry_run=self.safety.dry_run,
                hint="set DRY_RUN=true in .env and ASSISTANT_SAFETY__DRY_RUN=true",
            )
        self.safety.assert_phase2_invariants()
        if self.job_search.source_mode.allows_application:
            # Nothing defines such a mode today; the check exists so a
            # future mode cannot be enabled by editing one field while
            # the safety invariants still claim submission is off.
            raise ConfigurationError(
                "source mode permits application execution, which this "
                "milestone forbids",
                source_mode=self.job_search.source_mode.value,
            )

    def resolve_paths(self):
        """Fill in any unset path from :class:`core.paths.Paths`."""
        from core.paths import get_paths

        paths = get_paths()
        if self.application.paths_root is None:
            self.application.paths_root = paths.root
        if self.database.path is None:
            self.database.path = paths.db
        if self.application.resume_dir is None:
            self.application.resume_dir = paths.resume_dir
        if self.application.log_dir is None:
            self.application.log_dir = paths.logs
        return paths

    def redacted_summary(self) -> dict[str, Any]:
        """A loggable summary.

        Secrets are reported only as present/absent. This is the only
        configuration view intended to be printed or logged.
        """
        return {
            "application": {"name": self.application.name, "candidate_id": self.application.candidate_id},
            "ai": {
                "provider": self.ai.provider,
                "model": self.ai.model,
                "base_url": self.ai.base_url,
                "api_key_present": self.ai.has_api_key,
            },
            "database": {"path": str(self.database.path), "echo": self.database.echo},
            "browser": {"browser": self.browser.browser, "headless": self.browser.headless},
            "job_search": {
                "keywords": self.job_search.keywords,
                "locations": self.job_search.locations,
                "blacklist_count": len(self.job_search.company_blacklist),
            },
            "safety": {
                "safe_mode": self.safety.safe_mode,
                "dry_run": self.safety.dry_run,
                "require_human_approval": self.safety.require_human_approval,
                "allow_browser_navigation": self.safety.allow_browser_navigation,
                "allow_form_filling": self.safety.allow_form_filling,
                "allow_file_upload": self.safety.allow_file_upload,
                "allow_final_submission": self.safety.allow_final_submission,
            },
            "logging": {"level": self.logging.level, "format": self.logging.format},
            "api": {
                "host": self.api.host,
                "port": self.api.port,
                "cors_origins": list(self.api.cors_origins),
                "cors_allow_credentials": self.api.cors_allow_credentials,
                "docs_enabled": self.api.docs_enabled,
            },
            "credentials": {
                "linkedin_username_present": bool(self.linkedin_username),
                "linkedin_password_present": bool(
                    self.linkedin_password and self.linkedin_password.get_secret_value()
                ),
            },
        }


def load_settings(
    *,
    env_file: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
    validate: bool = True,
) -> AssistantSettings:
    """Build :class:`AssistantSettings`.

    Args:
        env_file: Explicit ``.env`` path. Defaults to ``.env`` in the working
            directory.
        overrides: Deep-merged overrides, applied last.
        validate: Run :meth:`AssistantSettings.assert_consistent` and resolve
            paths when true.

    Returns:
        Validated settings.

    Raises:
        ConfigurationError: If validation fails or a safety invariant is
            violated.
    """
    if env_file is not None:
        AssistantSettings.model_config["env_file"] = str(env_file)

    try:
        settings = AssistantSettings(**(overrides or {}))
    except ConfigurationError:
        raise
    except Exception as exc:  # pydantic ValidationError and friends
        raise ConfigurationError("could not load configuration", cause=str(exc)) from exc

    settings.resolve_paths()
    if validate:
        settings.assert_consistent()
    return settings
