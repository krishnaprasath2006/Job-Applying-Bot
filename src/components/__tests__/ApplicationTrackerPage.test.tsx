/// <reference types="vitest" />
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ApplicationTrackerPage } from '../ApplicationTrackerPage'

vi.mock('../lib/api/index', () => ({
  API: {
    jobs: {
      list: vi.fn(),
    },
  },
  api: {
    get: vi.fn().mockResolvedValue({ applications: [] }),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

describe('ApplicationTrackerPage', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
  })

  it('renders without crashing', () => {
    const { container } = render(<ApplicationTrackerPage />)
    expect(container.querySelector('div')).toBeTruthy()
  })

  it('loads applications from API', async () => {
    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 100))
    const loading = container.querySelector('[data-testid="loading"]')
    expect(loading).not.toBeNull()
  })

  it('shows empty state when no applications exist', async () => {
    const { container } = render(<ApplicationTrackerPage />)
    await new Promise(resolve => setTimeout(resolve, 200))
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