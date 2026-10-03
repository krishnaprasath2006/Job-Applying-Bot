"""Candidate profile validation.

The validator **reports**; it never repairs. There is deliberately no
``fix_profile`` function. Silently correcting a contradictory date range or
dropping a duplicated skill would hide exactly the kind of problem a human
needs to see, and it would mean the assistant decided something about a real
person's career history on its own.

Findings carry a stable :class:`~core.enums.ValidationCode` so tests and later
phases can branch on them without parsing messages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from core.enums import (
    FactStatus,
    ValidationCode,
    ValidationSeverity,
)
from core.errors import ProfileValidationError
from core.hashing import parse_iso_date, utc_now
from profile.models import CandidateProfile

__all__ = ["ValidationIssue", "ValidationReport", "CandidateProfileValidator"]

# Fields that must be VERIFIED before any real application can be prepared.
# Everything else is optional: an incomplete profile is a valid profile.
REQUIRED_FOR_APPLICATION: tuple[str, ...] = (
    "identity.full_name",
    "contact.email",
    "contact.phone",
    "location.current_country",
    "experience.total_years_experience",
    "education.highest_level",
    "authorization.requires_sponsorship",
    "availability.available_from",
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-().]{6,24}$")
_GPA_RE = re.compile(r"^\s*(?:([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)|([0-9]+(?:\.[0-9]+)?))\s*$")
_ALLOWED_URL_SCHEMES = {"http", "https"}

# Plausibility ceilings. Not correctness judgements - they catch typos such as
# "graduated in 3024" or a GPA of 4.5 that is probably out of 4.
_MAX_PLAUSIBLE_AGE = 100
_MAX_GPA_SCALE = 10.0
_MAX_EXPERIENCE_YEARS = 60


@dataclass(frozen=True)
class ValidationIssue:
    """One finding.

    Attributes:
        code: Stable identifier.
        severity: ERROR blocks real use; WARNING should be reviewed.
        field_path: Dotted path, or a section-level path such as
            ``experience.entries``.
        message: Operator-facing description.
        actual: The offending value, for display.
        expected: What was expected.
    """

    code: ValidationCode
    severity: ValidationSeverity
    field_path: str
    message: str
    actual: Any = None
    expected: Any = None

    def __str__(self) -> str:
        base = f"[{self.severity.value}] {self.code.value} at {self.field_path}: {self.message}"
        return f"{base} (actual={self.actual!r})" if self.actual is not None else base


@dataclass
class ValidationReport:
    """The full result of validating a profile.

    A report with zero issues on an empty template is expected and correct.
    ``is_valid`` means "nothing is wrong", not "ready to apply with".
    """

    issues: list[ValidationIssue] = field(default_factory=list)
    checked_at: Any = field(default_factory=utc_now)
    profile_id: str = ""
    completeness: float = 0.0

    def add(
        self,
        code: ValidationCode,
        field_path: str,
        message: str,
        severity: ValidationSeverity = ValidationSeverity.ERROR,
        actual: Any = None,
        expected: Any = None,
    ) -> None:
        self.issues.append(ValidationIssue(code, severity, field_path, message, actual, expected))

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is ValidationSeverity.WARNING]

    @property
    def is_valid(self) -> bool:
        """True when there are no ERROR-severity findings."""
        return not self.errors

    @property
    def blocking_issues(self) -> list[ValidationIssue]:
        return self.errors

    @property
    def missing_required(self) -> list[str]:
        return sorted(
            {
                i.field_path
                for i in self.issues
                if i.code
                in (
                    ValidationCode.MISSING_REQUIRED_FIELD,
                    ValidationCode.UNKNOWN_VALUE_FOR_REQUIRED_FIELD,
                )
            }
        )

    def by_code(self, code: ValidationCode) -> list[ValidationIssue]:
        return [i for i in self.issues if i.code is code]

    def has(self, code: ValidationCode) -> bool:
        return any(i.code is code for i in self.issues)

    def raise_if_invalid(self) -> None:
        """Raise :class:`ProfileValidationError` if there are ERROR findings.

        Note: an empty template *is* valid. This raises only for genuine
        contradictions, malformed values, and missing required facts.
        """
        if not self.is_valid:
            raise ProfileValidationError(
                f"profile validation failed with {len(self.errors)} error(s)",
                issues=self.errors,
                profile_id=self.profile_id,
            )

    def summary(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "completeness": self.completeness,
            "missing_required": self.missing_required,
            "codes": sorted({i.code.value for i in self.issues}),
        }


class CandidateProfileValidator:
    """Validates a :class:`CandidateProfile`.

    Usage::

        report = CandidateProfileValidator().validate(profile)
        if not report.is_valid:
            for issue in report.errors:
                print(issue)
    """

    def __init__(
        self,
        *,
        require_application_fields: bool = True,
        strict: bool = False,
    ) -> None:
        """
        Args:
            require_application_fields: Report ERROR for each required field
                that is ``UNKNOWN``. Set false to get a completeness report
                without treating gaps as errors.
            strict: Promote selected WARNINGs to ERRORs.
        """
        self.require_application_fields = require_application_fields
        self.strict = strict

    # -- entry point ---------------------------------------------------------
    def validate(self, profile: CandidateProfile) -> ValidationReport:
        """Run every rule and return a report.

        This method never raises for bad data. Reporting problems is the
        point; raising is the caller's decision.
        """
        report = ValidationReport(
            profile_id=profile.id,
            completeness=profile.completeness(),
        )

        self._check_invariants(profile, report)
        self._check_types(profile, report)
        self._check_formats(profile, report)
        self._check_dates(profile, report)
        self._check_experience(profile, report)
        self._check_skills(profile, report)
        self._check_education(profile, report)
        self._check_links(profile, report)
        self._check_contradictions(profile, report)
        if self.require_application_fields:
            self._check_required(profile, report)
        if self.strict:
            self._promote_warnings(report)
        return report

    def validate_or_raise(self, profile: CandidateProfile) -> ValidationReport:
        """Validate and raise :class:`ProfileValidationError` on ERROR findings."""
        report = self.validate(profile)
        report.raise_if_invalid()
        return report

    # -- rules ---------------------------------------------------------------
    def _check_invariants(self, profile: CandidateProfile, report: ValidationReport) -> None:
        """Structural rules that apply to every field."""
        for field_path, value, _section in profile.iter_fact_values():
            if value.status is FactStatus.UNKNOWN and value.value is not None:
                report.add(
                    ValidationCode.UNKNOWN_WITH_VALUE,
                    field_path,
                    "field is marked UNKNOWN but carries a value; this would hide "
                    "'I don't know' behind a real answer",
                    actual=value.value,
                    expected="value=None when status is UNKNOWN",
                )
            if value.status is FactStatus.UNKNOWN:
                if value.verified_at is not None:
                    report.add(
                        ValidationCode.CONTRADICTORY_VALUES,
                        field_path,
                        "field is UNKNOWN but has a verified_at timestamp",
                        actual=str(value.verified_at),
                    )
                continue
            if value.value is None:
                report.add(
                    ValidationCode.INVALID_TYPE,
                    field_path,
                    f"field is {value.status.value} but carries no value",
                    expected="a value",
                )
                continue
            if value.status is FactStatus.VERIFIED and not value.source:
                report.add(
                    ValidationCode.VALUE_WITHOUT_EVIDENCE,
                    field_path,
                    "VERIFIED fact has no source; a verified value must be traceable "
                    "to something the candidate or a document provided",
                    actual=value.value,
                    expected="source set (e.g. RESUME, USER_INPUT)",
                )
            if value.status is FactStatus.INFERRED and value.source_id is None:
                report.add(
                    ValidationCode.VALUE_WITHOUT_EVIDENCE,
                    field_path,
                    "INFERRED fact has no source_id, so the inference cannot be audited",
                    actual=value.value,
                )
            if value.status is FactStatus.INFERRED and value.verified_at is not None:
                report.add(
                    ValidationCode.INFERRED_MARKED_VERIFIED,
                    field_path,
                    "INFERRED fact carries a verified_at timestamp; inferred values are "
                    "never verified until a human promotes them",
                    actual=value.value,
                )
            if not isinstance(value.status, FactStatus):
                report.add(
                    ValidationCode.UNSUPPORTED_STATUS,
                    field_path,
                    "unsupported fact status",
                    actual=str(value.status),
                    expected="one of VERIFIED, UNKNOWN, INFERRED",
                )

    def _check_types(self, profile: CandidateProfile, report: ValidationReport) -> None:
        """Declared shape of list-valued fields."""
        list_paths = {
            "skills.proficient",
            "skills.expert",
            "skills.familiar",
            "skills.languages",
            "skills.tools",
            "location.preferred_locations",
            "preferences.desired_roles",
            "preferences.desired_locations",
            "authorization.authorized_countries",
            "experience.responsibilities",
            "experience.achievements",
            "experience.technologies",
        }
        bool_paths = {
            "location.willing_to_relocate",
            "preferences.remote_preference",
            "preferences.willing_to_relocate",
            "preferences.willing_to_travel",
            "authorization.requires_sponsorship",
            "authorization.sponsorship_available",
            "availability.open_to_contract",
            "availability.open_to_part_time",
        }
        for field_path, value, _section in profile.iter_fact_values():
            if value.status is FactStatus.UNKNOWN or value.value is None:
                continue
            if field_path in list_paths and not isinstance(value.value, (list, tuple, set)):
                report.add(
                    ValidationCode.INVALID_TYPE,
                    field_path,
                    "expected a list of strings",
                    actual=type(value.value).__name__,
                )
            if field_path in bool_paths and not isinstance(value.value, bool):
                report.add(
                    ValidationCode.INVALID_TYPE,
                    field_path,
                    "expected a boolean",
                    actual=type(value.value).__name__,
                )
            if field_path.endswith(".gpa") and not isinstance(value.value, (int, float, str)):
                report.add(
                    ValidationCode.INVALID_TYPE,
                    field_path,
                    "GPA must be a number or a string like '3.8/4.0'",
                    actual=type(value.value).__name__,
                )

    def _check_formats(self, profile: CandidateProfile, report: ValidationReport) -> None:
        """Email, phone, and URL syntax."""
        for field_path, value, _section in profile.iter_fact_values():
            if value.status is FactStatus.UNKNOWN or value.value is None:
                continue
            raw = value.value
            if field_path == "contact.email":
                if not _EMAIL_RE.match(str(raw).strip()):
                    report.add(
                        ValidationCode.MALFORMED_EMAIL,
                        field_path,
                        "value is not a valid email address",
                        actual=raw,
                    )
            if field_path == "contact.phone":
                if not _PHONE_RE.match(str(raw).strip()):
                    report.add(
                        ValidationCode.INVALID_PHONE,
                        field_path,
                        "value is not a plausible phone number",
                        actual=raw,
                    )
            if isinstance(raw, str) and "url" in field_path.lower():
                self._check_url(field_path, raw, report)

    def _check_url(self, field_path: str, raw: str, report: ValidationReport) -> None:
        text = raw.strip()
        parsed = urlparse(text)
        if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
            report.add(
                ValidationCode.INVALID_URL,
                field_path,
                "URL must start with http:// or https://",
                actual=raw,
                expected="http(s)://host/path",
            )
            return
        if not parsed.netloc:
            report.add(
                ValidationCode.INVALID_URL,
                field_path,
                "URL has no host component",
                actual=raw,
            )
            return
        if "." not in parsed.netloc and not parsed.netloc.startswith("localhost"):
            report.add(
                ValidationCode.INVALID_URL,
                field_path,
                "URL host does not look like a domain",
                actual=raw,
            )

    def _check_dates(self, profile: CandidateProfile, report: ValidationReport) -> None:
        """Parse every date-looking field and flag bad values."""
        date_paths: dict[str, str] = {}
        for index, entry in enumerate(profile.education.entries):
            for name in ("start_date", "end_date"):
                path = f"education.entries[{index}].{name}"
                date_paths[path] = entry.model_dump()[name]["value"]
        for index, entry in enumerate(profile.experience.entries):
            for name in ("start_date", "end_date"):
                path = f"experience.entries[{index}].{name}"
                date_paths[path] = entry.model_dump()[name]["value"]
        for index, entry in enumerate(profile.certifications.entries):
            for name in ("issue_date", "expiry_date"):
                path = f"certifications.entries[{index}].{name}"
                date_paths[path] = entry.model_dump()[name]["value"]
        for index, entry in enumerate(profile.projects.entries):
            for name in ("start_date", "end_date"):
                path = f"projects.entries[{index}].{name}"
                date_paths[path] = entry.model_dump()[name]["value"]
        for path in ("identity.date_of_birth", "availability.available_from"):
            section_name, field_name = path.split(".")
            date_paths[path] = getattr(profile, section_name).model_dump()[field_name]["value"]

        today = utc_now().date()
        for field_path, raw in date_paths.items():
            if raw is None:
                continue
            parsed = parse_iso_date(raw)
            if parsed is None:
                report.add(
                    ValidationCode.INVALID_DATE,
                    field_path,
                    "value could not be parsed as a date; use YYYY-MM-DD or YYYY",
                    actual=raw,
                    expected="YYYY-MM-DD or YYYY",
                )
                continue
            if parsed > today:
                severity = (
                    ValidationSeverity.WARNING
                    if field_path.startswith("availability.")
                    else ValidationSeverity.ERROR
                )
                report.add(
                    ValidationCode.DATE_IN_FUTURE,
                    field_path,
                    "date is in the future",
                    actual=raw,
                    expected=f"<= {today.isoformat()}",
                    severity=severity,
                )
            if field_path == "identity.date_of_birth":
                age = _years_between(parsed, today)
                if age is not None and age > _MAX_PLAUSIBLE_AGE:
                    report.add(
                        ValidationCode.INVALID_DATE,
                        field_path,
                        f"date of birth implies an age of {age}, which is implausible",
                        actual=raw,
                        severity=ValidationSeverity.WARNING,
                    )

    def _check_experience(self, profile: CandidateProfile, report: ValidationReport) -> None:
        """Ranges, overlaps, and total-years consistency."""
        spans: list[tuple[date, date, str]] = []
        for index, entry in enumerate(profile.experience.entries):
            base = f"experience.entries[{index}]"
            raw = entry.model_dump()
            start = parse_iso_date(raw["start_date"]["value"])
            end = parse_iso_date(raw["end_date"]["value"])
            is_current = raw["is_current"]["value"]

            if start and end and end < start:
                report.add(
                    ValidationCode.IMPOSSIBLE_DATE_RANGE,
                    base,
                    "end date is before the start date",
                    actual=f"{raw['start_date']['value']} -> {raw['end_date']['value']}",
                    severity=ValidationSeverity.ERROR,
                )
                continue
            if is_current is True and end is not None:
                report.add(
                    ValidationCode.CONTRADICTORY_VALUES,
                    base,
                    "role is marked current but also has an end date",
                    actual=raw["end_date"]["value"],
                )
            if is_current is not True and start and end is None:
                report.add(
                    ValidationCode.CONTRADICTORY_VALUES,
                    base,
                    "role has a start date but no end date and is not marked current",
                    actual=None,
                    expected="end_date set, or is_current=true",
                    severity=ValidationSeverity.WARNING,
                )
            if start is None and raw["employer"]["value"] is not None:
                report.add(
                    ValidationCode.INVALID_DATE,
                    f"{base}.start_date",
                    "role has an employer but no start date",
                    severity=ValidationSeverity.WARNING,
                )
            if start and end:
                spans.append((start, end, base))
            elif start and is_current is True:
                today = utc_now().date()
                spans.append((start, today, base))

        for i in range(len(spans)):
            for j in range(i + 1, len(spans)):
                a_start, a_end, a_path = spans[i]
                b_start, b_end, b_path = spans[j]
                if a_start <= b_end and b_start <= a_end:
                    report.add(
                        ValidationCode.OVERLAPPING_JOBS,
                        f"{a_path} / {b_path}",
                        "two roles overlap in time; full-time overlaps are unusual but "
                        "contract or part-time overlaps are normal",
                        actual=f"{a_start}..{a_end} overlaps {b_start}..{b_end}",
                        severity=ValidationSeverity.WARNING,
                    )

        claimed = profile.experience.total_years_experience.value
        computed_months = sum(m for m in (e.duration_months() for e in profile.experience.entries) if m)
        if isinstance(claimed, (int, float)) and computed_months:
            computed_years = round(computed_months / 12, 1)
            if abs(float(claimed) - computed_years) > 1.0:
                report.add(
                    ValidationCode.INCONSISTENT_EXPERIENCE_DURATION,
                    "experience.total_years_experience",
                    "stated total does not match the sum of individual roles",
                    actual=claimed,
                    expected=f"about {computed_years} years from the listed roles",
                )
            if float(claimed) > _MAX_EXPERIENCE_YEARS:
                report.add(
                    ValidationCode.IMPLAUSIBLE_YEARS_OF_EXPERIENCE,
                    "experience.total_years_experience",
                    f"more than {_MAX_EXPERIENCE_YEARS} years of experience is implausible",
                    actual=claimed,
                )

    def _check_skills(self, profile: CandidateProfile, report: ValidationReport) -> None:
        """Flag the same skill listed twice, case-insensitively."""
        seen: dict[str, list[str]] = {}
        for name in ("proficient", "expert", "familiar", "tools"):
            values = getattr(profile.skills, name).value
            if not isinstance(values, (list, tuple, set)):
                continue
            for item in values:
                if not isinstance(item, str):
                    report.add(
                        ValidationCode.INVALID_TYPE,
                        f"skills.{name}",
                        "skill entries must be strings",
                        actual=type(item).__name__,
                    )
                    continue
                key = item.strip().casefold()
                if key:
                    seen.setdefault(key, []).append(f"skills.{name}")

        for key, locations in seen.items():
            if len(locations) > 1:
                report.add(
                    ValidationCode.DUPLICATE_SKILL,
                    locations[0],
                    f"skill appears {len(locations)} times across skill groups",
                    actual=key,
                    expected="listed once",
                    severity=ValidationSeverity.WARNING,
                )

    def _check_education(self, profile: CandidateProfile, report: ValidationReport) -> None:
        """GPA plausibility."""
        for index, entry in enumerate(profile.education.entries):
            raw = entry.model_dump()["gpa"]["value"]
            if raw is None:
                continue
            path = f"education.entries[{index}].gpa"
            match = _GPA_RE.match(str(raw))
            if not match:
                report.add(
                    ValidationCode.INVALID_TYPE,
                    path,
                    "GPA must be a number or a ratio like '3.8/4.0'",
                    actual=raw,
                )
                continue
            numerator = match.group(1) or match.group(3)
            denominator = match.group(2)
            try:
                score = float(numerator)
            except ValueError:
                continue
            if score > _MAX_GPA_SCALE:
                report.add(
                    ValidationCode.IMPLAUSIBLE_GPA,
                    path,
                    f"GPA above {_MAX_GPA_SCALE} is implausible",
                    actual=raw,
                    severity=ValidationSeverity.WARNING,
                )
            if denominator:
                try:
                    scale = float(denominator)
                except ValueError:
                    continue
                if score > scale:
                    report.add(
                        ValidationCode.IMPLAUSIBLE_GPA,
                        path,
                        "GPA numerator exceeds its own denominator",
                        actual=raw,
                        severity=ValidationSeverity.WARNING,
                    )

    def _check_links(self, profile: CandidateProfile, report: ValidationReport) -> None:
        """URLs inside link and certification entries."""
        for index, entry in enumerate(profile.links.entries):
            raw = entry.model_dump()["url"]["value"]
            if raw is not None:
                self._check_url(f"links.entries[{index}].url", str(raw), report)
        for index, entry in enumerate(profile.certifications.entries):
            raw = entry.model_dump()["url"]["value"]
            if raw is not None:
                self._check_url(f"certifications.entries[{index}].url", str(raw), report)

    def _check_contradictions(self, profile: CandidateProfile, report: ValidationReport) -> None:
        """Cross-field inconsistencies that no single-field rule would catch."""
        reloc_pref = profile.preferences.willing_to_relocate.value
        reloc_loc = profile.location.willing_to_relocate.value
        if (
            reloc_pref is False
            and reloc_loc is True
        ):
            report.add(
                ValidationCode.CONTRADICTORY_VALUES,
                "preferences.willing_to_relocate / location.willing_to_relocate",
                "relocation preference says no in one place and yes in another",
                actual=f"preferences={reloc_pref}, location={reloc_loc}",
                expected="the same answer in both fields",
            )

        pref = profile.preferences
        lo, hi = pref.minimum_salary.value, pref.maximum_salary.value
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
            report.add(
                ValidationCode.CONTRADICTORY_VALUES,
                "preferences.minimum_salary",
                "minimum salary is greater than maximum salary",
                actual=f"min={lo}, max={hi}",
            )

        sponsorship = profile.authorization.requires_sponsorship.value
        visa = profile.authorization.visa_status.value
        if sponsorship is False and isinstance(visa, str) and "sponsor" in visa.lower():
            report.add(
                ValidationCode.CONTRADICTORY_VALUES,
                "authorization.requires_sponsorship",
                "sponsorship is not required but the visa status mentions sponsorship",
                actual=visa,
                expected="consistent visa status",
            )

        notice = profile.availability.notice_period_days.value
        if isinstance(notice, (int, float)) and notice < 0:
            report.add(
                ValidationCode.INVALID_TYPE,
                "availability.notice_period_days",
                "notice period cannot be negative",
                actual=notice,
            )

    def _check_required(self, profile: CandidateProfile, report: ValidationReport) -> None:
        """Report each required field that is not verified.

        This is an ERROR because these are exactly the fields a real
        application form requires. It is the mechanism that stops the assistant
        from proceeding on an empty profile.
        """
        by_path = {path: value for path, value, _ in profile.iter_fact_values()}
        for required in REQUIRED_FOR_APPLICATION:
            value = by_path.get(required)
            if value is None:
                report.add(
                    ValidationCode.MISSING_REQUIRED_FIELD,
                    required,
                    "required field is not present on this profile",
                    severity=ValidationSeverity.ERROR,
                )
                continue
            if value.status is FactStatus.UNKNOWN:
                report.add(
                    ValidationCode.UNKNOWN_VALUE_FOR_REQUIRED_FIELD,
                    required,
                    "required field is UNKNOWN; a real application cannot proceed "
                    "until the candidate supplies it",
                    actual=None,
                    severity=ValidationSeverity.ERROR,
                )
            elif value.status is FactStatus.INFERRED:
                report.add(
                    ValidationCode.INFERRED_MARKED_VERIFIED,
                    required,
                    "required field is only INFERRED; a human must verify it before use",
                    actual=value.value,
                    severity=ValidationSeverity.ERROR,
                )

    def _promote_warnings(self, report: ValidationReport) -> None:
        """Strict mode: treat every warning as an error."""
        report.issues = [
            ValidationIssue(
                code=i.code,
                severity=ValidationSeverity.ERROR,
                field_path=i.field_path,
                message=i.message,
                actual=i.actual,
                expected=i.expected,
            )
            if i.severity is ValidationSeverity.WARNING
            else i
            for i in report.issues
        ]


def _years_between(start: date, end: date) -> Optional[int]:
    return end.year - start.year - ((end.month, end.day) < (start.month, start.day))
