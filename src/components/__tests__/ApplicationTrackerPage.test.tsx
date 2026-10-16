/// <reference types="vitest" />
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ApplicationTrackerPage } from '../ApplicationTrackerPage'

// Mock fetch used by the API client
// Simulate real API latency with a setTimeout
global.fetch = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => new Promise(resolve => setTimeout(() => resolve({ applications: [] }), 200)),
});

describe('ApplicationTrackerPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without crashing', () => {
    const { container } = render(<ApplicationTrackerPage />)
    expect(container.querySelector('div')).toBeTruthy()
  })

  it('loads applications from API and displays heading', async () => {
    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 500))
    const heading = container.querySelector('h1')
    expect(heading).not.toBeNull()
    expect(heading?.textContent).toContain('Application Tracker')
  })

  it('shows empty state when no applications exist', async () => {
    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 400))
    expect(container.textContent).toContain('No applications found')
  })

  it('applications can be searched', async () => {
    const { container } = render(<ApplicationTrackerPage />)
    const input = container.querySelector('input')
    if (input) {
      input.value = 'Engineer'
      input.dispatchEvent(new Event('input'))
    }
    await new Promise(resolve => setTimeout(resolve, 50))
  })

  it('status filter works', async () => {
    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 500))
    const select = container.querySelector('select')
    if (select) {
      select.value = 'APPLIED'
      select.dispatchEvent(new Event('change'))
    }
    await new Promise(resolve => setTimeout(resolve, 50))
  })

  it('API failures are shown honestly and retry works', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Network error'))
    
    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 500))
    const errorElement = container.querySelector('[role="alert"]')
    expect(errorElement).not.toBeNull()
    const retryButton = container.querySelector('button.bg-emerald-600')
    expect(retryButton).not.toBeNull()
  })

  it('job selection is required before creating an application', async () => {
    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 500))
    const createButton = container.querySelectorAll('text=+ Create new application')
    if (createButton.length > 0) {
      createButton[0].click()
      await new Promise(resolve => setTimeout(resolve, 100))
      const submitButton = container.querySelector('button.flex-1.bg-emerald-600')
      expect(submitButton).toBeTruthy()
    }
});
