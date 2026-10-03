from dataclasses import dataclass, field
from typing import List, Optional
from src.core.enums import (
    RequirementKind,
    RequirementPriority,
    RequirementEvaluation,
    MatchDecision,
    HardGateStatus,
    JobStatus
)

@dataclass
class JobRequirement:
    id: str
    text: str
    category: RequirementKind
    priority: RequirementPriority
    min_years: Optional[float] = None

@dataclass
class HardGateResult:
    status: HardGateStatus
    reasons: List[str] = field(default_factory=list)

@dataclass
class RequirementScore:
    requirement_text: str
    kind: RequirementKind
    priority: RequirementPriority
    evaluation: RequirementEvaluation
    similarity: float
    reason: str
    candidate_field_path: Optional[str] = None

@dataclass
class MatchResult:
    decision: MatchDecision
    overall_score: int
    gate: HardGateResult
    scores: List[RequirementScore]
    summary: str

@dataclass
class Job:
    id: str
    title: str
    company: str
    location: str
    description: str
    requirements: List[JobRequirement] = field(default_factory=list)
    status: JobStatus = JobStatus.DISCOVERED
    match_result: Optional[MatchResult] = None
