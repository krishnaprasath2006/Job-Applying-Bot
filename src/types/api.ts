// FastAPI-compatible TypeScript types
// These match the actual FastAPI response schemas from R1-B
// DO NOT implement business logic here - these are transport contracts only

export interface ApiErrorResponse {
  error: {
    code: string;
    message: string;
    details: Record<string, any>;
  };
}

export interface CountSummary {
  count: number;
  query?: string;
}

export interface HealthReport {
  status: 'alive';
  service: string;
  version: string;
}

export interface ReadyReport {
  status: 'ready' | 'not_ready';
  checks: Record<string, boolean>;
  migration_version?: string;
  detail?: string;
}

export interface SafetyReport {
  dry_run: boolean;
  safe_mode: boolean;
  require_human_approval: boolean;
  allow_final_submission: boolean;
  actions?: Record<string, boolean>;
  submission_possible: boolean;
}

export interface DatabaseReport {
  path: string;
  tables: string[];
  profiles: number;
  resumes: number;
  evidence: number;
  model_runs: number;
  jobs: number;
  queued_for_review: number;
  open_reviews: number;
}

export interface AiStatusReport {
  configured: boolean;
  provider: string;
  model: string;
  api_key_present: boolean;
  providers_available: string[];
  embedding_scorer_available: boolean;
  source_mode: string;
  allows_application: boolean;
}

export interface ApiStatusReport {
  service: string;
  version: string;
  safety: SafetyReport;
  paths: Record<string, any>;
  database: DatabaseReport;
  configuration: Record<string, any>;
  ai: AiStatusReport;
}

// Profile types

/** Truth state of a single candidate fact. Only VERIFIED is application-safe. */
export type FactStatus = 'VERIFIED' | 'INFERRED' | 'UNKNOWN';

export interface FactEvidence {
  source_type: string;
  source_id?: string;
  source_location?: string;
  text_excerpt?: string;
  confidence: number;
  created_at: string;
}

export interface FactResponse {
  field_path: string;
  value: any;
  status: FactStatus;
  evidence: FactEvidence[];
  verified_at?: string;
  note?: string;
}

export interface FactUpdate {
  field_path: string;
  value: any;
  status?: FactStatus;
  evidence?: FactEvidence[];
}

export interface ProfileResponse {
  candidate_id: string;
  exists: boolean;
  profile: CandidateProfile;
}

export interface ProfileValidationResponse {
  candidate_id: string;
  is_valid: boolean;
  error_count: number;
  warning_count: number;
  completeness: number;
  missing_required: string[];
  issues: Array<{
    code: string;
    severity: string;
    field_path: string;
    message: string;
    actual: any;
    expected: any;
  }>;
}

export interface ProfileCompletenessResponse {
  candidate_id: string;
  completeness: number;
}

export interface UnknownFieldsResponse {
  candidate_id: string;
  unknown: Array<{
    field_path: string;
    required_for_application: string;
  }>;
  count: number;
}

// Profile schema (matches Python CandidateProfile)
export interface CandidateProfile {
  schema_version: string;
  id: string;
  candidate_id: string;
  version: number;
  identity: {
    section_path: string;
    full_name: FactValue;
    preferred_name: FactValue;
    pronouns: FactValue;
    date_of_birth: FactValue;
    nationality: FactValue;
    headline: FactValue;
    summary: FactValue;
  };
  contact: {
    section_path: string;
    email: FactValue;
    phone: FactValue;
    linkedin_url: FactValue;
    website: FactValue;
  };
  location: {
    section_path: string;
    current_city: FactValue;
    current_state: FactValue;
    current_country: FactValue;
    postal_code: FactValue;
    willing_to_relocate: FactValue;
    preferred_locations: FactValue;
    timezone: FactValue;
  };
  education: {
    section_path: string;
    entries: any[];
    highest_level: FactValue;
  };
  experience: {
    section_path: string;
    entries: any[];
    total_years_experience: FactValue;
    years_of_experience_verified: FactValue;
  };
  skills: {
    section_path: string;
    proficient: FactValue;
    expert: FactValue;
    familiar: FactValue;
    languages: FactValue;
    tools: FactValue;
  };
  projects: {
    section_path: string;
    entries: any[];
  };
  certifications: {
    section_path: string;
    entries: any[];
  };
  links: {
    section_path: string;
    entries: any[];
  };
  preferences: {
    section_path: string;
    desired_roles: FactValue;
    desired_locations: FactValue;
    remote_preference: FactValue;
    minimum_salary: FactValue;
    maximum_salary: FactValue;
    willing_to_relocate: FactValue;
    notice_period: FactValue;
    willing_to_travel: FactValue;
  };
  authorization: {
    section_path: string;
    requires_sponsorship: FactValue;
    authorized_countries: FactValue;
    visa_status: FactValue;
    sponsorship_available: FactValue;
    security_clearance: FactValue;
  };
  availability: {
    section_path: string;
    available_from: FactValue;
    notice_period_days: FactValue;
    hours_per_week: FactValue;
    open_to_contract: FactValue;
    open_to_part_time: FactValue;
  };
  created_at: string;
  updated_at: string;
}

export interface FactValue {
  field_path: string;
  value: any;
  status: FactStatus;
  source?: string;
  source_id?: string;
  source_location?: string;
  confidence: number;
  verified_at?: string;
  evidence: FactEvidence[];
}

// Resume types
export interface ResumeIngestRequest {
  path: string;
  variant?: string;
  role_focus?: string;
  skills?: string[];
  version?: string;
  allow_duplicate: boolean;
}

export interface ResumeResponse {
  resume: Resume;
}

export interface ResumeListResponse {
  resumes: Resume[];
  count: number;
}

export interface ResumeSectionsResponse {
  resume_id: string;
  by_section_type: Record<string, any[]>;
  section_types: string[];
}

export interface ResumeVariantsResponse {
  candidate_id: string;
  variants: string[];
  count: number;
}

export interface DuplicateCheckResponse {
  file_hash: string;
  is_duplicate: boolean;
  existing_resume_id?: string;
  existing_filename?: string;
}

export interface Resume {
  candidate_id: string;
  document_id?: string;
  variant?: string;
  role_focus?: string;
  version?: string;
  skills: string[];
  filename: string;
  file_type: 'PDF' | 'DOCX' | 'TXT' | 'MD' | 'UNKNOWN';
  file_hash: string;
  file_size_bytes?: number;
  page_count?: number;
  char_count: number;
  content_hash?: string;
  storage_path?: string;
  raw_text_path?: string;
  raw_text: string;
  status: 'STORED' | 'PARSED' | 'PARSE_FAILED' | 'DUPLICATE' | 'INVALID';
  parser_name?: string;
  parser_version?: string;
  metadata: Record<string, any>;
  is_synthetic: boolean;
  created_at: string;
  updated_at: string;
  sections: ResumeSection[];
  id: string;
}

export interface ResumeSection {
  id: string;
  resume_id: string;
  section_type: string;
  position: number;
  heading?: string;
  raw_text: string;
  items: any[];
  char_count: number;
  created_at: string;
}

// Job types
export interface JobIngestRequest {
  html: string;
  source: string;
  page_url: string;
  source_path: string;
}

export interface MatchRequest {
  scorer?: 'none' | 'lexical' | 'embedding';
}

export interface JobListResponse {
  jobs: Job[];
  count: number;
  limit?: number;
  offset: number;
}

export interface JobResponse {
  job: Job;
}

export interface AnalysisResponse {
  job_id: string;
  analysis: RequirementAnalysis;
  requirements: Requirement[];
}

export interface MatchResponse {
  job_id: string;
  outcome: MatchOutcome;
  result: MatchResult;
  review_reasons: string[];
}

export interface ReportResponse {
  job_id: string;
  report: MatchReport;
}

export interface RelevanceResponse {
  job_id: string;
  relevance: ResumeRelevance;
}

export interface ExplanationResponse {
  job_id: string;
  explanation: MatchExplanation;
}

export interface ReviewQueueResponse {
  queue: ReviewQueue;
  open_reviews: number;
  counts_by_reason: Record<string, number>;
}

export interface SubmitApplicationResponse {
  job_id: string;
  submitted: boolean;
  submission_possible: boolean;
  reason: string;
  application_status?: string;
}

// Job domain types (matching Python)
export interface Job {
  id: string;
  source: string;
  external_job_id?: string;
  company: string;
  title: string;
  location?: string;
  canonical_url?: string;
  url?: string;
  workplace_type?: string;
  employment_type?: string;
  experience_level?: string;
  salary_min?: number;
  salary_max?: number;
  salary_currency?: string;
  salary_period?: string;
  description_raw?: string;
  description_text?: string;
  description_hash?: string;
  identity_key?: string;
  status: 'DISCOVERED' | 'FETCHED' | 'NORMALIZED' | 'JD_PENDING' | 'JD_EXTRACTED' | 'JD_PARTIAL' | 'JD_FAILED' | 'ANALYSIS_PENDING' | 'ANALYZED' | 'MATCHED' | 'REVIEW_REQUIRED' | 'READY_FOR_APPLICATION' | 'APPLYING' | 'APPLIED' | 'REJECTED' | 'SKIPPED' | 'FAILED';
  posted_at?: string;
  discovered_at: string;
  first_seen_at?: string;
  last_seen_at?: string;
  seen_count: number;
  requirements: Requirement[];
  analysis_source: 'JOB_DATA' | 'CANDIDATE_DATA' | 'USER_PROVIDED' | 'AI_GENERAL';
  metadata: Record<string, any>;
}

export interface Requirement {
  id: string;
  kind: 'SKILL' | 'TOOL' | 'CERTIFICATION' | 'EDUCATION' | 'EXPERIENCE' | 'SOFT_SKILL' | 'LOCATION' | 'COMPENSATION' | 'AUTHORIZATION' | 'OTHER' | 'TECHNOLOGY' | 'PROGRAMMING_LANGUAGE' | 'FRAMEWORK' | 'DATABASE' | 'CLOUD' | 'YEARS_OF_EXPERIENCE' | 'WORKPLACE_TYPE' | 'EMPLOYMENT_TYPE' | 'SPONSORSHIP' | 'LANGUAGE' | 'DOMAIN';
  text: string;
  normalized?: string;
  priority: 'REQUIRED' | 'PREFERRED' | 'UNKNOWN';
  ambiguous: boolean;
  min_years?: number;
  source_excerpt?: string;
  extraction_source: 'DETERMINISTIC' | 'AI' | 'BROWSER' | 'HUMAN' | 'NONE';
  evidence: FactEvidence[];
  analysis_source: 'JOB_DATA' | 'AI_GENERAL';
  confidence: number;
}

export interface RequirementAnalysis {
  requirements: Requirement[];
  content_hash: string;
  analysis_id: string;
  cached: boolean;
  ai_fallback: boolean;
  ai_error_code?: string;
}

export interface MatchOutcome {
  result: MatchResult;
  match_id: string;
  cached: boolean;
  requirements_fingerprint: string;
  candidate_fingerprint: string;
  scorer_fingerprint: string;
  review_reasons: string[];
}

export interface MatchResult {
  decision: 'MATCH' | 'PARTIAL_MATCH' | 'HARD_MISMATCH' | 'INSUFFICIENT_EVIDENCE' | 'REVIEW_REQUIRED';
  gate: HardGateResult;
  scores: RequirementScore[];
  similarity_score?: number;
}

export interface GateCheck {
  requirement_text: string;
  kind: string;
  priority: 'REQUIRED' | 'PREFERRED' | 'UNKNOWN';
  evaluation: RequirementScore['evaluation'];
  reason: string;
  candidate_field_path?: string;
  requirement_index?: number;
}

export interface HardGateResult {
  status: 'PASS' | 'HARD_MISMATCH' | 'UNKNOWN' | 'REVIEW_REQUIRED';
  checks: GateCheck[];
}

export interface RequirementScore {
  requirement_text: string;
  kind: string;
  priority: 'REQUIRED' | 'PREFERRED' | 'UNKNOWN';
  evaluation: 'VERIFIED_MATCH' | 'DERIVED_MATCH' | 'VERIFIED_MISMATCH' | 'DERIVED_MISMATCH' | 'UNKNOWN' | 'REVIEW_REQUIRED';
  similarity?: number;
  reason: string;
  candidate_field_path?: string;
  requirement_index: number;
}

export interface MatchReport {
  // 11-dimension report
  dimensions: any[];
  overall: string;
}

export interface MatchExplanation {
  // Audit record for stored match
  job_id: string;
  candidate_id: string;
  match_id: string;
  decision: string;
  reasoning: string;
  evidence: any[];
}

export interface ReviewQueue {
  items: ReviewItem[];
}

export interface ReviewItem {
  job_id: string;
  title: string;
  company: string;
  url?: string;
  decision: 'MATCH' | 'PARTIAL_MATCH' | 'HARD_MISMATCH' | 'INSUFFICIENT_EVIDENCE' | 'REVIEW_REQUIRED';
  reasons: string[];
  similarity_score?: number;
  matched_at?: string;
  report?: string;
  status?: string;
}

export interface ResumeRelevance {
  decision: 'RECOMMENDED' | 'REVIEW_REQUIRED' | 'INSUFFICIENT_EVIDENCE';
  recommended_resume_id?: string;
  runner_up_resume_id?: string;
  reason: string;
  confidence: number;
  scores: Array<{
    resume_id: string;
    coverage: number;
    covered: string[];
    missed: string[];
  }>;
  tokens: string[];
}

// Error envelope
export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: Record<string, any>;
  };
}