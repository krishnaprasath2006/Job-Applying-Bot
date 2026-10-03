"""Request and response models for the HTTP boundary.

Import them from here rather than from the modules directly, so the route
surface has one obvious place to look when a payload changes.
"""

from __future__ import annotations

from api.schemas.common import (
    CountSummary,
    ErrorBody,
    ErrorEnvelope,
    HealthReport,
    ReadyReport,
)
from api.schemas.jobs import (
    AnalysisResponse,
    ExplanationResponse,
    JobIngestRequest,
    JobListResponse,
    JobResponse,
    MatchReport,
    MatchRequest,
    MatchResponse,
    RelevanceResponse,
    ReportResponse,
    ReviewQueueResponse,
    SubmitApplicationResponse,
)
from api.schemas.profile import (
    FactResponse,
    FactUpdate,
    ProfileCompletenessResponse,
    ProfileResponse,
    ProfileValidationResponse,
    UnknownFieldsResponse,
)
from api.schemas.resumes import (
    DuplicateCheckResponse,
    ResumeIngestRequest,
    ResumeListResponse,
    ResumeResponse,
    ResumeSectionsResponse,
    ResumeVariantsResponse,
)
from api.schemas.status import (
    AiStatusReport,
    ApiStatusReport,
    DatabaseReport,
    SafetyReport,
)

__all__ = [
    # common
    "CountSummary",
    "ErrorBody",
    "ErrorEnvelope",
    "HealthReport",
    "ReadyReport",
    # status
    "SafetyReport",
    "DatabaseReport",
    "AiStatusReport",
    "ApiStatusReport",
    # profile
    "FactUpdate",
    "FactResponse",
    "ProfileResponse",
    "ProfileValidationResponse",
    "ProfileCompletenessResponse",
    "UnknownFieldsResponse",
    # resumes
    "ResumeIngestRequest",
    "ResumeResponse",
    "ResumeListResponse",
    "ResumeSectionsResponse",
    "ResumeVariantsResponse",
    "DuplicateCheckResponse",
    # jobs
    "JobIngestRequest",
    "MatchRequest",
    "JobListResponse",
    "JobResponse",
    "AnalysisResponse",
    "MatchResponse",
    "ReportResponse",
    "RelevanceResponse",
    "ExplanationResponse",
    "ReviewQueueResponse",
    "SubmitApplicationResponse",
]