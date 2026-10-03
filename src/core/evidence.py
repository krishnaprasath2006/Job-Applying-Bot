"""The evidence model: every value must be able to say where it came from.

This is the single most important type in Phase 2. Later phases (RAG retrieval,
answer generation, ATS matching) all need to distinguish "the candidate said
this" from "a model guessed this", and that distinction is impossible to
reconstruct later unless it is captured at write time. So it is captured here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.enums import EvidenceSourceType, FactStatus
from core.errors import MissingEvidenceError
from core.hashing import utc_now

__all__ = ["Evidence", "Fact", "FactValue"]

_MAX_EXCERPT = 2000


class Evidence(BaseModel):
    """Provenance for a single value.

    Attributes:
        source_type: Which kind of document or input produced the value.
        source_id: Stable identifier for that document (a resume id, profile
            id, or document row id). Never a filesystem path, because paths
            change and are platform-specific.
        source_location: Human-readable pointer within the source, such as
            ``"experience[0]"`` or ``"page 2"``.
        text_excerpt: The exact supporting text, when the source had text.
            Truncated defensively so a whole resume can never land here.
        confidence: Calibrated score in ``[0, 1]`` describing how much the
            evidence supports the value, not how sure the model feels.
        created_at: When this evidence was recorded.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: EvidenceSourceType
    source_id: Optional[str] = Field(
        default=None,
        description="Stable id of the source document; required for RESUME/PROFILE/JOB_DESCRIPTION.",
    )
    source_location: Optional[str] = None
    # No max_length here on purpose. Pydantic applies a length constraint
    # before this validator runs, which would reject a long excerpt instead of
    # truncating it, and the truncated result is intentionally longer than the
    # cut-off point because it carries the "[truncated]" marker.
    text_excerpt: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("text_excerpt")
    @classmethod
    def _truncate_excerpt(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if len(cleaned) > _MAX_EXCERPT:
            return cleaned[:_MAX_EXCERPT] + "...[truncated]"
        return cleaned

    @model_validator(mode="after")
    def _require_id_for_document_sources(self) -> "Evidence":
        needs_id = {
            EvidenceSourceType.RESUME,
            EvidenceSourceType.PROFILE,
            EvidenceSourceType.JOB_DESCRIPTION,
            EvidenceSourceType.VERIFIED_ANSWER,
        }
        if self.source_type in needs_id and not (self.source_id or "").strip():
            raise ValueError(
                f"source_id is required for evidence of type {self.source_type.value}"
            )
        return self

    def cite(self) -> str:
        """Render a short human-readable citation for prompts and logs."""
        parts = [self.source_type.value]
        if self.source_id:
            parts.append(self.source_id)
        if self.source_location:
            parts.append(self.source_location)
        return ":".join(parts)


class Fact(BaseModel):
    """One candidate fact: a value, its truth status, and its evidence.

    The three-state model is the core safety property. ``VERIFIED`` means the
    candidate confirmed it. ``UNKNOWN`` means nobody knows it yet, which is a
    legitimate state and is the default everywhere. ``INFERRED`` means a
    parser or model proposed it; it is explicitly *not* application-safe
    until a human promotes it.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    field_path: str = Field(description="Dotted path of the field this fact describes.")
    value: Any = Field(default=None, description="The value, or None when UNKNOWN.")
    status: FactStatus = FactStatus.UNKNOWN
    evidence: list[Evidence] = Field(default_factory=list)
    verified_at: Optional[datetime] = None
    note: Optional[str] = None
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def is_known(self) -> bool:
        return self.status is not FactStatus.UNKNOWN and self.value is not None

    @property
    def is_application_safe(self) -> bool:
        """True only when this fact may be typed into a real form.

        All three conditions are required, not just the status. A ``VERIFIED``
        fact with no evidence attached cannot be typed into a real form,
        because there would be nothing to show if the value were ever
        questioned. ``assert_application_safe`` enforces the same rule and
        additionally explains why.
        """
        return self.is_known and self.status is FactStatus.VERIFIED and bool(self.evidence)

    def assert_application_safe(self) -> None:
        """Raise :class:`MissingEvidenceError` unless the fact is usable.

        Call this immediately before a value is used in a real application,
        never after.
        """
        if not self.is_known:
            raise MissingEvidenceError(
                "fact is UNKNOWN and cannot be used",
                field_path=self.field_path,
                status=self.status.value,
            )
        if self.status is not FactStatus.VERIFIED:
            raise MissingEvidenceError(
                "fact is not VERIFIED and cannot be used in a real application",
                field_path=self.field_path,
                status=self.status.value,
                hint="INFERRED values require explicit human verification",
            )
        if not self.evidence:
            raise MissingEvidenceError(
                "VERIFIED fact has no evidence attached",
                field_path=self.field_path,
            )


class FactValue(BaseModel):
    """A value plus status and evidence, ready to embed in a profile section.

    This is the JSON shape referenced by the Phase 2 specification::

        {
            "value": "Python",
            "status": "VERIFIED",
            "source": "USER_INPUT",
            "source_id": "user_2026_05_02",
            "verified_at": "..."
        }

    The inline ``source``/``source_id`` pair is the compact form used in JSON.
    ``evidence`` carries the full :class:`Evidence` records, including the
    excerpt that justifies the value, and is what the persistence layer writes
    to the ``evidence`` and ``fact_evidence`` tables.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    field_path: str = Field(default="", description="Dotted path of the field being described.")
    value: Any = None
    status: FactStatus = FactStatus.UNKNOWN
    source: Optional[EvidenceSourceType] = None
    source_id: Optional[str] = None
    source_location: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    verified_at: Optional[datetime] = None
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_consistency(self) -> "FactValue":
        if self.status is FactStatus.UNKNOWN:
            if self.value is not None:
                raise ValueError(
                    "a fact with status UNKNOWN must not carry a value; "
                    "set status to VERIFIED or INFERRED, or clear the value"
                )
        elif self.value is None:
            raise ValueError(f"a fact with status {self.status.value} must carry a value")

        # A VERIFIED fact must be traceable. "verified" means a person or a
        # deterministic source confirmed it, so the confirmation has to name
        # itself. Without this, a value could be marked VERIFIED and never
        # say who verified it, which is exactly the state the whole evidence
        # chain exists to prevent.
        if self.status is FactStatus.VERIFIED and not self.source:
            raise ValueError(
                "a VERIFIED fact must name its source; "
                "set source (and source_id for document sources)"
            )
        return self

    @property
    def is_application_safe(self) -> bool:
        # Delegate rather than reimplement: the two representations disagreed
        # once already, and a field that is safe here but unsafe after
        # conversion is exactly the kind of gap a real form would fall into.
        return self.to_fact().is_application_safe

    def to_fact(self) -> Fact:
        """Convert to the internal :class:`Fact` representation.

        Explicit evidence is carried through, excerpts included. When the
        compact form is used instead, one record is derived from the source
        fields so a cited value is never left with nothing to point at.
        """
        evidence = list(self.evidence)
        if not evidence and self.source is not None:
            evidence.append(
                Evidence(
                    source_type=self.source,
                    source_id=self.source_id,
                    source_location=self.source_location,
                    confidence=self.confidence,
                )
            )
        return Fact(
            field_path=self.field_path,
            value=self.value,
            status=self.status,
            evidence=evidence,
            verified_at=self.verified_at,
        )
