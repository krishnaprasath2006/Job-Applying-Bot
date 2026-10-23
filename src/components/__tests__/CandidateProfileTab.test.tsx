/// <reference types="vitest" />
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CandidateProfileTab } from '../CandidateProfileTab'

describe('CandidateProfileTab', () => {
  const mockProfile: any = {
    candidate_id: 'primary',
    identity: {
      full_name: 'Test Candidate',
      preferred_name: 'Test',
      pronouns: 'they/them',
      date_of_birth: '',
      nationality: '',
    },
    contact: {
      email: 'test@example.com',
      phone: '',
      linkedin_url: '',
      website: '',
    },
    location: {
      current_city: '',
      current_state: '',
      current_country: '',
      postal_code: '',
      willing_to_relocate: '',
      preferred_locations: '',
      timezone: '',
    },
    education: {
      entries: [],
      highest_level: '',
    },
    experience: {
      entries: [],
      total_years_experience: '',
      years_of_experience_verified: '',
    },
    skills: {
      proficient: '',
      expert: '',
      familiar: '',
      languages: '',
      tools: '',
    },
    projects: { entries: [] },
    certifications: { entries: [] },
    links: { entries: [] },
    preferences: {
      desired_roles: '',
      desired_locations: '',
      remote_preference: '',
      minimum_salary: '',
      maximum_salary: '',
      willing_to_relocate: '',
      notice_period: '',
      willing_to_travel: '',
    },
    authorization: {
      requires_sponsorship: '',
      authorized_countries: '',
      visa_status: '',
      sponsorship_available: '',
      security_clearance: '',
    },
    availability: {
      available_from: '',
      notice_period_days: '',
      hours_per_week: '',
      open_to_contract: '',
      open_to_part_time: '',
    },
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  }

// @ts-expect-error
  beforeEach(() => {
    // Mock the API module
    vi.mock('../lib/api/index', () => ({
      API: {
        profile: {
          read: vi.fn().mockResolvedValue({
            candidate_id: 'primary',
            exists: true,
            profile: mockProfile,
          }),
          update_fact: vi.fn().mockResolvedValue({
            candidate_id: 'primary',
            exists: true,
            profile: mockProfile,
          }),
        },
      },
    }))
  })

  it('renders without crashing', () => {
    const { container } = render(<CandidateProfileTab profile={mockProfile} onUpdateProfile={vi.fn()} onValidateProfile={vi.fn()} />)
    expect(container.querySelector('div')).toBeTruthy()
  })

  it('renders the Identity & Contact Information heading', () => {
    const { container } = render(<CandidateProfileTab profile={mockProfile} onUpdateProfile={vi.fn()} onValidateProfile={vi.fn()} />)
    expect(container.textContent).toContain('Identity & Contact Information')
  })

  it('renders the Skills section heading', () => {
    const { container } = render(<CandidateProfileTab profile={mockProfile} onUpdateProfile={vi.fn()} onValidateProfile={vi.fn()} />)
    expect(container.textContent).toContain('Skills')
  })
})