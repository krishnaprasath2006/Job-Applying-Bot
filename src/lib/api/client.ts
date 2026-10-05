// Base API client with error handling and typed responses

import type { ErrorEnvelope } from '../../types/api.js';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

export class ApiError extends Error {
  public readonly code: string;
  public readonly details: Record<string, any>;
  public readonly status: number;

  constructor(response: Response, envelope: ErrorEnvelope) {
    super(envelope.error.message);
    this.name = 'ApiError';
    this.code = envelope.error.code;
    this.details = envelope.error.details;
    this.status = response.status;
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let envelope: ErrorEnvelope;
    try {
      envelope = await response.json();
    } catch {
      envelope = {
        error: {
          code: 'HTTP_ERROR',
          message: response.statusText,
          details: { status: response.status },
        },
      };
    }
    throw new ApiError(response, envelope);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

/** Query values are coerced to strings; `undefined` entries are dropped. */
export type QueryParams = Record<string, string | number | boolean | undefined>;

function buildUrl(endpoint: string, params?: QueryParams): string {
  const url = new URL(`${API_BASE}${endpoint}`, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined) return;
      url.searchParams.append(key, String(value));
    });
  }
  return url.toString();
}

export const api = {
  get: async <T>(endpoint: string, params?: QueryParams): Promise<T> => {
    const response = await fetch(buildUrl(endpoint, params), {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
    });
    return handleResponse<T>(response);
  },

  post: async <T>(endpoint: string, body?: any): Promise<T> => {
    const response = await fetch(buildUrl(endpoint), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    return handleResponse<T>(response);
  },

  patch: async <T>(endpoint: string, body?: any): Promise<T> => {
    const response = await fetch(buildUrl(endpoint), {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    return handleResponse<T>(response);
  },

  delete: async <T>(endpoint: string): Promise<T> => {
    const response = await fetch(buildUrl(endpoint), {
      method: 'DELETE',
      headers: {
        'Accept': 'application/json',
      },
    });
    return handleResponse<T>(response);
  },
};

// Convenience method for checking if error is a specific code
export function isApiErrorCode(error: unknown, code: string): boolean {
  return error instanceof ApiError && error.code === code;
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}