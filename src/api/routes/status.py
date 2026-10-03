"""Liveness, readiness, and status.

Three endpoints that answer three different questions, kept apart on purpose:

* ``/health`` — is this process answering? No dependencies, because a liveness
  probe that opens SQLite turns a database blip into a restart loop.
* ``/ready`` — can it serve a real request? Every check is executed and its
  result reported.
* ``/status`` — what is configured, and what is stored?
"""

from __future__ import annotations

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

router = APIRouter(tags=["system"])
log = get_logger(__name__)


@router.get("/health", response_model=HealthReport, summary="Liveness")
def health() -> HealthReport:
    """Report that the process is serving.

    Intentionally does not touch SQLite, the AI provider, or the safety policy.
    """
    return HealthReport(status="alive", service=SERVICE_NAME, version=SERVICE_VERSION)


@router.get(
    "/ready",
    response_model=ReadyReport,
    summary="Readiness",
    responses={503: {"description": "A dependency is not usable."}},
)
def ready(assistant: AssistantDep, response: JSONResponse) -> ReadyReport:
    """Verify the dependencies a request actually needs.

    ``sqlite.readable`` is a real query, not a file check. ``schema.migrated``
    confirms the tables this code expects exist. ``safety.invariants`` re-runs
    the phase-two assertions, so a configuration that was edited after startup
    is caught here rather than on the first privileged call.
    """
    checks: dict[str, bool] = {}
    detail: str | None = None
    migration_version: str | None = None

    try:
        assistant.db.query_one(
            "SELECT count(*) AS n FROM sqlite_master WHERE type='table'"
        )
        checks["sqlite.readable"] = True
    except Exception as exc:  # noqa: BLE001 - readiness reports, never raises
        checks["sqlite.readable"] = False
        detail = f"sqlite is not readable: {type(exc).__name__}"

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
        # 503 with the body, rather than an error envelope: a failed readiness
        # probe is a report about the server, not a rejected request.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        log.warning("readiness_failed", extra={"readiness": report.checks})
    return report


def _ai_status(assistant: AssistantDep) -> AiStatusReport:
    """Describe AI from configuration, without contacting anything.

    ``embedding_scorer_available`` reflects the provider's declared
    capability, not a successful call: reporting "available" after a round trip
    would make a status poll depend on a model being up.
    """
    ai = assistant.settings.ai
    providers = available_providers()
    configured = ai.provider.strip().lower() in providers
    embedding_available = False
    if configured:
        try:
            embedding_available = bool(assistant.ai_provider().supports_embeddings)
        except Exception as exc:  # noqa: BLE001 - a broken provider is "not available"
            log.warning("ai_provider_build_failed", extra={"ai": {"error": type(exc).__name__}})
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


@router.get("/status", response_model=ApiStatusReport, summary="Application status")
def app_status(assistant: AssistantDep) -> ApiStatusReport:
    """Configuration and stored counts, from ``Assistant.status()``."""
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