"""Stable error envelopes for the HTTP boundary.

Every failure leaves this API as ``{"error": {"code", "message", "details"}}``.
Two properties matter more than the exact codes:

* **Stable.** A client may branch on ``code``. It is never a Python exception
  class name and never a raw internal message.
* **Safe.** Messages pass through :func:`core.redaction.redact` and no handler
  ever places a traceback in the response. Details are drawn from the typed
  fields the assistant's own errors carry (``error_code``, ``field``,
  ``issues``, ``from_state``), all of which were already designed to be
  reportable. Unmapped exceptions collapse to a generic 500 so an unexpected
  bug cannot leak a stack trace, a file path, or a credential.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.errors import (
    AIProviderError,
    ApplicationBoundaryError,
    AIResponseValidationError,
    AssistantError,
    ConfigurationError,
    DatabaseError,
    DuplicateResumeError,
    ImmutableFactError,
    InvalidStateTransitionError,
    JobExtractionError,
    JobNotFoundError,
    MigrationError,
    MissingEvidenceError,
    ModelNotFoundError,
    ProfileNotFoundError,
    ProfileValidationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RequirementExtractionError,
    ResumeNotFoundError,
    ResumeParseError,
    ResumeValidationError,
    SafetyViolationError,
    SourceAcquisitionError,
    SubmissionBlockedError,
    UnsupportedClaimError,
)
from core.redaction import redact

logger = logging.getLogger(__name__)

__all__ = [
    "install_exception_handlers",
    "error_response",
]


# --------------------------------------------------------------------------
# Mapping
# --------------------------------------------------------------------------
#: ``(status code, client code)`` per assistant error class. Order matters:
#: subclasses are registered before their bases, so ``SubmissionBlockedError``
#: is reported as a submission refusal rather than a generic safety violation,
#: and ``ImmutableFactError`` keeps its own code instead of collapsing into
#: ``SAFETY_VIOLATION``.
_STATUS_BY_ERROR: tuple[tuple[type[AssistantError], int, str], ...] = (
    (SubmissionBlockedError, status.HTTP_403_FORBIDDEN, "SUBMISSION_DISABLED"),
    (ApplicationBoundaryError, status.HTTP_403_FORBIDDEN, "BOUNDARY_VIOLATION"),
    (ImmutableFactError, status.HTTP_403_FORBIDDEN, "IMMUTABLE_FACT"),
    (SafetyViolationError, status.HTTP_403_FORBIDDEN, "SAFETY_VIOLATION"),
    (
        InvalidStateTransitionError,
        status.HTTP_409_CONFLICT,
        "INVALID_STATE_TRANSITION",
    ),
    (DuplicateResumeError, status.HTTP_409_CONFLICT, "DUPLICATE_RESUME"),
    (ProfileNotFoundError, status.HTTP_404_NOT_FOUND, "PROFILE_NOT_FOUND"),
    (JobNotFoundError, status.HTTP_404_NOT_FOUND, "JOB_NOT_FOUND"),
    (ResumeNotFoundError, status.HTTP_404_NOT_FOUND, "RESUME_NOT_FOUND"),
    (
        ProfileValidationError,
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PROFILE_INVALID",
    ),
    (ResumeValidationError, status.HTTP_422_UNPROCESSABLE_ENTITY, "RESUME_INVALID"),
    (ResumeParseError, status.HTTP_422_UNPROCESSABLE_ENTITY, "RESUME_PARSE_FAILED"),
    (JobExtractionError, status.HTTP_422_UNPROCESSABLE_ENTITY, "JOB_EXTRACTION_FAILED"),
    (
        RequirementExtractionError,
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "REQUIREMENT_EXTRACTION_FAILED",
    ),
    (MissingEvidenceError, status.HTTP_422_UNPROCESSABLE_ENTITY, "MISSING_EVIDENCE"),
    (UnsupportedClaimError, status.HTTP_422_UNPROCESSABLE_ENTITY, "UNSUPPORTED_CLAIM"),
    (
        ProviderTimeoutError,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "AI_PROVIDER_TIMEOUT",
    ),
    (
        ProviderUnavailableError,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "AI_PROVIDER_UNAVAILABLE",
    ),
    (ModelNotFoundError, status.HTTP_503_SERVICE_UNAVAILABLE, "AI_MODEL_NOT_FOUND"),
    (
        AIResponseValidationError,
        status.HTTP_502_BAD_GATEWAY,
        "AI_RESPONSE_INVALID",
    ),
    (AIProviderError, status.HTTP_503_SERVICE_UNAVAILABLE, "AI_PROVIDER_ERROR"),
    (SourceAcquisitionError, status.HTTP_502_BAD_GATEWAY, "SOURCE_ACQUISITION_FAILED"),
    (MigrationError, status.HTTP_500_INTERNAL_SERVER_ERROR, "MIGRATION_ERROR"),
    (ConfigurationError, status.HTTP_500_INTERNAL_SERVER_ERROR, "CONFIGURATION_ERROR"),
    (DatabaseError, status.HTTP_500_INTERNAL_SERVER_ERROR, "DATABASE_ERROR"),
)


def _mapping_for(error: AssistantError) -> tuple[int, str]:
    for error_type, status_code, code in _STATUS_BY_ERROR:
        if isinstance(error, error_type):
            return status_code, code
    return status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR"


#: Fields copied from a typed error into ``details``. Anything absent stays out
#: of the response rather than being sent as ``null``.
_REPORTABLE_FIELDS = (
    "error_code",
    "field",
    "issues",
    "from_state",
    "to_state",
    "allowed",
    "reason",
    "reason_code",
    "hint",
    "action",
    "resource_type",
    "resource_id",
    "source",
    "resume_id",
    "job_id",
    "provider",
    "model",
    "status_code",
    "attempt",
)


def _details_for(error: AssistantError) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for name in _REPORTABLE_FIELDS:
        value = getattr(error, name, None)
        if value is None:
            continue
        if isinstance(value, BaseException):
            continue
        if isinstance(value, (str, int, float, bool)):
            details[name] = value
        elif isinstance(value, dict):
            details[name] = value
        elif isinstance(value, (list, tuple)):
            details[name] = list(value)
    return details


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Optional[dict[str, Any]] = None,
) -> JSONResponse:
    """Build the one response shape every failure uses."""
    payload: dict[str, Any] = {
        "error": {
            "code": code,
            "message": redact(str(message)),
            "details": details or {},
        }
    }
    return JSONResponse(status_code=status_code, content=payload)


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------
async def assistant_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map a typed assistant error onto a stable envelope."""
    assert isinstance(exc, AssistantError)
    status_code, code = _mapping_for(exc)
    if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        # Server-side faults are logged in full here because the client will
        # only ever see the generic message.
        logger.error("api_error code=%s status=%d", code, status_code, exc_info=exc)
        message = (
            str(exc)
            if status_code < status.HTTP_500_INTERNAL_SERVER_ERROR
            else "the assistant could not complete this request"
        )
    else:
        message = str(exc)
    return error_response(status_code, code, message, _details_for(exc))


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Report malformed or unexpected request fields without echoing secrets.

    ``Pydantic`` error payloads are filtered to location, message, and type.
    ``input`` is dropped: it can contain whatever the caller submitted,
    including text that has no business being reflected back.
    """
    assert isinstance(exc, RequestValidationError)
    fields: list[dict[str, Any]] = []
    for item in exc.errors():
        fields.append(
            {
                "location": [str(part) for part in item.get("loc", ())],
                "message": redact(str(item.get("msg", "invalid value"))),
                "type": str(item.get("type", "value_error")),
            }
        )
    return error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "VALIDATION_FAILED",
        "the request body or query parameters were rejected",
        {"fields": fields},
    )


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Keep framework-raised HTTP errors in the same envelope.

    Registered against Starlette's ``HTTPException``, not FastAPI's subclass:
    the router raises the Starlette base for an unmatched path or a wrong
    method, and registering only the subclass would let those two answers
    escape the envelope.
    """
    assert isinstance(exc, StarletteHTTPException)
    code = {
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        409: "CONFLICT",
    }.get(exc.status_code, "HTTP_ERROR")
    detail = exc.detail if isinstance(exc.detail, str) else "request refused"
    return error_response(exc.status_code, code, detail)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last resort: log the traceback, return nothing revealing."""
    logger.error(
        "unhandled_error path=%s method=%s",
        request.url.path,
        request.method,
        exc_info=exc,
    )
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "the assistant could not complete this request",
    )


def install_exception_handlers(app: FastAPI) -> None:
    """Attach every handler to ``app``."""
    app.add_exception_handler(AssistantError, assistant_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)