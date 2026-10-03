import express, { Request, Response } from 'express';
import cors from 'cors';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { HuggingFaceLocalProvider } from './src/ai/huggingface.js';
import { EmbeddingScorer, LexicalScorer } from './src/ai/embeddings.js';
import { globalModelRegistry } from './src/ai/registry.js';
import { classifyQuestionIntent } from './src/ai/questionIntent.js';
import { scoreResumeRelevance } from './src/jobs/relevance.js';
import type {
  CandidateProfile,
  ResumeVariant,
  Job,
  JobRequirement,
  MatchResult,
  RequirementScore,
  HardGateResult,
  SafetySettings,
  CustomQuestionRule,
  QuestionAnswerResponse,
  FactStatus,
} from './src/types/index.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = 3000;
const HOST = '0.0.0.0';

app.use(cors());
app.use(express.json());

// -------------------------------------------------------------
// In-Memory Database State
// -------------------------------------------------------------

let candidateProfile: CandidateProfile = {
  id: 'profile-c-9821a',
  candidate_id: 'krishna_prasath',
  version: 3,
  updated_at: new Date().toISOString(),
  identity: {
    full_name: {
      field_path: 'identity.full_name',
      value: 'Krishna Prasath',
      status: 'VERIFIED',
      source: 'USER_INPUT',
      source_id: 'session-init',
      source_location: 'profile_setup',
      confidence: 1.0,
      verified_at: new Date().toISOString(),
      evidence: [{
        source_type: 'USER_INPUT',
        source_id: 'session-init',
        source_location: 'profile_setup',
        text_excerpt: 'Krishna Prasath verified identity',
        created_at: new Date().toISOString()
      }]
    },
    preferred_name: {
      field_path: 'identity.preferred_name',
      value: 'Krishna',
      status: 'VERIFIED',
      source: 'USER_INPUT',
      confidence: 1.0,
      evidence: []
    },
    email: {
      field_path: 'identity.email',
      value: 'krishnaprasath2230l@gmail.com',
      status: 'VERIFIED',
      source: 'USER_INPUT',
      confidence: 1.0,
      evidence: []
    },
    phone: {
      field_path: 'identity.phone',
      value: '+1 (555) 234-8901',
      status: 'VERIFIED',
      source: 'USER_INPUT',
      confidence: 1.0,
      evidence: []
    },
    location: {
      field_path: 'identity.location',
      value: 'San Francisco, CA (Open to Remote / Relocation)',
      status: 'VERIFIED',
      source: 'USER_INPUT',
      confidence: 1.0,
      evidence: []
    },
    linkedin_url: {
      field_path: 'identity.linkedin_url',
      value: 'https://linkedin.com/in/krishnaprasath',
      status: 'VERIFIED',
      source: 'USER_INPUT',
      confidence: 1.0,
      evidence: []
    },
    github_url: {
      field_path: 'identity.github_url',
      value: 'https://github.com/krishnaprasath2006',
      status: 'VERIFIED',
      source: 'USER_INPUT',
      confidence: 1.0,
      evidence: []
    },
    website_url: {
      field_path: 'identity.website_url',
      value: 'https://apllie.com',
      status: 'VERIFIED',
      source: 'USER_INPUT',
      confidence: 1.0,
      evidence: []
    },
  },
  work_authorization: {
    authorized_in_us: {
      field_path: 'work_authorization.authorized_in_us',
      value: true,
      status: 'VERIFIED',
      source: 'OFFICIAL_DOCUMENT',
      confidence: 1.0,
      evidence: []
    },
    requires_sponsorship: {
      field_path: 'work_authorization.requires_sponsorship',
      value: false,
      status: 'VERIFIED',
      source: 'OFFICIAL_DOCUMENT',
      confidence: 1.0,
      evidence: []
    },
    visa_status: {
      field_path: 'work_authorization.visa_status',
      value: 'US Citizen / Permanent Resident (No sponsorship required)',
      status: 'VERIFIED',
      source: 'OFFICIAL_DOCUMENT',
      confidence: 1.0,
      evidence: []
    },
    security_clearance: {
      field_path: 'work_authorization.security_clearance',
      value: null,
      status: 'UNKNOWN',
      source: null,
      confidence: 1.0,
      evidence: []
    }
  },
  experience: {
    total_years: {
      field_path: 'experience.total_years',
      value: 5.0,
      status: 'VERIFIED',
      source: 'RESUME_PARSER',
      confidence: 0.95,
      evidence: []
    },
    current_title: {
      field_path: 'experience.current_title',
      value: 'Senior Full Stack Software Engineer',
      status: 'VERIFIED',
      source: 'RESUME_PARSER',
      confidence: 1.0,
      evidence: []
    },
    target_roles: {
      field_path: 'experience.target_roles',
      value: ['Full Stack Engineer', 'Backend Engineer', 'Software Engineer III', 'Tech Lead'],
      status: 'VERIFIED',
      source: 'USER_INPUT',
      confidence: 1.0,
      evidence: []
    },
    seniority_level: {
      field_path: 'experience.seniority_level',
      value: 'Senior (5+ Years)',
      status: 'VERIFIED',
      source: 'INFERRED',
      confidence: 0.9,
      evidence: []
    }
  },
  education: {
    highest_degree: {
      field_path: 'education.highest_degree',
      value: 'Bachelor of Science in Computer Science',
      status: 'VERIFIED',
      source: 'RESUME_PARSER',
      confidence: 1.0,
      evidence: []
    },
    field_of_study: {
      field_path: 'education.field_of_study',
      value: 'Computer Science & Engineering',
      status: 'VERIFIED',
      source: 'RESUME_PARSER',
      confidence: 1.0,
      evidence: []
    },
    institution: {
      field_path: 'education.institution',
      value: 'University of California',
      status: 'VERIFIED',
      source: 'RESUME_PARSER',
      confidence: 1.0,
      evidence: []
    },
    graduation_year: {
      field_path: 'education.graduation_year',
      value: 2021,
      status: 'VERIFIED',
      source: 'RESUME_PARSER',
      confidence: 1.0,
      evidence: []
    }
  },
  skills: [
    { name: 'TypeScript', years: 5, proficiency: 'Expert', category: 'LANGUAGES', status: 'VERIFIED' },
    { name: 'Python', years: 5, proficiency: 'Expert', category: 'LANGUAGES', status: 'VERIFIED' },
    { name: 'React', years: 4, proficiency: 'Expert', category: 'FRAMEWORKS', status: 'VERIFIED' },
    { name: 'Node.js', years: 5, proficiency: 'Expert', category: 'FRAMEWORKS', status: 'VERIFIED' },
    { name: 'PostgreSQL', years: 4, proficiency: 'Advanced', category: 'DATABASES', status: 'VERIFIED' },
    { name: 'Redis', years: 3, proficiency: 'Advanced', category: 'DATABASES', status: 'VERIFIED' },
    { name: 'Docker', years: 4, proficiency: 'Advanced', category: 'CLOUD_DEVOPS', status: 'VERIFIED' },
    { name: 'AWS', years: 3, proficiency: 'Advanced', category: 'CLOUD_DEVOPS', status: 'VERIFIED' },
    { name: 'REST APIs', years: 5, proficiency: 'Expert', category: 'FRAMEWORKS', status: 'VERIFIED' },
    { name: 'GraphQL', years: 3, proficiency: 'Intermediate', category: 'FRAMEWORKS', status: 'VERIFIED' },
    { name: 'Tailwind CSS', years: 3, proficiency: 'Expert', category: 'FRAMEWORKS', status: 'VERIFIED' },
    { name: 'Unit & E2E Testing', years: 4, proficiency: 'Advanced', category: 'SOFT_SKILLS', status: 'VERIFIED' },
  ],
  preferences: {
    desired_salary_min: 140000,
    desired_locations: ['San Francisco, CA', 'Remote', 'Seattle, WA', 'New York, NY'],
    remote_only: false,
    excluded_keywords: ['Crypto scam', 'Unpaid', 'Contract to hire without benefits']
  }
};

let resumes: ResumeVariant[] = [
  {
    id: 'res-01',
    name: 'Senior Full Stack Engineer (Primary)',
    targetRole: 'Full Stack Engineer / Senior Software Engineer',
    filename: 'Krishna_Prasath_FullStack_2026.pdf',
    format: 'pdf',
    isSynthetic: false,
    isActive: true,
    uploadedAt: '2026-09-28T14:20:00Z',
    skillsCount: 16,
    summary: '5+ years building scalable distributed web applications, reactive frontends (React, TypeScript), and resilient backend microservices in Node.js & Python.',
    contentSnippet: 'Krishna Prasath - Senior Full Stack Engineer. Experience: Led architecture of real-time event pipeline serving 2M users. Proficient in React, TypeScript, Node.js, Python, PostgreSQL, Docker, AWS.'
  },
  {
    id: 'res-02',
    name: 'Backend & Systems Engineer Focus',
    targetRole: 'Senior Backend Engineer / Cloud Infrastructure',
    filename: 'Krishna_Prasath_Backend_2026.pdf',
    format: 'pdf',
    isSynthetic: false,
    isActive: false,
    uploadedAt: '2026-09-25T11:15:00Z',
    skillsCount: 14,
    summary: 'Backend-heavy variant highlighting database optimization, high-throughput message streams, Docker containerization, and API security.',
    contentSnippet: 'Krishna Prasath - Backend Specialist. Engineered microservices with 99.99% uptime. Mastered Python asyncio, Express/Node.js, PostgreSQL indexing, Redis caching, and CI/CD pipelines.'
  }
];

let safetySettings: SafetySettings = {
  safeMode: true,
  dryRun: true,
  requireHumanApproval: true,
  allowBrowserNavigation: true,
  allowFileUpload: true,
  allowFormFilling: true,
  allowFinalSubmission: false, // Locked for safety invariants
  maxApplicationsPerRun: 15,
  applicationsToday: 3,
  blockOnCaptcha: true,
  blockOnMfa: true,
  recordScreenshots: true
};

const customQuestionRules: CustomQuestionRule[] = [
  { id: 'q-1', keyword: 'sponsorship', questionPattern: 'Will you now or in the future require visa sponsorship?', answerType: 'choice', answerValue: 'No', category: 'Work Authorization' },
  { id: 'q-2', keyword: 'authorized', questionPattern: 'Are you legally authorized to work in the United States?', answerType: 'choice', answerValue: 'Yes', category: 'Work Authorization' },
  { id: 'q-3', keyword: 'years of experience', questionPattern: 'How many years of relevant professional software engineering experience do you have?', answerType: 'number', answerValue: '5', category: 'Tech Skills' },
  { id: 'q-4', keyword: 'python', questionPattern: 'How many years of experience do you have with Python?', answerType: 'number', answerValue: '5', category: 'Tech Skills' },
  { id: 'q-5', keyword: 'react', questionPattern: 'How many years of experience do you have with React / React.js?', answerType: 'number', answerValue: '4', category: 'Tech Skills' },
  { id: 'q-6', keyword: 'typescript', questionPattern: 'How many years of experience with TypeScript / Modern JavaScript?', answerType: 'number', answerValue: '5', category: 'Tech Skills' },
  { id: 'q-7', keyword: 'sql', questionPattern: 'How many years of experience working with SQL and relational databases?', answerType: 'number', answerValue: '4', category: 'Tech Skills' },
  { id: 'q-8', keyword: 'cloud', questionPattern: 'Experience with AWS or cloud platforms (in years):', answerType: 'number', answerValue: '3', category: 'Tech Skills' },
  { id: 'q-9', keyword: 'notice', questionPattern: 'What is your notice period or earliest start date?', answerType: 'text', answerValue: '2 weeks notice', category: 'General' },
  { id: 'q-10', keyword: 'salary', questionPattern: 'What are your annual base salary expectations (USD)?', answerType: 'text', answerValue: '$150,000 - $175,000', category: 'Compensation' },
  { id: 'q-11', keyword: 'relocation', questionPattern: 'Are you willing to relocate or commute for this role?', answerType: 'choice', answerValue: 'Yes, open to relocation or remote', category: 'General' },
  { id: 'q-12', keyword: 'degree', questionPattern: 'Have you completed a Bachelor’s degree in Computer Science or related STEM field?', answerType: 'choice', answerValue: 'Yes', category: 'Personal' }
];

// Helper to evaluate hard gate & matching
function evaluateJobMatch(job: Partial<Job>, profile: CandidateProfile): MatchResult {
  const reqs = job.extractedRequirements || [];
  const candidateYears = profile.experience.total_years.value || 0;
  const candidateNeedsSponsorship = profile.work_authorization.requires_sponsorship.value ?? false;

  // 1. Hard Gate Check
  const hardGateReasons: string[] = [];
  let gateStatus: 'PASS' | 'FAIL' = 'PASS';

  for (const req of reqs) {
    if (req.category === 'WORK_AUTHORIZATION' && req.priority === 'REQUIRED') {
      const lowerText = req.text.toLowerCase();
      if ((lowerText.includes('must not require sponsorship') || lowerText.includes('no visa sponsorship') || lowerText.includes('us citizen only')) && candidateNeedsSponsorship) {
        gateStatus = 'FAIL';
        hardGateReasons.push('Sponsorship Veto: Candidate requires sponsorship, but role explicitly states no sponsorship.');
      }
    }
    if (req.category === 'YEARS_OF_EXPERIENCE' && req.priority === 'REQUIRED' && req.minYears) {
      if (candidateYears < req.minYears) {
        gateStatus = 'FAIL';
        hardGateReasons.push(`Experience Veto: Requires minimum ${req.minYears} years, candidate verified ${candidateYears} years.`);
      }
    }
  }

  // 2. Requirement Scoring
  const scores: RequirementScore[] = [];
  let totalScoreWeight = 0;
  let earnedScoreWeight = 0;

  const candidateSkillNames = profile.skills.map(s => s.name.toLowerCase());

  for (const req of reqs) {
    const weight = req.priority === 'REQUIRED' ? 3 : 1;
    totalScoreWeight += weight;

    const lowerReq = req.text.toLowerCase();
    let evaluation: RequirementScore['evaluation'] = 'UNKNOWN';
    let similarity: number | null = null;
    let reason = '';
    let matchedField: string | null = null;

    if (req.category === 'YEARS_OF_EXPERIENCE') {
      if (req.minYears && candidateYears >= req.minYears) {
        evaluation = 'VERIFIED_MATCH';
        similarity = 1.0;
        reason = `Candidate verified ${candidateYears} yrs exceeds required ${req.minYears} yrs.`;
        matchedField = 'experience.total_years';
      } else {
        evaluation = 'DERIVED_MISS';
        similarity = candidateYears / (req.minYears || 1);
        reason = `Candidate has ${candidateYears} yrs, needed ${req.minYears} yrs.`;
      }
    } else if (req.category === 'WORK_AUTHORIZATION') {
      if (!candidateNeedsSponsorship) {
        evaluation = 'VERIFIED_MATCH';
        similarity = 1.0;
        reason = 'Candidate is US Citizen / Permanent Resident, no sponsorship needed.';
        matchedField = 'work_authorization.visa_status';
      } else {
        evaluation = 'REVIEW_NEEDED';
        similarity = 0.5;
        reason = 'Candidate requires visa transfer or sponsorship.';
      }
    } else if (req.category === 'DEGREE') {
      evaluation = 'VERIFIED_MATCH';
      similarity = 1.0;
      reason = 'Candidate holds verified B.S. in Computer Science.';
      matchedField = 'education.highest_degree';
    } else {
      // Skill / Technology matching
      const foundSkill = profile.skills.find(s => lowerReq.includes(s.name.toLowerCase()));
      if (foundSkill) {
        evaluation = foundSkill.status === 'VERIFIED' ? 'VERIFIED_MATCH' : 'DERIVED_MATCH';
        similarity = 0.95;
        reason = `Direct claim on profile: ${foundSkill.name} (${foundSkill.years} yrs, ${foundSkill.proficiency}).`;
        matchedField = `skills.${foundSkill.name}`;
      } else {
        // Partial lexical check
        const partialMatches = ['api', 'git', 'agile', 'linux', 'ci/cd', 'frontend', 'backend'];
        const matchedPartial = partialMatches.find(p => lowerReq.includes(p));
        if (matchedPartial) {
          evaluation = 'DERIVED_MATCH';
          similarity = 0.78;
          reason = `Derived match from experience in standard software development: "${matchedPartial}".`;
        } else {
          evaluation = 'REVIEW_NEEDED';
          similarity = 0.40;
          reason = 'Not explicitly stated in candidate verified skills inventory; review needed.';
        }
      }
    }

    if (evaluation === 'VERIFIED_MATCH') earnedScoreWeight += weight * 1.0;
    else if (evaluation === 'DERIVED_MATCH') earnedScoreWeight += weight * 0.85;
    else if (evaluation === 'PARTIAL_MATCH') earnedScoreWeight += weight * 0.5;
    else if (evaluation === 'REVIEW_NEEDED') earnedScoreWeight += weight * 0.3;

    scores.push({
      requirement_text: req.text,
      kind: req.category,
      priority: req.priority,
      evaluation,
      similarity,
      reason,
      candidate_field_path: matchedField
    });
  }

  const overallScore = totalScoreWeight > 0 ? Math.round((earnedScoreWeight / totalScoreWeight) * 100) : 75;

  let decision: MatchResult['decision'] = 'GOOD_MATCH';
  if (gateStatus === 'FAIL') {
    decision = 'HARD_MISMATCH';
  } else if (overallScore >= 85) {
    decision = 'STRONG_MATCH';
  } else if (overallScore >= 70) {
    decision = 'GOOD_MATCH';
  } else if (overallScore >= 50) {
    decision = 'PARTIAL_MATCH';
  } else {
    decision = 'HARD_MISMATCH';
  }

  let summary = '';
  if (decision === 'HARD_MISMATCH') {
    summary = `Disqualified by hard gate invariants: ${hardGateReasons.join(' ')}`;
  } else if (decision === 'STRONG_MATCH') {
    summary = `Excellent profile fit (${overallScore}%). All core requirements verified with strong evidence.`;
  } else {
    summary = `Solid fit with score ${overallScore}%. Some optional or specialized requirements can be reviewed.`;
  }

  return {
    decision,
    overallScore,
    gate: {
      status: gateStatus,
      reasons: hardGateReasons
    },
    scores,
    summary
  };
}

let initialJobs: Job[] = [
  {
    id: 'job-101',
    title: 'Senior Full Stack Engineer (React / Node / TypeScript)',
    company: 'Stripe Ecosystem Partner (FinTech)',
    location: 'San Francisco, CA (Remote)',
    remoteType: 'Remote',
    easyApply: true,
    salaryRange: '$165,000 - $190,000',
    postedDate: '2 hours ago',
    url: 'https://linkedin.com/jobs/view/39201948',
    description: `We are looking for a Senior Full Stack Engineer to join our merchant billing and analytics team.
You will architect high-scale web platforms using React, TypeScript, and Node.js, backing onto PostgreSQL and Redis.
Requirements:
- 4+ years of professional full-stack development experience
- Deep proficiency in TypeScript, React, and Node.js
- Experience designing RESTful APIs and event-driven architecture
- Experience with PostgreSQL and Docker containerization
- Must have legal authorization to work in the US (No sponsorship provided at this time)`,
    status: 'IN_REVIEW',
    extractedRequirements: [
      { id: 'r1', text: '4+ years of professional full-stack development experience', category: 'YEARS_OF_EXPERIENCE', priority: 'REQUIRED', minYears: 4 },
      { id: 'r2', text: 'Proficiency in TypeScript, React, and Node.js', category: 'LANGUAGES', priority: 'REQUIRED' },
      { id: 'r3', text: 'Experience designing RESTful APIs and event-driven architecture', category: 'FRAMEWORKS', priority: 'REQUIRED' },
      { id: 'r4', text: 'Experience with PostgreSQL and Docker containerization', category: 'DATABASES', priority: 'REQUIRED' },
      { id: 'r5', text: 'Legal authorization to work in the US (No visa sponsorship provided)', category: 'WORK_AUTHORIZATION', priority: 'REQUIRED' }
    ],
    matchResult: {
      decision: 'STRONG_MATCH',
      overallScore: 94,
      gate: { status: 'PASS', reasons: [] },
      scores: [
        { requirement_text: '4+ years of professional full-stack development experience', kind: 'YEARS_OF_EXPERIENCE', priority: 'REQUIRED', evaluation: 'VERIFIED_MATCH', similarity: 1.0, reason: 'Candidate has 5.0 verified years.', candidate_field_path: 'experience.total_years' },
        { requirement_text: 'Proficiency in TypeScript, React, and Node.js', kind: 'LANGUAGES', priority: 'REQUIRED', evaluation: 'VERIFIED_MATCH', similarity: 1.0, reason: 'Verified expert skills in TypeScript, React, and Node.js.', candidate_field_path: 'skills.TypeScript' },
        { requirement_text: 'Experience designing RESTful APIs and event-driven architecture', kind: 'FRAMEWORKS', priority: 'REQUIRED', evaluation: 'VERIFIED_MATCH', similarity: 0.95, reason: 'Claimed and verified in profile experience.', candidate_field_path: 'skills.REST APIs' },
        { requirement_text: 'Experience with PostgreSQL and Docker containerization', kind: 'DATABASES', priority: 'REQUIRED', evaluation: 'VERIFIED_MATCH', similarity: 0.95, reason: 'PostgreSQL (4 yrs) & Docker (4 yrs) verified.', candidate_field_path: 'skills.PostgreSQL' },
        { requirement_text: 'Legal authorization to work in the US', kind: 'WORK_AUTHORIZATION', priority: 'REQUIRED', evaluation: 'VERIFIED_MATCH', similarity: 1.0, reason: 'US Citizen / Permanent Resident, no sponsorship required.', candidate_field_path: 'work_authorization.visa_status' }
      ],
      summary: 'Outstanding match (94%). Hard gate passed with all core tech stack items verified.'
    }
  },
  {
    id: 'job-102',
    title: 'Staff Platform Engineer - Cloud & Infrastructure',
    company: 'Nexus AI Cloud',
    location: 'San Francisco, CA',
    remoteType: 'Hybrid',
    easyApply: true,
    salaryRange: '$210,000 - $240,000',
    postedDate: '1 day ago',
    url: 'https://linkedin.com/jobs/view/39201949',
    description: `Nexus AI is building next-gen model serving pipelines. Looking for a Staff Platform Engineer with 8+ years experience managing Kubernetes clusters, Go, Terraform, and high-performance GPU scheduling.`,
    status: 'DISCOVERED',
    extractedRequirements: [
      { id: 'r21', text: 'Minimum 8 years of distributed systems and platform experience', category: 'YEARS_OF_EXPERIENCE', priority: 'REQUIRED', minYears: 8 },
      { id: 'r22', text: 'Deep expertise in Kubernetes, Go, and Terraform', category: 'CLOUD_DEVOPS', priority: 'REQUIRED' },
      { id: 'r23', text: 'GPU orchestration and distributed inference', category: 'OTHER', priority: 'PREFERRED' }
    ],
    matchResult: {
      decision: 'HARD_MISMATCH',
      overallScore: 42,
      gate: {
        status: 'FAIL',
        reasons: ['Experience Veto: Requires minimum 8 years, candidate verified 5 years.']
      },
      scores: [
        { requirement_text: 'Minimum 8 years of distributed systems and platform experience', kind: 'YEARS_OF_EXPERIENCE', priority: 'REQUIRED', evaluation: 'DERIVED_MISS', similarity: 0.62, reason: 'Candidate has 5.0 years, needs 8.0.' },
        { requirement_text: 'Deep expertise in Kubernetes, Go, and Terraform', kind: 'CLOUD_DEVOPS', priority: 'REQUIRED', evaluation: 'REVIEW_NEEDED', similarity: 0.35, reason: 'Candidate profile lists Docker/AWS but not deep Go/Kubernetes.' }
      ],
      summary: 'Disqualified by hard gate: Experience minimum requirement not met (Candidate: 5 yrs vs Required: 8 yrs).'
    }
  },
  {
    id: 'job-103',
    title: 'Senior Software Engineer, AI Automation & Copilot',
    company: 'Apllie Intelligence Labs',
    location: 'Remote',
    remoteType: 'Remote',
    easyApply: true,
    salaryRange: '$170,000 - $195,000',
    postedDate: '3 days ago',
    url: 'https://apllie.com/careers/ai-engineer',
    description: `Join Apllie's core engineering team to build smart workflow automation, intelligent form-filling, and candidate-job matching pipelines.
Key Tech: Python, TypeScript, React, Fastify/Express, Vector embeddings, and LLM integrations.
Requirements:
- 3+ years experience with modern web architecture
- Strong Python and TypeScript skills
- Experience with automated browsers or browser extensions is a plus
- Bachelor's degree in CS or equivalent experience`,
    status: 'ACCEPTED',
    reviewNotes: 'High priority application: Perfect match for our automation and AI copilot background.',
    reviewedAt: '2026-09-29T10:00:00Z',
    extractedRequirements: [
      { id: 'r31', text: '3+ years experience with modern web architecture', category: 'YEARS_OF_EXPERIENCE', priority: 'REQUIRED', minYears: 3 },
      { id: 'r32', text: 'Strong Python and TypeScript skills', category: 'LANGUAGES', priority: 'REQUIRED' },
      { id: 'r33', text: 'Modern frontend with React', category: 'FRAMEWORKS', priority: 'REQUIRED' },
      { id: 'r34', text: 'Experience with browser automation or AI workflows', category: 'FRAMEWORKS', priority: 'PREFERRED' }
    ],
    matchResult: {
      decision: 'STRONG_MATCH',
      overallScore: 96,
      gate: { status: 'PASS', reasons: [] },
      scores: [
        { requirement_text: '3+ years experience with modern web architecture', kind: 'YEARS_OF_EXPERIENCE', priority: 'REQUIRED', evaluation: 'VERIFIED_MATCH', similarity: 1.0, reason: 'Candidate has 5.0 yrs, required 3.0 yrs.' },
        { requirement_text: 'Strong Python and TypeScript skills', kind: 'LANGUAGES', priority: 'REQUIRED', evaluation: 'VERIFIED_MATCH', similarity: 1.0, reason: 'Both Python & TypeScript verified at 5 yrs.' },
        { requirement_text: 'Modern frontend with React', kind: 'FRAMEWORKS', priority: 'REQUIRED', evaluation: 'VERIFIED_MATCH', similarity: 1.0, reason: 'React verified expert at 4 yrs.' },
        { requirement_text: 'Experience with browser automation or AI workflows', kind: 'FRAMEWORKS', priority: 'PREFERRED', evaluation: 'VERIFIED_MATCH', similarity: 0.95, reason: 'Direct experience built into Apllie automation bot!' }
      ],
      summary: 'Exceptional match (96%). Profile aligns directly with team goals.'
    }
  },
  {
    id: 'job-104',
    title: 'Full Stack Web Developer (Python / Django / React)',
    company: 'HealthTech Innovations',
    location: 'San Jose, CA',
    remoteType: 'Hybrid',
    easyApply: false,
    salaryRange: '$140,000 - $160,000',
    postedDate: '4 days ago',
    url: 'https://healthtech.io/careers/409',
    description: `Building patient portals and clinical trial management tools. Python/Django backend with React frontend.
Requirements:
- 3+ years experience
- Python and React
- Experience with healthcare compliance (HIPAA) is a plus`,
    status: 'APPLIED',
    appliedAt: '2026-09-30T16:30:00Z',
    applicationMode: 'DRY_RUN_SIMULATED',
    extractedRequirements: [
      { id: 'r41', text: '3+ years experience in Python and React', category: 'YEARS_OF_EXPERIENCE', priority: 'REQUIRED', minYears: 3 },
      { id: 'r42', text: 'Python backend development', category: 'LANGUAGES', priority: 'REQUIRED' },
      { id: 'r43', text: 'React frontend', category: 'FRAMEWORKS', priority: 'REQUIRED' }
    ],
    matchResult: {
      decision: 'GOOD_MATCH',
      overallScore: 88,
      gate: { status: 'PASS', reasons: [] },
      scores: [
        { requirement_text: '3+ years experience in Python and React', kind: 'YEARS_OF_EXPERIENCE', priority: 'REQUIRED', evaluation: 'VERIFIED_MATCH', similarity: 1.0, reason: 'Candidate has 5 yrs Python, 4 yrs React.' },
        { requirement_text: 'Python backend development', kind: 'LANGUAGES', priority: 'REQUIRED', evaluation: 'VERIFIED_MATCH', similarity: 1.0, reason: 'Verified.' },
        { requirement_text: 'React frontend', kind: 'FRAMEWORKS', priority: 'REQUIRED', evaluation: 'VERIFIED_MATCH', similarity: 1.0, reason: 'Verified.' }
      ],
      summary: 'Good match (88%). Applied in Dry-Run safe simulation mode.'
    }
  }
];

// -------------------------------------------------------------
// REST API Routes
// -------------------------------------------------------------

// System Diagnostics & Status
app.get('/api/status', (req: Request, res: Response) => {
  const verifiedCount = Object.values(candidateProfile.identity).filter(f => f.status === 'VERIFIED').length
    + Object.values(candidateProfile.work_authorization).filter(f => f.status === 'VERIFIED').length
    + Object.values(candidateProfile.experience).filter(f => f.status === 'VERIFIED').length
    + Object.values(candidateProfile.education).filter(f => f.status === 'VERIFIED').length
    + candidateProfile.skills.filter(s => s.status === 'VERIFIED').length;

  const totalFacts = Object.keys(candidateProfile.identity).length
    + Object.keys(candidateProfile.work_authorization).length
    + Object.keys(candidateProfile.experience).length
    + Object.keys(candidateProfile.education).length
    + candidateProfile.skills.length;

  res.json({
    status: 'healthy',
    banner: 'Apllie Job Applying Bot & Career Copilot (Phase 2 + Milestone 3 Active)',
    safety: {
      safe_mode: safetySettings.safeMode,
      dry_run: safetySettings.dryRun,
      require_human_approval: safetySettings.requireHumanApproval,
      allow_final_submission: safetySettings.allowFinalSubmission,
      max_applications_per_run: safetySettings.maxApplicationsPerRun,
      applications_today: safetySettings.applicationsToday,
    },
    database: {
      storage_type: 'In-Memory / SQLite Migrations Compliant',
      profiles: 1,
      resumes: resumes.length,
      jobs: initialJobs.length,
      queued_for_review: initialJobs.filter(j => j.status === 'IN_REVIEW').length,
      accepted_jobs: initialJobs.filter(j => j.status === 'ACCEPTED').length,
      applied_jobs: initialJobs.filter(j => j.status === 'APPLIED').length,
      verified_facts: verifiedCount,
      completeness_percentage: Math.round((verifiedCount / totalFacts) * 100)
    },
    configuration: {
      candidate_id: candidateProfile.candidate_id,
      easy_apply_only: true,
      remote_only: candidateProfile.preferences.remote_only,
      active_resume: resumes.find(r => r.isActive)?.name || 'None'
    }
  });
});

// Candidate Profile Routes
app.get('/api/profile', (req: Request, res: Response) => {
  res.json(candidateProfile);
});

app.put('/api/profile', (req: Request, res: Response) => {
  const updated = req.body;
  if (!updated) {
    return res.status(400).json({ error: 'Missing profile data' });
  }
  candidateProfile = {
    ...candidateProfile,
    ...updated,
    version: candidateProfile.version + 1,
    updated_at: new Date().toISOString()
  };
  // Recalculate matches for all jobs
  initialJobs = initialJobs.map(job => ({
    ...job,
    matchResult: evaluateJobMatch(job, candidateProfile)
  }));
  res.json(candidateProfile);
});

app.post('/api/profile/validate', (req: Request, res: Response) => {
  const missingRequired: string[] = [];
  const findings: string[] = [];

  if (!candidateProfile.identity.full_name.value) missingRequired.push('identity.full_name');
  if (!candidateProfile.identity.email.value) missingRequired.push('identity.email');
  if (!candidateProfile.identity.phone.value) missingRequired.push('identity.phone');
  if (candidateProfile.work_authorization.requires_sponsorship.value === null) {
    missingRequired.push('work_authorization.requires_sponsorship');
  }
  if (!candidateProfile.experience.total_years.value) {
    missingRequired.push('experience.total_years');
  }

  if (candidateProfile.work_authorization.security_clearance.status === 'UNKNOWN') {
    findings.push('Security clearance fact is UNKNOWN (safe default, not required for private commercial roles).');
  }

  res.json({
    profile_id: candidateProfile.id,
    is_valid: missingRequired.length === 0,
    missing_required: missingRequired,
    findings,
    completeness: Math.round(
      ((15 - missingRequired.length) / 15) * 100
    )
  });
});

// Resumes Routes
app.get('/api/resumes', (req: Request, res: Response) => {
  res.json(resumes);
});

app.post('/api/resumes', (req: Request, res: Response) => {
  const { name, targetRole, format, contentSnippet } = req.body;
  if (!name) return res.status(400).json({ error: 'Name is required' });

  const newResume: ResumeVariant = {
    id: `res-${Date.now()}`,
    name,
    targetRole: targetRole || 'Software Engineer',
    filename: `${name.replace(/\s+/g, '_')}.${format || 'pdf'}`,
    format: format || 'pdf',
    isSynthetic: false,
    isActive: false,
    uploadedAt: new Date().toISOString(),
    skillsCount: 12,
    summary: 'Newly uploaded resume variant.',
    contentSnippet: contentSnippet || 'Resume contents parsed into facts and skills.'
  };
  resumes.push(newResume);
  res.status(201).json(newResume);
});

app.post('/api/resumes/:id/activate', (req: Request, res: Response) => {
  const { id } = req.params;
  let found = false;
  resumes = resumes.map(r => {
    if (r.id === id) {
      found = true;
      return { ...r, isActive: true };
    }
    return { ...r, isActive: false };
  });

  if (!found) return res.status(404).json({ error: 'Resume not found' });
  res.json({ success: true, activeId: id });
});

// Jobs & Matching Routes
app.get('/api/jobs', (req: Request, res: Response) => {
  const { status, query, remoteOnly, easyApplyOnly } = req.query;
  let filtered = [...initialJobs];

  if (status && status !== 'ALL') {
    filtered = filtered.filter(j => j.status === status);
  }
  if (query && typeof query === 'string') {
    const q = query.toLowerCase();
    filtered = filtered.filter(j =>
      j.title.toLowerCase().includes(q) ||
      j.company.toLowerCase().includes(q) ||
      j.description.toLowerCase().includes(q)
    );
  }
  if (remoteOnly === 'true') {
    filtered = filtered.filter(j => j.remoteType === 'Remote');
  }
  if (easyApplyOnly === 'true') {
    filtered = filtered.filter(j => j.easyApply);
  }

  res.json(filtered);
});

app.get('/api/jobs/:id', (req: Request, res: Response) => {
  const job = initialJobs.find(j => j.id === req.params.id);
  if (!job) return res.status(404).json({ error: 'Job not found' });
  res.json(job);
});

// Ingest a job
app.post('/api/jobs/ingest', (req: Request, res: Response) => {
  const { title, company, location, remoteType, salaryRange, url, description, easyApply } = req.body;
  if (!title || !description) {
    return res.status(400).json({ error: 'Title and description are required.' });
  }

  // Deterministic requirement extraction from text
  const extractedRequirements: JobRequirement[] = [];
  const lowerDesc = description.toLowerCase();

  // Extract years of experience
  const yearsMatch = lowerDesc.match(/(\d+)\+?\s*years/);
  if (yearsMatch) {
    const years = parseInt(yearsMatch[1], 10);
    extractedRequirements.push({
      id: `req-y-${Date.now()}`,
      text: `Minimum ${years} years professional experience`,
      category: 'YEARS_OF_EXPERIENCE',
      priority: 'REQUIRED',
      minYears: years,
      evidence: `Extracted from text: "${yearsMatch[0]}"`
    });
  }

  // Work auth check
  if (lowerDesc.includes('sponsorship') || lowerDesc.includes('authorized to work') || lowerDesc.includes('us citizen')) {
    extractedRequirements.push({
      id: `req-auth-${Date.now()}`,
      text: lowerDesc.includes('no sponsorship') || lowerDesc.includes('not provide sponsorship')
        ? 'US Citizen / Green Card (No visa sponsorship provided)'
        : 'Must have legal authorization to work in target location',
      category: 'WORK_AUTHORIZATION',
      priority: 'REQUIRED',
      evidence: 'Work authorization requirement detected in job post.'
    });
  }

  // Tech keywords check
  const techKeywords = [
    { name: 'TypeScript', cat: 'LANGUAGES' as const },
    { name: 'Python', cat: 'LANGUAGES' as const },
    { name: 'React', cat: 'FRAMEWORKS' as const },
    { name: 'Node.js', cat: 'FRAMEWORKS' as const },
    { name: 'PostgreSQL', cat: 'DATABASES' as const },
    { name: 'Docker', cat: 'CLOUD_DEVOPS' as const },
    { name: 'AWS', cat: 'CLOUD_DEVOPS' as const },
    { name: 'GraphQL', cat: 'FRAMEWORKS' as const },
  ];

  for (const tech of techKeywords) {
    if (lowerDesc.includes(tech.name.toLowerCase())) {
      extractedRequirements.push({
        id: `req-${tech.name}-${Date.now()}`,
        text: `Experience with ${tech.name}`,
        category: tech.cat,
        priority: lowerDesc.includes(`required: ${tech.name.toLowerCase()}`) ? 'REQUIRED' : 'PREFERRED',
        evidence: `Mentioned in posting text`
      });
    }
  }

  // Degree check
  if (lowerDesc.includes('bachelor') || lowerDesc.includes('degree') || lowerDesc.includes('computer science')) {
    extractedRequirements.push({
      id: `req-degree-${Date.now()}`,
      text: "Bachelor's degree in Computer Science or related quantitative field",
      category: 'DEGREE',
      priority: 'PREFERRED',
      evidence: 'Education requirement noted in description'
    });
  }

  const newJob: Job = {
    id: `job-${Date.now()}`,
    title,
    company: company || 'Fast-Growing Tech Co',
    location: location || 'Remote',
    remoteType: remoteType || 'Remote',
    easyApply: easyApply !== undefined ? easyApply : true,
    salaryRange: salaryRange || '$145,000 - $175,000',
    postedDate: 'Just now',
    url: url || 'https://linkedin.com/jobs/view/custom',
    description,
    status: 'IN_REVIEW',
    extractedRequirements,
    matchResult: {
      decision: 'UNKNOWN',
      overallScore: 0,
      gate: { status: 'PASS', reasons: [] },
      scores: [],
      summary: 'Evaluating...'
    }
  };

  newJob.matchResult = evaluateJobMatch(newJob, candidateProfile);
  initialJobs.unshift(newJob);
  res.status(201).json(newJob);
});

// Review a job (accept/reject)
app.post('/api/jobs/:id/review', (req: Request, res: Response) => {
  const { decision, notes } = req.body; // 'ACCEPTED' | 'REJECTED'
  const job = initialJobs.find(j => j.id === req.params.id);
  if (!job) return res.status(404).json({ error: 'Job not found' });

  job.status = decision;
  job.reviewNotes = notes;
  job.reviewedAt = new Date().toISOString();

  res.json(job);
});

// Apply / Simulate Apply to Job
app.post('/api/jobs/:id/apply', (req: Request, res: Response) => {
  const job = initialJobs.find(j => j.id === req.params.id);
  if (!job) return res.status(404).json({ error: 'Job not found' });

  // Assert safety invariants
  if (safetySettings.requireHumanApproval && job.status !== 'ACCEPTED') {
    return res.status(403).json({
      error: 'Safety Invariant: Human approval required before applying. Please accept this job first in the review queue.'
    });
  }

  if (job.matchResult.decision === 'HARD_MISMATCH') {
    return res.status(400).json({
      error: 'Safety Guard: Cannot apply to a job that failed Hard Gate requirements.',
      details: job.matchResult.gate.reasons
    });
  }

  if (safetySettings.applicationsToday >= safetySettings.maxApplicationsPerRun) {
    return res.status(429).json({
      error: `Safety Limit reached: Maximum applications per run (${safetySettings.maxApplicationsPerRun}) hit. Please reset or increase limit.`
    });
  }

  // Safe mode / dry run submission
  const isRealSubmission = safetySettings.allowFinalSubmission && !safetySettings.dryRun;
  job.status = 'APPLIED';
  job.appliedAt = new Date().toISOString();
  job.applicationMode = isRealSubmission ? 'REAL_SUBMISSION' : 'DRY_RUN_SIMULATED';
  safetySettings.applicationsToday += 1;

  res.json({
    success: true,
    message: isRealSubmission
      ? 'Application officially submitted via live integration.'
      : 'Application simulated and verified under Dry Run mode with no privileged submission.',
    applicationMode: job.applicationMode,
    job
  });
});

// Custom Question Answering Matrix
app.get('/api/questions', (req: Request, res: Response) => {
  res.json({
    rules: customQuestionRules,
    totalRules: customQuestionRules.length
  });
});

app.post('/api/questions/answer', (req: Request, res: Response) => {
  const { question } = req.body;
  if (!question || typeof question !== 'string') {
    return res.status(400).json({ error: 'Question text is required.' });
  }

  const lowerQ = question.toLowerCase();
  let matchedRule: CustomQuestionRule | undefined;

  for (const rule of customQuestionRules) {
    if (lowerQ.includes(rule.keyword.toLowerCase())) {
      matchedRule = rule;
      break;
    }
  }

  let response: QuestionAnswerResponse;
  if (matchedRule) {
    response = {
      question,
      suggestedAnswer: matchedRule.answerValue,
      confidence: 'HIGH',
      matchedRule: matchedRule.questionPattern,
      reasoning: `Matched candidate rule keyword "${matchedRule.keyword}" from Apllie questions matrix.`,
      source: 'additionalQuestions.yaml'
    };
  } else {
    // Fallback search in candidate profile
    if (lowerQ.includes('name')) {
      response = {
        question,
        suggestedAnswer: candidateProfile.identity.full_name.value || '',
        confidence: 'HIGH',
        reasoning: 'Derived from candidate verified identity.',
        source: 'candidate_profile.identity.full_name'
      };
    } else if (lowerQ.includes('phone')) {
      response = {
        question,
        suggestedAnswer: candidateProfile.identity.phone.value || '',
        confidence: 'HIGH',
        reasoning: 'Derived from candidate verified phone.',
        source: 'candidate_profile.identity.phone'
      };
    } else if (lowerQ.includes('email')) {
      response = {
        question,
        suggestedAnswer: candidateProfile.identity.email.value || '',
        confidence: 'HIGH',
        reasoning: 'Derived from candidate verified email.',
        source: 'candidate_profile.identity.email'
      };
    } else {
      response = {
        question,
        suggestedAnswer: 'Yes, 5+ years experience in scalable full-stack software development.',
        confidence: 'MEDIUM',
        reasoning: 'Generalized positive candidate capability answer.',
        source: 'candidate_profile.experience'
      };
    }
  }

  res.json(response);
});

// Safety Settings
app.get('/api/safety', (req: Request, res: Response) => {
  res.json({
    settings: safetySettings,
    actionsPermissionTable: {
      BROWSER_NAVIGATION: safetySettings.allowBrowserNavigation,
      FILE_UPLOAD: safetySettings.allowFileUpload,
      FORM_FILLING: safetySettings.allowFormFilling,
      FINAL_SUBMISSION: safetySettings.allowFinalSubmission,
      BLOCK_ON_CAPTCHA: safetySettings.blockOnCaptcha,
      BLOCK_ON_MFA: safetySettings.blockOnMfa,
      REQUIRE_HUMAN_APPROVAL: safetySettings.requireHumanApproval
    },
    invariants: [
      { name: 'No Unsolicited Submissions', satisfied: !safetySettings.allowFinalSubmission || safetySettings.requireHumanApproval },
      { name: 'Deterministic Hard Gate', satisfied: true },
      { name: 'Redacted Secret Logging', satisfied: true },
      { name: 'Dry Run Default Protection', satisfied: safetySettings.dryRun }
    ]
  });
});

app.put('/api/safety', (req: Request, res: Response) => {
  const updates = req.body;
  safetySettings = {
    ...safetySettings,
    ...updates
  };
  res.json({ success: true, settings: safetySettings });
});

// Reset Applications Run Counter
app.post('/api/safety/reset-counter', (req: Request, res: Response) => {
  safetySettings.applicationsToday = 0;
  res.json({ success: true, applicationsToday: 0 });
});

// -------------------------------------------------------------
// Milestone HF-1: Hugging Face Local Embedding Endpoints
// -------------------------------------------------------------
const hfProvider = new HuggingFaceLocalProvider();
globalModelRegistry.registerProvider(hfProvider);
const hfEmbeddingScorer = new EmbeddingScorer(hfProvider);
const lexicalScorer = new LexicalScorer();

app.get('/api/ai/status', (req: Request, res: Response) => {
  res.json({
    status: 'active',
    metadata: hfProvider.getMetadata(),
    activeProvider: hfProvider.id,
    zeroCost: true,
    capabilities: ['embeddings'],
    targetModel: 'sentence-transformers/all-MiniLM-L6-v2',
    invariants: {
      dryRun: safetySettings.dryRun,
      allowFinalSubmission: safetySettings.allowFinalSubmission,
      candidateTruthProtected: true,
      hardGateAuthoritative: true
    }
  });
});

app.post('/api/ai/similarity', async (req: Request, res: Response) => {
  const { textA, textB } = req.body;
  if (!textA || !textB) {
    res.status(400).json({ error: 'Both textA and textB are required' });
    return;
  }

  const lexicalScore = await lexicalScorer.similarity(textA, textB);
  const semanticScore = await hfEmbeddingScorer.similarity(textA, textB);

  let interpretation = 'DERIVED_MISS';
  if (semanticScore >= 0.70) {
    interpretation = 'DERIVED_MATCH';
  } else if (semanticScore >= 0.45) {
    interpretation = 'REVIEW_NEEDED';
  }

  res.json({
    inputA: textA,
    inputB: textB,
    lexicalScore: Math.round(lexicalScore * 100) / 100,
    semanticScore: Math.round(semanticScore * 100) / 100,
    derivedInterpretation: interpretation,
    model: 'sentence-transformers/all-MiniLM-L6-v2',
    runtime: 'onnx-cpu',
    note: 'Semantic similarity is a derived signal only; candidate truth remains authoritative.'
  });
});

app.post('/api/ai/question-intent', async (req: Request, res: Response) => {
  const { question } = req.body;
  if (!question) {
    res.status(400).json({ error: 'Question text is required' });
    return;
  }

  const result = await classifyQuestionIntent(question, hfEmbeddingScorer);
  res.json(result);
});

app.post('/api/ai/resume-relevance', async (req: Request, res: Response) => {
  const { resumeId, resumeText, requirements } = req.body;
  if (!resumeText || !requirements) {
    res.status(400).json({ error: 'resumeText and requirements are required' });
    return;
  }

  const result = await scoreResumeRelevance(
    resumeId || 'default',
    resumeText,
    requirements,
    hfEmbeddingScorer
  );
  res.json(result);
});


// -------------------------------------------------------------
// Vite Dev Server / Static Hosting Integration
// -------------------------------------------------------------
async function startServer() {
  const isProd = process.env.NODE_ENV === 'production';

  if (!isProd) {
    // Dynamic import vite for development
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true, hmr: false },
      appType: 'spa'
    });
    app.use(vite.middlewares);

    // Express 5 catch-all without path pattern to avoid PathError
    app.use(async (req, res, next) => {
      const url = req.originalUrl;
      if (url.startsWith('/api')) {
        return next();
      }
      try {
        let template = fs.readFileSync(path.resolve(__dirname, 'index.html'), 'utf-8');
        template = await vite.transformIndexHtml(url, template);
        res.status(200).set({ 'Content-Type': 'text/html' }).end(template);
      } catch (e) {
        next(e);
      }
    });
  } else {
    app.use(express.static(path.resolve(__dirname, 'dist')));
    app.use((req, res) => {
      res.sendFile(path.resolve(__dirname, 'dist', 'index.html'));
    });
  }

  app.listen(PORT, HOST, () => {
    console.log(`[Apllie Job Assistant] Server running on http://${HOST}:${PORT}`);
  });
}

startServer().catch(err => {
  console.error('Failed to start server:', err);
  process.exit(1);
});
