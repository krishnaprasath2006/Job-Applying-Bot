"""Acceptance-run tests.

The acceptance checklist is the thing that claims "this system works", so it
needs the same scrutiny as the code it exercises. The two failures these tests
exist for were both data-integrity bugs that reported PASS:

* the run swapped ``Assistant.db`` after the services were built, so synthetic
  facts were written to the real ``data/assistant.db``;
* every candidate shared one JSON path, so a run for a synthetic candidate
  read the real candidate's profile file.

A checklist that quietly touches real data is worse than one that fails.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assistant.acceptance import FIXTURES, AcceptanceRunner, run_acceptance
from assistant.app import build_assistant
from core.errors import ProfileNotFoundError
from core.settings import load_settings
from candidate_profile.models import build_empty_profile
from candidate_profile.service import ProfileService


@pytest.fixture()
def runner() -> AcceptanceRunner:
    r = AcceptanceRunner()
    try:
        yield r
    finally:
        app = r.state.get("app")
        if app is not None:
            app.db.close()
        r.cleanup()


def make_service(db, tmp_path: Path) -> ProfileService:
    """A service whose JSON copy lives in a temporary directory."""
    return ProfileService(db, storage_path=tmp_path / "candidate_profile.json")


class TestChecklistOutcome:
    def test_every_step_passes(self, runner: AcceptanceRunner) -> None:
        runner.run()
        failures = [r for r in runner.results if not r["ok"]]
        assert failures == [], failures
        assert runner.failed == 0
        assert runner.passed == 24

    def test_the_run_reports_no_submission_and_is_machine_readable(self, capsys) -> None:
        assert run_acceptance(as_json=True) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["failed"] == 0
        assert len(payload["steps"]) == 24
        # The human-readable report carries the same two promises.
        assert run_acceptance() == 0
        out = capsys.readouterr().out
        assert "no browser, no submission" in out
        assert "REAL SUBMISSION REMAINS DISABLED." in out


class TestTheRunTouchesNoRealData:
    def test_the_database_is_inside_the_sandbox(self, runner: AcceptanceRunner) -> None:
        runner.run()
        db_path = runner.state["app"].db.path.resolve()
        assert runner.tmp.resolve() in db_path.parents

    def test_every_writable_path_is_inside_the_sandbox(self, runner: AcceptanceRunner) -> None:
        runner.run()
        paths = runner.state["app"].paths
        for path in (paths.profile_dir, paths.resume_dir, paths.logs, paths.db):
            assert runner.tmp.resolve() in Path(path).resolve().parents, path

    def test_the_sandbox_profile_file_is_not_the_real_one(
        self, runner: AcceptanceRunner, project_root: Path
    ) -> None:
        runner.run()
        service = runner.state["app"].profile_service
        written = Path(service.path_for("acceptance"))
        assert runner.tmp.resolve() in written.resolve().parents
        assert project_root.resolve() not in written.resolve().parents

    def test_the_real_profile_file_is_never_rewritten(
        self, runner: AcceptanceRunner, project_root: Path
    ) -> None:
        real = project_root / "data" / "profile" / "candidate_profile.json"
        before = real.read_bytes() if real.exists() else None
        runner.run()
        assert (real.read_bytes() if real.exists() else None) == before


class TestServiceConstructionOrder:
    def test_the_database_override_is_used_by_the_services_too(self, tmp_path: Path) -> None:
        # The bug was passing the path but letting the already-built services
        # keep the configured database.
        settings = load_settings(env_file=None)
        settings = settings.model_copy(
            update={
                "application": settings.application.model_copy(
                    update={"paths_root": tmp_path, "candidate_id": "probe"}
                )
            }
        )
        target = tmp_path / "override.db"
        app = build_assistant(settings=settings, database_path=target)
        try:
            assert app.db.path.resolve() == target.resolve()
            assert app.profile_service.repository.db is app.db
            assert app.resume_service.repository.db is app.db
        finally:
            app.db.close()


class TestPerCandidateStorage:
    def test_the_default_candidate_keeps_the_documented_filename(self, db, tmp_path: Path) -> None:
        service = make_service(db, tmp_path)
        assert service.path_for("primary") == tmp_path / "candidate_profile.json"

    def test_another_candidate_gets_its_own_file(self, db, tmp_path: Path) -> None:
        service = make_service(db, tmp_path)
        assert service.path_for("acceptance") == tmp_path / "acceptance.json"

    def test_two_candidates_do_not_share_a_file(self, db, tmp_path: Path) -> None:
        service = make_service(db, tmp_path)
        assert service.path_for("primary") != service.path_for("acceptance")

    def test_writing_one_candidate_does_not_create_the_other(self, db, tmp_path: Path) -> None:
        service = make_service(db, tmp_path)
        service.create_profile("acceptance", persist_json=True)
        assert (tmp_path / "acceptance.json").exists()
        assert not (tmp_path / "candidate_profile.json").exists()

    def test_another_candidates_file_is_not_returned(self, db, tmp_path: Path) -> None:
        service = make_service(db, tmp_path)
        service.create_profile("primary", persist_json=True)
        service.create_profile("acceptance", persist_json=True)
        loaded = service.load_profile("acceptance")
        assert loaded.candidate_id == "acceptance"

    def test_a_file_naming_a_different_candidate_is_refused(self, db, tmp_path: Path) -> None:
        # A renamed or copied file must not hand back the wrong person.
        service = make_service(db, tmp_path)
        build_empty_profile("someone-else").save(tmp_path / "candidate_profile.json")
        service.create_profile("primary", persist_json=False)
        with pytest.raises(ProfileNotFoundError):
            service.load_profile("primary")

    def test_no_storage_configured_means_no_paths(self, db) -> None:
        assert ProfileService(db).path_for("primary") is None


class TestDatabaseRebuild:
    def test_a_profile_can_be_rebuilt_without_its_json_file(self, db, tmp_path: Path) -> None:
        from core.enums import EvidenceSourceType, FactStatus

        service = make_service(db, tmp_path)
        service.create_profile("rebuild", persist_json=True)
        service.update_fact(
            "identity.full_name",
            "Synthetic Test Candidate",
            status=FactStatus.VERIFIED,
            source=EvidenceSourceType.USER_INPUT,
            source_id="tests/fixtures/synthetic_candidate.json",
            candidate_id="rebuild",
        )
        (tmp_path / "rebuild.json").unlink()
        rebuilt = service.load_profile_from_database("rebuild")
        assert rebuilt.candidate_id == "rebuild"
        fact = next(f for f in rebuilt.to_facts() if f.field_path == "identity.full_name")
        assert fact.value == "Synthetic Test Candidate"
        assert fact.status is FactStatus.VERIFIED

    def test_the_rebuild_keeps_evidence(self, db, tmp_path: Path) -> None:
        from core.enums import EvidenceSourceType, FactStatus
        from core.evidence import Evidence

        service = make_service(db, tmp_path)
        service.create_profile("cited", persist_json=True)
        service.update_fact(
            "contact.email",
            "synthetic.tester@synthetic-candidate.invalid",
            status=FactStatus.VERIFIED,
            source=EvidenceSourceType.USER_INPUT,
            source_id="fixture",
            evidence=[
                Evidence(
                    source_type=EvidenceSourceType.USER_INPUT,
                    source_id="fixture",
                    source_location="facts[0]",
                    text_excerpt="SYNTHETIC EVIDENCE",
                )
            ],
            candidate_id="cited",
        )
        (tmp_path / "cited.json").unlink()
        rebuilt = service.load_profile_from_database("cited")
        fact = next(f for f in rebuilt.to_facts() if f.field_path == "contact.email")
        assert len(fact.evidence) == 1
        assert fact.is_application_safe is True

    def test_rebuilding_an_unknown_candidate_fails_loudly(self, db, tmp_path: Path) -> None:
        service = make_service(db, tmp_path)
        with pytest.raises(ProfileNotFoundError):
            service.load_profile_from_database("nobody")


class TestSingleFactReads:
    def test_a_fact_can_be_read_without_the_json_file(self, db, tmp_path: Path) -> None:
        from core.enums import EvidenceSourceType, FactStatus

        service = make_service(db, tmp_path)
        service.create_profile("reader", persist_json=True)
        service.update_fact(
            "identity.full_name",
            "Synthetic Test Candidate",
            status=FactStatus.VERIFIED,
            source=EvidenceSourceType.USER_INPUT,
            source_id="fixture",
            candidate_id="reader",
        )
        (tmp_path / "reader.json").unlink()
        # Requiring the file first would make a healthy database look empty.
        assert service.get_fact("identity.full_name", "reader") is not None

    def test_an_unknown_candidate_yields_none(self, db, tmp_path: Path) -> None:
        service = make_service(db, tmp_path)
        assert service.get_fact("identity.full_name", "nobody") is None


class TestEvidenceIsRequiredForApplicationSafety:
    def test_a_cited_fact_with_no_explicit_evidence_is_still_safe(self, db, tmp_path: Path) -> None:
        # The compact source pointer is itself a citation, so a fact written
        # in the short JSON form is usable. What is not usable is a fact with
        # no source at all, which the model refuses outright.
        from core.enums import EvidenceSourceType, FactStatus

        service = make_service(db, tmp_path)
        service.create_profile("bare", persist_json=True)
        profile = service.update_fact(
            "identity.full_name",
            "Synthetic Test Candidate",
            status=FactStatus.VERIFIED,
            source=EvidenceSourceType.USER_INPUT,
            source_id="fixture",
            candidate_id="bare",
        )
        fact = next(f for f in profile.to_facts() if f.field_path == "identity.full_name")
        assert fact.status is FactStatus.VERIFIED
        assert len(fact.evidence) == 1
        assert fact.is_application_safe is True

    def test_an_inferred_fact_is_never_application_safe(self, db, tmp_path: Path) -> None:
        from core.enums import EvidenceSourceType, FactStatus

        service = make_service(db, tmp_path)
        service.create_profile("guessed", persist_json=True)
        profile = service.update_fact(
            "identity.headline",
            "Synthetic Headline",
            status=FactStatus.INFERRED,
            source=EvidenceSourceType.AI_GENERAL
            if hasattr(EvidenceSourceType, "AI_GENERAL")
            else EvidenceSourceType.SYSTEM,
            source_id="ollama",
            candidate_id="guessed",
            actor="ollama",
        )
        fact = next(f for f in profile.to_facts() if f.field_path == "identity.headline")
        assert fact.status is FactStatus.INFERRED
        assert fact.is_application_safe is False

    def test_adding_evidence_makes_it_application_safe(self, db, tmp_path: Path) -> None:
        from core.enums import EvidenceSourceType, FactStatus
        from core.evidence import Evidence

        service = make_service(db, tmp_path)
        service.create_profile("cited", persist_json=True)
        service.update_fact(
            "identity.full_name",
            "Synthetic Test Candidate",
            status=FactStatus.VERIFIED,
            source=EvidenceSourceType.USER_INPUT,
            source_id="fixture",
            evidence=[
                Evidence(source_type=EvidenceSourceType.USER_INPUT, source_id="fixture")
            ],
            candidate_id="cited",
        )
        detail = service.get_fact_with_evidence("identity.full_name", "cited")
        assert detail is not None
        assert detail["is_application_safe"] is True
        assert len(detail["evidence"]) == 1


class TestEvidenceExcerptsSurvive:
    def test_an_excerpt_is_not_replaced_by_a_stub(self, db, tmp_path: Path) -> None:
        # FactValue.to_fact used to rebuild evidence from the source fields
        # and drop what it was given, so every excerpt was lost on the way to
        # the database.
        from core.enums import EvidenceSourceType, FactStatus
        from core.evidence import Evidence

        excerpt = "SYNTHETIC EVIDENCE: identity.full_name = Synthetic Test Candidate"
        service = make_service(db, tmp_path)
        service.create_profile("cited", persist_json=True)
        service.update_fact(
            "identity.full_name",
            "Synthetic Test Candidate",
            status=FactStatus.VERIFIED,
            source=EvidenceSourceType.USER_INPUT,
            source_id="fixture",
            evidence=[
                Evidence(
                    source_type=EvidenceSourceType.USER_INPUT,
                    source_id="fixture",
                    source_location="facts[0]",
                    text_excerpt=excerpt,
                )
            ],
            candidate_id="cited",
        )
        (tmp_path / "cited.json").unlink()
        rebuilt = service.load_profile_from_database("cited")
        fact = next(f for f in rebuilt.to_facts() if f.field_path == "identity.full_name")
        assert fact.evidence[0].text_excerpt == excerpt
        assert fact.evidence[0].source_location == "facts[0]"

    def test_the_two_representations_agree_about_safety(self, db, tmp_path: Path) -> None:
        from core.enums import EvidenceSourceType, FactStatus
        from candidate_profile.models import build_empty_profile

        section = build_empty_profile("x").identity

        unknown = section.full_name
        assert unknown.is_application_safe is unknown.to_fact().is_application_safe
        assert unknown.is_application_safe is False

        inferred = section.with_update(
            "identity.full_name",
            "Synthetic Test Candidate",
            status=FactStatus.INFERRED,
            source=EvidenceSourceType.SYSTEM,
            source_id="ollama",
        )
        # with_update on a section returns the section, with its section prefix
        # stripped from the path, so the fact is read back off that result.
        inferred_value = inferred.full_name
        assert inferred_value.value == "Synthetic Test Candidate"
        assert inferred_value.is_application_safe is inferred_value.to_fact().is_application_safe
        assert inferred_value.is_application_safe is False


class TestSyntheticFixtureContract:
    def test_the_fixture_declares_itself_synthetic(self) -> None:
        payload = json.loads((FIXTURES / "synthetic_candidate.json").read_text(encoding="utf-8"))
        assert "SYNTHETIC" in payload["_fixture_notice"]
        assert "TEST DATA ONLY" in payload["_fixture_notice"]

    def test_every_fixture_fact_carries_evidence(self) -> None:
        # Step 11 of the checklist retrieves evidence, so a fixture whose facts
        # have none would make that step untestable.
        payload = json.loads((FIXTURES / "synthetic_candidate.json").read_text(encoding="utf-8"))
        for fact in payload["facts"]:
            assert fact.get("evidence"), fact["field_path"]

    def test_fixture_emails_use_an_invalid_tld(self) -> None:
        payload = json.loads((FIXTURES / "synthetic_candidate.json").read_text(encoding="utf-8"))
        for fact in payload["facts"]:
            if isinstance(fact["value"], str) and "@" in fact["value"]:
                assert fact["value"].endswith(".invalid"), fact["field_path"]
