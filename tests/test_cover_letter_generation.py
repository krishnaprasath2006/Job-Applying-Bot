"""Tests for cover-letter generation from candidate profile and job data."""

from __future__ import annotations

import pytest
from pathlib import Path

from core.enums import FactStatus
from core.evidence import FactValue
from candidate_profile.models import build_empty_profile, with_fact_update
from resumes.cover_letter import _candidate_facts, _build_cover_letter_from_data


def test_facts_extraction():
    """Verify that verified facts are correctly extracted from profile."""
    profile = build_empty_profile()
    profile = with_fact_update(profile, 'identity.full_name', 'John Doe', 
                              status=FactStatus.VERIFIED, source='USER_INPUT')
    profile = with_fact_update(profile, 'experience.total_years_experience', '5', 
                              status=FactStatus.VERIFIED, source='USER_INPUT')
    profile = with_fact_update(profile, 'education.highest_level', "Bachelor's Degree", 
                              status=FactStatus.VERIFIED, source='USER_INPUT')
    
    facts = _candidate_facts(profile)
    assert 'identity.full_name' in facts
    assert facts['identity.full_name'] == 'John Doe'
    assert facts['experience.total_years_experience'] == '5'


def test_cover_letter_generation_from_data():
    """Verify that a cover letter can be generated from available data without AI."""
    profile = build_empty_profile()
    profile = with_fact_update(profile, 'identity.full_name', 'John Doe', 
                              status=FactStatus.VERIFIED, source='USER_INPUT')
    profile = with_fact_update(profile, 'experience.total_years_experience', '5', 
                              status=FactStatus.VERIFIED, source='USER_INPUT')
    
    facts = _candidate_facts(profile)
    
    resume_text = "EXPERIENCE\n5 years as Software Engineer at Tech Corp\nSKILLS\nPython, Java, SQL"
    
    letter = _build_cover_letter_from_data(
        profile, resume_text, 
        "Software Engineer", 
        "Tech Corp", 
        "We are looking for a software engineer",
        "5+ years experience, Python"
    )
    
    assert letter is not None
    assert len(letter) > 0
    # Verify it contains the candidate name
    assert "John Doe" in letter
    # Verify it contains the company name
    assert "Tech Corp" in letter
    # Verify it contains the job title
    assert "Software Engineer" in letter
