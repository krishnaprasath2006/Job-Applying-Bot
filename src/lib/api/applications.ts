// Applications API client
import { api } from './client.js';

// List applications with optional filtering
export const applicationApi = {
  list: (params?: {
    status?: string;
    company?: string;
    job_title?: string;
    has_followup?: boolean;
    before_followup?: string;
    after_followup?: string;
    limit?: number;
    offset?: number;
  }): Promise<any> => {
    return api.get('/applications', params);
  },

  // Get a single application
  get: (appId: string): Promise<any> => {
    return api.get(`/applications/${encodeURIComponent(appId)}`);
  },

  // Create a new application
  create: (payload: {
    job_id: string;
    status?: string;
    notes?: string;
    resume_id?: string;
    cover_letter_draft_id?: string;
    source_url?: string;
    source_job_metadata?: Record<string, any>;
    application_date?: string;
    next_followup?: string;
    interviewer_name?: string;
    interviewer_contact?: string;
  }): Promise<any> => {
    return api.post('/applications', payload);
  },

  // Update an existing application
  update: (appId: string, payload: {
    status?: string;
    notes?: string;
    resume_id?: string;
    cover_letter_draft_id?: string;
    source_url?: string;
    source_job_metadata?: Record<string, any>;
    application_date?: string;
    next_followup?: string;
    interviewer_name?: string;
    interviewer_contact?: string;
  }): Promise<any> => {
    return api.patch(`/applications/${encodeURIComponent(appId)}`, payload);
  },

  // Delete an application
  delete: (appId: string): Promise<void> => {
    return api.delete(`/applications/${encodeURIComponent(appId)}`);
  },

  // Transition application status
  transitionStatus: (appId: string, newStatus: string, note?: string): Promise<any> => {
    return api.post(`/applications/${encodeURIComponent(appId)}/transition`, { status: newStatus, note });
  },
};
