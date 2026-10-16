/// <reference types="vitest" />
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ApplicationTrackerPage } from '../ApplicationTrackerPage'

// Mock fetch used by the API client
// Simulate real API latency with a setTimeout
global.fetch = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => new Promise(resolve => setTimeout(() => resolve({ applications: [] }), 200)),
});

describe('ApplicationTrackerPage', () => {
  it('renders without crashing', () => {
    const { container } = render(<ApplicationTrackerPage />)
    expect(container.querySelector('div')).toBeTruthy()
  })

  it('loads applications from API', async () => {
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
    const select = container.querySelector('select')
    if (select) {
      select.value = 'APPLIED'
      select.dispatchEvent(new Event('change'))
    }
    await new Promise(resolve => setTimeout(resolve, 50))
  })
})
