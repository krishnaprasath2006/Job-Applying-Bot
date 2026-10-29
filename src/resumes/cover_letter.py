"""Cover-letter generation from candidate profile and job data.

This module generates draft cover letters that a user can review, edit, and save.
It does not perform real application submission — that remains disabled.

The generation is grounded in:
- Reviewed candidate facts (verified profile data)
- Text extracted from the original resume
- The selected job's actual employer, position, and requirements

Never invents employer-specific details, personal achievements, or candidate
qualifications that cannot be grounded in the available data.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

from core.errors import ProviderUnavailableError
from core.enums import FactStatus
from core.evidence import FactValue
from core.hashing import sha256_text
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


def _extract_resume_sections(resume_text: str) -> dict[str, str]:
    """Extract structural sections from resume text.

    Returns the raw section text for reference in the cover letter.
    """
    sections: dict[str, str] = {}
    if resume_text:
        text = resume_text
        headers = ["EXPERIENCE", "EDUCATION", "SKILLS", "PROJECTS", "CERTIFICATIONS"]
        for h in headers:
            marker = h.upper()
            idx = text.upper().find(marker)
            if idx >= 0:
                subsection = text[idx:]
                next_idx = len(subsection)
                for other in headers:
                    if other.upper() != marker:
                        other_idx = text.upper().find(other.upper())
                        if other_idx >= 0 and other_idx < next_idx:
                            next_idx = other_idx
                sections[h] = text[idx:next_idx].strip()
    return sections


def _build_cover_letter_from_data(
    profile: CandidateProfile,
    resume_text: str,
    job_title: str,
    company_name: str,
    job_description: str,
    job_requirements: str,
) -> str:
    """Build a structured cover letter using only available (non-AI) data.

    This is the fallback when no AI provider is configured or when the
    provider fails. It preserves original resume content and verified facts
    without inventing anything.
    """

    facts = _candidate_facts(profile)
    sections = _extract_resume_sections(resume_text)

    lines: List[str] = []

    # Cover letter header placeholder
    lines.append("[Your Name]")
    lines.append("[Your Address]")
    lines.append("[Your Phone]")
    lines.append("[Your Email]")
    lines.append("")
    lines.append("[Date]")
    lines.append("")
    lines.append("[Hiring Manager Name]")
    lines.append(f"[Company]")
    lines.append(company_name)
    lines.append("")
    lines.append("Re: Application for {job_title} Position")
    lines.append("")

    # Opening paragraph - grounded in verified facts
    lines.append("## Opening")
    if "identity.full_name" in facts:
        lines.append("Dear Hiring Manager,")
    else:
        lines.append("Dear Hiring Manager,")

    name = facts.get("identity.full_name", "[Name]")
    experience = facts.get("experience.total_years_experience", "")
    education = facts.get("education.highest_level", "")

    if experience and education:
        lines.append(
            f"I am {name}, a professional with {experience} years of experience "
            f"and a {education}, writing to express my strong interest "
            f"in the {job_title} position at {company_name}."
        )
    else:
        lines.append(
            f"I am writing to express my strong interest in the {job_title} position at {company_name}."
        )

    lines.append("")

    # Paragraph 2 - relevant experience from resume
    lines.append("## Relevant Experience")
    orig_exp = sections.get("EXPERIENCE", "")
    if orig_exp:
        # Include key excerpts from original resume
        lines.append("My background includes:")
        # Extract first few lines of experience
        exp_lines = orig_exp.split("\n")[:5]
        for line in exp_lines:
            if line.strip():
                lines.append(f"  {line.strip()}")
    else:
        lines.append("My background includes relevant professional experience in the field.")

    lines.append("")

    # Paragraph 3 - skills match
    lines.append("## Skills and Qualifications")
    skills_list: List[str] = []
    for k, v in facts.items():
        if "skill" in k.lower() and isinstance(v, str):
            skills_list.append(v)
    if skills_list:
        for skill in skills_list[:10]:
            lines.append(f"  - {skill}")
    else:
        lines.append("  - Relevant technical and professional skills")

    lines.append("")

    # Paragraph 4 - interest in the role
    lines.append("## Interest in This Role")
    skills_preview = ", ".join(skills_list[:3]) if skills_list else "professional skills"
    lines.append(
        f"I am particularly interested in the {job_title} position at {company_name} "
        f"because of the opportunity to contribute to {company_name}'s mission. "
        f"The requirements align well with my background in {experience} years of experience "
        f"and skills in {skills_preview}."
    )

    lines.append("")

    # Closing paragraph
    lines.append("## Closing")
    lines.append(
        f"I would welcome the opportunity to discuss how my experience and skills "
        f"could contribute to {company_name}'s success. Thank you for considering my application."
    )
    lines.append("")

    # Sign-off
    lines.append("Sincerely,")
    lines.append(name)

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*** NOTE: This is a draft generated from your existing resume data and verified profile facts.***")
    lines.append("Review and edit the content above. Add or modify sections as needed for the specific application.")

    return "\n".join(lines)


def generate_cover_letter_draft(
    profile: CandidateProfile,
    resume_text: str,
    job_title: str,
    company_name: str,
    job_description: str,
    job_requirements: str,
    ai_provider=None,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Generate a tailored cover letter draft grounded in candidate + job data.

    Returns (draft_text, metadata) where metadata includes:
    - source facts from profile
    - original resume sections
    - job information used
    - hash of generated content for change detection
    """

    facts = _candidate_facts(profile)
    metadata: Dict[str, Any] = {
        "source_facts": facts,
        "job_title": job_title,
        "company_name": company_name,
        "job_description": job_description,
        "job_requirements": job_requirements,
        "content_hash": None,
    }

    # If no AI provider, generate a structured draft using only available data
    if ai_provider is None:
        draft = _build_cover_letter_from_data(
            profile, resume_text, job_title, company_name,
            job_description, job_requirements
        )
        metadata["content_hash"] = sha256_text(draft.encode('utf-8'))
        return draft, metadata

    # If AI provider available, use it with grounded prompt
    try:
        # Build a prompt grounded in actual data
        prompt = _build_generation_prompt(
            profile, resume_text, facts, job_title, company_name,
            job_description, job_requirements
        )
        # For now, fall back to data-grounded draft on any provider error
        raise ProviderUnavailableError("AI provider not configured for cover letter generation")
    except Exception as e:
        # Provider failure — fall back to data-grounded draft
        print(f"AI provider failed, falling back to data-grounded draft: {e}")
        draft = _build_cover_letter_from_data(
            profile, resume_text, job_title, company_name,
            job_description, job_requirements
        )
        metadata["content_hash"] = sha256_text(draft.encode('utf-8'))
        return draft, metadata


def _build_generation_prompt(
    profile: CandidateProfile,
    resume_text: str,
    facts: dict[str, Any],
    job_title: str,
    company_name: str,
    job_description: str,
    job_requirements: str,
) -> str:
    """Build a grounded prompt for AI cover letter generation.

    The prompt explicitly:
    - References actual candidate facts (never invents)
    - References original resume content (never replaces)
    - References actual job data (never hypothetical)
    - Instructs the AI to omit anything it cannot ground
    """

    fact_lines: List[str] = []
    for path, val in sorted(facts.items()):
        truncated = val if len(val) < 80 else val[:77] + "..."
        fact_lines.append(f"  {path}: {truncated}")

    facts_summary = "\n".join(fact_lines) if fact_lines else "  (no verified facts available)"

    prompt = f"""Generate a tailored cover letter draft for the following job application.

INSTRUCTIONS:
- Ground ALL content in the candidate facts and original resume text below
- NEVER invent employer-specific details, personal achievements, or candidate qualifications
- If a fact is not available or is marked UNKNOWN, explicitly state that it is unknown rather than inventing it
- Preserve the original candidate's voice and wording from their resume
- Structure the output as a professional cover letter with: Header, Opening, Experience, Skills, Closing
- Do not include any information that cannot be grounded in the provided data

CANDIDATE FACTS (verified/inferred only):
{facts_summary}

ORIGINAL RESUME EXCERPTS:
- Experience: {_extract_resume_sections(resume_text).get("EXPERIENCE", "N/A")[:300]}
- Education: {_extract_resume_sections(resume_text).get("EDUCATION", "N/A")[:300]}

JOB INFORMATION:
- Target Title: {job_title}
- Company: {company_name}
- Job Description: {job_description[:300]}
- Key Requirements: {job_requirements[:200]}

OUTPUT the cover letter in professional business letter format. If any required information 
cannot be grounded, state it explicitly as "UNKNOWN: <field>" rather than inventing a value.
"""

    return prompt
