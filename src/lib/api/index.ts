// API Client exports

export * from './client.js';
export * from './status.js';
export * from './profile.js';
export * from './resumes.js';
export * from './jobs.js';
export * from './reviews.js';
export * from './ai.js';

// Convenience: combined API object
import { api } from './client.js';
import { statusApi } from './status.js';
import { profileApi } from './profile.js';
import { resumeApi } from './resumes.js';
import { jobApi } from './jobs.js';
import { reviewApi } from './reviews.js';
import { aiApi } from './ai.js';

export const API = {
  // Raw client
  raw: api,
  // Domain APIs
  status: statusApi,
  profile: profileApi,
  resumes: resumeApi,
  jobs: jobApi,
  reviews: reviewApi,
  ai: aiApi,
};