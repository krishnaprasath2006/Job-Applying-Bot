"""Candidate evidence: the person side of matching.

The fixture candidate is the same synthetic profile Phase 2 ships — years,
stack, sponsorship, education — read straight from its facts so these tests
exercise the real bridge (facts in, claims out) rather than a hand-made
shape. The unit cases cover what must *not* become a claim: blanks, booleans
in the years field, out-of-range numbers, and facts the profile still calls
unknown.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.enums import EvidenceSourceType, FactStatus
from core.evidence import Evidence, Fact
from jobs.candidate import CandidateClaim, CandidateEvidence, FactRef
from jobs.models import RequirementKind
from profile.models import build_empty_profile


def facts_from_fixture(payload: dict) -> list[Fact]:
    """The fixture's fact list as :class:`Fact` records, evidence rebuilt."""
    facts: list[Fact] = []
    for item in payload["facts"]:
        evidence = [
            Evidence(
                source_type=EvidenceSourceType(entry["source_type"]),
                source_id=entry.get("source_id"),
                source_location=entry.get("source_location"),
                text_excerpt=entry.get("text_excerpt"),
                confidence=entry.get("confidence", 1.0),
            )
            for entry in item.get("evidence", [])
        ]
        facts.append(
            Fact(
                field_path=item["field_path"],
                value=item["value"],
                status=FactStatus(item["status"]),
                evidence=evidence,
            )
        )
    return facts


def a_fact(
    path: str,
    value: object,
    status: FactStatus = FactStatus.VERIFIED,
    excerpt: str | None = None,
) -> Fact:
    evidence = (
        [
            Evidence(
                source_type=EvidenceSourceType.USER_INPUT,
                source_id="test",
                text_excerpt=excerpt or str(path),
            )
        ]
        if value is not None
        else []
    )
    return Fact(field_path=path, value=value, status=status, evidence=evidence)


# ---------------------------------------------------------------------------
# Reading the shipped fixture
# ---------------------------------------------------------------------------
class TestTheFixtureCandidate:
    @pytest.fixture()
    def evidence(self, synthetic_candidate: dict) -> CandidateEvidence:
        return CandidateEvidence.from_facts(facts_from_fixture(synthetic_candidate))

    def test_the_stack_is_a_set_of_claims(self, evidence: CandidateEvidence) -> None:
        names = {claim.normalized for claim in evidence.claims}
        assert {"python", "sql", "pandas"} <= names

    def test_years_are_read_from_the_resume_fact(
        self, evidence: CandidateEvidence
    ) -> None:
        assert evidence.years_of_experience == 3.0
        assert evidence.years_source is not None
        assert evidence.years_source.field_path == "experience.total_years_experience"
        assert evidence.years_source.status is FactStatus.VERIFIED
        assert evidence.years_source.evidence[0].source_type is EvidenceSourceType.RESUME

    def test_sponsorship_is_recorded_as_said_not_guessed(
        self, evidence: CandidateEvidence
    ) -> None:
        assert evidence.requires_sponsorship is False
        assert evidence.sponsorship_source is not None
        assert evidence.sponsorship_source.field_path == (
            "authorization.requires_sponsorship"
        )

    def test_every_claim_keeps_the_evidence_it_came_with(
        self, evidence: CandidateEvidence
    ) -> None:
        assert evidence.claims
        for claim in evidence.claims:
            assert claim.source.field_path
            assert claim.source.status is FactStatus.VERIFIED
            assert claim.source.evidence
            assert claim.source.evidence[0].text_excerpt

    def test_education_and_location_land_in_their_categories(
        self, evidence: CandidateEvidence
    ) -> None:
        assert evidence.claim_for("bachelors").kind is RequirementKind.EDUCATION
        assert evidence.claim_for("testville").kind is RequirementKind.LOCATION


# ---------------------------------------------------------------------------
# What does not become a claim or a scalar
# ---------------------------------------------------------------------------
class TestRefusals:
    def test_an_empty_profile_is_empty_evidence(self) -> None:
        evidence = CandidateEvidence.from_facts(build_empty_profile("candidate").to_facts())
        assert evidence.claims == []
        assert evidence.years_of_experience is None
        assert evidence.requires_sponsorship is None

    def test_a_fact_with_no_value_contributes_nothing(self) -> None:
        evidence = CandidateEvidence.from_facts(
            [a_fact("skills.proficient", None), a_fact("experience.total_years_experience", None)]
        )
        assert evidence.claims == []
        assert evidence.years_of_experience is None
        assert evidence.years_source is None

    def test_an_unknown_fact_with_a_value_is_not_evidence(self) -> None:
        # A value under UNKNOWN would make the profile contradict itself;
        # the reader sides with the status, not the stray value.
        evidence = CandidateEvidence.from_facts(
            [
                Fact(
                    field_path="skills.proficient",
                    value=["Python"],
                    status=FactStatus.UNKNOWN,
                )
            ]
        )
        assert evidence.claims == []

    def test_blank_and_non_string_list_entries_are_dropped(self) -> None:
        evidence = CandidateEvidence.from_facts(
            [a_fact("skills.proficient", ["", "   ", "Python", 42, None])]
        )
        assert [claim.text for claim in evidence.claims] == ["Python"]

    def test_a_non_list_skill_value_yields_nothing(self) -> None:
        evidence = CandidateEvidence.from_facts([a_fact("skills.proficient", 42)])
        assert evidence.claims == []

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (True, None),
            (75, None),
            (-1, None),
            ("about three", None),
            (None, None),
        ],
    )
    def test_an_unusable_years_value_is_refused(
        self, value: object, expected: float | None
    ) -> None:
        evidence = CandidateEvidence.from_facts(
            [a_fact("experience.total_years_experience", value)]
        )
        assert evidence.years_of_experience == expected
        assert evidence.years_source is None

    @pytest.mark.parametrize("value", ["no", 0, 1, "yes"])
    def test_a_non_boolean_sponsorship_value_is_refused(
        self, value: object
    ) -> None:
        evidence = CandidateEvidence.from_facts(
            [a_fact("authorization.requires_sponsorship", value)]
        )
        assert evidence.requires_sponsorship is None
        assert evidence.sponsorship_source is None

    def test_the_first_usable_years_fact_wins(self) -> None:
        evidence = CandidateEvidence.from_facts(
            [
                a_fact("experience.total_years_experience", 3),
                a_fact("experience.total_years_experience", 5),
            ]
        )
        assert evidence.years_of_experience == 3.0

    def test_a_numeric_string_is_accepted_as_years(self) -> None:
        evidence = CandidateEvidence.from_facts(
            [a_fact("experience.total_years_experience", "4")]
        )
        assert evidence.years_of_experience == 4.0

    def test_repeats_within_one_fact_become_one_claim(self) -> None:
        evidence = CandidateEvidence.from_facts(
            [a_fact("skills.proficient", ["Python", "python", " Python "])]
        )
        assert len(evidence.claims) == 1
        assert evidence.claims[0].text == "Python"

    def test_the_same_skill_from_two_fields_is_kept_twice(self) -> None:
        evidence = CandidateEvidence.from_facts(
            [
                a_fact("skills.proficient", ["Python"]),
                a_fact("experience.entries[0].technologies", ["Python"]),
            ]
        )
        matches = [claim for claim in evidence.claims if claim.normalized == "python"]
        assert len(matches) == 2
        assert {claim.source.field_path for claim in matches} == {
            "skills.proficient",
            "experience.entries[0].technologies",
        }


# ---------------------------------------------------------------------------
# Where each claim is filed
# ---------------------------------------------------------------------------
class TestCategories:
    @pytest.mark.parametrize(
        ("path", "value", "kind"),
        [
            ("skills.proficient", ["Python"], RequirementKind.PROGRAMMING_LANGUAGE),
            ("skills.languages", ["French"], RequirementKind.LANGUAGE),
            ("education.highest_level", "Bachelors", RequirementKind.EDUCATION),
            (
                "education.entries[0].degree",
                "BSc Computer Science",
                RequirementKind.EDUCATION,
            ),
            (
                "certifications.entries[0].name",
                "AWS Certified Solutions Architect",
                RequirementKind.CERTIFICATION,
            ),
            ("location.current_city", "Testville", RequirementKind.LOCATION),
            ("location.preferred_locations", ["Remote"], RequirementKind.LOCATION),
            (
                "experience.entries[0].technologies",
                ["Django"],
                RequirementKind.FRAMEWORK,
            ),
            (
                "experience.entries[0].employment_type",
                "Full-time",
                RequirementKind.EMPLOYMENT_TYPE,
            ),
            (
                "preferences.remote_preference",
                "Remote",
                RequirementKind.WORKPLACE_TYPE,
            ),
            ("skills.proficient", ["Nonexistent-Skill-Zzz"], RequirementKind.OTHER),
        ],
    )
    def test_each_field_lands_in_the_taxonomy(
        self, path: str, value: object, kind: RequirementKind
    ) -> None:
        evidence = CandidateEvidence.from_facts([a_fact(path, value)])
        assert [claim.kind for claim in evidence.claims] == [kind]

    def test_an_inferred_claim_stays_labelled_inferred(self) -> None:
        evidence = CandidateEvidence.from_facts(
            [a_fact("skills.proficient", ["Python"], status=FactStatus.INFERRED)]
        )
        assert evidence.claims[0].source.status is FactStatus.INFERRED

    def test_the_comparison_form_is_normalised_text(self) -> None:
        evidence = CandidateEvidence.from_facts(
            [a_fact("skills.proficient", ["  Fast   API  "])]
        )
        claim = evidence.claims[0]
        assert claim.text == "Fast   API"
        assert claim.normalized == "fast api"


# ---------------------------------------------------------------------------
# Querying the evidence
# ---------------------------------------------------------------------------
class TestQueries:
    @pytest.fixture()
    def evidence(self) -> CandidateEvidence:
        return CandidateEvidence.from_facts(
            [
                a_fact("skills.proficient", ["Python", "SQL"]),
                a_fact("skills.languages", ["French"]),
                a_fact("experience.total_years_experience", 3),
            ]
        )

    def test_a_claim_is_found_regardless_of_how_it_is_spelled(
        self, evidence: CandidateEvidence
    ) -> None:
        assert evidence.claim_for("PYTHON") is not None
        assert evidence.has_claim("python")
        assert not evidence.has_claim("rust")

    def test_an_empty_query_matches_nothing(self, evidence: CandidateEvidence) -> None:
        assert evidence.claim_for("") is None

    def test_claims_of_kind_only_return_that_kind(
        self, evidence: CandidateEvidence
    ) -> None:
        languages = evidence.claims_of_kind(RequirementKind.LANGUAGE)
        assert [claim.text for claim in languages] == ["French"]
        assert evidence.claims_of_kind(RequirementKind.CLOUD) == []

    def test_a_found_claim_points_back_at_its_fact(
        self, evidence: CandidateEvidence
    ) -> None:
        claim = evidence.claim_for("python")
        assert claim is not None
        assert claim.source.field_path == "skills.proficient"
        assert claim.source.evidence[0].text_excerpt is not None


# ---------------------------------------------------------------------------
# The models themselves
# ---------------------------------------------------------------------------
class TestModels:
    def test_the_comparison_form_is_filled_in_when_it_is_absent(self) -> None:
        assert CandidateClaim(text="Python").normalized == "python"

    def test_an_explicit_comparison_form_is_kept(self) -> None:
        claim = CandidateClaim(text="Python", normalized="kept")
        assert claim.normalized == "kept"

    def test_an_unknown_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            CandidateClaim(text="Python", bogus=True)  # type: ignore[call-arg]

    def test_a_ref_is_not_a_dumping_ground(self) -> None:
        with pytest.raises(ValidationError):
            FactRef(field_path="skills.proficient", note="hi")  # type: ignore[call-arg]

    def test_years_outside_the_model_range_are_refused(self) -> None:
        with pytest.raises(ValidationError):
            CandidateEvidence(years_of_experience=61.0)

    def test_the_evidence_survives_a_round_trip(self) -> None:
        original = CandidateEvidence.from_facts(
            [
                a_fact("skills.proficient", ["Python"]),
                a_fact("experience.total_years_experience", 3),
                a_fact("authorization.requires_sponsorship", False),
            ]
        )
        assert CandidateEvidence.model_validate(original.model_dump()) == original


# ---------------------------------------------------------------------------
# The bridge from a stored profile
# ---------------------------------------------------------------------------
class TestProfileBridge:
    def test_a_settled_profile_field_becomes_a_claim_with_evidence(self) -> None:
        profile = build_empty_profile("candidate").with_update(
            "skills.proficient",
            ["Python", "SQL"],
            status=FactStatus.VERIFIED,
            source=EvidenceSourceType.RESUME,
            source_id="resume.txt",
            evidence=[
                Evidence(
                    source_type=EvidenceSourceType.RESUME,
                    source_id="resume.txt",
                    text_excerpt="Python, SQL",
                )
            ],
        )
        evidence = CandidateEvidence.from_facts(profile.to_facts())
        claim = evidence.claim_for("python")
        assert claim is not None
        assert claim.source.status is FactStatus.VERIFIED
        assert claim.source.evidence[0].text_excerpt == "Python, SQL"

    def test_a_fresh_field_defaults_to_inferred_and_says_so(self) -> None:
        profile = build_empty_profile("candidate").with_update(
            "skills.proficient", ["Python"]
        )
        evidence = CandidateEvidence.from_facts(profile.to_facts())
        claim = evidence.claim_for("python")
        assert claim is not None
        assert claim.source.status is FactStatus.INFERRED

    def test_the_years_scalar_travels_through_the_profile(self) -> None:
        profile = build_empty_profile("candidate").with_update(
            "experience.total_years_experience",
            3,
            status=FactStatus.VERIFIED,
            source=EvidenceSourceType.RESUME,
            source_id="resume.txt",
        )
        evidence = CandidateEvidence.from_facts(profile.to_facts())
        assert evidence.years_of_experience == 3.0
        assert evidence.years_source is not None
        assert evidence.years_source.status is FactStatus.VERIFIED


# ---------------------------------------------------------------------------
# Layer boundary
# ---------------------------------------------------------------------------
class TestLayerBoundary:
    def test_candidate_evidence_depends_only_on_core_and_jobs(
        self, project_root: Path
    ) -> None:
        """One line of coupling here puts the profile layer inside matching."""
        text = (project_root / "src" / "jobs" / "candidate.py").read_text(
            encoding="utf-8"
        )
        forbidden = re.compile(
            r"^\s*(?:from|import)\s+(?:profile|database|assistant|automation|"
            r"selenium|requests|httpx)\b",
            re.MULTILINE,
        )
        assert forbidden.search(text) is None
