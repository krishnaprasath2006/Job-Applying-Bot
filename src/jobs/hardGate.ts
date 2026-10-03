import type { CandidateProfile, JobRequirement, HardGateResult } from '../types/index.js';

/**
 * Hard Requirement Gate:
 * Evaluates absolute non-negotiables:
 * 1. Work authorization / Visa sponsorship constraints.
 * 2. Minimum total years of professional experience.
 * NOTE: A failure at this gate can NEVER be overridden by any semantic similarity or AI score.
 */
export function evaluateHardGate(
  profile: CandidateProfile,
  requirements: JobRequirement[]
): HardGateResult {
  const reasons: string[] = [];

  const requiresSponsorshipFact = profile.work_authorization.requires_sponsorship.value;
  const authorizedInUsFact = profile.work_authorization.authorized_in_us.value;
  const candidateYears = profile.experience.total_years.value || 0;

  for (const req of requirements) {
    const textLower = req.text.toLowerCase();

    // Check Visa Sponsorship Veto
    if (
      (textLower.includes('no sponsorship') ||
        textLower.includes('must be authorized without sponsorship') ||
        textLower.includes('no visa sponsorship')) &&
      requiresSponsorshipFact === true
    ) {
      reasons.push(
        `Job requires no visa sponsorship, but candidate requires sponsorship (work_authorization.requires_sponsorship=true)`
      );
    }

    // Check US Authorization Veto
    if (
      (textLower.includes('us citizen') || textLower.includes('authorized to work in us')) &&
      authorizedInUsFact === false
    ) {
      reasons.push(
        `Job requires US work authorization, but candidate is not authorized (work_authorization.authorized_in_us=false)`
      );
    }

    // Check Minimum Experience Veto
    if (req.minYears && req.minYears > 0) {
      if (candidateYears < req.minYears - 1) {
        reasons.push(
          `Candidate experience (${candidateYears} yrs) is significantly below mandatory minimum requirement (${req.minYears} yrs for '${req.text}')`
        );
      }
    }
  }

  return {
    status: reasons.length > 0 ? 'FAIL' : 'PASS',
    reasons
  };
}
