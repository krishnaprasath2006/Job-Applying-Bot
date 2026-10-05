// AI API

import { api } from './client.js';
import type { AiStatusReport, ApiStatusReport } from '../../types/api.js';

export const aiApi = {
  // Get AI status (truthful - no network probes)
  getStatus: (): Promise<AiStatusReport> =>
    api.get<ApiStatusReport>('/status').then((status) => status.ai),
};