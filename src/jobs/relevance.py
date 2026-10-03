import re
from typing import List, Dict, Any, Optional
from src.jobs.models import JobRequirement
from src.ai.embeddings import SemanticScorer, LexicalScorer

SECTION_HEADER_PATTERN = re.compile(
    r"^(SUMMARY|EXPERIENCE|WORK EXPERIENCE|EDUCATION|SKILLS|TECHNICAL SKILLS|PROJECTS|CERTIFICATIONS)",
    re.IGNORECASE
)

def extract_resume_sections(resume_text: str) -> List[Dict[str, str]]:
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    sections = []
    current_section = "General"
    current_lines = []

    for line in lines:
        if SECTION_HEADER_PATTERN.match(line):
            if current_lines:
                sections.append({
                    "section": current_section,
                    "content": " ".join(current_lines)
                })
                current_lines = []
            current_section = line.upper()
        else:
            current_lines.append(line)

    if current_lines:
        sections.append({
            "section": current_section,
            "content": " ".join(current_lines)
        })

    return sections or [{"section": "Full Resume", "content": resume_text}]

def score_resume_relevance(
    resume_id: str,
    resume_text: str,
    requirements: List[JobRequirement],
    scorer: Optional[SemanticScorer] = None
) -> Dict[str, Any]:
    active_scorer = scorer or LexicalScorer()
    sections = extract_resume_sections(resume_text)

    if not requirements or not sections:
        return {
            "resume_id": resume_id,
            "overall_relevance": 0.0,
            "section_scores": [],
            "method": "LEXICAL_FALLBACK" if isinstance(active_scorer, LexicalScorer) else "HF_SEMANTIC_EMBEDDING"
        }

    section_scores = []
    for sec in sections:
        sec_total = sum(active_scorer.similarity(req.text, sec["content"]) for req in requirements)
        avg_score = sec_total / len(requirements)
        section_scores.append({
            "section": sec["section"],
            "score": round(avg_score, 2)
        })

    weighted_sum = 0.0
    weight_total = 0.0

    for s in section_scores:
        w = 1.0
        sec_upper = s["section"].upper()
        if "SKILL" in sec_upper or "EXPERIENCE" in sec_upper:
            w = 2.0
        elif "SUMMARY" in sec_upper:
            w = 1.2
        weighted_sum += s["score"] * w
        weight_total += w

    overall = round(weighted_sum / weight_total, 2) if weight_total > 0 else 0.0

    return {
        "resume_id": resume_id,
        "overall_relevance": overall,
        "section_scores": section_scores,
        "method": "HF_SEMANTIC_EMBEDDING" if "EmbeddingScorer" in active_scorer.name else "LEXICAL_FALLBACK"
    }
