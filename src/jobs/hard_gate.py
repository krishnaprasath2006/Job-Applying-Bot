from src.core.enums import HardGateStatus
from src.jobs.models import HardGateResult, JobRequirement
from src.profile.models import CandidateProfile

def evaluate_hard_gate(
    profile: CandidateProfile,
    requirements: list[JobRequirement]
) -> HardGateResult:
    """
    Evaluates mandatory non-negotiable requirements:
    1. Visa sponsorship veto.
    2. Work authorization veto.
    3. Severe minimum years deficit.
    CRITICAL: A failure here produces an irreversible veto that semantic scores cannot bypass.
    """
    reasons = []

    sponsorship_needed = profile.work_authorization.requires_sponsorship.value
    authorized_in_us = profile.work_authorization.authorized_in_us.value
    candidate_years = profile.experience.total_years.value or 0.0

    for req in requirements:
        text_lower = req.text.lower()

        # Visa sponsorship constraint
        if ("no sponsorship" in text_lower or "no visa sponsorship" in text_lower or "without sponsorship" in text_lower) and sponsorship_needed:
            reasons.append(
                "Job requires candidate not require visa sponsorship, but candidate profile specifies requires_sponsorship=True"
            )

        # US authorization constraint
        if ("us citizen" in text_lower or "authorized to work in us" in text_lower or "us work authorization" in text_lower) and not authorized_in_us:
            reasons.append(
                "Job requires US work authorization, but candidate profile specifies authorized_in_us=False"
            )

        # Severe experience constraint
        if req.min_years and req.min_years > 0:
            if candidate_years < req.min_years - 1.5:
                reasons.append(
                    f"Candidate total experience ({candidate_years} yrs) severely below required minimum ({req.min_years} yrs for '{req.text}')"
                )

    status = HardGateStatus.FAIL if reasons else HardGateStatus.PASS
    return HardGateResult(status=status, reasons=reasons)
