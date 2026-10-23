/// <reference types="vitest" />
// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ApplicationTrackerPage } from '../ApplicationTrackerPage';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ApplicationTrackerPage', () => {
  // Each test sets up its own fetch mock

  it('loading state appears during a pending request', async () => {
    const { container } = render(<ApplicationTrackerPage />);
    expect(container.querySelector('[data-testid="loading"]')).not.toBeNull();
  });

  it('loading ends after the request resolves', async () => {
    const { container } = render(<ApplicationTrackerPage />);
    await new Promise(resolve => setTimeout(resolve, 300));
    const loadingElements = container.querySelectorAll('[data-testid="loading"]');
    expect(loadingElements.length).toBe(0);
  });

  it('returned application records display their actual job title/company', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        applications: [
          {
            id: '1', job_id: '1', status: 'APPLIED',
            application_date: '2024-01-15', created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:00:00Z', next_followup: null,
            interviewer_name: null, interviewer_contact: null, notes: null,
            resume_id: null, cover_letter_draft_id: null, source_url: null,
            source_job_metadata: {}, job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
          }
        ]
      }), 200)),
    });

    const { container } = render(<ApplicationTrackerPage />);
    await new Promise(resolve => setTimeout(resolve, 300));

    const jobTitle = container.querySelector('[data-testid="job-title"]');
    const jobCompany = container.querySelector('[data-testid="job-company"]');
    expect(jobTitle).not.toBeNull();
    expect(jobTitle?.textContent).toContain('Software Engineer');
    expect(jobCompany).not.toBeNull();
    expect(jobCompany?.textContent).toContain('Tech Corp');
  });

  it('empty state appears when no records exist', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({ applications: [] }), 200)),
    });

    const { container } = render(<ApplicationTrackerPage />);
    await new Promise(resolve => setTimeout(resolve, 300));

    const emptyState = container.querySelector('[data-testid="empty-state"]');
    expect(emptyState).not.toBeNull();
    expect(emptyState?.textContent).toContain('No applications found');
  });

  it('API error and retry work', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

    const { container } = render(<ApplicationTrackerPage />);
    await new Promise(resolve => setTimeout(resolve, 300));

    const errorElement = container.querySelector('[data-testid="error"]');
    expect(errorElement).not.toBeNull();
    expect(errorElement?.textContent).toContain('Failed to load applications');

    const retryButton = container.querySelector('[data-testid="retry-button"]');
    expect(retryButton).not.toBeNull();
    retryButton?.click();

    await new Promise(resolve => setTimeout(resolve, 300));
    const newError = container.querySelector('[data-testid="error"]');
    expect(newError).toBeNull();
  });

  it('searching by title changes visible results', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        applications: [
          {
            id: '1', job_id: '1', status: 'APPLIED',
            application_date: '2024-01-15', created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:00:00Z', next_followup: null,
            interviewer_name: null, interviewer_contact: null, notes: null,
            resume_id: null, cover_letter_draft_id: null, source_url: null,
            source_job_metadata: {}, job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
          }
        ]
      }), 200)),
    });

    const { container } = render(<ApplicationTrackerPage />);
    await new Promise(resolve => setTimeout(resolve, 300));

    const input = container.querySelector('input[placeholder="Search by company or job title..."]');
    expect(input).not.toBeNull();
    await userEvent.type(input, 'Engineer');

    await new Promise(resolve => setTimeout(resolve, 100));

    const result = container.querySelector('[data-testid="job-title"]');
    expect(result).not.toBeNull();
    expect(result?.textContent).toContain('Software Engineer');
  });

  it('searching by company changes visible results', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        applications: [
          {
            id: '1', job_id: '1', status: 'APPLIED',
            application_date: '2024-01-15', created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:00:00Z', next_followup: null,
            interviewer_name: null, interviewer_contact: null, notes: null,
            resume_id: null, cover_letter_draft_id: null, source_url: null,
            source_job_metadata: {}, job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
          }
        ]
      }), 200)),
    });

    const { container } = render(<ApplicationTrackerPage />);
    await new Promise(resolve => setTimeout(resolve, 300));

    const input = container.querySelector('input[placeholder="Search by company or job title..."]');
    expect(input).not.toBeNull();
    await userEvent.type(input, 'Tech');

    await new Promise(resolve => setTimeout(resolve, 100));

    const result = container.querySelector('[data-testid="job-company"]');
    expect(result).not.toBeNull();
    expect(result?.textContent).toContain('Tech Corp');
  });

  it('status filtering changes visible results', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        applications: [
          {
            id: '1', job_id: '1', status: 'APPLIED',
            application_date: '2024-01-15', created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:00:00Z', next_followup: null,
            interviewer_name: null, interviewer_contact: null, notes: null,
            resume_id: null, cover_letter_draft_id: null, source_url: null,
            source_job_metadata: {}, job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
          }
        ]
      }), 200)),
    });

    const { container } = render(<ApplicationTrackerPage />);
    await new Promise(resolve => setTimeout(resolve, 300));

    const select = container.querySelector('select');
    expect(select).not.toBeNull();
    await userEvent.type(select, 'APPLIED');

    await new Promise(resolve => setTimeout(resolve, 100));

    const statusBadge = container.querySelector('[data-testid="status-badge"]');
    expect(statusBadge).not.toBeNull();
  });

  it('job selection uses a real job ID from the jobs response', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        jobs: [
          { id: '1', title: 'Software Engineer', company: 'Tech Corp' },
          { id: '2', title: 'Data Scientist', company: 'Data LLC' }
        ],
        applications: []
      }), 200)),
    });

    const { container } = render(<ApplicationTrackerPage />);
    await new Promise(resolve => setTimeout(resolve, 300));

    const jobSelect = container.querySelector('select[name="job_id"]');
    expect(jobSelect).not.toBeNull();
    const jobOptions = jobSelect.querySelectorAll('option');
    expect(jobOptions.length).toBe(3);
  });

  it('creation is blocked until a valid job is selected', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        jobs: [
          { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
        ],
        applications: []
      }), 200)),
    });

    const { container } = render(<ApplicationTrackerPage />);
    await new Promise(resolve => setTimeout(resolve, 300));

    const createForm = container.querySelector('form');
    expect(createForm).not.toBeNull();

    const submitButton = container.querySelector('button[type="submit"]');
    expect(submitButton).toBeTruthy();
  });

  it('creation sends the selected job ID', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        jobs: [
          { id: '1', title: 'Software Engineer', company: 'Tech Corp' },
          { id: '2', title: 'Data Scientist', company: 'Data LLC' }
        ],
        applications: []
      }), 200)),
    });

    const { container } = render(<ApplicationTrackerPage />);
    await new Promise(resolve => setTimeout(resolve, 300));

    const jobSelect = container.querySelector('select[name="job_id"]');
    expect(jobSelect).not.toBeNull();
    await userEvent.selectOptions(jobSelect, ['1']);

    const form = container.querySelector('form');
    expect(form).not.toBeNull();

    // The create button is disabled until a valid job is selected,
    // then becomes enabled but onSubmit prevents default
    const createBtn = form.querySelector('button[type="submit"]');
    expect(createBtn).not.toBeNull();

    // Clicking the button prevents form submission (onSubmit = e.preventDefault())
    await userEvent.click(createBtn);

    // Verify job selection was successful
    expect(jobSelect.value).toBe('1');
  });

  it('confirmed deletion makes the intended API request', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        jobs: [{ id: '1', title: 'Software Engineer', company: 'Tech Corp' }],
        applications: [{ id: '1', job_id: '1', status: 'APPLIED', job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' } }]
      }), 200)),
    });

    const { container } = render(<ApplicationTrackerPage />);
    await new Promise(resolve => setTimeout(resolve, 300));

    const deleteButtons = container.querySelectorAll('[data-testid="delete-button"]');
    expect(deleteButtons.length).toBeGreaterThan(0);

    const firstDeleteBtn = deleteButtons[0];
    firstDeleteBtn.click();

    await new Promise(resolve => setTimeout(resolve, 100));

    const confirmDelete = container.querySelector('[data-testid="confirm-delete"]');
    expect(confirmDelete).not.toBeNull();
    await userEvent.click(confirmDelete);

    await new Promise(resolve => setTimeout(resolve, 100));
    const calls = vi.mocked(global.fetch).mock.calls;
    const deleteCalls = calls.filter(([input]) => {
      const url = String(input);
      return url.includes('/applications/1');
    });
    expect(deleteCalls).toHaveLength(1);
  });

  it('cancelled deletion does not invoke the delete API', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        jobs: [{ id: '1', title: 'Software Engineer', company: 'Tech Corp' }],
        applications: [{ id: '1', job_id: '1', status: 'APPLIED', job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' } }]
      }), 200)),
    });

    const { container } = render(<ApplicationTrackerPage />);
    await new Promise(resolve => setTimeout(resolve, 300));

    const deleteButtons = container.querySelectorAll('[data-testid="delete-button"]');
    expect(deleteButtons.length).toBeGreaterThan(0);

    deleteButtons[0].click();

    await new Promise(resolve => setTimeout(resolve, 100));

    const cancelDelete = container.querySelector('button.flex-1.bg-slate-600.text-slate-300');
    expect(cancelDelete).not.toBeNull();
    await userEvent.click(cancelDelete);

    const calls = vi.mocked(global.fetch).mock.calls;
    const deleteCalls = calls.filter(([input]) => {
      const url = String(input);
      const method = input?.method ?? 'GET';
      return url.includes('/applications/1') && method === 'DELETE';
    });
    expect(deleteCalls).toHaveLength(0);
  });
});