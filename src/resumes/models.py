"""Resume domain model.

A :class:`Resume` is an immutable record of one ingested file. The original
bytes are never modified: the parsed text is stored alongside them, and the
file itself is copied into a managed directory read-only in spirit.

Multi-resume support is structural from the start: every resume has a
``candidate_id`` and an optional ``variant`` such as ``AI Engineer``, and the
schema supports any number of them. Choosing which resume suits which job is a
later phase and is deliberately absent here.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.enums import ResumeFileType, ResumeStatus, SectionType
from core.hashing import utc_now
from core.model_run import PROMPT_VERSION

__all__ = ["ResumeSection", "Resume", "PARSER_NAME", "PARSER_VERSION"]

PARSER_NAME = "deterministic_section_parser"
PARSER_VERSION = "phase2-v1"

#: A role_focus slug: lowercase letters, digits, single hyphens.
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: Section headings recognised without AI. This is a deterministic keyword
#: table, not a guess: a heading that matches nothing simply produces no
#: section, which is reported rather than filled in.
_SECTION_KEYWORDS: dict[SectionType, tuple[str, ...]] = {
    SectionType.SUMMARY: ("summary", "profile", "objective", "about", "personal"),
    SectionType.EDUCATION: ("education", "academic", "qualification", "degree"),
    SectionType.EXPERIENCE: (
        "experience",
        "employment",
        "work history",
        "professional",
        "internship",
        "career",
    ),
    SectionType.SKILLS: ("skill", "technical", "competenc", "technolog", "tool"),
    SectionType.PROJECTS: ("project", "portfolio"),
    SectionType.CERTIFICATIONS: ("certif", "licen", "credential", "course"),
    SectionType.ACHIEVEMENTS: ("achievement", "award", "honor", "publication", "accomplish"),
    SectionType.LINKS: ("link", "reference", "github", "website"),    SectionType.CONTACT: ("contact",),
}


class ResumeSection(BaseModel):
    """One structured section extracted from a resume.

    Attributes:
        section_type: Which kind of section.
        position: Order within the resume, used to preserve document order.
        heading: The original heading text, so a human can see what the parser
            keyed on.
        raw_text: Unmodified text of the section.
        items: Split entries, e.g. one dict per job or degree.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str = ""
    resume_id: str = ""
    section_type: SectionType
    position: int = 0
    heading: Optional[str] = None
    raw_text: str = ""
    items: list[dict[str, Any]] = Field(default_factory=list)
    char_count: int = Field(default=0, validate_default=True)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("char_count", mode="before")
    @classmethod
    def _count_chars(cls, value: Any, info: Any) -> int:
        if value:
            return int(value)
        return len((info.data or {}).get("raw_text", ""))

    @model_validator(mode="after")
    def _count_chars_after(self) -> "ResumeSection":
        """Derive ``char_count`` from ``raw_text`` once both are validated.

        ``raw_text`` is declared after ``char_count``, so a field validator on
        ``char_count`` cannot see it. ``validate_default`` plus this final pass
        guarantees the count is never silently left at zero.
        """
        if not self.char_count:
            object.__setattr__(self, "char_count", len(self.raw_text))
        return self

    def is_empty(self) -> bool:
        return not self.raw_text.strip() and not self.items


class Resume(BaseModel):
    """One ingested resume.

    Attributes:
        candidate_id: Whose resume this is.
        document_id: Link to the stored document row.
        variant: Optional intended use, e.g. ``AI Engineer``. Selection is a
            later phase; Phase 2 only stores and indexes it.
        role_focus: What this variant is aimed at. Metadata that travels with
            the resume so a later selection phase can reason about fit.
        version: Human-meaningful revision label, e.g. ``v2``. Never used to
            order anything automatically; ordering uses ``created_at``.
        skills: Skills this variant emphasises. Metadata only; the resume
            parser never invents an entry here.
        filename: Original filename, kept as metadata only.
        file_type: Detected container type.
        file_hash: SHA-256 of the file bytes, the content identity.
        content_hash: SHA-256 of normalised extracted text, used to spot the
            same resume in a different format.
        raw_text: Preserved extracted text.
        storage_path: Where the untouched original lives.
        raw_text_path: Where the extracted text lives.
        status: Lifecycle state.
        is_synthetic: True for test fixtures. Synthetic data is tagged in the
            database so it can never be mistaken for a real resume.
        id: Derived last, from ``file_hash``. Field order matters: it is
            declared after ``file_hash`` so Pydantic has already validated it
            by the time the id is derived.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    candidate_id: str = "primary"
    document_id: Optional[str] = None
    variant: Optional[str] = None
    role_focus: Optional[str] = None
    version: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    filename: str
    file_type: ResumeFileType = ResumeFileType.UNKNOWN
    file_hash: str
    file_size_bytes: Optional[int] = None
    page_count: Optional[int] = None
    char_count: int = 0
    content_hash: Optional[str] = None

    storage_path: Optional[str] = None
    raw_text_path: Optional[str] = None
    raw_text: str = ""

    status: ResumeStatus = ResumeStatus.STORED
    parser_name: Optional[str] = None
    parser_version: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_synthetic: bool = False

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    sections: list[ResumeSection] = Field(default_factory=list)

    # Declared after file_hash so Pydantic has validated it first.
    # validate_default is required: Pydantic skips validators for values that
    # were never supplied, so without it the derivation never runs and every
    # resume would be stored with an empty id.
    id: str = Field(default="", validate_default=True)

    @field_validator("id", mode="before")
    @classmethod
    def _derive_id(cls, value: Any, info: Any) -> str:
        if value:
            return str(value)
        file_hash = (info.data or {}).get("file_hash")
        if not file_hash:
            return ""
        return f"resume-{file_hash[:16]}"

    @field_validator("role_focus")
    @classmethod
    def _validate_role_focus(cls, value: Optional[str]) -> Optional[str]:
        """Require a slug so ``role_focus`` is comparable across variants.

        The value is metadata used to pick a resume variant in a later phase, so
        it has to be one predictable token. Free text such as "Machine Learning
        Engineer" would make two spellings of the same role look different.
        """
        if value is None:
            return None
        text = value.strip().lower()
        if not text:
            return None
        if not _SLUG_RE.match(text):
            raise ValueError(
                "role_focus must be a lowercase slug such as 'ml-engineer', "
                f"got {value!r}"
            )
        return text

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: Optional[str]) -> Optional[str]:
        """Require a short label, not a number or a free-text note."""
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        if len(text) > 20:
            raise ValueError(f"version label must be 20 characters or fewer, got {value!r}")
        return text

    @model_validator(mode="before")
    @classmethod
    def _normalise_skills(cls, data: Any) -> Any:
        """Trim and drop empty skills, preserving the candidate's ordering.

        Duplicates are left in place rather than silently merged: the profile
        validator reports duplicate skills as a finding, and silently
        de-duplicating here would hide that from the user.
        """
        if not isinstance(data, dict):
            return data
        skills = data.get("skills")
        if not isinstance(skills, list):
            return data
        cleaned = [s.strip() for s in skills if isinstance(s, str) and s.strip()]
        return {**data, "skills": cleaned}

    @model_validator(mode="after")
    def _derive_dependent_fields(self) -> "Resume":
        """Fill values that depend on fields declared later in the class.

        ``char_count`` and the section id stamps both need data that Pydantic
        has not yet validated when a ``field_validator`` runs, because the
        fields they read (``raw_text``, ``id``) come later in declaration
        order. Running once at the end removes that ordering dependency
        entirely, so these values can no longer silently stay empty.
        """
        if not self.char_count:
            object.__setattr__(self, "char_count", len(self.raw_text))
        for index, section in enumerate(self.sections):
            if not section.id:
                section.id = f"{self.id or 'resume'}-sec-{index}"
            if not section.resume_id:
                section.resume_id = self.id
        return self

    def section(self, section_type: SectionType) -> Optional[ResumeSection]:
        for item in self.sections:
            if item.section_type is section_type:
                return item
        return None

    def sections_of(self, section_type: SectionType) -> list[ResumeSection]:
        return [s for s in self.sections if s.section_type is section_type]

    def all_text(self) -> str:
        """Return the preserved text, preferring ``raw_text``."""
        return self.raw_text or "\n".join(s.raw_text for s in self.sections)

    def has_content(self) -> bool:
        """Whether this resume yielded usable text."""
        return bool(self.all_text().strip())

    def variants(self) -> list[str]:
        return [s for s in (self.variant,) if s]

    def is_application_ready(self) -> bool:
        """Whether this resume has the minimum needed for later form filling.

        Phase 2 only reports this. It is not a gate: selection of which resume
        suits which job is a later phase, and an empty variant list is a valid
        starting point rather than an error.
        """
        return bool(self.has_content())

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, raw: str) -> "Resume":
        try:
            return cls.model_validate(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ValueError(f"resume JSON is invalid: {exc}") from exc
