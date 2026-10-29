from __future__ import annotations
"""Application lifecycle tracking schemas."""

from enum import Enum

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, UrlConstraints

from api.schemas.jobs import JobResponse


class ApplicationStatus(str, Enum):
    """Application lifecycle statuses."""
    SAVED = "SAVED"
    INTERESTED = "INTERESTED"
    PREPARING = "PREPARING"
    APPLIED = "APPLIED"
    ASSESSMENT = "ASSESSMENT"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationCreate(BaseModel):
    """Fields needed to create a new application tracking entry."""
    job_id: str = Field(..., description="Reference to stored job ID")
    status: ApplicationStatus = Field(default=ApplicationStatus.SAVED, description="Initial application status")
    notes: Optional[str] = Field(default=None, max_length=2000, description="User notes")
    resume_id: Optional[str] = Field(
        default=None, max_length=100, description="Optional resume variant ID"
    )
    cover_letter_draft_id: Optional[str] = Field(
        default=None, max_length=100, description="Optional cover-letter draft ID"
    )
    source_url: Optional[str] = Field(
        default=None, max_length=2000, description="Source URL of the job posting"
    )
    source_job_metadata: Optional[str] = Field(
        default=None, description="Optional JSON metadata from the job source"
    )


class ApplicationUpdate(BaseModel):
    """Fields that can be updated in an existing application."""
    status: Optional[ApplicationStatus] = Field(
        default=None, description="New application status"
    )
    notes: Optional[Optional[str]] = Field(
        default=None, max_length=2000, description="User notes"
    )
    resume_id: Optional[Optional[str]] = Field(
        default=None, max_length=100, description="Optional resume variant ID"
    )
    cover_letter_draft_id: Optional[Optional[str]] = Field(
        default=None, max_length=100, description="Optional cover-letter draft ID"
    )
    source_url: Optional[Optional[str]] = Field(
        default=None, max_length=2000, description="Source URL"
    )
    source_job_metadata: Optional[Optional[str]] = Field(
        default=None, description="Optional JSON metadata"
    )
    application_date: Optional[Optional[date]] = Field(
        default=None, description="Application date (set when user confirms applied)"
    )
    next_followup: Optional[Optional[date]] = Field(
        default=None, description="Next follow-up date"
    )
    interviewer_name: Optional[Optional[str]] = Field(
        default=None, max_length=100, description="Recruiter/contact name"
    )
    interviewer_contact: Optional[Optional[str]] = Field(
        default=None, max_length=200, description="Recruiter contact details"
    )


class ApplicationResponse(BaseModel):
    """Full application record response."""
    model_config = ConfigDict(extra="forbid")

    id: str
    job_id: str
    status: ApplicationStatus
    job: Optional[JobResponse] = Field(
        default=None, description="Nested job details if loaded"
    )
    application_date: Optional[date] = Field(
        default=None, description="When the user confirmed applied"
    )
    created_at: datetime
    updated_at: datetime
    next_followup: Optional[date] = Field(
        default=None, description="Next follow-up date"
    )
    interviewer_name: Optional[str] = Field(
        default=None, max_length=100, description="Recruiter/contact name"
    )
    interviewer_contact: Optional[str] = Field(
        default=None, max_length=200, description="Recruiter contact details"
    )
    notes: Optional[str] = Field(
        default=None, max_length=2000, description="User notes"
    )
    resume_id: Optional[str] = Field(
        default=None, max_length=100, description="Resume variant ID"
    )
    cover_letter_draft_id: Optional[str] = Field(
        default=None, max_length=100, description="Cover-letter draft ID"
    )
    source_url: Optional[str] = Field(
        default=None, max_length=2000, description="Source URL"
    )
    source_job_metadata: Optional[str] = Field(
        default=None, description="Optional JSON metadata"
    )


class ApplicationListResponse(BaseModel):
    """List of applications with pagination."""
    model_config = ConfigDict(extra="forbid")

    applications: List[ApplicationResponse]
    count: int
    limit: Optional[int] = None
    offset: Optional[int] = None


class ApplicationStatusUpdate(BaseModel):
    """Request to update only the application status."""
    status: ApplicationStatus = Field(
        description="New application status"
    )
    note: Optional[str] = Field(
        default=None, max_length=500, description="Optional note for this transition"
    )


class ApplicationFilter(BaseModel):
    """Filter parameters for listing applications."""
    status: Optional[ApplicationStatus] = Field(
        default=None, description="Filter by status"
    )
    company: Optional[str] = Field(
        default=None, max_length=200, description="Filter by company name"
    )
    job_title: Optional[str] = Field(
        default=None, max_length=200, description="Filter by job title text search"
    )
    has_followup: Optional[bool] = Field(
        default=None, description="Filter applications with/without follow-up date"
    )
    before_followup: Optional[date] = Field(
        default=None, description="Filter applications with follow-up before this date"
    )
    after_followup: Optional[date] = Field(
        default=None, description="Filter applications with follow-up after this date"
    )
