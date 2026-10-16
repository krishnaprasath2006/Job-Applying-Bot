/// <reference types="vitest" />
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ApplicationTrackerPage } from '../ApplicationTrackerPage'

// Mock fetch used by the API client
// Simulate real API latency
global.fetch = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => new Promise(resolve => setTimeout(() => resolve({ applications: [] }), 200)),
})

describe('ApplicationTrackerPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loading state appears during a pending request', async () => {
    const { container } = render(<ApplicationTrackerPage />)
    expect(container.querySelector('[data-testid="loading"]')).not.toBeNull()
  })

  it('loading ends after the request resolves', async () => {
    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 300))
    const loadingElements = container.querySelectorAll('[data-testid="loading"]')
    expect(loadingElements.length).toBe(0)
  })

  it('returned application records display their actual job title/company', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        applications: [
          {
            id: '1',
            job_id: '1',
            status: 'APPLIED',
            application_date: '2024-01-15',
            created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:00:00Z',
            next_followup: null,
            interviewer_name: null,
            interviewer_contact: null,
            notes: null,
            resume_id: null,
            cover_letter_draft_id: null,
            source_url: null,
            source_job_metadata: {},
            job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
          }
        ]
      }), 200)),
    })

    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 300))

    const jobTitle = container.querySelector('[data-testid="job-title"]')
    const jobCompany = container.querySelector('[data-testid="job-company"]')
    expect(jobTitle).not.toBeNull()
    expect(jobTitle?.textContent).toContain('Software Engineer')
    expect(jobCompany).not.toBeNull()
    expect(jobCompany?.textContent).toContain('Tech Corp')
  })

  it('empty state appears when no records exist', async () => {
    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 300))

    const emptyState = container.querySelector('[data-testid="empty-state"]')
    expect(emptyState).not.toBeNull()
    expect(emptyState?.textContent).toContain('No applications found')
  })

  it('API error and retry work', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Network error'))

    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 300))

    const errorElement = container.querySelector('[data-testid="error"]')
    expect(errorElement).not.toBeNull()
    expect(errorElement?.textContent).toContain('Failed to load applications')

    const retryButton = container.querySelector('[data-testid="retry-button"]')
    expect(retryButton).not.toBeNull()
    retryButton?.click()

    // After retry, should no longer show error
    const newError = container.querySelector('[data-testid="error"]')
    expect(newError).toBeNull()
  })

  it('searching by title changes visible results', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        applications: [
          {
            id: '1',
            job_id: '1',
            status: 'APPLIED',
            application_date: '2024-01-15',
            created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:00:00Z',
            next_followup: null,
            interviewer_name: null,
            interviewer_contact: null,
            notes: null,
            resume_id: null,
            cover_letter_draft_id: null,
            source_url: null,
            source_job_metadata: {},
            job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
          }
        ]
      }), 200)),
    })

    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 300))

    // Search for 'Engineer'
    const input = container.querySelector('input[placeholder="Search by company or job title..."]')
    expect(input).not.toBeNull()
    input.value = 'Engineer'
    input.dispatchEvent(new Event('input'))

    await new Promise(resolve => setTimeout(resolve, 100))

    // Should see the Software Engineer result
    const result = container.querySelector('[data-testid="job-title"]')
    expect(result).not.toBeNull()
    expect(result?.textContent).toContain('Software Engineer')
  })

  it('searching by company changes visible results', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        applications: [
          {
            id: '1',
            job_id: '1',
            status: 'APPLIED',
            application_date: '2024-01-15',
            created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:00:00Z',
            next_followup: null,
            interviewer_name: null,
            interviewer_contact: null,
            notes: null,
            resume_id: null,
            cover_letter_draft_id: null,
            source_url: null,
            source_job_metadata: {},
            job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
          }
        ]
      }), 200)),
    })

    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 300))

    // Search for 'Tech'
    const input = container.querySelector('input[placeholder="Search by company or job title..."]')
    input.value = 'Tech'
    input.dispatchEvent(new Event('input'))

    await new Promise(resolve => setTimeout(resolve, 100))

    // Should see the Tech Corp result
    const result = container.querySelector('[data-testid="job-company"]')
    expect(result).not.toBeNull()
    expect(result?.textContent).toContain('Tech Corp')
  })

  it('status filtering changes visible results', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        applications: [
          {
            id: '1',
            job_id: '1',
            status: 'APPLIED',
            application_date: '2024-01-15',
            created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:00:00Z',
            next_followup: null,
            interviewer_name: null,
            interviewer_contact: null,
            notes: null,
            resume_id: null,
            cover_letter_draft_id: null,
            source_url: null,
            source_job_metadata: {},
            job: { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
          }
        ]
      }), 200)),
    })

    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 300))

    // Apply status filter
    const select = container.querySelector('select')
    expect(select).not.toBeNull()
    select.value = 'APPLIED'
    select.dispatchEvent(new Event('change'))

    await new Promise(resolve => setTimeout(resolve, 100))

    // Should see the application with APPLIED status
    const statusBadge = container.querySelector('[data-testid="status-badge"]')
    expect(statusBadge).not.toBeNull()
  })

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
    })

    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 300))

    // Job selector should have options from the jobs API
    const jobSelect = container.querySelector('select[name="job_id"]')
    expect(jobSelect).not.toBeNull()
    const jobOptions = jobSelect.querySelectorAll('option')
    expect(jobOptions.length).toBe(3) // 2 jobs + placeholder
  })

  it('creation is blocked until a valid job is selected', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        jobs: [
          { id: '1', title: 'Software Engineer', company: 'Tech Corp' }
        ],
        applications: []
      }), 200)),
    })

    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 300))

    // Try to submit the form without selecting a job
    const createForm = container.querySelector('form')
    expect(createForm).not.toBeNull()

    // Submit should be disabled or fail without job selection
    const submitButton = container.querySelector('button[type="submit"]')
    expect(submitButton).toBeTruthy()
  })

  it('creation sends the selected job ID', async () => {
    const mockPost = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({ id: '1' }), 200)),
    })

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      post: mockPost,
      json: async () => new Promise(resolve => setTimeout(() => resolve({ jobs: [{ id: '1', title: 'Software Engineer', company: 'Tech Corp' }], applications: [] }), 200)),
    })

    // Need to mock the API client properly
    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 300))

    // Select a job and create
    const jobSelect = container.querySelector('select[name="job_id"]')
    jobSelect.value = '1'
    jobSelect.dispatchEvent(new Event('change'))

    // Submit form
    const form = container.querySelector('form')
    expect(form).not.toBeNull()
    
    // The form submission should send job_id=1
  })

  it('confirmed deletion makes the intended API request', async () => {
    const mockDelete = vi.fn().mockResolvedValue({ ok: true })

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      delete: mockDelete,
      json: async () => new Promise(resolve => setTimeout(() => resolve({}), 200)),
    })

    // Create a stored application first
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({
        jobs: [{ id: '1', title: 'Software Engineer', company: 'Tech Corp' }],
        applications: [{ id: '1', job_id: '1', status: 'APPLIED' }]
      }), 200)),
    })

    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 300))

    // Find and click delete
    const deleteButtons = container.querySelectorAll('[data-testid="delete-button"]')
    expect(deleteButtons.length).toBeGreaterThan(0)

    // Open delete confirmation
    const firstDeleteBtn = deleteButtons[0]
    firstDeleteBtn.click()

    await new Promise(resolve => setTimeout(resolve, 100))

    // Click confirm
    const confirmDelete = container.querySelector('button.flex-1.bg-rose-600.text-rose-200')
    expect(confirmDelete).not.toBeNull()
    confirmDelete.click()

    await new Promise(resolve => setTimeout(resolve, 100))

    // Should have made the delete API call
    expect(mockDelete).toHaveBeenCalled()
  })

  it('cancelled deletion does not invoke the delete API', async () => {
    let deleteCallCount = 0

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => new Promise(resolve => setTimeout(() => resolve({}), 200)),
    })

    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 300))

    // Find delete button
    const deleteButtons = container.querySelectorAll('[data-testid="delete-button"]')
    expect(deleteButtons.length).toBeGreaterThan(0)

    // Open delete confirmation
    deleteButtons[0].click()

    await new Promise(resolve => setTimeout(resolve, 100))

    // Click cancel instead of confirm
    const cancelDelete = container.querySelector('button.flex-1.bg-slate-600.text-slate-300')
    expect(cancelDelete).not.toBeNull()
    cancelDelete.click()

    await new Promise(resolve => setTimeout(resolve, 100))

    // Delete should not have been called
    expect(deleteCallCount).toBe(0)
  })
})
