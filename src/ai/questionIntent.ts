import type {
  QuestionTaxonomyCategory,
  QuestionIntentClassification
} from '../types/index.js';
import type { SemanticScorer } from './embeddings.js';

interface TaxonomyDefinition {
  category: QuestionTaxonomyCategory;
  anchorText: string;
  targetProfilePath?: string;
  description: string;
}

const TAXONOMY_ANCHORS: TaxonomyDefinition[] = [
  {
    category: 'WORK_AUTHORIZATION',
    anchorText: 'are you legally authorized to work in the United States without restriction citizen permanent resident',
    targetProfilePath: 'work_authorization.authorized_in_us',
    description: 'Legal authorization to work in the country'
  },
  {
    category: 'SPONSORSHIP',
    anchorText: 'will you now or in the future require visa sponsorship employment visa H-1B transfer green card',
    targetProfilePath: 'work_authorization.requires_sponsorship',
    description: 'Future immigration or visa sponsorship requirements'
  },
  {
    category: 'YEARS_EXPERIENCE',
    anchorText: 'how many total years of professional full-time software engineering work experience do you have',
    targetProfilePath: 'experience.total_years',
    description: 'Cumulative years of professional experience'
  },
  {
    category: 'SKILL_EXPERIENCE',
    anchorText: 'how many years of experience do you have with technology programming language framework tool Python React AWS Docker',
    targetProfilePath: 'skills',
    description: 'Specific technology tenure questions'
  },
  {
    category: 'EDUCATION',
    anchorText: 'what is your highest level of completed education degree university college Bachelor Master PhD',
    targetProfilePath: 'education.highest_degree',
    description: 'Academic degree attainment'
  },
  {
    category: 'COMPENSATION',
    anchorText: 'what is your desired annual base salary expectation target compensation rate pay hourly',
    targetProfilePath: 'preferences.desired_salary_min',
    description: 'Salary and remuneration expectations'
  },
  {
    category: 'AVAILABILITY',
    anchorText: 'what is your notice period earliest start date availability how soon can you start work',
    targetProfilePath: undefined,
    description: 'Notice period and work start timing'
  },
  {
    category: 'LOCATION',
    anchorText: 'are you willing to relocate or commute to office location in-person on-site hybrid requirement',
    targetProfilePath: 'preferences.desired_locations',
    description: 'Office commute and relocation willingness'
  }
];

/**
 * Classifies raw screening question intent against canonical taxonomy definitions
 * using semantic embeddings or lexical fallback.
 * NOTE: This component ONLY classifies intent. It NEVER generates or guesses answer values.
 */
export async function classifyQuestionIntent(
  rawQuestion: string,
  scorer: SemanticScorer
): Promise<QuestionIntentClassification> {
  const normalized = rawQuestion.trim().toLowerCase();

  // 1. Fast deterministic keyword match for unambiguous high-frequency legal questions
  if (normalized.includes('sponsorship') || normalized.includes('sponsor')) {
    return {
      rawQuestion,
      category: 'SPONSORSHIP',
      confidence: 0.98,
      targetProfilePath: 'work_authorization.requires_sponsorship',
      explanation: 'Deterministic match on sponsorship keyword',
      method: 'DETERMINISTIC_RULE'
    };
  }

  if (
    normalized.includes('legally authorized') ||
    normalized.includes('work authorization') ||
    normalized.includes('authorized to work')
  ) {
    return {
      rawQuestion,
      category: 'WORK_AUTHORIZATION',
      confidence: 0.98,
      targetProfilePath: 'work_authorization.authorized_in_us',
      explanation: 'Deterministic match on legal work authorization keywords',
      method: 'DETERMINISTIC_RULE'
    };
  }

  // 2. Semantic Embedding Centroid similarity calculation
  let bestCategory: QuestionTaxonomyCategory = 'UNKNOWN';
  let bestScore = 0.0;
  let bestAnchor: TaxonomyDefinition | undefined = undefined;

  for (const anchor of TAXONOMY_ANCHORS) {
    const score = await scorer.similarity(rawQuestion, anchor.anchorText);
    if (score > bestScore) {
      bestScore = score;
      bestCategory = anchor.category;
      bestAnchor = anchor;
    }
  }

  // Minimum threshold to prevent spurious matching on alien questions
  const MIN_CONFIDENCE_THRESHOLD = 0.40;

  if (bestScore >= MIN_CONFIDENCE_THRESHOLD && bestAnchor) {
    return {
      rawQuestion,
      category: bestCategory,
      confidence: Math.round(bestScore * 100) / 100,
      targetProfilePath: bestAnchor.targetProfilePath,
      explanation: `Semantic centroid match to ${bestCategory} (similarity: ${bestScore.toFixed(3)})`,
      method: 'HF_EMBEDDING_CENTROID'
    };
  }

  return {
    rawQuestion,
    category: 'UNKNOWN',
    confidence: Math.round(bestScore * 100) / 100,
    explanation: 'Question intent fell below confidence threshold; requires human review',
    method: 'FALLBACK'
  };
}
