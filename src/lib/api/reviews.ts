// Reviews API (uses jobApi for review operations)

import { jobApi } from './jobs.js';

export const reviewApi = {
  getQueue: jobApi.getReviewQueue,
  getStatus: jobApi.reviewStatus,
  resolve: jobApi.resolveReview,
};