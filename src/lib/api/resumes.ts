// Resume API

import { api } from './client.js';
import type {
  ResumeIngestRequest,
  ResumeResponse,
  ResumeListResponse,
  ResumeSectionsResponse,
  ResumeVariantsResponse,
  DuplicateCheckResponse,
} from '../../types/api.js';

export const resumeApi = {
  // List all resumes for the candidate
  list: (candidateId: string = 'primary'): Promise<ResumeListResponse> =>
    api.get('/resumes'),

  // Ingest a resume file (server-side path)
  ingest: (payload: ResumeIngestRequest, candidateId: string = 'primary'): Promise<ResumeResponse> =>
    api.post('/resumes', payload),

  // Check if content hash is already stored
  checkDuplicate: (fileHash: string, candidateId: string = 'primary'): Promise<DuplicateCheckResponse> =>
    api.get('/resumes/duplicates', { file_hash: fileHash }),

  // Find content hashes stored more than once
  findDuplicates: (candidateId: string = 'primary'): Promise<{ candidate_id: string; duplicates: any[]; count: number }> =>
    api.get('/resumes/duplicates/stored'),

  // List variant names
  listVariants: (candidateId: string = 'primary'): Promise<{ candidate_id: string; variants: string[]; count: number }> =>
    api.get('/resumes/variants'),

  // Get section index
  sectionIndex: (candidateId: string = 'primary'): Promise<ResumeSectionsResponse> =>
    api.get('/resumes/sections'),

  // Get a single resume
  get: (resumeId: string): Promise<ResumeResponse> =>
    api.get(`/resumes/${encodeURIComponent(resumeId)}`),

  // Delete a resume
  delete: (resumeId: string): Promise<void> =>
    api.delete(`/resumes/${encodeURIComponent(resumeId)}`),
};