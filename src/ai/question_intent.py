from typing import Dict, Any, Optional
from dataclasses import dataclass
from src.ai.embeddings import SemanticScorer

@dataclass
class TaxonomyAnchor:
    category: str
    anchor_text: str
    target_profile_path: Optional[str]
    description: str

TAXONOMY_ANCHORS = [
    TaxonomyAnchor(
        category="WORK_AUTHORIZATION",
        anchor_text="are you legally authorized to work in the United States citizenship permanent resident",
        target_profile_path="work_authorization.authorized_in_us",
        description="Legal right to work in the United States"
    ),
    TaxonomyAnchor(
        category="SPONSORSHIP",
        anchor_text="will you now or in the future require visa sponsorship employment visa H-1B transfer",
        target_profile_path="work_authorization.requires_sponsorship",
        description="Future immigration or visa sponsorship requirement"
    ),
    TaxonomyAnchor(
        category="YEARS_EXPERIENCE",
        anchor_text="how many total years of professional full time work experience do you have",
        target_profile_path="experience.total_years",
        description="Overall tenure of professional experience"
    ),
    TaxonomyAnchor(
        category="SKILL_EXPERIENCE",
        anchor_text="how many years of experience with Python React AWS Docker Kubernetes",
        target_profile_path="skills",
        description="Technology or tool tenure questions"
    ),
    TaxonomyAnchor(
        category="EDUCATION",
        anchor_text="what is your highest completed education level degree university college",
        target_profile_path="education.highest_degree",
        description="Highest academic qualification"
    ),
    TaxonomyAnchor(
        category="COMPENSATION",
        anchor_text="what is your desired annual base salary expectation compensation rate",
        target_profile_path="preferences.desired_salary_min",
        description="Remuneration and salary expectations"
    )
]

def classify_question_intent(raw_question: str, scorer: SemanticScorer) -> Dict[str, Any]:
    """
    Classifies screening question intent against canonical taxonomy centroids.
    CRITICAL: This function ONLY classifies intent. It NEVER generates or guesses answer values.
    """
    normalized = raw_question.strip().lower()

    # Deterministic high-confidence matches on explicit keywords
    if "sponsorship" in normalized or "sponsor" in normalized:
        return {
            "raw_question": raw_question,
            "category": "SPONSORSHIP",
            "confidence": 0.98,
            "target_profile_path": "work_authorization.requires_sponsorship",
            "explanation": "Deterministic match on sponsorship keywords",
            "method": "DETERMINISTIC_RULE"
        }

    if "legally authorized" in normalized or "work authorization" in normalized or "authorized to work" in normalized:
        return {
            "raw_question": raw_question,
            "category": "WORK_AUTHORIZATION",
            "confidence": 0.98,
            "target_profile_path": "work_authorization.authorized_in_us",
            "explanation": "Deterministic match on work authorization keywords",
            "method": "DETERMINISTIC_RULE"
        }

    # Semantic centroid similarity calculation
    best_category = "UNKNOWN"
    best_score = 0.0
    best_target_path = None

    for anchor in TAXONOMY_ANCHORS:
        sim = scorer.similarity(raw_question, anchor.anchor_text)
        if sim > best_score:
            best_score = sim
            best_category = anchor.category
            best_target_path = anchor.target_profile_path

    if best_score >= 0.40:
        return {
            "raw_question": raw_question,
            "category": best_category,
            "confidence": round(best_score, 2),
            "target_profile_path": best_target_path,
            "explanation": f"Semantic centroid match to {best_category} (similarity: {best_score:.3f})",
            "method": "HF_EMBEDDING_CENTROID"
        }

    return {
        "raw_question": raw_question,
        "category": "UNKNOWN",
        "confidence": round(best_score, 2),
        "target_profile_path": None,
        "explanation": "Question intent below confidence threshold; requires human review",
        "method": "FALLBACK"
    }
