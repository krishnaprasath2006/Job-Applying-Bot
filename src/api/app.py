"""The FastAPI application factory.

``create_app`` is the only place the HTTP surface is assembled. It:

* builds the assistant once, in the lifespan, so every request shares one
  object graph and one SQLite connection;
* installs the typed-error handlers and the CORS policy from
  :class:`core.settings.ApiSettings`;
* exposes no browser, no driver, and no submission path.

Startup order matters and is deliberate. ``build_assistant`` validates the
safety invariants before it opens the database, so a configuration that would
permit submission fails the process rather than serving requests. If anything
goes wrong in the lifespan, the exception propagates and the app never reports
itself ready.

Run it with::

    python -m uvicorn api.app:create_app --factory --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import get_assistant
from api.errors import install_exception_handlers
from api.routes import api_router, health_router
from api.version import SERVICE_NAME, SERVICE_VERSION
from assistant.app import Assistant, build_assistant
from core.logging_config import configure_logging, get_logger
from core.settings import AssistantSettings, load_settings

log = get_logger(__name__)

__all__ = ["create_app", "app"]


def create_app(
    *,
    settings: Optional[AssistantSettings] = None,
    database_path: Optional[Path] = None,
    env_file: Optional[str] = None,
) -> FastAPI:
    """Build the ASGI application.

    Args:
        settings: Pre-built settings, used by tests to pin a database and
            safety configuration without touching the environment.
        database_path: Override the SQLite location. Applied through
            ``build_assistant`` rather than by replacing ``app.state.assistant.db``
            afterwards, because the services hold their own references to the
            same connection and swapping it late would leave them writing
            somewhere else.
        env_file: Explicit ``.env`` path.

    Returns:
        A configured :class:`fastapi.FastAPI`.

    Raises:
        ConfigurationError: If settings are invalid or a safety invariant is
            violated. The application does not start in that case.
    """

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Resolved here rather than at import time so a bad configuration
        # surfaces as a failed startup, not an import error that looks like a
        # code problem.
        resolved = settings or load_settings(env_file=env_file)
        configure_logging(level=resolved.logging.level, fmt=resolved.logging.format)
        # Validates the phase-two invariants before touching the database.
        assistant: Assistant = build_assistant(
            settings=resolved, database_path=database_path
        )
        application.state.assistant = assistant
        log.info(
            "api_started",
            extra={
                "api": {
                    "host": resolved.api.host,
                    "port": resolved.api.port,
                    "database": str(assistant.db.path),
                    "submission_possible": assistant.safety.status()[
                        "submission_possible"
                    ],
                }
            },
        )
        try:
            yield
        finally:
            # Closed on shutdown so a reload or a test run does not leave a
            # WAL file open against a database the next run wants to migrate.
            assistant.close()
            log.info("api_stopped")

    application = FastAPI(
        title="Job Applying Bot API",
        version=SERVICE_VERSION,
        summary="Local-first HTTP boundary over the canonical Python assistant.",
        description=(
            "Every route delegates to an existing service on the canonical "
            "assistant: profile facts, resumes, job analysis, matching, and "
            "review. Application submission is disabled and cannot be enabled "
            "through this API."
        ),
        lifespan=lifespan,
        # Hidden while submission is disabled: a submit button is not a
        # disabled state, it is a promise the server will not keep.
        docs_url="/docs" if (settings is None or settings.api.docs_enabled) else None,
        redoc_url=None,
    )

    application.state.service_name = SERVICE_NAME
    application.state.assistant = None

    api = settings.api if settings is not None else _api_settings_from_env(env_file)
    _install_cors(application, api)
    install_exception_handlers(application)

    application.include_router(health_router)
    application.include_router(api_router, prefix="/api")

    # Document the typed errors on every route so the OpenAPI schema advertises
    # the envelope a client will actually receive.
    _declare_error_responses(application)

    return application


def _api_settings_from_env(env_file: Optional[str] = None):
    """Read API settings without building the whole assistant twice.

    Falls back to the defaults when the environment is unreadable; the real
    validation still happens in the lifespan, where a failure stops startup
    rather than being swallowed here.
    """
    try:
        return load_settings(env_file=env_file).api
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "api_settings_unavailable_defaults_used",
            extra={"api": {"error": type(exc).__name__}},
        )
        from core.settings import ApiSettings

        return ApiSettings()


def _install_cors(application: FastAPI, api: Any) -> None:
    """Add CORS with the configured origins.

    Credentials are off by default and the origins are explicit. A wildcard
    with credentials would let any page on the machine drive the assistant,
    which is the opposite of a local-first boundary.
    """
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(api.cors_origins),
        allow_credentials=bool(api.cors_allow_credentials),
        allow_methods=list(api.cors_allow_methods),
        allow_headers=list(api.cors_allow_headers),
    )


def _declare_error_responses(application: FastAPI) -> None:
    """Attach the shared error responses to every documented route."""
    from fastapi.openapi.utils import get_openapi

    def custom_openapi() -> dict[str, Any]:
        if application.openapi_schema:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
        )
        error_schema = {
            "type": "object",
            "properties": {
                "error": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "details": {"type": "object"},
                    },
                    "required": ["code", "message"],
                }
            },
            "required": ["error"],
        }
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components.setdefault(
            "ErrorEnvelope",
            {"type": "object", "properties": {"error": error_schema["properties"]["error"]}},
        )
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                if not isinstance(operation, dict):
                    continue
                responses = operation.setdefault("responses", {})
                responses.setdefault(
                    "422",
                    {
                        "description": "Validation failed.",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}
                        },
                    },
                )
        application.openapi_schema = schema
        return schema

    application.openapi = custom_openapi  # type: ignore[method-assign]
    # Keep the dependency importable from here so the wiring is discoverable in
    # one file: routes reach the assistant through it.
    application.state.assistant_dependency = get_assistant


#: Module-level instance for ``uvicorn api.app:app``.
#: Uses a lazy lifespan, so importing this module does not open a database —
#: which is what lets the test suite import routes without side effects.
app = create_app()