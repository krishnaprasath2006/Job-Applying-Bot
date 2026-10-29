"""FastAPI sidecar serve lifecycle — Phase 2.

Provides the ``/api/ready`` readiness gate and sidecar lifecycle hooks that
the Tauri desktop shell uses to start, monitor, and shut down the local
FastAPI sidecar process.

Key responsibilities:
- /api/ready  — checks SQLite readability, migration status, and safety
  invariants. Returns 200 OK when all checks pass, 503 otherwise.
- /api/start  — tentative hook; the actual sidecar start is managed by the
  Tauri Rust/Node sidecar lifecycle (prepare-dev-sidecar.mjs).
- /api/shutdown — graceful shutdown hook; the Tauri sidecar process forwards
  a shutdown JSON command to the FastAPI process's stdin.
- Safety invariant re-check on every readiness probe, so a configuration
  edit after startup is caught rather than on the first privileged call.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from api.dependencies import AssistantDep
from api.schemas import (
    ApiStatusReport,
    AiStatusReport,
    DatabaseReport,
    HealthReport,
    ReadyReport,
    SafetyReport,
)
from api.version import SERVICE_NAME, SERVICE_VERSION
from ai.registry import available_providers
from core.logging_config import get_logger
from core.paths import Paths, get_paths, load_paths_with_data_root, set_data_root, get_data_root
from core.settings import AssistantSettings, load_settings, ApiSettings
from core.errors import ConfigurationError

router = APIRouter(tags=["system"])

log = get_logger(__name__)


@router.get(
    "/ready",
    response_model=ReadyReport,
    summary="Readiness",
    responses={503: {"description": "A dependency is not usable."}},
)
def ready(assistant: AssistantDep, response: JSONResponse) -> ReadyReport:
    """Verify that the application can serve requests.

    Checks:
    - SQLite is readable (real query, not file check).
    - Schema migrations are applied.
    - Safety phase-2 invariants are intact (dry_run, safe_mode,
      require_human_approval, no submission).

    On failure, returns 503 with detailed check results so the Tauri shell
    can decide whether to start the sidecar or show "Try again".
    """
    checks: dict[str, bool] = {}
    detail: str | None = None
    migration_version: str | None = None

    try:
        # SQLite readability: actual query, not filesystem check
        row = assistant.db.query_one(
            "SELECT count(*) AS n FROM sqlite_master WHERE type='table'"
        )
        checks["sqlite.readable"] = True
    except Exception as exc:  # noqa: BLE001 - readiness reports, never raises
        checks["sqlite.readable"] = False
        detail = detail or f"sqlite is not readable: {type(exc).__name__}"

    try:
        row = assistant.db.query_one("SELECT count(*) AS n FROM schema_migrations")
        applied = int(row["n"]) if row else 0
        migration_version = str(applied)
        checks["schema.migrated"] = applied > 0
    except Exception as exc:  # noqa: BLE001
        checks["schema.migrated"] = False
        detail = detail or f"migrations unreadable: {type(exc).__name__}"

    try:
        assistant.settings.safety.assert_phase2_invariants()
        checks["safety.invariants"] = True
    except Exception as exc:  # noqa: BLE001
        checks["safety.invariants"] = False
        detail = detail or f"safety invariants violated: {type(exc).__name__}"

    ready_now = all(checks.values())
    report = ReadyReport(
        status="ready" if ready_now else "not_ready",
        checks=checks,
        migration_version=migration_version,
        detail=detail,
    )
    if not ready_now:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        log.warning("readiness_failed", extra={"readiness": report.checks})
    return report


@router.get("/health", response_model=HealthReport, summary="Liveness")
def health() -> HealthReport:
    """Report that the process is serving.

    Intentionally does not touch SQLite, the AI provider, or the safety policy.
    A liveness probe that opens SQLite turns a database blip into a restart loop.
    """
    from core.paths import get_data_root
    data_root = get_data_root()
    return HealthReport(
        status="alive",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        data_root_env=os.environ.get("ASSISTANT_DESKTOP_DATA_ROOT"),
    )


@router.get("/status", response_model=ApiStatusReport, summary="Application status")
def app_status(assistant: AssistantDep) -> ApiStatusReport:
    """Configuration and stored counts from ``Assistant.status()``."""
    report: dict[str, Any] = assistant.status()
    return ApiStatusReport(
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        safety=SafetyReport(**report["safety"]),
        paths=report["paths"],
        database=DatabaseReport(**report["database"]),
        configuration=report["configuration"],
        ai=_ai_status(assistant),
    )


def _ai_status(assistant: AssistantDep) -> AiStatusReport:
    """Describe AI from configuration, without contacting anything."""
    ai = assistant.settings.ai
    providers = available_providers()
    configured = ai.provider.strip().lower() in providers
    embedding_available = False
    if configured:
        try:
            embedding_available = bool(assistant.ai_provider().supports_embeddings)
        except Exception:  # noqa: BLE001 - a broken provider is "not available"
            log.warning("ai_provider_build_failed", extra={"ai": {"error": "type"}})
    source_mode = assistant.settings.job_search.source_mode
    return AiStatusReport(
        configured=configured,
        provider=ai.provider,
        model=ai.model,
        api_key_present=ai.has_api_key,
        providers_available=providers,
        embedding_scorer_available=embedding_available,
        source_mode=source_mode,
        allows_application=source_mode.allows_application,
    )