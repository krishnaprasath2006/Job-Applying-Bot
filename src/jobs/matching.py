from typing import List, Optional
from src.core.enums import (
    RequirementEvaluation,
    MatchDecision,
    HardGateStatus,
    RequirementPriority
)
from src.jobs.models import (
    JobRequirement,
    MatchResult,
    RequirementScore,
    HardGateResult
)
from src.jobs.hard_gate import evaluate_hard_gate
from src.profile.models import CandidateProfile
from src.ai.embeddings import SemanticScorer, LexicalScorer

def evaluate_job_match(
    profile: CandidateProfile,
    requirements: List[JobRequirement],
    scorer: Optional[SemanticScorer] = None
) -> MatchResult:
    active_scorer = scorer or LexicalScorer()

    # 1. Hard Gate Evaluation (AUTHORITATIVE VETO)
    gate_result = evaluate_hard_gate(profile, requirements)
    if gate_result.status == HardGateStatus.FAIL:
        scores = [
            RequirementScore(
                requirement_text=req.text,
                kind=req.category,
                priority=req.priority,
                evaluation=RequirementEvaluation.DERIVED_MISS,
                similarity=0.0,
                reason="Hard Requirement Gate Veto (Mandatory constraint failed)"
            )
            for req in requirements
        ]
        return MatchResult(
            decision=MatchDecision.HARD_MISMATCH,
            overall_score=0,
            gate=gate_result,
            scores=scores,
            summary=f"Hard Gate Veto: {'; '.join(gate_result.reasons)}"
        )

    # 2. Requirement Matching with Semantic Scorer
    scores: List[RequirementScore] = []
    total_score = 0.0
    required_count = 0
    required_matched_count = 0

    for req in requirements:
        # Check direct verified claim in candidate skills
        direct_match = next(
            (s for s in profile.skills if s.name.lower() == req.text.lower() or s.name.lower() in req.text.lower()),
            None
        )

        if direct_match:
            scores.append(
                RequirementScore(
                    requirement_text=req.text,
                    kind=req.category,
                    priority=req.priority,
                    evaluation=RequirementEvaluation.VERIFIED_MATCH,
                    similarity=1.0,
                    reason=f"Direct verified claim match ({direct_match.name}, {direct_match.years} yrs)",
                    candidate_field_path=f"skills[{direct_match.name}]"
                )
            )
            total_score += 1.0
            if req.priority == RequirementPriority.REQUIRED:
                required_count += 1
                required_matched_count += 1
            continue

        # Semantic distance evaluation
        best_sim = 0.0
        best_skill_name = ""

        for skill in profile.skills:
            sim = active_scorer.similarity(req.text, f"{skill.name} ({skill.proficiency})")
            if sim > best_sim:
                best_sim = sim
                best_skill_name = skill.name

        # Also check current job title
        current_title = profile.experience.current_title.value or ""
        title_sim = active_scorer.similarity(req.text, current_title)
        if title_sim > best_sim:
            best_sim = title_sim
            best_skill_name = current_title

        if best_sim >= 0.70:
            evaluation = RequirementEvaluation.DERIVED_MATCH
            reason = f"High semantic similarity ({best_sim:.2f}) with '{best_skill_name}' via {active_scorer.name}"
            total_score += best_sim
            if req.priority == RequirementPriority.REQUIRED:
                required_count += 1
                required_matched_count += 1
        elif best_sim >= 0.45:
            evaluation = RequirementEvaluation.REVIEW_NEEDED
            reason = f"Moderate semantic overlap ({best_sim:.2f}) with '{best_skill_name}'. Human review required."
            total_score += best_sim * 0.7
            if req.priority == RequirementPriority.REQUIRED:
                required_count += 1
        else:
            evaluation = RequirementEvaluation.DERIVED_MISS
            reason = f"Insufficient semantic overlap (best: {best_sim:.2f} with '{best_skill_name}')"
            if req.priority == RequirementPriority.REQUIRED:
                required_count += 1

        scores.append(
            RequirementScore(
                requirement_text=req.text,
                kind=req.category,
                priority=req.priority,
                evaluation=evaluation,
                similarity=round(best_sim, 2),
                reason=reason,
                candidate_field_path=f"skills[{best_skill_name}]" if best_skill_name else None
            )
        )

    overall_score = int(round((total_score / len(requirements)) * 100)) if requirements else 0

    if overall_score >= 80 and (required_count == 0 or required_matched_count / required_count >= 0.8):
        decision = MatchDecision.STRONG_MATCH
    elif overall_score >= 60 and (required_count == 0 or required_matched_count / required_count >= 0.6):
        decision = MatchDecision.GOOD_MATCH
    elif overall_score < 45:
        decision = MatchDecision.PARTIAL_MATCH
    else:
        decision = MatchDecision.PARTIAL_MATCH

    return MatchResult(
        decision=decision,
        overall_score=overall_score,
        gate=gate_result,
        scores=scores,
        summary=f"{decision.value}: Score {overall_score}%. Gate PASSED. {required_matched_count}/{required_count} core requirements matched."
    )
