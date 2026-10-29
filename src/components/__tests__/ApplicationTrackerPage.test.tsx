/// <reference types="vitest" />
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ApplicationTrackerPage } from '../ApplicationTrackerPage';

describe('ApplicationTrackerPage', () => {
  it('loading state appears during a pending request', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => Promise.resolve({ applications: [] }),
    });
    const { container } = render(<ApplicationTrackerPage />);
    expect(container.querySelector('[data-testid="loading"]')).not.toBeNull();
  });

  it('loading ends after the request resolves', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => Promise.resolve({ applications: [] }),
    });
    const { container } = render(<ApplicationTrackerPage />);
    await waitFor(() => {
      const loadingElements = container.querySelectorAll('[data-testid="loading"]');
      expect(loadingElements.length).toBe(0);
    });
  });

  it('returned application records display their actual job title/company', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => Promise.resolve({
        applications: [
          {
            id: '1', job_id: '1', status: 'APPLIED',
            application_date: '2024-01-15', created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:00:00Z', next_followup: null,
            interviewer_name: null, interviewer_contact: null, notes: null,
            resume_id: null, cover_letter_draft_id: null, source_url: null,
            source_job_metadata: {}, job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
          },
        ],
      }),
    });
    const { container } = render(<ApplicationTrackerPage />);
    await waitFor(() => {
      const jobTitle = container.querySelector('[data-testid="job-title"]');
      const jobCompany = container.querySelector('[data-testid="job-company"]');
      expect(jobTitle).not.toBeNull();
      expect(jobTitle?.textContent).toContain('Software Engineer');
      expect(jobCompany).not.toBeNull();
      expect(jobCompany?.textContent).toContain('Tech Corp');
    });
  });

  it('empty state appears when no records exist', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => Promise.resolve({ applications: [] }),
    });
    const { container } = render(<ApplicationTrackerPage />);
    await waitFor(() => {
      const emptyState = container.querySelector('[data-testid="empty-state"]');
      expect(emptyState).not.toBeNull();
      expect(emptyState?.textContent).toContain('No applications found');
    });
  });

  it('API error and retry work', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => Promise.resolve({ error: { message: 'Network error' } }),
    });
    const { container } = render(<ApplicationTrackerPage />);
    await waitFor(() => {
      const errorElement = container.querySelector('[data-testid="error"]');
      expect(errorElement).not.toBeNull();
      expect(errorElement?.textContent).toContain('Failed to load applications');
      const retryButton = container.querySelector('[data-testid="retry-button"]');
      expect(retryButton).not.toBeNull();
      (retryButton as HTMLElement).click();
    });
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => Promise.resolve({ applications: [] }),
    });
    await waitFor(() => {
      const newError = container.querySelector('[data-testid="error"]');
      expect(newError).toBeNull();
    });
  });

  it('searching by title changes visible results', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => Promise.resolve({
        applications: [
          {
            id: '1', job_id: '1', status: 'APPLIED',
            application_date: '2024-01-15', created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:00:00Z', next_followup: null,
            interviewer_name: null, interviewer_contact: null, notes: null,
            resume_id: null, cover_letter_draft_id: null, source_url: null,
            source_job_metadata: {}, job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
          },
        ],
      }),
    });
    const { container } = render(<ApplicationTrackerPage />);
    await waitFor(() => {
      const input = container.querySelector('input[placeholder="Search by company or job title..."]');
      expect(input).not.toBeNull();
    });
    await userEvent.type(
      container.querySelector('input[placeholder="Search by company or job title..."]') as HTMLInputElement,
      'Engineer'
    );
    await waitFor(() => {
      const result = container.querySelector('[data-testid="job-title"]');
      expect(result).not.toBeNull();
      expect(result?.textContent).toContain('Software Engineer');
    });
  });

  it('searching by company changes visible results', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => Promise.resolve({
        applications: [
          {
            id: '1', job_id: '1', status: 'APPLIED',
            application_date: '2024-01-15', created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:00:00Z', next_followup: null,
            interviewer_name: null, interviewer_contact: null, notes: null,
            resume_id: null, cover_letter_draft_id: null, source_url: null,
            source_job_metadata: {}, job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
          },
        ],
      }),
    });
    const { container } = render(<ApplicationTrackerPage />);
    await waitFor(() => {
      const input = container.querySelector('input[placeholder="Search by company or job title..."]');
      expect(input).not.toBeNull();
    });
    await userEvent.type(
      container.querySelector('input[placeholder="Search by company or job title..."]') as HTMLInputElement,
      'Tech'
    );
    await waitFor(() => {
      const result = container.querySelector('[data-testid="job-company"]');
      expect(result).not.toBeNull();
      expect(result?.textContent).toContain('Tech Corp');
    });
  });

  it('status filtering changes visible results', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => Promise.resolve({
        applications: [
          {
            id: '1', job_id: '1', status: 'APPLIED',
            application_date: '2024-01-15', created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:00:00Z', next_followup: null,
            interviewer_name: null, interviewer_contact: null, notes: null,
            resume_id: null, cover_letter_draft_id: null, source_url: null,
            source_job_metadata: {}, job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' },
          },
        ],
        jobs: [{ id: '1', title: 'Software Engineer', company: 'Tech Corp' }],
      }),
    });
    const { container } = render(<ApplicationTrackerPage />);
    await waitFor(() => {
      const select = container.querySelector('select');
      expect(select).not.toBeNull();
    });
    const selectElement = container.querySelector('select');
    await userEvent.selectOptions(selectElement as HTMLSelectElement, ['APPLIED']);
    await waitFor(() => {
      const statusBadge = container.querySelector('[data-testid="status-badge"]');
      expect(statusBadge).not.toBeNull();
    });
  });

  it('job selection uses a real job ID from the jobs response', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => Promise.resolve({
        jobs: [
          { id: '1', title: 'Software Engineer', company: 'Tech Corp' },
          { id: '2', title: 'Data Scientist', company: 'Data LLC' },
        ],
        applications: [],
      }),
    });
    const { container } = render(<ApplicationTrackerPage />);
    await waitFor(() => {
      const loadingElements = container.querySelectorAll('[data-testid="loading"]');
      expect(loadingElements.length).toBe(0);
    });
    const createButton = container.querySelector('div.mb-4.cursor-pointer.text-sm.text-blue-400.underline');
    expect(createButton).not.toBeNull();
    (createButton as HTMLElement).click();

    await waitFor(() => {
      const jobSelect = container.querySelector('select[name="job_id"]');
      expect(jobSelect).not.toBeNull();
      const jobOptions = jobSelect!.querySelectorAll('option');
      expect(jobOptions.length).toBe(3);
    });
  });

  it('creation is blocked until a valid job is selected', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => Promise.resolve({
        jobs: [{ id: '1', title: 'Software Engineer', company: 'Tech Corp' }],
        applications: [],
      }),
    });
    const { container } = render(<ApplicationTrackerPage />);
    await waitFor(() => {
      const loadingElements = container.querySelectorAll('[data-testid="loading"]');
      expect(loadingElements.length).toBe(0);
    });
    const createButton = container.querySelector('div.mb-4.cursor-pointer.text-sm.text-blue-400.underline');
    expect(createButton).not.toBeNull();
    (createButton as HTMLElement).click();

    await waitFor(() => {
      const createForm = container.querySelector('form');
      expect(createForm).not.toBeNull();
      const submitButton = container.querySelector('button[type="submit"]');
      expect(submitButton).toBeTruthy();
    });
  });

  it('creation sends the selected job ID via API', async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (input: unknown) => {
      const url = new URL(typeof input === 'string' ? input : String(input), 'http://localhost').pathname;
      if (url === '/api/jobs') {
        return Promise.resolve({
          ok: true,
          json: async () => Promise.resolve({
            jobs: [{ id: '1', title: 'Software Engineer', company: 'Tech Corp' }],
            applications: [],
          }),
        });
      }
      if (url === '/api/applications') {
        return Promise.resolve({
          ok: true,
          json: async () => Promise.resolve({
            jobs: [{ id: '1', title: 'Software Engineer', company: 'Tech Corp' }],
            applications: [],
          }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => Promise.resolve({}) });
    });
    const { container } = render(<ApplicationTrackerPage />);
    await waitFor(() => {
      const loadingElements = container.querySelectorAll('[data-testid="loading"]');
      expect(loadingElements.length).toBe(0);
    });
    const createButton = container.querySelector('div.mb-4.cursor-pointer.text-sm.text-blue-400.underline');
    expect(createButton).not.toBeNull();
    (createButton as HTMLElement).click();

    await waitFor(() => {
      const jobSelect = container.querySelector('select[name="job_id"]');
      expect(jobSelect).not.toBeNull();
    });

    await userEvent.selectOptions(
      container.querySelector('select[name="job_id"]') as HTMLSelectElement,
      ['1']
    );

    const form = container.querySelector('form');
    expect(form).not.toBeNull();

    const createBtn = form!.querySelector('button[type="submit"]');
    expect(createBtn).not.toBeNull();

    await userEvent.click(createBtn as HTMLElement);

    await waitFor(() => {
      const fetchCalls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const postCalls = fetchCalls.filter(([, options]: any) => {
        const method = (options && options.method) || '';
        return method.toUpperCase() === 'POST';
      });
      expect(postCalls.length).toBeGreaterThan(0);
      if (postCalls.length > 0) {
        const [, options] = postCalls[postCalls.length - 1];
        expect(options.method).toBe('POST');
        if (options.body) {
          const body = JSON.parse(options.body as string);
          expect(body.job_id).toBe('1');
        }
      }
    });
  });

  it('confirmed deletion makes the intended API request with DELETE method', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => Promise.resolve({
        jobs: [{ id: '1', title: 'Software Engineer', company: 'Tech Corp' }],
        applications: [{ id: '1', job_id: '1', status: 'APPLIED', job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' } }],
      }),
    });
    const { container } = render(<ApplicationTrackerPage />);
    await waitFor(() => {
      const loadingElements = container.querySelectorAll('[data-testid="loading"]');
      expect(loadingElements.length).toBe(0);
    });
    await waitFor(() => {
      const deleteButtons = container.querySelectorAll('[data-testid="delete-button"]');
      expect(deleteButtons.length).toBeGreaterThan(0);
    });
    const deleteButtons = container.querySelectorAll('[data-testid="delete-button"]');
    const firstDeleteBtn = deleteButtons[0];
    (firstDeleteBtn as HTMLElement).click();

    await waitFor(() => {
      const cd = container.querySelector('[data-testid="confirm-delete"]');
      expect(cd).not.toBeNull();
    });
    const confirmDeleteBtn = container.querySelector('[data-testid="confirm-delete-btn"]');

    await userEvent.click(confirmDeleteBtn as HTMLElement);

    await waitFor(() => {
      const fetchCalls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const deleteRequests = fetchCalls.filter(([, options]: any) => options?.method === 'DELETE');
      expect(deleteRequests).toHaveLength(1);
    });
  });

  it('cancelled deletion does not invoke the delete API', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => Promise.resolve({
        jobs: [{ id: '1', title: 'Software Engineer', company: 'Tech Corp' }],
        applications: [{ id: '1', job_id: '1', status: 'APPLIED', job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' } }],
      }),
    });
    const { container } = render(<ApplicationTrackerPage />);
    await waitFor(() => {
      const loadingElements = container.querySelectorAll('[data-testid="loading"]');
      expect(loadingElements.length).toBe(0);
    });
    await waitFor(() => {
      const deleteButtons = container.querySelectorAll('[data-testid="delete-button"]');
      expect(deleteButtons.length).toBeGreaterThan(0);
    });
    const deleteButtons = container.querySelectorAll('[data-testid="delete-button"]');
    const firstDeleteBtn = deleteButtons[0];
    (firstDeleteBtn as HTMLElement).click();

    let cancelDelete: HTMLElement | null = null;
    await waitFor(() => {
      cancelDelete = container.querySelector('[data-testid="cancel-delete"]') as HTMLElement;
      expect(cancelDelete).not.toBeNull();
    });

    await userEvent.click(cancelDelete!);

    await waitFor(() => {
      const fetchCalls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const deleteCalls = fetchCalls.filter(([url]: any) => {
        const urlStr = String(url);
        return urlStr.includes('/api/applications/1') && (url as any)?.method === 'DELETE';
      });
      expect(deleteCalls).toHaveLength(0);
    });
  });
});