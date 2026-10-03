import type {
  CandidateProfile,
  JobRequirement,
  MatchResult,
  RequirementScore,
  MatchDecision
} from '../types/index.js';
import { evaluateHardGate } from './hardGate.js';
import type { SemanticScorer } from '../ai/embeddings.js';
import { LexicalScorer } from '../ai/embeddings.js';

export async function evaluateJobMatch(
  profile: CandidateProfile,
  requirements: JobRequirement[],
  scorer?: SemanticScorer
): Promise<MatchResult> {
  const activeScorer = scorer || new LexicalScorer();

  // 1. Hard Gate Evaluation (AUTHORITATIVE - NEVER OUTVOTED)
  const gateResult = evaluateHardGate(profile, requirements);
  if (gateResult.status === 'FAIL') {
    const scores: RequirementScore[] = requirements.map((req) => ({
      requirement_text: req.text,
      kind: req.category,
      priority: req.priority,
      evaluation: 'DERIVED_MISS',
      similarity: 0.0,
      reason: 'Hard Requirement Gate Veto (Non-negotiable qualification failed)'
    }));

    return {
      decision: 'HARD_MISMATCH',
      overallScore: 0,
      gate: gateResult,
      scores,
      summary: `Hard Gate Veto: ${gateResult.reasons.join('; ')}`
    };
  }

  // 2. Requirement Matching with Semantic Scorer
  const scores: RequirementScore[] = [];
  let totalScore = 0;
  let requiredCount = 0;
  let requiredMatchedCount = 0;

  for (const req of requirements) {
    let matchedSkill = profile.skills.find(
      (s) =>
        s.name.toLowerCase() === req.text.toLowerCase() ||
        req.text.toLowerCase().includes(s.name.toLowerCase())
    );

    if (matchedSkill) {
      scores.push({
        requirement_text: req.text,
        kind: req.category,
        priority: req.priority,
        evaluation: 'VERIFIED_MATCH',
        similarity: 1.0,
        reason: `Direct verified claim match (${matchedSkill.name}, ${matchedSkill.years} yrs)`,
        candidate_field_path: `skills[${matchedSkill.name}]`
      });
      totalScore += 1.0;
      if (req.priority === 'REQUIRED') {
        requiredCount++;
        requiredMatchedCount++;
      }
      continue;
    }

    // Evaluate against candidate skills using semantic similarity
    let highestSim = 0.0;
    let bestSkillName = '';

    for (const skill of profile.skills) {
      const sim = await activeScorer.similarity(req.text, `${skill.name} (${skill.proficiency})`);
      if (sim > highestSim) {
        highestSim = sim;
        bestSkillName = skill.name;
      }
    }

    // Also check current and target job titles
    const titleSim = await activeScorer.similarity(
      req.text,
      profile.experience.current_title.value || ''
    );
    if (titleSim > highestSim) {
      highestSim = titleSim;
      bestSkillName = profile.experience.current_title.value || '';
    }

    let evaluation: RequirementScore['evaluation'] = 'UNKNOWN';
    let reason = '';

    if (highestSim >= 0.70) {
      evaluation = 'DERIVED_MATCH';
      reason = `High semantic similarity (${highestSim.toFixed(2)}) with candidate skill '${bestSkillName}' via ${activeScorer.name}`;
      totalScore += highestSim;
      if (req.priority === 'REQUIRED') {
        requiredCount++;
        requiredMatchedCount++;
      }
    } else if (highestSim >= 0.45) {
      evaluation = 'REVIEW_NEEDED';
      reason = `Moderate semantic overlap (${highestSim.toFixed(2)}) with '${bestSkillName}'. Human review recommended.`;
      totalScore += highestSim * 0.7;
      if (req.priority === 'REQUIRED') requiredCount++;
    } else {
      evaluation = 'DERIVED_MISS';
      reason = `Insufficient semantic overlap (best: ${highestSim.toFixed(2)} with '${bestSkillName}').`;
      if (req.priority === 'REQUIRED') requiredCount++;
    }

    scores.push({
      requirement_text: req.text,
      kind: req.category,
      priority: req.priority,
      evaluation,
      similarity: Math.round(highestSim * 100) / 100,
      reason,
      candidate_field_path: bestSkillName ? `skills[${bestSkillName}]` : undefined
    });
  }

  const overallScore =
    requirements.length > 0 ? Math.round((totalScore / requirements.length) * 100) : 0;

  // Determine overall match decision
  let decision: MatchDecision = 'PARTIAL_MATCH';
  if (overallScore >= 80 && (requiredCount === 0 || requiredMatchedCount / requiredCount >= 0.8)) {
    decision = 'STRONG_MATCH';
  } else if (overallScore >= 60 && (requiredCount === 0 || requiredMatchedCount / requiredCount >= 0.6)) {
    decision = 'GOOD_MATCH';
  } else if (overallScore < 45) {
    decision = 'PARTIAL_MATCH';
  }

  return {
    decision,
    overallScore,
    gate: gateResult,
    scores,
    summary: `${decision}: Score ${overallScore}%. Gate PASSED. ${requiredMatchedCount}/${requiredCount} core requirements satisfied.`
  };
}
