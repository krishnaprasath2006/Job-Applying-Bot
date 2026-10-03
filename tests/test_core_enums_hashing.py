"""Tests for the closed enums, hashing, and date parsing."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from core.enums import (
    EvidenceSourceType,
    FactStatus,
    ResumeFileType,
    SectionType,
    ValidationCode,
)
from core.errors import ConfigurationError
from core.hashing import (
    ensure_utc,
    parse_iso_date,
    parse_iso_datetime,
    sha256_bytes,
    sha256_text,
    short_hash,
    utc_now,
)
from safety.policies import Action


class TestClosedEnums:
    def test_unknown_value_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            FactStatus("NOT_A_STATUS")

    def test_case_and_separator_variations_are_accepted(self) -> None:
        assert SectionType("summary") is SectionType.SUMMARY
        assert SectionType("  Summary  ") is SectionType.SUMMARY
        assert FactStatus("inferred") is FactStatus.INFERRED
        assert ResumeFileType("pdf") is ResumeFileType.PDF

    def test_still_closed_to_nonsense(self) -> None:
        for bad in ["not_a_section", "", "12", "summaries"]:
            with pytest.raises(ValueError):
                SectionType(bad)

    def test_empty_string_is_not_a_meaningful_value(self) -> None:
        with pytest.raises(ValueError):
            SectionType("")

    def test_enums_serialize_as_plain_strings(self) -> None:
        assert FactStatus.VERIFIED.value == "VERIFIED"
        assert str(SectionType.SKILLS) == "SKILLS"

    def test_action_table_is_closed(self) -> None:
        with pytest.raises(ValueError):
            Action("delete_everything")

    def test_evidence_source_types_are_limited(self) -> None:
        expected = {"RESUME", "PROFILE", "USER_INPUT", "JOB_DESCRIPTION", "VERIFIED_ANSWER", "SYSTEM"}
        assert {s.name for s in EvidenceSourceType} == expected

    def test_resume_file_types_are_limited(self) -> None:
        assert {f.name for f in ResumeFileType} == {"PDF", "DOCX", "TXT", "MD", "UNKNOWN"}

    def test_validation_codes_exist(self) -> None:
        assert len(list(ValidationCode)) > 10


class TestHashing:
    def test_sha256_text_is_stable_and_hex(self) -> None:
        a = sha256_text("SYNTHETIC TEST DATA ONLY")
        b = sha256_text("SYNTHETIC TEST DATA ONLY")
        assert a == b
        assert len(a) == 64
        assert all(c in "0123456789abcdef" for c in a)

    def test_different_input_differs(self) -> None:
        assert sha256_text("a") != sha256_text("b")

    def test_unicode_is_hashed_as_utf8(self) -> None:
        assert sha256_text("café") == sha256_bytes("café".encode("utf-8"))

    def test_short_hash_embeds_the_full_digest_prefix(self) -> None:
        # short_hash returns "<slug>-<digest prefix>", so the digest prefix is
        # at the end rather than the start.
        full = sha256_text("SYNTHETIC")
        assert full[:12] in short_hash("SYNTHETIC")
        assert short_hash("SYNTHETIC").startswith("synthetic-")

    def test_utc_now_is_timezone_aware(self) -> None:
        now = utc_now()
        assert now.tzinfo is not None
        assert now.utcoffset() == timezone.utc.utcoffset(None)


class TestDateParsing:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("2026-03-02", date(2026, 3, 2)),
            ("2026-03", date(2026, 3, 1)),
            ("2026", date(2026, 1, 1)),
            ("03/2026", date(2026, 3, 1)),
            ("Mar 2026", date(2026, 3, 1)),
        ],
    )
    def test_supported_formats(self, text: str, expected: date) -> None:
        assert parse_iso_date(text) == expected

    def test_iso_datetime_with_z_suffix(self) -> None:
        parsed = parse_iso_datetime("2026-03-02T10:30:00Z")
        assert parsed == datetime(2026, 3, 2, 10, 30, tzinfo=timezone.utc)

    def test_naive_datetime_is_assumed_utc(self) -> None:
        assert parse_iso_datetime("2026-03-02T10:30:00") == datetime(
            2026, 3, 2, 10, 30, tzinfo=timezone.utc
        )

    def test_unparseable_returns_none_rather_than_guessing(self) -> None:
        assert parse_iso_date("sometime last year") is None
        assert parse_iso_datetime("not a date") is None

    def test_none_and_blank_are_none(self) -> None:
        assert parse_iso_date(None) is None
        assert parse_iso_date("   ") is None

    def test_numeric_dates_are_rejected_as_ambiguous(self) -> None:
        # 20260302 could be a YYYYMMDD stamp or a serial number. Refusing is
        # the safe answer; guessing would silently corrupt a date range.
        with pytest.raises(ConfigurationError):
            parse_iso_date(20260302)

    def test_ensure_utc_attaches_timezone(self) -> None:
        naive = datetime(2026, 1, 1, 12, 0)
        assert ensure_utc(naive).tzinfo is timezone.utc

    def test_ensure_utc_converts_aware_datetime(self) -> None:
        from datetime import timedelta

        offset = timezone(timedelta(hours=5, minutes=30))
        aware = datetime(2026, 1, 1, 12, 0, tzinfo=offset)
        assert ensure_utc(aware) == datetime(2026, 1, 1, 6, 30, tzinfo=timezone.utc)
