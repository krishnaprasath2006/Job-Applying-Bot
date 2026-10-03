"""Profile request and response models.

Responses reuse ``profile.models`` and ``profile.validator`` types where one
exists, so the wire shape is the domain shape rather than a hand-kept copy that
drifts. Only the write payload is defined here, because the HTTP edge is the
only place a partial update is expressed.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.evidence import Evidence
from core.enums import FactStatus
from profile.models import CandidateProfile

__all__ = [
    "FactUpdate",
    "FactResponse",
    "ProfileResponse",
    "ProfileValidationResponse",
    "ProfileCompletenessResponse",
    "UnknownFieldsResponse",
]


class FactUpdate(BaseModel):
    """A single fact write.

    ``extra="forbid"`` is load-bearing: a typo like ``source`` where the model
    wants ``source_type`` must fail loudly rather than quietly dropping the
    provenance that makes a fact trustworthy.

    ``status`` is optional because the service can infer one. It is validated
    below that a supplied ``value`` always carries a status, so a caller cannot
    write a value with no declared confidence in it.
    """

    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(
        min_length=1,
        max_length=200,
        description="Dotted path of the fact, e.g. ``basics.email``.",
    )
    value: Any = None
    status: Optional[FactStatus] = None
    evidence: Optional[list[Evidence]] = None

    def evidence_rows(self) -> Optional[list[Evidence]]:
        """Evidence as supplied, or ``None`` when the caller sent none.

        No evidence is manufactured here. A caller that asserts a value
        without provenance is making a claim, and the profile service is the
        layer entitled to decide what an unsupported claim means.
        """
        return self.evidence or None


class FactResponse(BaseModel):
    """One stored fact with its evidence."""

    model_config = ConfigDict(extra="forbid")

    field_path: str
    value: Any = None
    status: FactStatus = FactStatus.UNKNOWN
    evidence: list[Evidence] = Field(default_factory=list)
    verified_at: Optional[str] = None
    note: Optional[str] = None


class ProfileResponse(BaseModel):
    """The candidate profile as stored."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    exists: bool
    profile: CandidateProfile


class ProfileValidationResponse(BaseModel):
    """Validation findings, serialised from ``profile.validator.ValidationReport``.

    ``ValidationReport`` is a dataclass, not a Pydantic model, so it is mapped
    field by field rather than embedded. ``is_valid`` means "nothing is wrong",
    which on an empty template is true — the response deliberately carries no
    "ready to apply" verdict. Deciding readiness is the safety layer's job, and
    inventing it in a route would create a second opinion that nothing else
    shares.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    is_valid: bool
    error_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    completeness: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_required: list[str] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)


class ProfileCompletenessResponse(BaseModel):
    """How much of the profile is answered."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    completeness: float = Field(ge=0.0, le=1.0)


class UnknownFieldsResponse(BaseModel):
    """Fields still unknown, so a UI can prompt for exactly those."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    unknown: list[dict[str, Any]] = Field(default_factory=list)
    count: int = Field(default=0, ge=0)