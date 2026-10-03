from dataclasses import dataclass, field
from typing import List, Optional, Any
from src.core.enums import FactStatus

@dataclass
class CandidateFact:
    field_path: str
    value: Any
    status: FactStatus = FactStatus.VERIFIED
    source: str = "OFFICIAL_RECORD"
    confidence: float = 1.0

@dataclass
class SkillClaim:
    name: str
    years: float
    proficiency: str = "Advanced"
    category: str = "Technical"
    status: FactStatus = FactStatus.VERIFIED

@dataclass
class WorkAuthorization:
    authorized_in_us: CandidateFact
    requires_sponsorship: CandidateFact
    visa_status: CandidateFact
    security_clearance: CandidateFact

@dataclass
class ExperienceSummary:
    total_years: CandidateFact
    current_title: CandidateFact
    target_roles: CandidateFact

@dataclass
class EducationSummary:
    highest_degree: CandidateFact
    field_of_study: CandidateFact
    institution: CandidateFact

@dataclass
class CandidateProfile:
    id: str
    full_name: CandidateFact
    email: CandidateFact
    phone: CandidateFact
    location: CandidateFact
    work_authorization: WorkAuthorization
    experience: ExperienceSummary
    education: EducationSummary
    skills: List[SkillClaim] = field(default_factory=list)
