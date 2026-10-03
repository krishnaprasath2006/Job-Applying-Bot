from enum import Enum

class JobStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    INGESTED = "INGESTED"
    ANALYZED = "ANALYZED"
    SCORED = "SCORED"
    QUEUED_FOR_REVIEW = "QUEUED_FOR_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"

class FactStatus(str, Enum):
    VERIFIED = "VERIFIED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"

class HardGateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"

class MatchDecision(str, Enum):
    STRONG_MATCH = "STRONG_MATCH"
    GOOD_MATCH = "GOOD_MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    HARD_MISMATCH = "HARD_MISMATCH"
    UNKNOWN = "UNKNOWN"

class RequirementKind(str, Enum):
    LANGUAGES = "LANGUAGES"
    FRAMEWORKS = "FRAMEWORKS"
    DATABASES = "DATABASES"
    CLOUD_DEVOPS = "CLOUD_DEVOPS"
    DEGREE = "DEGREE"
    YEARS_OF_EXPERIENCE = "YEARS_OF_EXPERIENCE"
    WORK_AUTHORIZATION = "WORK_AUTHORIZATION"
    SOFT_SKILLS = "SOFT_SKILLS"
    OTHER = "OTHER"

class RequirementPriority(str, Enum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    UNKNOWN = "UNKNOWN"

class RequirementEvaluation(str, Enum):
    VERIFIED_MATCH = "VERIFIED_MATCH"
    DERIVED_MATCH = "DERIVED_MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    DERIVED_MISS = "DERIVED_MISS"
    REVIEW_NEEDED = "REVIEW_NEEDED"
    UNKNOWN = "UNKNOWN"

class ModelCapability(str, Enum):
    EMBEDDINGS = "embeddings"
    RERANKING = "reranking"
    TEXT_GENERATION = "text_generation"
    JSON_GENERATION = "json_generation"
