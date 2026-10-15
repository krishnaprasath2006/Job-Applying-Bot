/// <reference types="vitest" />
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ApplicationTrackerPage } from '../ApplicationTrackerPage'

describe('ApplicationTrackerPage', () => {
  beforeEach(() => {
    // Mock the API module
    vi.mock('../lib/api/index', () => ({
      API: {
        jobs: {
          list: vi.fn(),
        },
        api: {
          get: vi.fn().mockResolvedValue({ applications: [] }),
          post: vi.fn(),
          patch: vi.fn(),
          delete: vi.fn(),
        },
      },
    }))
  })

  it('renders without crashing', () => {
    const { container } = render(<ApplicationTrackerPage />)
    expect(container.querySelector('div')).toBeTruthy()
  })

  it('renders application list unavailable notice', () => {
    const { container } = render(<ApplicationTrackerPage />)
    expect(container.textContent).toContain('Application list not available via API in this release')
  })

  it('shows loading applications text', () => {
    const { container } = render(<ApplicationTrackerPage />)
    expect(container.textContent).toContain('Loading applications...')
  })
})