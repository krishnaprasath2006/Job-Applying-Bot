"""Tests for the evidence chain: the rule that every value says where it came from."""

from __future__ import annotations

import pytest

from core.enums import EvidenceSourceType, FactStatus
from core.errors import MissingEvidenceError
from core.evidence import Evidence, Fact, FactValue


class TestEvidence:
    def test_document_sources_require_a_source_id(self) -> None:
        with pytest.raises(ValueError):
            Evidence(source_type=EvidenceSourceType.RESUME, source_id=None)

    def test_document_sources_with_id_are_valid(self) -> None:
        ev = Evidence(source_type=EvidenceSourceType.RESUME, source_id="resume-abc")
        assert ev.source_type is EvidenceSourceType.RESUME

    def test_user_input_does_not_require_a_source_id(self) -> None:
        # A person answering in a session is self-describing.
        ev = Evidence(source_type=EvidenceSourceType.USER_INPUT)
        assert ev.source_type is EvidenceSourceType.USER_INPUT

    def test_excerpt_is_truncated_defensively(self) -> None:
        ev = Evidence(
            source_type=EvidenceSourceType.RESUME,
            source_id="resume-abc",
            text_excerpt="x" * 5000,
        )
        # A whole resume must never be stored here, but an over-long excerpt is
        # truncated rather than rejected, so parsing cannot fail on it.
        assert ev.text_excerpt is not None
        assert ev.text_excerpt.endswith("...[truncated]")
        assert len(ev.text_excerpt) < 5000

    def test_blank_excerpt_becomes_none(self) -> None:
        assert Evidence(source_type=EvidenceSourceType.SYSTEM, text_excerpt="   ").text_excerpt is None

    def test_confidence_must_be_a_probability(self) -> None:
        with pytest.raises(ValueError):
            Evidence(source_type=EvidenceSourceType.SYSTEM, confidence=1.5)
        with pytest.raises(ValueError):
            Evidence(source_type=EvidenceSourceType.SYSTEM, confidence=-0.1)

    def test_evidence_is_immutable(self) -> None:
        ev = Evidence(source_type=EvidenceSourceType.SYSTEM)
        with pytest.raises(ValueError):
            ev.confidence = 0.5  # type: ignore[misc]


class TestFactValue:
    def test_unknown_cannot_carry_a_value(self) -> None:
        with pytest.raises(ValueError, match="UNKNOWN"):
            FactValue(field_path="x", value="something", status=FactStatus.UNKNOWN)

    def test_verified_must_carry_a_value(self) -> None:
        with pytest.raises(ValueError):
            FactValue(
                field_path="x",
                value=None,
                status=FactStatus.VERIFIED,
                source=EvidenceSourceType.USER_INPUT,
            )

    def test_verified_must_name_its_source(self) -> None:
        with pytest.raises(ValueError, match="source"):
            FactValue(field_path="x", value="something", status=FactStatus.VERIFIED)

    def test_empty_default_is_unknown_and_empty(self) -> None:
        fv = FactValue()
        assert fv.status is FactStatus.UNKNOWN
        assert fv.value is None
        assert not fv.is_application_safe

    def test_only_verified_is_application_safe(self) -> None:
        base = dict(field_path="x", value="something", source=EvidenceSourceType.USER_INPUT)
        assert FactValue(status=FactStatus.VERIFIED, **base).is_application_safe
        assert not FactValue(status=FactStatus.INFERRED, **base).is_application_safe


class TestFact:
    def _fact(self, **kwargs) -> Fact:
        base = dict(field_path="identity.full_name", value="SYNTHETIC NAME")
        base.update(kwargs)
        return Fact(**base)

    def test_unknown_fact_is_not_application_safe(self) -> None:
        assert not Fact(field_path="x").is_application_safe

    def test_inferred_is_not_application_safe(self) -> None:
        assert not self._fact(status=FactStatus.INFERRED).is_application_safe

    def test_verified_without_evidence_is_not_application_safe(self) -> None:
        fact = self._fact(status=FactStatus.VERIFIED)
        assert not fact.is_application_safe

    def test_verified_with_evidence_is_application_safe(self) -> None:
        fact = self._fact(
            status=FactStatus.VERIFIED,
            evidence=[Evidence(source_type=EvidenceSourceType.USER_INPUT, source_id="s")],
        )
        assert fact.is_application_safe

    def test_assert_application_safe_refuses_unknown(self) -> None:
        with pytest.raises(MissingEvidenceError):
            Fact(field_path="x").assert_application_safe()

    def test_assert_application_safe_refuses_inferred(self) -> None:
        with pytest.raises(MissingEvidenceError, match="VERIFIED"):
            self._fact(status=FactStatus.INFERRED).assert_application_safe()

    def test_assert_application_safe_refuses_verified_without_evidence(self) -> None:
        with pytest.raises(MissingEvidenceError, match="evidence"):
            self._fact(status=FactStatus.VERIFIED).assert_application_safe()

    def test_assert_application_safe_accepts_a_complete_verified_fact(self) -> None:
        self._fact(
            status=FactStatus.VERIFIED,
            evidence=[Evidence(source_type=EvidenceSourceType.USER_INPUT, source_id="s")],
        ).assert_application_safe()

    def test_extra_fields_are_refused(self) -> None:
        with pytest.raises(ValueError):
            FactValue(field_path="x", value=None, made_up_field="oops")  # type: ignore[call-arg]
