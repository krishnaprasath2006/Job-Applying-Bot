"""Tests for tailored resume generation from candidate profile and job data."""

from __future__ import annotations

import pytest
from pathlib import Path

from core.enums import FactStatus
from core.evidence import FactValue
from candidate_profile.models import build_empty_profile, with_fact_update
from resumes.models import Resume
from resumes.generation import _candidate_facts, _build_draft_from_data, generate_resume_draft


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
    assert 'education.highest_level' in facts


def test_draft_generation_from_data():
    """Verify that a draft can be generated from available data without AI."""
    profile = build_empty_profile()
    profile = with_fact_update(profile, 'identity.full_name', 'John Doe', 
                              status=FactStatus.VERIFIED, source='USER_INPUT')
    profile = with_fact_update(profile, 'experience.total_years_experience', '5', 
                              status=FactStatus.VERIFIED, source='USER_INPUT')
    
    facts = _candidate_facts(profile)
    
    resume = Resume(
        candidate_id='test',
        filename='test_resume.pdf',
        file_type='pdf',
        file_hash='hash123',
        file_size_bytes=1000,
        char_count=100,
        content_hash='content123',
        raw_text="EXPERIENCE\n5 years as Software Engineer at Tech Corp\nSKILLS\nPython, Java, SQL",
        status='PARSED',
        parser_name='test',
        parser_version='1',
        is_synthetic=False,
        page_count=1,
    )
    
    draft = _build_draft_from_data(
        profile, resume, facts, 
        "Software Engineer", 
        "We are looking for a software engineer with 5+ years experience",
        "5+ years experience, Python, Java"
    )
    
    assert draft is not None
    assert len(draft) > 0
    # Verify it contains the job title
    assert "Software Engineer" in draft
    # Verify it contains the candidate name
    assert "John Doe" in draft


def test_draft_contains_verified_facts():
    """Verify that the draft contains verified candidate facts."""
    profile = build_empty_profile()
    profile = with_fact_update(profile, 'identity.full_name', 'Jane Smith', 
                              status=FactStatus.VERIFIED, source='USER_INPUT')
    profile = with_fact_update(profile, 'experience.total_years_experience', '8', 
                              status=FactStatus.VERIFIED, source='USER_INPUT')
    
    facts = _candidate_facts(profile)
    
    resume = Resume(
        candidate_id='test',
        filename='test_resume.pdf',
        file_type='pdf',
        file_hash='hash123',
        file_size_bytes=1000,
        char_count=100,
        content_hash='content123',
        raw_text="EXPERIENCE\n8 years as Senior Developer\nSKILLS\nPython, React",
        status='PARSED',
        parser_name='test',
        parser_version='1',
        is_synthetic=False,
        page_count=1,
    )
    
    draft = _build_draft_from_data(
        profile, resume, facts, 
        "Senior Developer", 
        "We are looking for a senior developer with 8+ years experience",
        "8+ years experience, Python, React"
    )
    
    assert draft is not None
    assert "Jane Smith" in draft
    assert "8 years" in draft
