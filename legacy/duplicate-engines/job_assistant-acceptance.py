#!/usr/bin/env python3
import sys
import json
from src.core.enums import (
    FactStatus,
    HardGateStatus,
    MatchDecision,
    RequirementKind,
    RequirementPriority,
    RequirementEvaluation,
    ModelCapability
)
from src.core.settings import global_settings
from src.core.errors import SafetyViolationError
from src.safety.policies import global_safety_policy, Action
from src.profile.models import (
    CandidateProfile,
    CandidateFact,
    SkillClaim,
    WorkAuthorization,
    ExperienceSummary,
    EducationSummary
)
from src.jobs.models import JobRequirement
from src.jobs.hard_gate import evaluate_hard_gate
from src.jobs.matching import evaluate_job_match
from src.jobs.relevance import score_resume_relevance
from src.ai.huggingface import HuggingFaceLocalProvider
from src.ai.embeddings import EmbeddingScorer, LexicalScorer
from src.ai.registry import global_model_registry
from src.ai.question_intent import classify_question_intent

def build_sample_candidate_profile(requires_sponsorship: bool = False, authorized_in_us: bool = True) -> CandidateProfile:
    return CandidateProfile(
        id="cand-001",
        full_name=CandidateFact("full_name", "Jane Doe", FactStatus.VERIFIED),
        email=CandidateFact("email", "jane.doe@example.com", FactStatus.VERIFIED),
        phone=CandidateFact("phone", "+1-555-0199", FactStatus.VERIFIED),
        location=CandidateFact("location", "San Francisco, CA", FactStatus.VERIFIED),
        work_authorization=WorkAuthorization(
            authorized_in_us=CandidateFact("work_authorization.authorized_in_us", authorized_in_us, FactStatus.VERIFIED),
            requires_sponsorship=CandidateFact("work_authorization.requires_sponsorship", requires_sponsorship, FactStatus.VERIFIED),
            visa_status=CandidateFact("work_authorization.visa_status", "US Citizen" if authorized_in_us else "H-1B", FactStatus.VERIFIED),
            security_clearance=CandidateFact("work_authorization.security_clearance", "None", FactStatus.VERIFIED)
        ),
        experience=ExperienceSummary(
            total_years=CandidateFact("experience.total_years", 6.5, FactStatus.VERIFIED),
            current_title=CandidateFact("experience.current_title", "Senior Full-Stack Engineer", FactStatus.VERIFIED),
            target_roles=CandidateFact("experience.target_roles", ["Software Engineer", "Full-Stack Engineer"], FactStatus.VERIFIED)
        ),
        education=EducationSummary(
            highest_degree=CandidateFact("education.highest_degree", "Bachelor of Science in Computer Science", FactStatus.VERIFIED),
            field_of_study=CandidateFact("education.field_of_study", "Computer Science", FactStatus.VERIFIED),
            institution=CandidateFact("education.institution", "University of California, Berkeley", FactStatus.VERIFIED)
        ),
        skills=[
            SkillClaim("Python", 5.0, "Expert", "Languages", FactStatus.VERIFIED),
            SkillClaim("React", 4.0, "Advanced", "Frameworks", FactStatus.VERIFIED),
            SkillClaim("TypeScript", 4.0, "Advanced", "Languages", FactStatus.VERIFIED),
            SkillClaim("PostgreSQL", 4.0, "Advanced", "Databases", FactStatus.VERIFIED),
            SkillClaim("Docker", 3.0, "Intermediate", "DevOps", FactStatus.VERIFIED),
        ]
    )

def run_acceptance_tests() -> int:
    print("=" * 60)
    print("AI STUDIO JOB ASSISTANT — ACCEPTANCE VERIFICATION SUITE")
    print("=" * 60)
    passed = 0
    total = 0

    def assert_test(name: str, condition: bool, detail: str = ""):
        nonlocal passed, total
        total += 1
        if condition:
            passed += 1
            print(f" [PASS] {name} {('- ' + detail) if detail else ''}")
        else:
            print(f" [FAIL] {name} - FAILED: {detail}")
            sys.exit(1)

    # 1. Safety Invariants Verification
    print("\n--- 1. Safety Policy Invariants ---")
    try:
        global_safety_policy.assert_phase2_invariants()
        assert_test("Dry-run & permanent submission freeze", True)
    except SafetyViolationError as e:
        assert_test("Dry-run & permanent submission freeze", False, str(e))

    try:
        global_safety_policy.check(Action.SUBMIT_APPLICATION)
        assert_test("Submission action permanently blocked", False, "Expected SafetyViolationError")
    except SafetyViolationError:
        assert_test("Submission action permanently blocked", True)

    # 2. Hugging Face Local Provider Verification
    print("\n--- 2. Hugging Face Local Provider & Cache ---")
    hf_provider = HuggingFaceLocalProvider(offline_mode=True)
    assert_test("HF Provider supports EMBEDDINGS", hf_provider.supports(ModelCapability.EMBEDDINGS))
    assert_test("HF Provider dimension is 384", hf_provider.dimension == 384)
    meta = hf_provider.get_metadata()
    assert_test("HF Provider ₹0 cost verified", meta.zero_cost is True)
    assert_test("HF Provider device is CPU", meta.device == "cpu")

    vectors = hf_provider.get_embeddings(["Python backend engineering", "React frontend development"])
    assert_test("Generated 2 embeddings", len(vectors) == 2)
    assert_test("Vector 1 dimension matches 384", len(vectors[0]) == 384)
    assert_test("Vector 2 dimension matches 384", len(vectors[1]) == 384)

    # 3. Embedding Scorer & Graceful Fallback
    print("\n--- 3. Semantic Scorer & Lexical Fallback ---")
    scorer = EmbeddingScorer(hf_provider)
    sim_high = scorer.similarity("Python programming language", "Python software development")
    sim_low = scorer.similarity("Python programming language", "French culinary pastry baking")
    assert_test("Semantic similarity discriminates domain concepts", sim_high > sim_low, f"high={sim_high:.3f}, low={sim_low:.3f}")

    # Lexical fallback check
    lexical = LexicalScorer()
    lex_sim = lexical.similarity("Docker containerization", "Docker containerization deployment")
    assert_test("Lexical fallback calculates Jaccard token overlap", lex_sim > 0.0)

    # 4. Hard Gate Authoritative Veto Verification
    print("\n--- 4. Hard Gate Authoritative Veto ---")
    candidate_sponsored = build_sample_candidate_profile(requires_sponsorship=True)
    strict_visa_job = [
        JobRequirement("r1", "Candidates must not require visa sponsorship now or in future", RequirementKind.WORK_AUTHORIZATION, RequirementPriority.REQUIRED),
        JobRequirement("r2", "Python", RequirementKind.LANGUAGES, RequirementPriority.REQUIRED)
    ]
    match_veto = evaluate_job_match(candidate_sponsored, strict_visa_job, scorer=scorer)
    assert_test(
        "Hard Gate Veto triggers HARD_MISMATCH regardless of high Python skill",
        match_veto.decision == MatchDecision.HARD_MISMATCH and match_veto.overall_score == 0
    )
    assert_test(
        "Hard Gate status is FAIL",
        match_veto.gate.status == HardGateStatus.FAIL
    )

    # 5. Candidate Fact Immutability Verification
    print("\n--- 5. Candidate Fact Immutability ---")
    candidate_standard = build_sample_candidate_profile(requires_sponsorship=False)
    initial_skills = [s.name for s in candidate_standard.skills]
    initial_sponsorship = candidate_standard.work_authorization.requires_sponsorship.value

    job_reqs = [
        JobRequirement("j1", "Python", RequirementKind.LANGUAGES, RequirementPriority.REQUIRED),
        JobRequirement("j2", "Kubernetes orchestration", RequirementKind.CLOUD_DEVOPS, RequirementPriority.PREFERRED),
    ]
    match_result = evaluate_job_match(candidate_standard, job_reqs, scorer=scorer)

    assert_test("Candidate skills unchanged post-match", [s.name for s in candidate_standard.skills] == initial_skills)
    assert_test("Candidate fact status unchanged post-match", candidate_standard.work_authorization.requires_sponsorship.value == initial_sponsorship)
    assert_test("Missing skill not converted to verified", all(s.name != "Kubernetes" for s in candidate_standard.skills))

    # 6. Resume Relevance Scoring
    print("\n--- 6. Resume Section Relevance Scoring ---")
    sample_resume = """
    SUMMARY
    Senior Full-Stack Engineer with 6+ years building distributed backend services in Python and React.
    
    EXPERIENCE
    Lead Engineer at TechCorp. Designed high-throughput microservices using Python and Docker.
    
    SKILLS
    Python, React, TypeScript, PostgreSQL, Docker, Git
    """
    rel_result = score_resume_relevance("res-1", sample_resume, job_reqs, scorer=scorer)
    assert_test("Resume relevance returns valid overall score", rel_result["overall_relevance"] > 0.0)
    assert_test("Section scores breakdown populated", len(rel_result["section_scores"]) >= 2)

    # 7. Question Intent Classification Foundation
    print("\n--- 7. Screening Question Intent Foundation ---")
    q1 = "Will you now or in the future require employment visa sponsorship?"
    intent1 = classify_question_intent(q1, scorer=scorer)
    assert_test("Question intent classifies sponsorship", intent1["category"] == "SPONSORSHIP")
    assert_test("Question intent maps target path without guessing answer", intent1["target_profile_path"] == "work_authorization.requires_sponsorship")

    q2 = "Are you legally authorized to work in the United States?"
    intent2 = classify_question_intent(q2, scorer=scorer)
    assert_test("Question intent classifies work authorization", intent2["category"] == "WORK_AUTHORIZATION")

    print("\n" + "=" * 60)
    print(f"ACCEPTANCE SUITE SUMMARY: {passed}/{total} tests PASSED (100% SUCCESS)")
    print("=" * 60)
    return 0

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "acceptance":
        sys.exit(run_acceptance_tests())
    
    print("Job Assistant CLI")
    print("Usage: python job_assistant.py acceptance")
    sys.exit(0)

if __name__ == "__main__":
    main()
