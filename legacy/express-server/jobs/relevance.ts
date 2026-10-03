import type { JobRequirement, ResumeRelevanceResult } from '../types/index.js';
import type { SemanticScorer } from '../ai/embeddings.js';
import { LexicalScorer } from '../ai/embeddings.js';

export interface ResumeSectionBlock {
  sectionName: string;
  content: string;
}

/**
 * Splits resume text into heuristic section blocks (Summary, Skills, Experience, Education, Projects).
 */
export function extractResumeSections(resumeText: string): ResumeSectionBlock[] {
  const lines = resumeText.split('\n').map((l) => l.trim()).filter(Boolean);
  const sections: ResumeSectionBlock[] = [];

  let currentSection = 'General';
  let currentLines: string[] = [];

  const sectionHeaders = /^(SUMMARY|EXPERIENCE|WORK EXPERIENCE|EDUCATION|SKILLS|TECHNICAL SKILLS|PROJECTS|CERTIFICATIONS)/i;

  for (const line of lines) {
    if (sectionHeaders.test(line)) {
      if (currentLines.length > 0) {
        sections.push({
          sectionName: currentSection,
          content: currentLines.join(' ')
        });
        currentLines = [];
      }
      currentSection = line.toUpperCase();
    } else {
      currentLines.push(line);
    }
  }

  if (currentLines.length > 0) {
    sections.push({
      sectionName: currentSection,
      content: currentLines.join(' ')
    });
  }

  return sections.length > 0 ? sections : [{ sectionName: 'Full Resume', content: resumeText }];
}

/**
 * Evaluates the semantic relevance of a resume against a set of job requirements.
 * Accepts any SemanticScorer (Hugging Face EmbeddingScorer or LexicalScorer fallback).
 */
export async function scoreResumeRelevance(
  resumeId: string,
  resumeText: string,
  requirements: JobRequirement[],
  scorer?: SemanticScorer
): Promise<ResumeRelevanceResult> {
  const activeScorer = scorer || new LexicalScorer();
  const sections = extractResumeSections(resumeText);

  if (requirements.length === 0 || sections.length === 0) {
    return {
      resumeId,
      overallRelevance: 0.0,
      sectionScores: [],
      method: activeScorer instanceof LexicalScorer ? 'LEXICAL_FALLBACK' : 'HF_SEMANTIC_EMBEDDING',
      timestamp: new Date().toISOString()
    };
  }

  const requirementTexts = requirements.map((r) => r.text);
  const sectionScores: Array<{ section: string; score: number }> = [];

  for (const section of sections) {
    let sectionTotal = 0;
    for (const reqText of requirementTexts) {
      const sim = await activeScorer.similarity(reqText, section.content);
      sectionTotal += sim;
    }
    const sectionAvg = sectionTotal / requirementTexts.length;
    sectionScores.push({
      section: section.sectionName,
      score: Math.round(sectionAvg * 100) / 100
    });
  }

  // Weight Experience and Skills sections higher if present
  let weightedSum = 0;
  let weightTotal = 0;

  for (const s of sectionScores) {
    let weight = 1.0;
    if (s.section.includes('SKILL')) weight = 2.0;
    if (s.section.includes('EXPERIENCE')) weight = 2.0;
    if (s.section.includes('SUMMARY')) weight = 1.2;

    weightedSum += s.score * weight;
    weightTotal += weight;
  }

  const overall = weightTotal > 0 ? weightedSum / weightTotal : 0;

  return {
    resumeId,
    overallRelevance: Math.round(overall * 100) / 100,
    sectionScores,
    method: activeScorer.name.includes('EmbeddingScorer')
      ? 'HF_SEMANTIC_EMBEDDING'
      : 'LEXICAL_FALLBACK',
    timestamp: new Date().toISOString()
  };
}
