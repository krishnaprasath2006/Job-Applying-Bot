"""Job models, normalisation, and deduplication.

Phase 2 defines these but creates no jobs: fetching and scraping are later
phases, and the browser is untouched.
"""

from jobs.deduplicator import DeduplicationResult, JobDeduplicator, JobIdentity, extract_posting_id
from jobs.models import Job, JobStatus, Requirement, RequirementKind
from jobs.normalizer import (
    normalize_company,
    normalize_skill,
    normalize_skill_list,
    normalize_text,
    normalize_title,
    slugify,
)

__all__ = [
    "DeduplicationResult",
    "Job",
    "JobDeduplicator",
    "JobIdentity",
    "JobStatus",
    "Requirement",
    "RequirementKind",
    "extract_posting_id",
    "normalize_company",
    "normalize_skill",
    "normalize_skill_list",
    "normalize_text",
    "normalize_title",
    "slugify",
]