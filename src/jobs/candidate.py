"""Candidate evidence: what the candidate is known to have, and where each
claim came from.

Matching reads a posting from one side and a person from the other. This
module is the person side: a flat, queryable view of one profile's facts,
built from Phase 2's :class:`core.evidence.Fact` records so every claim
carries the evidence it was verified with and the truth status it holds.

Nothing here guesses. A fact without a value contributes nothing; a list
element that is not text contributes nothing; the two scalars the gate must
never approximate — years of experience and whether sponsorship is needed —
are read as the profile states them, or not at all. When the profile is
empty this is an empty structure, which is a valid thing to be: an unknown
candidate is not a failing candidate, and the matcher will say so rather
than invent a person.

The bridge from a stored profile is deliberately one line::

    CandidateEvidence.from_facts(profile.to_facts())

so this module depends only on ``core`` and its siblings inside ``jobs`` —
never on the profile package, the database, or the browser.
"""

from __future__ import annotations

from typing import Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.enums import FactStatus
from core.evidence import Evidence, Fact
from jobs.models import RequirementKind
from jobs.normalizer import normalize_text
from jobs.requirements import classify_term

__all__ = ["CandidateClaim", "CandidateEvidence", "FactRef"]

# Profile fields whose value is a claim about what the candidate has. The
# two scalars are handled separately; everything else is compared as text.
_CLAIM_FIELDS = frozenset(
    {
        "skills.proficient",
        "skills.expert",
        "skills.familiar",
        "skills.tools",
        "skills.languages",
        "education.highest_level",
        "location.current_city",
        "location.current_state",
        "location.current_country",
        "location.preferred_locations",
        "preferences.desired_roles",
        "preferences.desired_locations",
        "preferences.remote_preference",
    }
)
_CLAIM_SUFFIXES = (
    ".technologies",
    ".degree",
    ".field_of_study",
    ".employment_type",
)
_YEARS_FIELD = "experience.total_years_experience"
_SPONSORSHIP_FIELD = "authorization.requires_sponsorship"
_MAX_YEARS = 60.0


class FactRef(BaseModel):
    """The profile fact a value came from.

    Attributes:
        field_path: Dotted path of the fact, e.g. ``skills.proficient``.
        status: Truth state the profile holds for it. ``INFERRED`` claims
            stay labelled so a resume parse is never mistaken for a
            confirmed one.
        evidence: The records backing the value, quotes intact.
    """

    model_config = ConfigDict(extra="forbid")

    field_path: str = ""
    status: FactStatus = FactStatus.UNKNOWN
    evidence: list[Evidence] = Field(default_factory=list)


class CandidateClaim(BaseModel):
    """One thing the candidate is known to have, as the profile states it.

    Attributes:
        text: The claim as written ("Python", "Bachelors", "Testville").
        normalized: Lower-cased comparison form, filled in from ``text``.
        kind: Same taxonomy the requirements are read with, so both sides
            of a comparison agree on what they are comparing.
        source: Where the claim came from and how true it is held to be.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    normalized: str = ""
    kind: RequirementKind = RequirementKind.OTHER
    source: FactRef = Field(default_factory=FactRef)

    def model_post_init(self, __context: object) -> None:
        if not self.normalized:
            self.normalized = normalize_text(self.text).lower()


class CandidateEvidence(BaseModel):
    """Everything matching needs about one candidate, evidence intact.

    Attributes:
        claims: Every non-scalar claim, in fact order. The same skill under
            two different profile fields appears twice, each with its own
            source — provenance is not deduplicated away.
        years_of_experience: Total years as the profile states them, or
            ``None`` when unknown or unusable (out of range, not a number).
        years_source: The fact ``years_of_experience`` was read from.
        requires_sponsorship: Whether sponsorship is needed, or ``None``
            when the profile has not said.
        sponsorship_source: The fact ``requires_sponsorship`` was read from.
    """

    model_config = ConfigDict(extra="forbid")

    claims: list[CandidateClaim] = Field(default_factory=list)
    years_of_experience: Optional[float] = Field(default=None, ge=0.0, le=_MAX_YEARS)
    years_source: Optional[FactRef] = None
    requires_sponsorship: Optional[bool] = None
    sponsorship_source: Optional[FactRef] = None

    @classmethod
    def from_facts(cls, facts: Iterable[Fact]) -> "CandidateEvidence":
        """Build the evidence view from flattened profile facts.

        Facts are taken as given and in order: the caller decides what to
        feed it (``profile.to_facts()`` for a stored profile, a parsed
        fixture's facts in a test). Each fact either becomes claims, becomes
        one of the two scalars, or contributes nothing. When two facts speak
        for the same scalar the first usable one wins, so the result depends
        only on the order the profile reports.
        """
        claims: list[CandidateClaim] = []
        years: Optional[float] = None
        years_source: Optional[FactRef] = None
        sponsorship: Optional[bool] = None
        sponsorship_source: Optional[FactRef] = None

        for fact in facts:
            if fact.value is None or fact.status is FactStatus.UNKNOWN:
                # A fact with nothing in it, or one the profile still calls
                # unknown, is not evidence of anything.
                continue
            path = fact.field_path
            ref = FactRef(
                field_path=path,
                status=fact.status,
                evidence=list(fact.evidence),
            )
            if path == _YEARS_FIELD:
                parsed = _as_years(fact.value)
                if parsed is not None and years is None:
                    years, years_source = parsed, ref
            elif path == _SPONSORSHIP_FIELD:
                if isinstance(fact.value, bool) and sponsorship is None:
                    sponsorship, sponsorship_source = fact.value, ref
            elif _is_claim_field(path):
                _collect_claims(claims, path, fact.value, ref)

        return cls(
            claims=claims,
            years_of_experience=years,
            years_source=years_source,
            requires_sponsorship=sponsorship,
            sponsorship_source=sponsorship_source,
        )

    def claim_for(self, normalized: str) -> Optional[CandidateClaim]:
        """First claim whose comparison form equals ``normalized``.

        The query is normalised the same way claims are, so callers may pass
        either a requirement's ``normalized`` or the raw term.
        """
        key = normalize_text(normalized).lower()
        if not key:
            return None
        return next((claim for claim in self.claims if claim.normalized == key), None)

    def has_claim(self, normalized: str) -> bool:
        """Whether any claim matches ``normalized``."""
        return self.claim_for(normalized) is not None

    def claims_of_kind(self, kind: RequirementKind) -> list[CandidateClaim]:
        """Every claim filed under ``kind``, in fact order."""
        return [claim for claim in self.claims if claim.kind is kind]


def _as_years(value: object) -> Optional[float]:
    """The years a fact states, or ``None`` when it cannot be trusted.

    Booleans are rejected before numbers because ``True`` is an ``int`` in
    Python, and a flag landing in the years field must not become one year
    of experience. Anything outside 0–60 is treated as unusable rather than
    clamped: silently turning "300" into "60" would invent a candidate.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        years = float(value)
    elif isinstance(value, str):
        try:
            years = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if 0.0 <= years <= _MAX_YEARS:
        return years
    return None


def _is_claim_field(path: str) -> bool:
    if path in _CLAIM_FIELDS:
        return True
    if path.endswith(_CLAIM_SUFFIXES):
        return True
    return path.startswith("certifications.entries[") and path.endswith(".name")


def _texts_of(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


def _collect_claims(
    claims: list[CandidateClaim],
    path: str,
    value: object,
    ref: FactRef,
) -> None:
    """Append this fact's claims, dropping blanks and repeats within it."""
    seen: set[str] = set()
    for raw in _texts_of(value):
        text = raw.strip()
        normalized = normalize_text(text).lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        claims.append(
            CandidateClaim(text=text, kind=_kind_for(path, text), source=ref)
        )


def _kind_for(path: str, text: str) -> RequirementKind:
    """Category for one claim: the field decides when it can, else the lexicon."""
    if "certifications" in path:
        return RequirementKind.CERTIFICATION
    if path.startswith("education"):
        return RequirementKind.EDUCATION
    if path.startswith("location") or path == "preferences.desired_locations":
        return RequirementKind.LOCATION
    if path == "skills.languages":
        return RequirementKind.LANGUAGE
    if path.endswith(".employment_type"):
        return RequirementKind.EMPLOYMENT_TYPE
    if path == "preferences.remote_preference":
        return RequirementKind.WORKPLACE_TYPE
    return classify_term(text)
