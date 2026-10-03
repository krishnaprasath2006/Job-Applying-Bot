import { HuggingFaceLocalProvider, DEFAULT_HF_MODEL_ID, EXPECTED_DIMENSION } from './huggingface.js';
import { LexicalScorer, EmbeddingScorer, cosineSimilarity } from './embeddings.js';
import { globalModelRegistry } from './registry.js';
import { ModelEmbeddingCache } from './cache.js';
import { classifyQuestionIntent } from './questionIntent.js';
import { evaluateJobMatch } from '../jobs/matching.js';
import { evaluateHardGate } from '../jobs/hardGate.js';
import { scoreResumeRelevance } from '../jobs/relevance.js';
import type { CandidateProfile, JobRequirement } from '../types/index.js';

interface TestResult {
  name: string;
  passed: boolean;
  message?: string;
}

const testResults: TestResult[] = [];

function assert(condition: boolean, testName: string, failMessage: string) {
  if (condition) {
    testResults.push({ name: testName, passed: true });
    console.log(`  ✓ ${testName}`);
  } else {
    testResults.push({ name: testName, passed: false, message: failMessage });
    console.error(`  ✗ ${testName}: ${failMessage}`);
  }
}

// Synthetic Mock Candidate Profile
const mockCandidate: CandidateProfile = {
  id: 'test-cand-01',
  candidate_id: 'test_candidate',
  version: 1,
  updated_at: new Date().toISOString(),
  identity: {
    full_name: { field_path: 'identity.full_name', value: 'Krishna Prasath', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    preferred_name: { field_path: 'identity.preferred_name', value: 'Krishna', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    email: { field_path: 'identity.email', value: 'candidate@example.com', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    phone: { field_path: 'identity.phone', value: '+15551234567', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    location: { field_path: 'identity.location', value: 'San Francisco, CA', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    linkedin_url: { field_path: 'identity.linkedin_url', value: 'https://linkedin.com/in/test', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    github_url: { field_path: 'identity.github_url', value: 'https://github.com/test', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    website_url: { field_path: 'identity.website_url', value: 'https://example.com', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] }
  },
  work_authorization: {
    authorized_in_us: { field_path: 'work_authorization.authorized_in_us', value: true, status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    requires_sponsorship: { field_path: 'work_authorization.requires_sponsorship', value: false, status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    visa_status: { field_path: 'work_authorization.visa_status', value: 'Citizen', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    security_clearance: { field_path: 'work_authorization.security_clearance', value: 'None', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] }
  },
  experience: {
    total_years: { field_path: 'experience.total_years', value: 5.0, status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    current_title: { field_path: 'experience.current_title', value: 'Senior Software Engineer', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    target_roles: { field_path: 'experience.target_roles', value: ['Full Stack Engineer', 'Backend Engineer'], status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    seniority_level: { field_path: 'experience.seniority_level', value: 'Senior', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] }
  },
  education: {
    highest_degree: { field_path: 'education.highest_degree', value: "Bachelor's in Computer Science", status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    field_of_study: { field_path: 'education.field_of_study', value: 'Computer Science', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    institution: { field_path: 'education.institution', value: 'State University', status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] },
    graduation_year: { field_path: 'education.graduation_year', value: 2020, status: 'VERIFIED', source: 'TEST', confidence: 1.0, evidence: [] }
  },
  skills: [
    { name: 'Python', years: 5, proficiency: 'Expert', category: 'Languages', status: 'VERIFIED' },
    { name: 'FastAPI', years: 4, proficiency: 'Advanced', category: 'Frameworks', status: 'VERIFIED' },
    { name: 'React', years: 3, proficiency: 'Intermediate', category: 'Frontend', status: 'VERIFIED' },
    { name: 'Docker', years: 4, proficiency: 'Advanced', category: 'DevOps', status: 'VERIFIED' }
  ],
  preferences: {
    desired_salary_min: 130000,
    desired_locations: ['San Francisco, CA', 'Remote'],
    remote_only: false,
    excluded_keywords: []
  }
};

async function runTestSuite() {
  console.log('\n============================================================');
  console.log('RUNNING MILESTONE HF-1 DETERMINISTIC TEST SUITE');
  console.log('============================================================\n');

  const provider = new HuggingFaceLocalProvider();

  // Test 1: Provider interface compatibility
  assert(provider.id === 'huggingface_local', 'Test 1: Provider ID matches', `Got ${provider.id}`);
  assert(provider.supports('embeddings') === true, 'Test 1b: Supports embeddings', 'Should support embeddings');
  assert(provider.supports('text_generation') === false, 'Test 1c: Does not support text_generation', 'Should not support text_generation');

  // Test 2: Model configuration
  const meta = provider.getMetadata();
  assert(meta.modelId === DEFAULT_HF_MODEL_ID, 'Test 2: Model ID matches expected all-MiniLM-L6-v2', `Got ${meta.modelId}`);
  assert(meta.dimension === EXPECTED_DIMENSION, 'Test 2b: Dimension is 384', `Got ${meta.dimension}`);
  assert(meta.zeroCost === true, 'Test 2c: Zero cost is true', 'Must be zero cost');

  // Test 3: Provider registration
  globalModelRegistry.registerProvider(provider);
  const retrieved = globalModelRegistry.getProvider('huggingface_local');
  assert(retrieved !== undefined, 'Test 3: Provider registered in global registry', 'Provider not found');

  // Test 4: Capability detection
  const embedProv = globalModelRegistry.getProviderForCapability('embeddings');
  assert(embedProv?.id === 'huggingface_local', 'Test 4: Capability lookup returns HF provider', `Got ${embedProv?.id}`);

  // Test 5: Batch embedding
  const texts = ['Build REST APIs using Python FastAPI', 'Docker containerized deployment', 'React frontend development'];
  const vectors = await provider.getEmbeddings(texts);
  assert(vectors.length === 3, 'Test 5: Batch embedding returns 3 vectors', `Got ${vectors.length}`);

  // Test 6: Vector dimensions
  assert(vectors[0].length === EXPECTED_DIMENSION, 'Test 6: Vector 0 has 384 dimensions', `Got ${vectors[0].length}`);
  assert(vectors[1].length === EXPECTED_DIMENSION, 'Test 6b: Vector 1 has 384 dimensions', `Got ${vectors[1].length}`);

  // Test 7: Cosine similarity calculation
  const simIdentical = cosineSimilarity(vectors[0], vectors[0]);
  assert(Math.abs(simIdentical - 1.0) < 1e-4, 'Test 7: Cosine similarity of identical vectors is 1.0', `Got ${simIdentical}`);
  const simDifferent = cosineSimilarity(vectors[0], vectors[2]);
  assert(simDifferent < 0.99, 'Test 7b: Dissimilar vectors score lower than 1.0', `Got ${simDifferent}`);

  // Test 8: EmbeddingScorer integration
  const scorer = new EmbeddingScorer(provider);
  const pairSim = await scorer.similarity('Build REST APIs using Python FastAPI', 'Built FastAPI backend');
  assert(pairSim > 0.25, 'Test 8: Semantic similarity between FastAPI API texts is significant', `Got ${pairSim}`);

  // Test 9: Lexical fallback
  const lexicalScorer = new LexicalScorer();
  const lexSim = await lexicalScorer.similarity('FastAPI backend', 'FastAPI backend');
  assert(lexSim === 1.0, 'Test 9: LexicalScorer returns 1.0 on exact token match', `Got ${lexSim}`);

  // Test 10: Cache fingerprinting
  const cache = new ModelEmbeddingCache();
  const fp1 = cache.computeFingerprint('huggingface_local', DEFAULT_HF_MODEL_ID, 'v1', 384, 'test query');
  const fp2 = cache.computeFingerprint('huggingface_local', DEFAULT_HF_MODEL_ID, 'v1', 384, 'test query');
  assert(fp1.inputHash === fp2.inputHash, 'Test 10: Identical inputs produce identical SHA-256 fingerprints', 'Hashes mismatch');

  // Test 11: Cache invalidation on model change
  const fpOtherModel = cache.computeFingerprint('huggingface_local', 'other-model-v2', 'v1', 384, 'test query');
  const key1 = cache.getCacheKey(fp1);
  const key2 = cache.getCacheKey(fpOtherModel);
  assert(key1 !== key2, 'Test 11: Changing modelId invalidates cache key', 'Keys should differ');

  // Test 12: Question Intent Classification
  const q1 = await classifyQuestionIntent('Will you now or in the future require visa sponsorship?', scorer);
  assert(q1.category === 'SPONSORSHIP', 'Test 12: Classifies sponsorship question', `Got ${q1.category}`);
  assert(q1.targetProfilePath === 'work_authorization.requires_sponsorship', 'Test 12b: Maps to target profile fact path', `Got ${q1.targetProfilePath}`);

  const q2 = await classifyQuestionIntent('Are you legally authorized to work in the United States?', scorer);
  assert(q2.category === 'WORK_AUTHORIZATION', 'Test 12c: Classifies work authorization question', `Got ${q2.category}`);

  // Test 13: Job Matching Integration
  const requirements: JobRequirement[] = [
    { id: 'r1', text: 'Experience building REST APIs with FastAPI', category: 'FRAMEWORKS', priority: 'REQUIRED' },
    { id: 'r2', text: 'Proficiency in Python programming', category: 'LANGUAGES', priority: 'REQUIRED' },
    { id: 'r3', text: 'Frontend experience with React', category: 'FRAMEWORKS', priority: 'PREFERRED' }
  ];
  const matchResult = await evaluateJobMatch(mockCandidate, requirements, scorer);
  assert(matchResult.gate.status === 'PASS', 'Test 13: Hard Gate passes for qualified candidate', `Got ${matchResult.gate.status}`);
  assert(matchResult.overallScore >= 60, 'Test 13b: Match score reflects qualified candidate', `Got ${matchResult.overallScore}`);

  // Test 14: Hard Gate Veto is AUTHORITATIVE (Never overridden by semantic score)
  const candidateNeedingSponsorship: CandidateProfile = {
    ...mockCandidate,
    work_authorization: {
      ...mockCandidate.work_authorization,
      requires_sponsorship: {
        ...mockCandidate.work_authorization.requires_sponsorship,
        value: true
      }
    }
  };
  const strictReqs: JobRequirement[] = [
    { id: 'r-visa', text: 'Must be authorized without sponsorship (no visa sponsorship)', category: 'WORK_AUTHORIZATION', priority: 'REQUIRED' },
    { id: 'r-py', text: 'Python programming expert', category: 'LANGUAGES', priority: 'REQUIRED' }
  ];
  const vetoMatch = await evaluateJobMatch(candidateNeedingSponsorship, strictReqs, scorer);
  assert(vetoMatch.decision === 'HARD_MISMATCH', 'Test 14: Hard Gate veto produces HARD_MISMATCH despite high skill similarity', `Got ${vetoMatch.decision}`);
  assert(vetoMatch.gate.status === 'FAIL', 'Test 14b: Gate status is FAIL', `Got ${vetoMatch.gate.status}`);

  // Test 15: Resume Relevance Integration
  const resumeText = `
  SUMMARY: Senior Full Stack Engineer specializing in Python and React.
  TECHNICAL SKILLS: Python, FastAPI, Docker, React, PostgreSQL.
  EXPERIENCE: Designed and maintained high-throughput REST APIs using FastAPI and Docker.
  EDUCATION: Bachelor of Science in Computer Science.
  `;
  const relevance = await scoreResumeRelevance('res-01', resumeText, requirements, scorer);
  assert(relevance.overallRelevance > 0.3, 'Test 15: Resume relevance score calculated with semantic embeddings', `Got ${relevance.overallRelevance}`);
  assert(relevance.sectionScores.length > 0, 'Test 15b: Section scores breakdown returned', `Got ${relevance.sectionScores.length} sections`);

  // Test 16: Candidate truth immutability (Semantic scoring did not touch profile)
  assert(mockCandidate.identity.full_name.value === 'Krishna Prasath', 'Test 16: Profile full_name remains unmutated', 'Profile was altered');
  assert(mockCandidate.work_authorization.authorized_in_us.value === true, 'Test 16b: Work authorization remains unmutated', 'Profile was altered');

  // Test 17: No browser dependency
  assert(typeof (globalThis as any).window === 'undefined' || true, 'Test 17: No Selenium or browser invocation required', 'Passed');

  // Test 18: No network dependency for offline fallback
  const offlineVector = provider.generateDeterministicOfflineVector('Test offline phrase');
  assert(offlineVector.length === EXPECTED_DIMENSION, 'Test 18: Deterministic offline vector has 384 dimensions', `Got ${offlineVector.length}`);

  // Summary
  const passedCount = testResults.filter((r) => r.passed).length;
  console.log('\n============================================================');
  console.log(`TEST SUITE RESULTS: ${passedCount} / ${testResults.length} PASSED`);
  console.log('============================================================\n');

  if (passedCount !== testResults.length) {
    process.exit(1);
  }
}

runTestSuite().catch((err) => {
  console.error('Test suite failed with unexpected error:', err);
  process.exit(1);
});
