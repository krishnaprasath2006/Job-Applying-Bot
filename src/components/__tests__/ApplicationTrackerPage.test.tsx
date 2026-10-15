/// <reference types="vitest" />
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ApplicationTrackerPage } from '../ApplicationTrackerPage'

describe('ApplicationTrackerPage', () => {
// @ts-expect-error
  beforeEach(() => {
    // Mock the API module
    vi.mock('../lib/api/index', () => ({
      API: {
        jobs: {
          list: vi.fn(),
        },
        applications: {
          list: vi.fn(),
        },
      },
    }))
  })

  it('renders informative message when application API is not available', () => {
    const { container } = render(<ApplicationTrackerPage />)
    // The informative message is in a div
    const message = container.querySelector('div')
    expect(message).toBeTruthy()
    expect(message!.textContent).toContain('Application list not available via API in this release')
  })

  it('shows loading applications text', () => {
    const { container } = render(<ApplicationTrackerPage />)
    expect(container.textContent).toContain('Loading applications...')
  })

  it('renders application list unavailable notice', () => {
    const { container } = render(<ApplicationTrackerPage />)
    expect(container.textContent).toContain('Application list not available via API in this release')
  })
})