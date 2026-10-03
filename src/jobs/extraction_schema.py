"""The shape a model must return when it reads requirements from a posting.

A model's reading of a job description is an opinion, and an opinion that
cannot be checked is not worth storing. This module pins the opinion down:

* ``category`` and ``priority`` are the stored enums, not free text, so a
  response that invents a category is rejected rather than silently mapped to
  "other";
* ``evidence`` asks for the span the reading came from, which is what lets a
  human check it against the posting;
* conversion produces the same :class:`~jobs.models.Requirement` rows the
  deterministic extractor produces, marked ``AI`` instead of ``DETERMINISTIC``
  so the two can never be confused after the fact.

The deterministic path (:mod:`jobs.requirements`) and this one are therefore
two ways of filling the same table, not two schemas that later need
reconciling.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.enums import AnalysisSource, ExtractionMethod, RequirementPriority
from jobs.models import Requirement, RequirementKind
from jobs.normalizer import normalize_text
from jobs.requirements import merge_requirements

__all__ = ["ExtractedRequirement", "RequirementExtraction"]


class ExtractedRequirement(BaseModel):
    """One requirement, as a model should report it."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        min_length=1,
        max_length=2000,
        description="The requirement as the posting states it.",
    )
    category: RequirementKind = Field(
        description="Which sort of requirement this is, from the fixed vocabulary."
    )
    priority: RequirementPriority = Field(
        default=RequirementPriority.UNKNOWN,
        description="REQUIRED, PREFERRED, or UNKNOWN when the posting does not say.",
    )
    min_years: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=60.0,
        description="Minimum years requested, when the text states a number.",
    )
    evidence: Optional[str] = Field(
        default=None,
        description="The verbatim span of the posting this reading came from.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="How confident the reading is, in [0, 1].",
    )

    @field_validator("text")
    @classmethod
    def _text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must contain more than whitespace")
        return stripped

    def to_requirement(self) -> Requirement:
        """This reading as a stored requirement, attributed to a model."""
        return Requirement(
            kind=self.category,
            text=self.text,
            normalized=normalize_text(self.text).lower(),
            priority=self.priority,
            min_years=self.min_years,
            source_excerpt=(self.evidence or "").strip() or None,
            extraction_source=ExtractionMethod.AI,
            analysis_source=AnalysisSource.JOB_DATA,
            confidence=self.confidence,
        )


class RequirementExtraction(BaseModel):
    """Everything one extraction call should return."""

    model_config = ConfigDict(extra="forbid")

    requirements: list[ExtractedRequirement] = Field(
        default_factory=list,
        description="Requirements read from the description, in the order they appear.",
    )

    def to_requirements(self) -> list[Requirement]:
        """All readings as stored requirements, in order.

        Duplicates are folded here rather than rejected above: the model's
        response is kept as it arrived, and the shared merge rule decides what
        a duplicate, or two readings that disagree, means — the same rule the
        deterministic path follows.
        """
        return merge_requirements(
            [item.to_requirement() for item in self.requirements]
        )
