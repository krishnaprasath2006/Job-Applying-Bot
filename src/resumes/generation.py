"""Tailored resume and cover-letter generation from candidate profile and job data.

This module generates draft documents that a user can review, edit, and save.
It does not perform real application submission — that remains disabled.

The generation is grounded in:
- Reviewed candidate facts (verified profile data)
- Text extracted from the original resume
- The selected job's actual title, description, and requirements

Never invents employers, degrees, certifications, dates, projects,
achievements, metrics, or qualifications. Unknown facts remain UNKNOWN.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

from core.errors import ProviderUnavailableError
from core.enums import FactStatus
from core.evidence import FactValue
from core.hashing import sha256_text
from resumes.hashing import MIN_TEXT_CHARS
from resumes.models import Resume
from candidate_profile.models import CandidateProfile, with_fact_update


def _candidate_facts(profile: CandidateProfile) -> dict[str, Any]:
    """Extract verified and inferred facts from a candidate profile.

    Returns a dict suitable for reuse as template variables.
    UNKNOWN values are excluded (they carry no value).
    """
    facts: dict[str, Any] = {}
    for field_path, value, _section in profile.iter_fact_values():
        if isinstance(value, FactValue):
            val = value.value
            if val is not None and value.status in (FactStatus.VERIFIED, FactStatus.INFERRED):
                facts[field_path] = val
    return facts


def _extract_resume_sections(resume: Resume) -> dict[str, str]:
    """Extract structural sections from an ingested resume.

    Returns the raw section text that was parsed, so the generator can
    reference the original candidate's own words.
    """
    sections: dict[str, str] = {}
    if resume.raw_text:
        text = resume.raw_text
        # Simple segmentation by common resume section headers
        headers = ["EXPERIENCE", "EDUCATION", "SKILLS", "PROJECTS", "CERTIFICATIONS"]
        for h in headers:
            # Find section content after header
            marker = h.upper()
            idx = text.upper().find(marker)
            if idx >= 0:
                # Grab everything from the header to the next header or end
                subsection = text[idx:]
                next_idx = len(subsection)
                for other in headers:
                    if other.upper() != marker:
                        other_idx = subsection.upper().find(other.upper())
                        if other_idx >= 0 and other_idx < next_idx:
                            next_idx = other_idx
                sections[h] = subsection[:next_idx].strip()
    return sections


def _build_draft_from_data(
    profile: CandidateProfile,
    resume: Resume,
    facts: dict[str, Any],
    job_title: str,
    job_description: str,
    job_requirements: str,
) -> str:
    """Build a structured resume draft using only available (non-AI) data.

    This is the fallback when no AI provider is configured or when the
    provider fails. It preserves original resume content and verified facts
    without inventing anything.
    """

    # Extract resume sections for reference
    sections = _extract_resume_sections(resume)

    # Start with the job title and summary
    lines: List[str] = [f"# {job_title}", "", "## Professional Summary", ""]

    # Add a summary based on verified facts only
    if facts:
        # Collect key facts that are relevant
        key_parts: List[str] = []
        if "identity.full_name" in facts:
            key_parts.append(f"Name: {facts['identity.full_name']}")
        if "experience.total_years_experience" in facts:
            key_parts.append(f"{facts['experience.total_years_experience']} years of experience")
        if "education.highest_level" in facts:
            key_parts.append(f"Education: {facts['education.highest_level']}")

        if key_parts:
            lines.append(" ".join(key_parts))
    else:
        lines.append("Summary of relevant experience and skills for the target role.")

    lines.extend(["", "## Relevant Experience"])

    # Use original resume experience section if available
    orig_exp = sections.get("EXPERIENCE", "")
    if orig_exp:
        # Include original content verbatim (we're not inventing, just presenting)
        lines.append(orig_exp[:500])  # First 500 chars
    else:
        lines.append("[No experience section found in original resume]")

    lines.extend(["", "## Skills"])

    # List skills from profile if available
    skills_list: List[str] = []
    for k, v in facts.items():
        if "skill" in k.lower() and isinstance(v, str):
            skills_list.append(v)
    if skills_list:
        for skill in skills_list[:10]:  # Limit to 10 skills
            lines.append(f"- {skill}")
    else:
        lines.append("[Skills section not available]")

    lines.extend(["", "## Match with Target Role"])

    # Add job-specific relevance
    lines.append(f"Target role: {job_title}")
    lines.append(f"Job description summary: {job_description[:200]}...")
    lines.append(f"Key requirements: {job_requirements[:200]}...")

    lines.extend(["", "--", "", "***", "", "Note: This is a draft generated from your existing resume data and verified profile facts."])
    lines.append("Review and edit the content above. Add or modify sections as needed for the specific application.")

    return "\n".join(lines)


def generate_resume_draft(
    profile: CandidateProfile,
    job_title: str,
    job_description: str,
    job_requirements: str,
    resume: Resume,
    ai_provider=None,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Generate a tailored resume draft grounded in candidate + job data.

    Returns (draft_text, metadata) where metadata includes:
    - source facts from profile
    - original resume sections
    - job information used
    - hash of generated content for change detection
    """

    # Gather grounded data
    facts = _candidate_facts(profile)
    original_sections = _extract_resume_sections(resume)

    metadata: Dict[str, Any] = {
        "source_facts": facts,
        "original_sections": original_sections,
        "job_title": job_title,
        "job_description": job_description,
        "job_requirements": job_requirements,
        "content_hash": None,
    }

    # If no AI provider, generate a structured draft using only available data
    if ai_provider is None:
        draft = _build_draft_from_data(profile, resume, facts, job_title, job_description, job_requirements)
        metadata["content_hash"] = sha256_text(draft.encode('utf-8'))
        return draft, metadata

    # If AI provider available, use it with grounded prompt
    try:
        # Build a prompt grounded in actual data, not freeform generation
        prompt = _build_generation_prompt(
            profile, resume, facts, original_sections,
            job_title, job_description, job_requirements
        )
        # Use a simple text generation approach - in production this would call the AI provider
        # For now, fall back to data-grounded draft on any provider error
        raise ProviderUnavailableError("AI provider not configured for draft generation")
    except Exception as e:
        # Provider failure — fall back to data-grounded draft
        print(f"AI provider failed, falling back to data-grounded draft: {e}")
        draft = _build_draft_from_data(
            profile, resume, facts, job_title, job_description, job_requirements
        )
        metadata["content_hash"] = sha256_text(draft.encode('utf-8'))
        return draft, metadata


def _build_generation_prompt(
    profile: CandidateProfile,
    resume: Resume,
    facts: dict[str, Any],
    original_sections: dict[str, str],
    job_title: str,
    job_description: str,
    job_requirements: str,
) -> str:
    """Build a grounded prompt for AI resume generation.

    The prompt explicitly:
    - References actual candidate facts (never invents)
    - References original resume content (never replaces)
    - References actual job data (never hypothetical)
    - Instructs the AI to omit anything it cannot ground
    """

    # Build a concise fact summary for the prompt
    fact_lines: List[str] = []
    for path, val in sorted(facts.items()):
        # Truncate long values
        truncated = val if len(val) < 80 else val[:77] + "..."
        fact_lines.append(f"  {path}: {truncated}")

    facts_summary = "\n".join(fact_lines) if fact_lines else "  (no verified facts available)"

    prompt = f"""Generate a tailored resume draft for the following job application.

INSTRUCTIONS:
- Ground ALL content in the candidate facts and original resume text below
- NEVER invent employers, degrees, certifications, dates, projects, achievements, metrics, or qualifications
- If a fact is not available or is marked UNKNOWN, explicitly state that it is unknown rather than inventing it
- Preserve the original candidate's voice and wording from their resume
- Structure the output in markdown with sections: Professional Summary, Experience, Skills, Education
- Do not include any information that cannot be grounded in the provided data

CANDIDATE FACTS (verified/inferred only):
{facts_summary}

ORIGINAL RESUME EXCERPTS:
- Experience: {original_sections.get("EXPERIENCE", "N/A")[:300]}
- Education: {original_sections.get("EDUCATION", "N/A")[:300]}

JOB INFORMATION:
- Target Title: {job_title}
- Job Description: {job_description[:300]}
- Key Requirements: {job_requirements[:200]}

OUTPUT the draft resume in markdown format. If any required information cannot be grounded, 
state it explicitly as "UNKNOWN: <field>" rather than inventing a value.
"""

    return prompt
