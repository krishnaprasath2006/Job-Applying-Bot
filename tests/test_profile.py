"""Tests for the profile: defaults, the three-state rule, and the validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.enums import EvidenceSourceType, FactStatus, ValidationCode, ValidationSeverity
from core.evidence import Evidence, FactValue
from candidate_profile.models import CandidateProfile, build_empty_profile
from candidate_profile.validator import REQUIRED_FOR_APPLICATION, CandidateProfileValidator

_EVIDENCE = [
    Evidence(
        source_type=EvidenceSourceType.USER_INPUT,
        source_id="test-session",
        source_location="manual entry",
        text_excerpt="SYNTHETIC TEST DATA",
    )
]

# Exactly the eight fields an application cannot proceed without.
_REQUIRED = {
    "identity.full_name",
    "contact.email",
    "contact.phone",
    "location.current_country",
    "experience.total_years_experience",
    "education.highest_level",
    "authorization.requires_sponsorship",
    "availability.available_from",
}


def fact_of(profile: CandidateProfile, path: str) -> FactValue:
    """Look up one FactValue by dotted path."""
    for candidate_path, value, _section in profile.iter_fact_values():
        if candidate_path == path:
            return value
    raise AssertionError(f"{path} is not a field on the profile")


def value_of(profile: CandidateProfile, path: str):
    return fact_of(profile, path).value


def build(**fields) -> CandidateProfile:
    """A profile with the given fields set to VERIFIED with evidence."""
    profile = build_empty_profile("test")
    for path, value in fields.items():
        profile = profile.with_update(
            path, value, status=FactStatus.VERIFIED, evidence=list(_EVIDENCE)
        )
    return profile


def complete_profile() -> CandidateProfile:
    return build(
        **{
            "identity.full_name": "SYNTHETIC NAME",
            "contact.email": "synthetic@example.invalid",
            "contact.phone": "+911234567890",
            "location.current_country": "India",
            "experience.total_years_experience": 5,
            "education.highest_level": "Masters",
            "authorization.requires_sponsorship": False,
            "availability.available_from": "2026-04-01",
        }
    )


class TestDefaults:
    def test_new_profile_is_entirely_unknown(self) -> None:
        p = build_empty_profile("test")
        assert len(p.unknown_fields()) == p.fact_count()
        assert p.verified_fields() == []
        assert p.inferred_fields() == []

    def test_no_fact_carries_a_value(self) -> None:
        p = build_empty_profile("test")
        assert all(f.value is None for f in p.to_facts())
        assert p.completeness() == 0.0

    def test_empty_profile_is_incomplete_but_not_broken(self) -> None:
        # An empty profile is a legitimate starting state. It is incomplete,
        # which is a different thing from invalid.
        report = CandidateProfileValidator().validate(build_empty_profile("test"))
        assert report.is_valid is False
        assert report.completeness == 0.0

    def test_required_set_is_the_documented_eight(self) -> None:
        assert set(REQUIRED_FOR_APPLICATION) == _REQUIRED

    def test_every_required_field_is_flagged_when_unknown(self) -> None:
        report = CandidateProfileValidator().validate(build_empty_profile("test"))
        flagged = {
            i.field_path
            for i in report.issues
            if i.code == ValidationCode.UNKNOWN_VALUE_FOR_REQUIRED_FIELD
        }
        assert flagged == _REQUIRED

    def test_profile_has_44_fields(self) -> None:
        assert build_empty_profile("test").fact_count() == 44


class TestUpdates:
    def test_setting_a_value_with_no_status_gives_inferred_never_verified(self) -> None:
        p = build_empty_profile("test").with_update("identity.full_name", "SYNTHETIC NAME")
        assert fact_of(p, "identity.full_name").status is FactStatus.INFERRED
        assert fact_of(p, "identity.full_name").is_application_safe is False

    def test_explicit_verified_records_source_and_timestamp(self) -> None:
        p = build_empty_profile("test").with_update(
            "identity.full_name",
            "SYNTHETIC NAME",
            status=FactStatus.VERIFIED,
            evidence=list(_EVIDENCE),
        )
        fv = fact_of(p, "identity.full_name")
        assert fv.status is FactStatus.VERIFIED
        assert fv.verified_at is not None
        assert fv.source is EvidenceSourceType.USER_INPUT
        assert fv.source_id == "test-session"
        assert fv.is_application_safe is True

    def test_update_is_immutable(self) -> None:
        p = build_empty_profile("test")
        q = p.with_update("identity.full_name", "SYNTHETIC NAME")
        assert value_of(p, "identity.full_name") is None
        assert value_of(q, "identity.full_name") == "SYNTHETIC NAME"

    def test_unknown_field_is_refused_not_silently_created(self) -> None:
        p = build_empty_profile("test")
        with pytest.raises(AttributeError):
            p.with_update("identity.does_not_exist", "value")

    def test_clearing_a_value_returns_it_to_unknown_and_drops_stale_metadata(self) -> None:
        p = build_empty_profile("test").with_update(
            "identity.full_name",
            "SYNTHETIC NAME",
            status=FactStatus.VERIFIED,
            evidence=list(_EVIDENCE),
        )
        cleared = fact_of(p.with_update("identity.full_name", None), "identity.full_name")
        assert cleared.status is FactStatus.UNKNOWN
        assert cleared.value is None
        # A verified_at left behind on an empty field would misreport it.
        assert cleared.verified_at is None
        assert cleared.evidence == []

    def test_cannot_promote_to_verified_without_a_source(self) -> None:
        p = build_empty_profile("test")
        with pytest.raises(ValueError, match="source"):
            p.with_update("identity.full_name", "SYNTHETIC", status=FactStatus.VERIFIED)

    def test_a_real_change_bumps_version_and_timestamp(self) -> None:
        p = build_empty_profile("test")
        q = p.with_update("identity.full_name", "SYNTHETIC NAME")
        assert q.version == p.version + 1
        assert q.updated_at >= p.updated_at

    def test_repeating_the_same_value_is_not_an_edit(self) -> None:
        p = build_empty_profile("test").with_update("identity.full_name", "SYNTHETIC NAME")
        again = p.with_update("identity.full_name", "SYNTHETIC NAME")
        assert again.version == p.version

    def test_verified_value_rewritten_as_verified_is_an_edit_only_when_evidence_grows(self) -> None:
        p = build_empty_profile("test").with_update(
            "identity.full_name",
            "SYNTHETIC NAME",
            status=FactStatus.VERIFIED,
            evidence=list(_EVIDENCE),
        )
        assert p.with_update("identity.full_name", "SYNTHETIC NAME").version == p.version
        assert (
            p.with_update(
                "identity.full_name",
                "SYNTHETIC NAME",
                status=FactStatus.VERIFIED,
                evidence=list(_EVIDENCE) + list(_EVIDENCE),
            ).version
            == p.version + 1
        )


class TestPersistence:
    def test_round_trip_preserves_every_field(self, tmp_path: Path) -> None:
        p = complete_profile()
        path = tmp_path / "candidate_profile.json"
        p.save(path)
        loaded = CandidateProfile.load(path)
        assert loaded.fact_count() == p.fact_count()
        assert set(loaded.verified_fields()) == set(p.verified_fields())
        assert value_of(loaded, "identity.full_name") == "SYNTHETIC NAME"

    def test_round_trip_preserves_evidence_and_version(self, tmp_path: Path) -> None:
        p = complete_profile()
        path = tmp_path / "p.json"
        p.save(path)
        loaded = CandidateProfile.load(path)
        assert loaded.version == p.version
        assert fact_of(loaded, "identity.full_name").evidence[0].source_id == "test-session"

    def test_round_trip_preserves_unknown(self, tmp_path: Path) -> None:
        p = build_empty_profile("test")
        path = tmp_path / "p.json"
        p.save(path)
        loaded = CandidateProfile.load(path)
        assert len(loaded.unknown_fields()) == p.fact_count()

    def test_missing_file_is_an_error_not_an_empty_profile(self, tmp_path: Path) -> None:
        # Falling back to an empty profile would silently discard real data.
        with pytest.raises(FileNotFoundError):
            CandidateProfile.load(tmp_path / "absent.json")

    def test_corrupt_file_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "p.json"
        path.write_text("{ not json", encoding="utf-8")
        with pytest.raises(ValueError):
            CandidateProfile.load(path)

    def test_committed_example_is_valid_and_mostly_unknown(self, project_root: Path) -> None:
        example = project_root / "data" / "profile" / "candidate_profile.example.json"
        p = CandidateProfile.load(example)
        assert p.fact_count() == 44
        # It exists to demonstrate the shape, so two fields are filled in.
        assert len(p.verified_fields()) == 2
        assert len(p.unknown_fields()) == 42


class TestValidator:
    def test_a_complete_profile_is_valid(self) -> None:
        report = CandidateProfileValidator().validate(complete_profile())
        assert report.is_valid is True, [i.message for i in report.issues]

    def test_completeness_counts_only_application_safe_fields(self) -> None:
        # Eight of forty-four fields are set, and completeness measures how much
        # of the profile could be typed into a real form, not how many fields
        # are merely populated.
        profile = complete_profile()
        assert len(profile.verified_fields()) == 8
        assert profile.completeness() == pytest.approx(8 / 44, abs=1e-4)

    def test_inferred_values_do_not_count_towards_completeness(self) -> None:
        p = build_empty_profile("test").with_update("identity.full_name", "SYNTHETIC")
        assert p.completeness() == 0.0

    def test_bad_email_is_an_error(self) -> None:
        report = CandidateProfileValidator().validate(build(**{"contact.email": "not-an-email"}))
        assert any(i.code == ValidationCode.MALFORMED_EMAIL for i in report.issues)

    def test_bad_url_is_an_error(self) -> None:
        # A javascript: scheme in a link field would be injected into an
        # outgoing application email, so it must not be accepted.
        report = CandidateProfileValidator().validate(
            build(**{"contact.linkedin_url": "javascript:alert(1)"})
        )
        assert any(i.code == ValidationCode.INVALID_URL for i in report.issues)

    def test_good_url_is_accepted(self) -> None:
        report = CandidateProfileValidator().validate(
            build(**{"contact.linkedin_url": "https://www.example.invalid/in/synthetic"})
        )
        assert not any(i.code == ValidationCode.INVALID_URL for i in report.issues)

    def test_end_date_before_start_date_is_an_error(self) -> None:
        report = CandidateProfileValidator().validate(
            build(**{"identity.date_of_birth": "not-a-date"})
        )
        assert any(i.code == ValidationCode.INVALID_DATE for i in report.issues)

    def test_inferred_value_for_a_required_field_is_an_error(self) -> None:
        # An INFERRED value cannot fill a required field, so the report must
        # distinguish "we do not know" from "something guessed".
        p = build_empty_profile("test").with_update("identity.full_name", "SYNTHETIC")
        report = CandidateProfileValidator().validate(p)
        codes = {i.code for i in report.issues}
        assert ValidationCode.UNKNOWN_VALUE_FOR_REQUIRED_FIELD in codes

    def test_maximum_salary_below_minimum_is_a_contradiction(self) -> None:
        report = CandidateProfileValidator().validate(
            build(**{"preferences.minimum_salary": 500000, "preferences.maximum_salary": 100000})
        )
        assert any(i.code == ValidationCode.CONTRADICTORY_VALUES for i in report.issues)

    def test_salary_range_within_bounds_is_fine(self) -> None:
        report = CandidateProfileValidator().validate(
            build(**{"preferences.minimum_salary": 100000, "preferences.maximum_salary": 500000})
        )
        assert not any(i.code == ValidationCode.CONTRADICTORY_VALUES for i in report.issues)

    def test_sponsorship_contradiction_is_an_error(self) -> None:
        report = CandidateProfileValidator().validate(
            build(
                **{
                    "authorization.requires_sponsorship": False,
                    "authorization.visa_status": "no sponsorship required",
                }
            )
        )
        assert any(i.code == ValidationCode.CONTRADICTORY_VALUES for i in report.issues)

    def test_relocation_contradiction_is_an_error(self) -> None:
        report = CandidateProfileValidator().validate(
            build(
                **{
                    "preferences.willing_to_relocate": False,
                    "location.willing_to_relocate": True,
                }
            )
        )
        assert any(i.code == ValidationCode.CONTRADICTORY_VALUES for i in report.issues)

    def test_duplicate_skill_across_lists_is_reported(self) -> None:
        report = CandidateProfileValidator().validate(
            build(**{"skills.proficient": ["Python"], "skills.expert": ["Python"]})
        )
        assert any(i.code == ValidationCode.DUPLICATE_SKILL for i in report.issues)

    def test_validation_never_mutates_the_profile(self) -> None:
        p = build_empty_profile("test")
        before = p.model_dump(mode="json")
        CandidateProfileValidator().validate(p)
        assert p.model_dump(mode="json") == before

    def test_issues_carry_codes_and_severities(self) -> None:
        report = CandidateProfileValidator().validate(build_empty_profile("test"))
        assert report.issues
        assert all(isinstance(i.code, ValidationCode) for i in report.issues)
        assert all(isinstance(i.severity, ValidationSeverity) for i in report.issues)

    def test_raise_if_invalid_refuses_an_incomplete_profile(self) -> None:
        from core.errors import ProfileValidationError

        report = CandidateProfileValidator().validate(build_empty_profile("test"))
        with pytest.raises(ProfileValidationError):
            report.raise_if_invalid()

    def test_raise_if_invalid_passes_a_complete_profile(self) -> None:
        CandidateProfileValidator().validate(complete_profile()).raise_if_invalid()
