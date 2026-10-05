// Jobs API

import { api } from './client.js';
import type {
  JobIngestRequest,
  MatchRequest,
  JobListResponse,
  JobResponse,
  AnalysisResponse,
  MatchResponse,
  ReportResponse,
  RelevanceResponse,
  ExplanationResponse,
  ReviewQueueResponse,
  SubmitApplicationResponse,
} from '../../types/api.js';

export const jobApi = {
  // List jobs with filters
  list: (params?: {
    status?: string;
    source?: string;
    candidate_id?: string;
    limit?: number;
    offset?: number;
  }): Promise<JobListResponse> =>
    api.get('/jobs', params),

  // Ingest a job from HTML
  ingest: (payload: JobIngestRequest): Promise<JobResponse> =>
    api.post('/jobs', payload),

  // Get review queue
  getReviewQueue: (): Promise<ReviewQueueResponse> =>
    api.get('/jobs/reviews'),

  // Get a single job
  get: (jobId: string): Promise<JobResponse> =>
    api.get(`/jobs/${encodeURIComponent(jobId)}`),

  // Analyze job (deterministic)
  analyze: (jobId: string): Promise<AnalysisResponse> =>
    api.post(`/jobs/${encodeURIComponent(jobId)}/analysis`),

  // Match job against candidate
  match: (jobId: string, payload: MatchRequest): Promise<MatchResponse> =>
    api.post(`/jobs/${encodeURIComponent(jobId)}/match`, payload),

  // Get dimension report
  report: (jobId: string): Promise<ReportResponse> =>
    api.get(`/jobs/${encodeURIComponent(jobId)}/report`),

  // Get resume relevance
  relevance: (jobId: string): Promise<RelevanceResponse> =>
    api.get(`/jobs/${encodeURIComponent(jobId)}/relevance`),

  // Get match explanation
  explain: (jobId: string): Promise<ExplanationResponse> =>
    api.get(`/jobs/${encodeURIComponent(jobId)}/explanation`),

  // Get review status
  reviewStatus: (jobId: string): Promise<{ job_id: string; review_status: string; open: boolean }> =>
    api.get(`/jobs/${encodeURIComponent(jobId)}/review`),

  // Resolve review
  resolveReview: (jobId: string, note?: string): Promise<{ job_id: string; resolved: boolean; review_status: string }> =>
    api.post(`/jobs/${encodeURIComponent(jobId)}/review/resolve`, { note }),

  // Apply (always returns SUBMISSION_DISABLED)
  apply: (jobId: string): Promise<SubmitApplicationResponse> =>
    api.post(`/jobs/${encodeURIComponent(jobId)}/apply`),
};