export type FactStatus = 'VERIFIED' | 'INFERRED' | 'UNKNOWN';

export interface FactEvidence {
  source_type: string;
  source_id: string;
  source_location: string;
  text_excerpt: string;
  created_at: string;
}

export interface CandidateFact<T> {
  field_path: string;
  value: T | null;
  status: FactStatus;
  source: string | null;
  source_id?: string | null;
  source_location?: string | null;
  confidence: number;
  verified_at?: string | null;
  evidence: FactEvidence[];
}

export interface CandidateProfile {
  id: string;
  candidate_id: string;
  version: number;
  updated_at: string;
  identity: {
    full_name: CandidateFact<string>;
    preferred_name: CandidateFact<string>;
    email: CandidateFact<string>;
    phone: CandidateFact<string>;
    location: CandidateFact<string>;
    linkedin_url: CandidateFact<string>;
    github_url: CandidateFact<string>;
    website_url: CandidateFact<string>;
  };
  work_authorization: {
    authorized_in_us: CandidateFact<boolean>;
    requires_sponsorship: CandidateFact<boolean>;
    visa_status: CandidateFact<string>;
    security_clearance: CandidateFact<string>;
  };
  experience: {
    total_years: CandidateFact<number>;
    current_title: CandidateFact<string>;
    target_roles: CandidateFact<string[]>;
    seniority_level: CandidateFact<string>;
  };
  education: {
    highest_degree: CandidateFact<string>;
    field_of_study: CandidateFact<string>;
    institution: CandidateFact<string>;
    graduation_year: CandidateFact<number>;
  };
  skills: Array<{
    name: string;
    years: number;
    proficiency: 'Beginner' | 'Intermediate' | 'Advanced' | 'Expert';
    category: string;
    status: FactStatus;
  }>;
  preferences: {
    desired_salary_min: number;
    desired_locations: string[];
    remote_only: boolean;
    excluded_keywords: string[];
  };
}

export interface ResumeVariant {
  id: string;
  name: string;
  targetRole: string;
  filename: string;
  format: 'pdf' | 'docx' | 'txt';
  isSynthetic: boolean;
  isActive: boolean;
  uploadedAt: string;
  skillsCount: number;
  summary: string;
  contentSnippet: string;
}

export type RequirementKind =
  | 'LANGUAGES'
  | 'FRAMEWORKS'
  | 'DATABASES'
  | 'CLOUD_DEVOPS'
  | 'DEGREE'
  | 'YEARS_OF_EXPERIENCE'
  | 'WORK_AUTHORIZATION'
  | 'SOFT_SKILLS'
  | 'OTHER';

export type RequirementPriority = 'REQUIRED' | 'PREFERRED' | 'UNKNOWN';

export type RequirementEvaluation =
  | 'VERIFIED_MATCH'
  | 'DERIVED_MATCH'
  | 'PARTIAL_MATCH'
  | 'DERIVED_MISS'
  | 'REVIEW_NEEDED'
  | 'UNKNOWN';

export interface JobRequirement {
  id: string;
  text: string;
  category: RequirementKind;
  priority: RequirementPriority;
  minYears?: number | null;
  evidence?: string | null;
}

export interface HardGateResult {
  status: 'PASS' | 'FAIL' | 'UNKNOWN';
  reasons: string[];
}

export interface RequirementScore {
  requirement_text: string;
  kind: RequirementKind;
  priority: RequirementPriority;
  evaluation: RequirementEvaluation;
  similarity: number | null;
  reason: string;
  candidate_field_path?: string | null;
}

export type MatchDecision =
  | 'STRONG_MATCH'
  | 'GOOD_MATCH'
  | 'PARTIAL_MATCH'
  | 'HARD_MISMATCH'
  | 'UNKNOWN';

export interface MatchResult {
  decision: MatchDecision;
  overallScore: number;
  gate: HardGateResult;
  scores: RequirementScore[];
  summary: string;
}

export type JobStatus =
  | 'DISCOVERED'
  | 'IN_REVIEW'
  | 'ACCEPTED'
  | 'REJECTED'
  | 'APPLIED';

export interface Job {
  id: string;
  title: string;
  company: string;
  location: string;
  remoteType: 'Remote' | 'Hybrid' | 'On-site';
  easyApply: boolean;
  salaryRange: string;
  postedDate: string;
  url: string;
  description: string;
  status: JobStatus;
  extractedRequirements: JobRequirement[];
  matchResult: MatchResult;
  reviewNotes?: string;
  reviewedAt?: string;
  appliedAt?: string;
  applicationMode?: 'DRY_RUN_SIMULATED' | 'REAL_SUBMISSION';
}

export interface SafetySettings {
  safeMode: boolean;
  dryRun: boolean;
  requireHumanApproval: boolean;
  allowBrowserNavigation: boolean;
  allowFileUpload: boolean;
  allowFormFilling: boolean;
  allowFinalSubmission: boolean;
  maxApplicationsPerRun: number;
  applicationsToday: number;
  blockOnCaptcha: boolean;
  blockOnMfa: boolean;
  recordScreenshots: boolean;
}

export interface CustomQuestionRule {
  id: string;
  keyword: string;
  questionPattern: string;
  answerType: 'number' | 'text' | 'boolean' | 'choice';
  answerValue: string;
  category: 'Tech Skills' | 'Work Authorization' | 'Personal' | 'Compensation' | 'General';
}

export interface QuestionAnswerResponse {
  question: string;
  suggestedAnswer: string;
  confidence: 'HIGH' | 'MEDIUM' | 'LOW';
  matchedRule?: string;
  reasoning: string;
  source: string;
}

// -------------------------------------------------------------
// AI & Hugging Face Local Embedding Types (Milestone HF-1)
// -------------------------------------------------------------
export type ModelCapability = 'embeddings' | 'reranking' | 'text_generation' | 'json_generation';

export interface AIProviderConfig {
  provider: 'huggingface_local' | 'ollama' | 'lexical';
  modelId: string;
  cacheDir: string;
  enabled: boolean;
  device: 'cpu' | 'gpu';
  dimension: number;
  runtime: 'onnx' | 'transformers_js';
}

export interface ModelMetadata {
  provider: string;
  modelId: string;
  dimension: number;
  device: string;
  runtime: string;
  modelRevision?: string;
  loaded: boolean;
  supportsBatching: boolean;
  zeroCost: boolean;
  license: string;
}

export interface ModelCacheFingerprint {
  provider: string;
  modelId: string;
  modelRevision: string;
  dimension: number;
  inputHash: string;
  createdAt: string;
}

export type QuestionTaxonomyCategory =
  | 'WORK_AUTHORIZATION'
  | 'SPONSORSHIP'
  | 'YEARS_EXPERIENCE'
  | 'SKILL_EXPERIENCE'
  | 'EDUCATION'
  | 'COMPENSATION'
  | 'AVAILABILITY'
  | 'LOCATION'
  | 'UNKNOWN';

export interface QuestionIntentClassification {
  rawQuestion: string;
  category: QuestionTaxonomyCategory;
  confidence: number;
  targetProfilePath?: string;
  explanation: string;
  method: 'DETERMINISTIC_RULE' | 'HF_EMBEDDING_CENTROID' | 'FALLBACK';
}

export interface ResumeRelevanceResult {
  resumeId: string;
  overallRelevance: number;
  sectionScores: Array<{
    section: string;
    score: number;
  }>;
  method: 'HF_SEMANTIC_EMBEDDING' | 'LEXICAL_FALLBACK';
  timestamp: string;
}

