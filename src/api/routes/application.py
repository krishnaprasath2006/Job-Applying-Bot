"""Application lifecycle tracking routes.

Handles creating, retrieving, updating, and deleting tracked job applications,
along with status transitions and history.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from api.dependencies import AssistantDep
from api.schemas.application import (
    ApplicationCreate,
    ApplicationUpdate,
    ApplicationResponse,
    ApplicationListResponse,
    ApplicationStatusUpdate,
    ApplicationStatus,
)
from database.repositories.application_repository import ApplicationRepository


router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED, summary="Add job to application tracker")
def create_application(
    assistant: AssistantDep,
    payload: ApplicationCreate,
) -> ApplicationResponse:
    """Add a job to the application tracking system."""
    repo: ApplicationRepository = assistant.application_repository
    app_id = repo.create(payload)
    return repo.get(app_id)


@router.get("", response_model=ApplicationListResponse, summary="List tracked applications")
def list_applications(
    assistant: AssistantDep,
    status: Optional[ApplicationStatus] = Query(
        default=None, alias="status", description="Filter by application status"
    ),
    company: Optional[str] = Query(
        default=None, max_length=200, description="Filter by company name"
    ),
    job_title: Optional[str] = Query(
        default=None, max_length=200, description="Filter by job title text search"
    ),
    has_followup: Optional[bool] = Query(
        default=None, description="Filter by whether follow-up date exists"
    ),
    before_followup: Optional[date] = Query(
        default=None, description="Filter applications with follow-up before this date"
    ),
    after_followup: Optional[date] = Query(
        default=None, description="Filter applications with follow-up after this date"
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
) -> ApplicationListResponse:
    """List tracked applications with filtering and pagination."""
    repo: ApplicationRepository = assistant.application_repository
    applications, total = repo.list_applications(
        status=status,
        job_id=None,
        limit=limit,
        offset=offset,
    )
    return ApplicationListResponse(
        applications=applications,
        count=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{app_id}", response_model=ApplicationResponse, summary="Retrieve application")
def retrieve_application(
    assistant: AssistantDep,
    app_id: str,
) -> ApplicationResponse:
    """Retrieve a single application by ID."""
    repo: ApplicationRepository = assistant.application_repository
    app = repo.get(app_id)
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application {app_id} not found",
        )
    return app


@router.patch("/{app_id}", response_model=ApplicationResponse, summary="Update application")
def update_application(
    assistant: AssistantDep,
    app_id: str,
    payload: ApplicationUpdate,
) -> ApplicationResponse:
    """Update an existing application."""
    repo: ApplicationRepository = assistant.application_repository
    app = repo.get(app_id)
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application {app_id} not found",
        )
    updated = repo.update(app_id, payload)
    return updated


@router.post("/{app_id}/transition", response_model=dict, summary="Transition application status")
def transition_status(
    assistant: AssistantDep,
    app_id: str,
    payload: ApplicationStatusUpdate,
) -> dict[str, Any]:
    """Transition application status with audit logging."""
    repo: ApplicationRepository = assistant.application_repository
    try:
        transition = repo.transition_status(
            app_id=app_id,
            new_status=payload.status,
            note=payload.note,
            actor="user",
        )
        return transition
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete application")
def delete_application(
    assistant: AssistantDep,
    app_id: str,
) -> None:
    """Delete an application from the tracker."""
    repo: ApplicationRepository = assistant.application_repository
    deleted = repo.delete(app_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application {app_id} not found",
        )
