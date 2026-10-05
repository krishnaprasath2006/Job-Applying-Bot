// Status / Health / Readiness API

import { api } from './client.js';
import type { HealthReport, ReadyReport, ApiStatusReport } from '../../types/api.js';

export const statusApi = {
  health: (): Promise<HealthReport> => api.get('/health'),
  ready: (): Promise<ReadyReport> => api.get('/ready'),
  status: (): Promise<ApiStatusReport> => api.get('/status'),
};