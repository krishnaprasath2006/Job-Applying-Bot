"""Assistant application container.

Wires configuration, logging, the database, and the services together, so that
command-line code and future phases construct the same object graph. Keeping
this in one place is what stops each call site from wiring its own slightly
different set of repositories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.errors import ConfigurationError
from core.paths import Paths, get_paths
from core.redaction import register_secret
from core.settings import AssistantSettings, load_settings
from database.connection import Database, connect
from database.repositories.documents import DocumentRepository, EvidenceRepository
from database.repositories.jobs import JobRepository
from database.repositories.model_runs import ModelRunRepository
from database.repositories.profiles import ProfileRepository
from database.repositories.resumes import ResumeRepository
from resumes.service import ResumeService
from candidate_profile.service import ProfileService
from safety.policies import SafetyPolicy
from assistant.job_service import JobService

__all__ = ["Assistant", "build_assistant"]


@dataclass
class Assistant:
    """The assembled assistant.

    Attributes:
        settings: Validated configuration.
        paths: Resolved filesystem locations.
        db: The SQLite database, already migrated.
        safety: The policy object every privileged action must pass through.
        profile_service / resume_service: The Phase 2 services.
        job_service: Milestone 3 job intelligence — analysis, matching,
            explanation, and the review queue.
    """

    settings: AssistantSettings
    paths: Paths
    db: Database
    safety: SafetyPolicy
    profile_service: ProfileService
    resume_service: ResumeService
    job_service: JobService
    _repositories: dict[str, Any] = field(default_factory=dict, repr=False)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Assistant":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- lazily constructed repositories -------------------------------------
    @property
    def evidence_repository(self) -> EvidenceRepository:
        return self._repo("evidence", EvidenceRepository)

    @property
    def document_repository(self) -> DocumentRepository:
        return self._repo("documents", DocumentRepository)

    @property
    def profile_repository(self) -> ProfileRepository:
        return self._repo("profiles", ProfileRepository)

    @property
    def resume_repository(self) -> ResumeRepository:
        return self._repo("resumes", ResumeRepository)

    @property
    def job_repository(self) -> JobRepository:
        return self._repo("jobs", JobRepository)

    @property
    def model_run_repository(self) -> ModelRunRepository:
        return self._repo("model_runs", ModelRunRepository)

    def _repo(self, key: str, factory: Any) -> Any:
        if key not in self._repositories:
            self._repositories[key] = factory(self.db)
        return self._repositories[key]

    def ai_provider(self) -> Any:
        """Build the configured AI provider.

        Returned as an interface so callers never import a concrete provider.
        """
        from ai.registry import build_provider

        return build_provider(self.settings.ai)

    def build_scorer(self, kind: str) -> Any:
        """Build a semantic scorer by name: ``none``, ``lexical``, ``embedding``.

        The seam is the one matching already holds - a
        :class:`ai.embeddings.SemanticScorer` handed in, never a scorer
        the matcher chose for itself. ``embedding`` reaches for the
        configured provider, so it fails here, loudly and typed, when no
        provider is configured, instead of deep inside a match.

        Raises:
            ConfigurationError: Unknown kind, or ``embedding`` without a
                usable provider.
        """
        if kind == "none":
            return None
        if kind == "lexical":
            from ai.embeddings import LexicalScorer

            return LexicalScorer()
        if kind == "embedding":
            from ai.embeddings import EmbeddingScorer

            try:
                provider = self.ai_provider()
            except ConfigurationError:
                raise
            except Exception as exc:  # provider build failures stay typed
                raise ConfigurationError(
                    "embedding scorer requested but the provider failed to build",
                    hint="check ai.provider / ai model settings",
                    cause=str(exc),
                ) from exc
            if not getattr(provider, "supports_embeddings", False):
                raise ConfigurationError(
                    "the configured provider does not support embeddings",
                    hint="use --scorer lexical, or configure an embedding provider",
                )
            return EmbeddingScorer(provider, on_run=self.job_service.record_model_run)
        raise ConfigurationError(
            f"unknown scorer {kind!r}",
            hint="choose none, lexical or embedding",
        )

    def status(self) -> dict[str, Any]:
        """A single dict summarising the whole system, for ``assistant status``."""
        return {
            "safety": self.safety.status(),
            "paths": self.paths.describe(),
            "database": {
                "path": str(self.db.path),
                "tables": self.db.table_names(),
                "profiles": self.profile_repository.count(),
                "resumes": self.resume_repository.count(),
                "evidence": self.evidence_repository.count(),
                "model_runs": self.model_run_repository.count(),
                "jobs": self.job_repository.count(),
                "queued_for_review": len(self.job_service.review_queue()),
                "open_reviews": self.job_service.open_review_count(),
            },
            "configuration": self.settings.redacted_summary(),
        }


def build_assistant(
    *,
    settings: Optional[AssistantSettings] = None,
    env_file: Optional[str] = None,
    database_path: Optional[Path] = None,
    validate_safety: bool = True,
) -> Assistant:
    """Construct the assistant.

    Args:
        settings: Pre-built settings. Loaded from the environment when absent.
        env_file: Explicit ``.env`` path.
        database_path: Override the configured database location. The override
            is applied *before* the services are built, so every repository
            ends up on the same database. Swapping ``Assistant.db`` afterwards
            would leave the already-constructed services writing to the
            original file, which is how a test run ends up in real data.
        validate_safety: Assert the Phase 2 safety invariants. On by default,
            and there is deliberately no flag to turn the assertions off.

    Returns:
        A wired :class:`Assistant` with the database already migrated.

    Raises:
        ConfigurationError: If configuration is invalid or a safety invariant
            is violated. This happens before any work starts, on purpose.
    """
    resolved = settings or load_settings(env_file=env_file)
    if validate_safety:
        resolved.safety.assert_phase2_invariants()

    for secret in resolved.secret_values():
        register_secret(secret)

    paths = get_paths(resolved.application.paths_root)
    paths.ensure_runtime_dirs()

    db = connect(
        database_path or resolved.database.path,
        enable_wal=resolved.database.enable_wal,
        busy_timeout_seconds=resolved.database.busy_timeout_seconds,
        enable_foreign_keys=resolved.database.enable_foreign_keys,
    )

    safety = SafetyPolicy(resolved.safety)
    profile_service = ProfileService(db, storage_path=paths.candidate_profile)
    return Assistant(
        settings=resolved,
        paths=paths,
        db=db,
        safety=safety,
        profile_service=profile_service,
        resume_service=ResumeService(db, paths=paths),
        job_service=JobService(
            db,
            profile_service=profile_service,
            candidate_id=resolved.application.candidate_id,
            source_mode=resolved.job_search.source_mode,
        ),
    )
