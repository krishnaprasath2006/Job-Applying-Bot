"""Candidate profile domain model.

The profile is the assistant's memory of one real person. Every field is a
:class:`~core.evidence.FactValue`: a value, a truth status, and evidence.

Two invariants are enforced by the models themselves, so a caller cannot
violate them by accident:

1. ``UNKNOWN`` never carries a value. An unknown field is ``None``; putting a
   string there would make "I don't know" indistinguishable from "yes".
2. Nothing is ``VERIFIED`` without a source.

The template this module generates is intentionally empty. A profile full of
``UNKNOWN`` is correct and complete; a profile full of plausible guesses would
make the assistant confidently wrong about a real person.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.enums import FactStatus
from core.evidence import Evidence, Fact, FactValue
from core.hashing import short_hash, utc_now
from core.paths import Paths, get_paths

__all__ = [
    "ExperienceEntry",
    "EducationEntry",
    "ProjectEntry",
    "CertificationEntry",
    "IdentitySection",
    "ContactSection",
    "LocationSection",
    "EducationSection",
    "ExperienceSection",
    "SkillsSection",
    "ProjectsSection",
    "CertificationsSection",
    "LinksSection",
    "PreferencesSection",
    "AuthorizationSection",
    "AvailabilitySection",
    "CandidateProfile",
    "PROFILE_SCHEMA_VERSION",
    "build_empty_profile",
    "with_fact_update",
]

PROFILE_SCHEMA_VERSION = "phase2-v1"

TModel = TypeVar("TModel", bound=BaseModel)


class _Section(BaseModel):
    """Base for profile sections.

    Attributes:
        section_path: Dotted path prefix used when building fact ids.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    section_path: str = ""

    def fact_values(self) -> list[FactValue]:
        """Return every :class:`FactValue` in this section, in field order."""
        return [
            value
            for name, value in self
            if isinstance(value, FactValue)
        ]

    def with_update(self, path: str, value: Any, **kwargs: Any) -> Any:
        """Return a copy of this section or entry with one fact replaced.

        Same semantics as :func:`with_fact_update`, but relative to this
        object, so an entry can be built in one expression.
        """
        return with_fact_update(self, path, value, **kwargs)

    def _prefix(self) -> str:
        return self.section_path or type(self).__name__.lower()


class IdentitySection(_Section):
    """Legal name and identifiers.

    ``full_name`` is left ``UNKNOWN`` in the template. The assistant must never
    guess it, not even from a filename.
    """

    section_path: str = "identity"
    full_name: FactValue = Field(default_factory=lambda: FactValue(field_path="identity.full_name"))
    preferred_name: FactValue = Field(default_factory=lambda: FactValue(field_path="identity.preferred_name"))
    pronouns: FactValue = Field(default_factory=lambda: FactValue(field_path="identity.pronouns"))
    date_of_birth: FactValue = Field(default_factory=lambda: FactValue(field_path="identity.date_of_birth"))
    nationality: FactValue = Field(default_factory=lambda: FactValue(field_path="identity.nationality"))
    headline: FactValue = Field(default_factory=lambda: FactValue(field_path="identity.headline"))
    summary: FactValue = Field(default_factory=lambda: FactValue(field_path="identity.summary"))


class ContactSection(_Section):
    """How to reach the candidate. Never prefilled with anything real."""

    section_path: str = "contact"
    email: FactValue = Field(default_factory=lambda: FactValue(field_path="contact.email"))
    phone: FactValue = Field(default_factory=lambda: FactValue(field_path="contact.phone"))
    linkedin_url: FactValue = Field(default_factory=lambda: FactValue(field_path="contact.linkedin_url"))
    website: FactValue = Field(default_factory=lambda: FactValue(field_path="contact.website"))


class LocationSection(_Section):
    """Where the candidate is and where they can work."""

    section_path: str = "location"
    current_city: FactValue = Field(default_factory=lambda: FactValue(field_path="location.current_city"))
    current_state: FactValue = Field(default_factory=lambda: FactValue(field_path="location.current_state"))
    current_country: FactValue = Field(default_factory=lambda: FactValue(field_path="location.current_country"))
    postal_code: FactValue = Field(default_factory=lambda: FactValue(field_path="location.postal_code"))
    willing_to_relocate: FactValue = Field(default_factory=lambda: FactValue(field_path="location.willing_to_relocate"))
    preferred_locations: FactValue = Field(default_factory=lambda: FactValue(field_path="location.preferred_locations"))
    timezone: FactValue = Field(default_factory=lambda: FactValue(field_path="location.timezone"))


class EducationEntry(_Section):
    """One qualification. Dates are ``YYYY-MM-DD`` or ``YYYY``."""

    section_path: str = "education"
    institution: FactValue = Field(default_factory=lambda: FactValue(field_path="education.institution"))
    degree: FactValue = Field(default_factory=lambda: FactValue(field_path="education.degree"))
    field_of_study: FactValue = Field(default_factory=lambda: FactValue(field_path="education.field_of_study"))
    start_date: FactValue = Field(default_factory=lambda: FactValue(field_path="education.start_date"))
    end_date: FactValue = Field(default_factory=lambda: FactValue(field_path="education.end_date"))
    is_current: FactValue = Field(default_factory=lambda: FactValue(field_path="education.is_current"))
    grade: FactValue = Field(default_factory=lambda: FactValue(field_path="education.grade"))
    gpa: FactValue = Field(default_factory=lambda: FactValue(field_path="education.gpa"))
    location: FactValue = Field(default_factory=lambda: FactValue(field_path="education.location"))
    description: FactValue = Field(default_factory=lambda: FactValue(field_path="education.description"))


class EducationSection(_Section):
    """All qualifications. The template ships an empty list, not a placeholder."""

    section_path: str = "education"
    entries: list[EducationEntry] = Field(default_factory=list)
    highest_level: FactValue = Field(default_factory=lambda: FactValue(field_path="education.highest_level"))


class ExperienceEntry(_Section):
    """One role. ``employment_type`` distinguishes internship from full time."""

    section_path: str = "experience"
    employer: FactValue = Field(default_factory=lambda: FactValue(field_path="experience.employer"))
    title: FactValue = Field(default_factory=lambda: FactValue(field_path="experience.title"))
    employment_type: FactValue = Field(default_factory=lambda: FactValue(field_path="experience.employment_type"))
    location: FactValue = Field(default_factory=lambda: FactValue(field_path="experience.location"))
    start_date: FactValue = Field(default_factory=lambda: FactValue(field_path="experience.start_date"))
    end_date: FactValue = Field(default_factory=lambda: FactValue(field_path="experience.end_date"))
    is_current: FactValue = Field(default_factory=lambda: FactValue(field_path="experience.is_current"))
    description: FactValue = Field(default_factory=lambda: FactValue(field_path="experience.description"))
    responsibilities: FactValue = Field(default_factory=lambda: FactValue(field_path="experience.responsibilities"))
    achievements: FactValue = Field(default_factory=lambda: FactValue(field_path="experience.achievements"))
    technologies: FactValue = Field(default_factory=lambda: FactValue(field_path="experience.technologies"))

    def duration_months(self) -> Optional[int]:
        """Return the span in whole months, or ``None`` if dates are unknown.

        Returns ``None`` rather than guessing when either endpoint is missing.
        A wrong duration is worse than an absent one because it feeds
        ``years_of_experience``, which employers sanity-check.
        """
        from core.hashing import parse_iso_date

        start = parse_iso_date(self.start_date.value)
        end = parse_iso_date(self.end_date.value)
        if start is None:
            return None
        if end is None:
            if self.is_current.value is True:
                end = utc_now().date()
            else:
                return None
        if end < start:
            return None
        return (end.year - start.year) * 12 + (end.month - start.month)


class ExperienceSection(_Section):
    """All roles, plus a separately tracked total.

    ``total_years_experience`` is ``UNKNOWN`` in the template even though it
    could be computed from the entries. The computed value belongs in an
    ``INFERRED`` field derived at read time, not as a hand-written verified
    claim.
    """

    section_path: str = "experience"
    entries: list[ExperienceEntry] = Field(default_factory=list)
    total_years_experience: FactValue = Field(
        default_factory=lambda: FactValue(field_path="experience.total_years_experience")
    )
    years_of_experience_verified: FactValue = Field(
        default_factory=lambda: FactValue(field_path="experience.years_of_experience_verified")
    )


class SkillsSection(_Section):
    """Skill groups.

    ``proficient`` and ``expert`` are part of the vocabulary but carry no
    default values, because assigning a proficiency level to someone is a
    judgement the candidate has to make.
    """

    section_path: str = "skills"
    proficient: FactValue = Field(default_factory=lambda: FactValue(field_path="skills.proficient"))
    expert: FactValue = Field(default_factory=lambda: FactValue(field_path="skills.expert"))
    familiar: FactValue = Field(default_factory=lambda: FactValue(field_path="skills.familiar"))
    languages: FactValue = Field(default_factory=lambda: FactValue(field_path="skills.languages"))
    tools: FactValue = Field(default_factory=lambda: FactValue(field_path="skills.tools"))

    def all_skills(self) -> list[str]:
        """Flatten every skill group into one de-duplicated, sorted list."""
        seen: set[str] = set()
        for name in ("proficient", "expert", "familiar", "tools", "languages"):
            values = getattr(self, name).value
            if isinstance(values, (list, tuple, set)):
                for item in values:
                    if isinstance(item, str) and item.strip():
                        seen.add(item.strip())
        return sorted(seen, key=str.casefold)


class ProjectEntry(_Section):
    """One project. No metrics are invented; ``metrics`` stays empty."""

    section_path: str = "projects"
    name: FactValue = Field(default_factory=lambda: FactValue(field_path="projects.name"))
    description: FactValue = Field(default_factory=lambda: FactValue(field_path="projects.description"))
    role: FactValue = Field(default_factory=lambda: FactValue(field_path="projects.role"))
    technologies: FactValue = Field(default_factory=lambda: FactValue(field_path="projects.technologies"))
    link: FactValue = Field(default_factory=lambda: FactValue(field_path="projects.link"))
    start_date: FactValue = Field(default_factory=lambda: FactValue(field_path="projects.start_date"))
    end_date: FactValue = Field(default_factory=lambda: FactValue(field_path="projects.end_date"))
    metrics: FactValue = Field(default_factory=lambda: FactValue(field_path="projects.metrics"))


class ProjectsSection(_Section):
    section_path: str = "projects"
    entries: list[ProjectEntry] = Field(default_factory=list)


class CertificationEntry(_Section):
    """One certification. ``expires`` is a real date or ``UNKNOWN``."""

    section_path: str = "certifications"
    name: FactValue = Field(default_factory=lambda: FactValue(field_path="certifications.name"))
    issuer: FactValue = Field(default_factory=lambda: FactValue(field_path="certifications.issuer"))
    issue_date: FactValue = Field(default_factory=lambda: FactValue(field_path="certifications.issue_date"))
    expiry_date: FactValue = Field(default_factory=lambda: FactValue(field_path="certifications.expiry_date"))
    credential_id: FactValue = Field(default_factory=lambda: FactValue(field_path="certifications.credential_id"))
    url: FactValue = Field(default_factory=lambda: FactValue(field_path="certifications.url"))


class CertificationsSection(_Section):
    section_path: str = "certifications"
    entries: list[CertificationEntry] = Field(default_factory=list)


class LinkEntry(_Section):
    section_path: str = "links"
    label: FactValue = Field(default_factory=lambda: FactValue(field_path="links.label"))
    url: FactValue = Field(default_factory=lambda: FactValue(field_path="links.url"))
    kind: FactValue = Field(default_factory=lambda: FactValue(field_path="links.kind"))


class LinksSection(_Section):
    section_path: str = "links"
    entries: list[LinkEntry] = Field(default_factory=list)


class PreferencesSection(_Section):
    """What the candidate wants. Salary is left ``UNKNOWN`` on purpose."""

    section_path: str = "preferences"
    desired_roles: FactValue = Field(default_factory=lambda: FactValue(field_path="preferences.desired_roles"))
    desired_locations: FactValue = Field(default_factory=lambda: FactValue(field_path="preferences.desired_locations"))
    remote_preference: FactValue = Field(default_factory=lambda: FactValue(field_path="preferences.remote_preference"))
    minimum_salary: FactValue = Field(default_factory=lambda: FactValue(field_path="preferences.minimum_salary"))
    maximum_salary: FactValue = Field(default_factory=lambda: FactValue(field_path="preferences.maximum_salary"))
    willing_to_relocate: FactValue = Field(default_factory=lambda: FactValue(field_path="preferences.willing_to_relocate"))
    notice_period: FactValue = Field(default_factory=lambda: FactValue(field_path="preferences.notice_period"))
    willing_to_travel: FactValue = Field(default_factory=lambda: FactValue(field_path="preferences.willing_to_travel"))


class AuthorizationSection(_Section):
    """Work authorisation.

    The most sensitive fields in the profile. An unauthorised answer here can
    cost a real person a visa or a job, so the validator treats any value
    without evidence as an error rather than a warning.
    """

    section_path: str = "authorization"
    requires_sponsorship: FactValue = Field(
        default_factory=lambda: FactValue(field_path="authorization.requires_sponsorship")
    )
    authorized_countries: FactValue = Field(
        default_factory=lambda: FactValue(field_path="authorization.authorized_countries")
    )
    visa_status: FactValue = Field(default_factory=lambda: FactValue(field_path="authorization.visa_status"))
    sponsorship_available: FactValue = Field(
        default_factory=lambda: FactValue(field_path="authorization.sponsorship_available")
    )
    security_clearance: FactValue = Field(default_factory=lambda: FactValue(field_path="authorization.security_clearance"))


class AvailabilitySection(_Section):
    section_path: str = "availability"
    available_from: FactValue = Field(default_factory=lambda: FactValue(field_path="availability.available_from"))
    notice_period_days: FactValue = Field(default_factory=lambda: FactValue(field_path="availability.notice_period_days"))
    hours_per_week: FactValue = Field(default_factory=lambda: FactValue(field_path="availability.hours_per_week"))
    open_to_contract: FactValue = Field(default_factory=lambda: FactValue(field_path="availability.open_to_contract"))
    open_to_part_time: FactValue = Field(default_factory=lambda: FactValue(field_path="availability.open_to_part_time"))


class CandidateProfile(BaseModel):
    """One candidate's profile.

    The template is generated by :func:`build_empty_profile`, which fills every
    field with ``UNKNOWN``. Nothing is inferred, defaulted, or guessed.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: str = PROFILE_SCHEMA_VERSION
    id: str = Field(default="")
    candidate_id: str = "primary"
    version: int = Field(default=1, ge=1)

    identity: IdentitySection = Field(default_factory=IdentitySection)
    contact: ContactSection = Field(default_factory=ContactSection)
    location: LocationSection = Field(default_factory=LocationSection)
    education: EducationSection = Field(default_factory=EducationSection)
    experience: ExperienceSection = Field(default_factory=ExperienceSection)
    skills: SkillsSection = Field(default_factory=SkillsSection)
    projects: ProjectsSection = Field(default_factory=ProjectsSection)
    certifications: CertificationsSection = Field(default_factory=CertificationsSection)
    links: LinksSection = Field(default_factory=LinksSection)
    preferences: PreferencesSection = Field(default_factory=PreferencesSection)
    authorization: AuthorizationSection = Field(default_factory=AuthorizationSection)
    availability: AvailabilitySection = Field(default_factory=AvailabilitySection)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("id", mode="before")
    @classmethod
    def _derive_id(cls, value: Any) -> str:
        """Give the profile a stable id derived from the candidate id."""
        return value or ""

    @model_validator(mode="after")
    def _assign_id(self) -> "CandidateProfile":
        if not self.id:
            self.__dict__["id"] = f"profile-{short_hash(self.candidate_id, 8)}"
        return self

    # -- traversal -----------------------------------------------------------
    def iter_fact_values(self):
        """Yield ``(field_path, FactValue, section_name)`` for every field.

        Entries inside list sections get an indexed path such as
        ``experience.entries[0].employer``.
        """
        for section_name in self._section_names():
            section = getattr(self, section_name)
            yield from self._iter_section(section_name, section)

    def _iter_section(self, section_name: str, section: Any, prefix: str | None = None):
        base = prefix or section_name
        for name, value in section:
            if isinstance(value, FactValue):
                yield value.field_path or f"{base}.{name}", value, section_name
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, BaseModel):
                        yield from self._iter_section(section_name, item, f"{base}.{name}[{index}]")

    def _section_names(self) -> list[str]:
        return [
            name
            for name in type(self).model_fields
            if name
            not in {"schema_version", "id", "candidate_id", "version", "created_at", "updated_at"}
        ]

    def to_facts(self) -> list[Fact]:
        """Flatten to :class:`Fact` records, preserving evidence."""
        facts: list[Fact] = []
        for field_path, value, _section in self.iter_fact_values():
            fact = value.to_fact()
            fact.field_path = field_path
            facts.append(fact)
        return facts

    def fact_count(self) -> int:
        return sum(1 for _ in self.iter_fact_values())

    def completeness(self) -> float:
        """Fraction of fields that may be typed into a real application.

        Only application-safe facts count, so an ``INFERRED`` field counts as
        incomplete on purpose: a guessed value is not progress. Used to show
        progress. It is *not* a quality measure: a profile at 100% can still be
        wrong, because a ``VERIFIED`` fact is only as good as the human who
        confirmed it.
        """
        total = 0
        known = 0
        for _path, value, _section in self.iter_fact_values():
            total += 1
            if value.is_application_safe:
                known += 1
        return round(known / total, 4) if total else 0.0

    def unknown_fields(self) -> list[str]:
        """Paths of every field whose status is ``UNKNOWN``."""
        return [path for path, value, _ in self.iter_fact_values() if value.status.value == "UNKNOWN"]

    def inferred_fields(self) -> list[str]:
        return [path for path, value, _ in self.iter_fact_values() if value.status.value == "INFERRED"]

    def verified_fields(self) -> list[str]:
        return [path for path, value, _ in self.iter_fact_values() if value.status.value == "VERIFIED"]

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent, exclude_none=False)

    @classmethod
    def from_json(cls, raw: str) -> "CandidateProfile":
        """Parse a profile from JSON text.

        Raises:
            ValueError: If the JSON does not match the schema.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"profile JSON is invalid: {exc}") from exc
        return cls.model_validate(data)

    def save(self, path: Optional[Path] = None, paths: Optional[Paths] = None) -> Path:
        """Write the profile to disk atomically.

        The candidate's real profile is git-ignored; this writes the local
        working copy only.
        """
        target = Path(path) if path is not None else (paths or get_paths()).candidate_profile
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(self.to_json(), encoding="utf-8")
        tmp.replace(target)
        return target

    @classmethod
    def load(cls, path: Optional[Path] = None, paths: Optional[Paths] = None) -> "CandidateProfile":
        """Load a profile from disk.

        Raises:
            FileNotFoundError: If the profile file does not exist.
        """
        source = Path(path) if path is not None else (paths or get_paths()).candidate_profile
        if not source.is_file():
            raise FileNotFoundError(f"candidate profile not found at {source}")
        return cls.from_json(source.read_text(encoding="utf-8"))

    def with_update(self, path: str, value: Any, **kwargs: Any) -> "CandidateProfile":
        """Return a copy with one field replaced, matching a dotted path.

        The version is incremented and ``updated_at`` refreshed only when the
        replacement actually differs from the current value. Re-saving an
        unchanged value therefore leaves the audit trail alone, while any real
        change to a fact is distinguishable from a no-op.

        Args:
            path: Dotted path such as ``identity.full_name`` or
                ``experience.entries[0].employer``.
            value: New value, or ``None`` to set the field ``UNKNOWN``.
            **kwargs: Passed to :class:`~core.evidence.FactValue`, e.g.
                ``status=FactStatus.VERIFIED``.

        Raises:
            AttributeError: If ``path`` does not exist on the profile.
        """
        before = _lookup_fact_value(self, path)
        updated = with_fact_update(self, path, value, **kwargs)
        after = _lookup_fact_value(updated, path)
        if before is not None and after is not None and before == after:
            return updated
        return updated.model_copy(update={"version": self.version + 1, "updated_at": utc_now()})


def with_fact_update(model: TModel, path: str, value: Any, **kwargs: Any) -> TModel:
    """Return a deep copy of ``model`` with one :class:`FactValue` replaced.

    Works on a whole profile, a section, or a single entry, so entries can be
    built the same way as top-level fields::

        entry = ExperienceEntry().with_update('experience.start_date', '2019-01-01', **verified)

    Args:
        model: Any profile model containing :class:`FactValue` fields.
        path: Dotted path relative to ``model``. Supports list indices, e.g.
            ``entries[0].employer``.
        value: New value. Passing ``None`` resets the field to ``UNKNOWN``.
        **kwargs: Overrides for the new :class:`FactValue`, e.g. ``status``,
            ``source``, ``source_id``. Unspecified fields keep their current
            value.

    Returns:
        A new model. The original is never mutated.

    Raises:
        AttributeError: If ``path`` does not resolve on ``model``.
        TypeError: If the leaf is neither a :class:`FactValue` nor assignable.
    """
    clone = model.model_copy(deep=True)
    target: Any = clone
    parts = _split_path(path)
    parts = _strip_own_prefix(model, parts)
    if not parts:
        raise AttributeError(f"cannot resolve an empty field path for {type(model).__name__}")
    for part in parts[:-1]:
        target = _descend(target, part)

    leaf, _index = _split_list_index(parts[-1])
    if not hasattr(target, leaf):
        raise AttributeError(f"{type(model).__name__} has no field {leaf!r} (from {path!r})")

    current = getattr(target, leaf)
    if not isinstance(current, FactValue):
        setattr(target, leaf, value)
        return clone

    # A None value means UNKNOWN, so drop stale VERIFIED metadata rather than
    # leaving a verified_at timestamp attached to an empty field. Evidence is
    # dropped for the same reason: evidence describing a value that is no
    # longer there would make the field look supported when it is not.
    if value is None:
        status = kwargs.pop("status", FactStatus.UNKNOWN)
        if status is FactStatus.UNKNOWN:
            kwargs.update(
                {
                    "source": None,
                    "source_id": None,
                    "source_location": None,
                    "confidence": 0.0,
                    "verified_at": None,
                    "evidence": [],
                }
            )
        kwargs["status"] = status
    # Setting a value on an UNKNOWN field is a claim, so default to INFERRED.
    # Promoting to VERIFIED must be requested explicitly.
    elif "status" not in kwargs:
        kwargs["status"] = (
            FactStatus.VERIFIED if current.status is FactStatus.VERIFIED else FactStatus.INFERRED
        )

    # Derive the compact source fields from the evidence records when they were
    # not given directly, so ``with_update(..., evidence=[ev])`` is enough to
    # satisfy the VERIFIED-needs-a-source rule without repeating the same
    # source_type/source_id twice.
    evidence = kwargs.get("evidence")
    if isinstance(evidence, list) and evidence:
        if "source" not in kwargs and kwargs.get("status") is FactStatus.VERIFIED:
            kwargs["source"] = evidence[0].source_type
        if "source_id" not in kwargs and current.source_id is None:
            kwargs["source_id"] = evidence[0].source_id
        if "source_location" not in kwargs and current.source_location is None:
            kwargs["source_location"] = evidence[0].source_location
        if kwargs.get("verified_at") is None and kwargs.get("status") is FactStatus.VERIFIED:
            kwargs["verified_at"] = utc_now()

    replacement = FactValue(
        field_path=path,
        value=value,
        status=kwargs.pop("status", current.status),
        source=kwargs.pop("source", current.source),
        source_id=kwargs.pop("source_id", current.source_id),
        source_location=kwargs.pop("source_location", current.source_location),
        confidence=kwargs.pop("confidence", current.confidence),
        verified_at=kwargs.pop("verified_at", current.verified_at),
        evidence=kwargs.pop("evidence", current.evidence),
        **kwargs,
    )
    setattr(target, leaf, replacement)
    return clone


def _lookup_fact_value(model: TModel, path: str) -> Optional[FactValue]:
    """Return the :class:`FactValue` at ``path``, or ``None`` if there is none.

    Used to compare a value before and after an update so an unchanged save
    does not look like an edit. A path that does not resolve returns ``None``
    rather than raising, because callers here are already deciding whether the
    update was a real change.
    """
    target: Any = model
    parts = _strip_own_prefix(model, _split_path(path))
    for part in parts[:-1]:
        try:
            target = _descend(target, part)
        except (AttributeError, IndexError, KeyError, TypeError):
            return None
    leaf, _index = _split_list_index(parts[-1]) if parts else ("", None)
    if not leaf or not hasattr(target, leaf):
        return None
    current = getattr(target, leaf)
    return current if isinstance(current, FactValue) else None


def _split_path(path: str) -> list[str]:
    return [p for p in path.replace("]", "").replace("[", ".").split(".") if p]


def _strip_own_prefix(model: Any, parts: list[str]) -> list[str]:
    """Allow a full-profile path to be used on a section or entry.

    ``ExperienceEntry().with_update("experience.employer", ...)`` and
    ``ExperienceEntry().with_update("employer", ...)`` are equivalent. Without
    this, passing the profile-level path to an entry fails with a confusing
    "has no attribute" error.
    """
    own = getattr(model, "section_path", None) or type(model).__name__.lower()
    if parts and parts[0] == own:
        return parts[1:]
    return parts


def _split_list_index(part: str) -> tuple[str, Optional[int]]:
    if part.isdigit():
        return "", int(part)
    return part, None


def _descend(target: Any, part: str) -> Any:
    name, index = _split_list_index(part)
    if index is not None:
        container = getattr(target, name)
        return container[index]
    return getattr(target, name)


def build_empty_profile(candidate_id: str = "primary") -> CandidateProfile:
    """Return a profile in which every single field is ``UNKNOWN``.

    This is the shipped default and the correct starting state. No name, no
    degree, no GPA, no employer, no date, no skill, no salary, no work
    authorisation: all ``UNKNOWN`` with no evidence.
    """
    return CandidateProfile(candidate_id=candidate_id)


def evidence_from_document(
    source_type, source_id: str, **kwargs: Any
) -> Evidence:
    """Convenience constructor for evidence pointing at a stored document."""
    return Evidence(source_type=source_type, source_id=source_id, **kwargs)
