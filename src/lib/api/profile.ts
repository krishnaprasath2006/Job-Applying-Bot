// Profile API

import { api } from './client.js';
import type {
  ProfileResponse,
  FactResponse,
  FactUpdate,
  ProfileValidationResponse,
  ProfileCompletenessResponse,
  UnknownFieldsResponse,
} from '../../types/api.js';

export const profileApi = {
  // Get the profile (returns empty template if absent)
  get: (candidateId: string = 'primary'): Promise<ProfileResponse> =>
    api.get('/profile'),

  // Update a single fact
  updateFact: (candidateId: string, payload: FactUpdate): Promise<ProfileResponse> =>
    api.post('/profile', payload),

  // Get a single fact with evidence
  getFact: (fieldPath: string, candidateId: string = 'primary'): Promise<FactResponse> =>
    api.get(`/profile/facts/${encodeURIComponent(fieldPath)}`),

  // Validate the profile
  validate: (candidateId: string = 'primary'): Promise<ProfileValidationResponse> =>
    api.get('/profile/validation'),

  // Get completeness fraction
  completeness: (candidateId: string = 'primary'): Promise<ProfileCompletenessResponse> =>
    api.get('/profile/completeness'),

  // List unknown fields
  unknownFields: (candidateId: string = 'primary'): Promise<UnknownFieldsResponse> =>
    api.get('/profile/unknown'),
};