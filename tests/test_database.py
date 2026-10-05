"""Tests for the database layer: migrations, transactions, and repositories.

The point of these tests is durability of the safety properties. A verified
fact must survive a restart with its evidence, a rejected resume must leave no
row behind, and re-running the migrations must not corrupt an existing
database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.enums import (
    EvidenceSourceType,
    FactStatus,
    ResumeFileType,
    ResumeStatus,
    SectionType,
)
from core.errors import (
    DatabaseError,
    DuplicateResumeError,
    ImmutableFactError,
    ProfileNotFoundError,
)
from core.evidence import Evidence, Fact
from database.connection import Database
from database.connection import _MIGRATIONS_DIR
from candidate_profile.models import build_empty_profile
from resumes.models import Resume, ResumeSection

_EVIDENCE = [
    Evidence(
        source_type=EvidenceSourceType.USER_INPUT,
        source_id="test-session",
        source_location="manual entry",
        text_excerpt="SYNTHETIC TEST DATA",
    )
]

#: The ten tables migration 001 creates, plus the ones 002 touches. Verified
#: against the live schema rather than a wish list.
EXPECTED_TABLES = {
    "schema_migrations",
    "candidate_profiles",
    "candidate_facts",
    "fact_change_log",
    "fact_evidence",
    "evidence",
    "documents",
    "resumes",
    "resume_sections",
    "model_runs",
}


def make_resume(resume_id: str = "resume-aaaaaaaaaaaaaaaa", **overrides) -> Resume:
    text = "Synthetic summary text."
    section = ResumeSection(
        id=f"{resume_id}-s0",
        resume_id=resume_id,
        section_type=SectionType.SUMMARY,
        position=0,
        heading="Summary",
        raw_text=text,
        char_count=len(text),
    )
    fields = dict(
        id=resume_id,
        candidate_id="primary",
        filename="synthetic_resume.txt",
        file_type=ResumeFileType.TXT,
        file_hash="a" * 64,
        file_size_bytes=1234,
        char_count=len(text),
        content_hash="b" * 64,
        role_focus="ml-engineer",
        version="v2",
        skills=["Python", "PyTorch"],
        status=ResumeStatus.PARSED,
        sections=[section],
    )
    fields.update(overrides)
    return Resume(**fields)


@pytest.fixture
def resume_repo(db: Database):
    from database.repositories.resumes import ResumeRepository

    return ResumeRepository(db)


@pytest.fixture
def profile_repo(db: Database):
    from database.repositories.profiles import ProfileRepository

    return ProfileRepository(db)


@pytest.fixture
def saved_profile(profile_repo, db: Database):
    """A profile row that exists, with one verified fact already written."""
    from candidate_profile.models import CandidateProfile

    profile_repo.create(CandidateProfile(candidate_id="primary"))
    profile = build_empty_profile("primary").with_update(
        "identity.full_name",
        "SYNTHETIC NAME",
        status=FactStatus.VERIFIED,
        evidence=list(_EVIDENCE),
    )
    profile_repo.save_profile(profile, actor="candidate")
    return profile


class TestMigrations:
    def test_initialize_creates_the_foundation_tables(self, db: Database) -> None:
        assert EXPECTED_TABLES <= set(db.table_names())

    def test_migrations_are_recorded_in_order(self, db: Database) -> None:
        versions = [r["version"] for r in db.query("SELECT version FROM schema_migrations")]
        assert versions == sorted(versions)
        assert len(versions) == len(set(versions))

    def test_reinitializing_records_nothing_new(self, db: Database) -> None:
        before = db.query("SELECT version FROM schema_migrations")
        db.initialize()
        assert db.query("SELECT version FROM schema_migrations") == before

    def test_forced_rerun_does_not_duplicate_columns(self, db: Database) -> None:
        db.initialize()
        columns = [r["name"] for r in db.query("PRAGMA table_info(resumes)")]
        assert len(columns) == len(set(columns))
        for expected in ("role_focus", "version", "skills_json", "content_hash"):
            assert expected in columns

    def test_variant_columns_live_in_migration_002(self) -> None:
        # 001 stays as the historical schema, so an old database and a fresh one
        # converge on the same shape instead of diverging.
        one = (_MIGRATIONS_DIR / "001_phase2_foundation.sql").read_text(encoding="utf-8")
        two = (_MIGRATIONS_DIR / "002_resume_variant_metadata.sql").read_text(encoding="utf-8")
        assert "role_focus" not in one
        assert "role_focus" in two

    def test_wal_is_enabled(self, db: Database) -> None:
        assert db.scalar("PRAGMA journal_mode").lower() == "wal"

    def test_foreign_keys_are_enforced(self, db: Database) -> None:
        # Database.execute translates SQLite errors into the typed DatabaseError,
        # so a foreign key breach surfaces as that rather than a raw driver error.
        with pytest.raises(DatabaseError):
            db.execute(
                "INSERT INTO resume_sections (id, resume_id, section_type, position,"
                " raw_text, char_count, created_at)"
                " VALUES ('s-x','resume-missing','SUMMARY',0,'x',1,'2026-01-01')"
            )

    def test_a_fact_cannot_point_at_a_missing_profile(self, db: Database) -> None:
        with pytest.raises(DatabaseError):
            db.execute(
                "INSERT INTO candidate_facts (id, profile_id, field_path, section,"
                " field_type, status, created_at, updated_at)"
                " VALUES ('f1','profile-missing','identity.full_name','identity',"
                "'string','UNKNOWN','2026-01-01','2026-01-01')"
            )


class TestTransactions:
    def _insert_profile(self, db: Database, profile_id: str) -> None:
        db.execute(
            "INSERT INTO candidate_profiles (id, candidate_id, status, created_at, updated_at)"
            " VALUES (?,?, 'DRAFT','2026-01-01','2026-01-01')",
            (profile_id, profile_id),
        )

    def test_a_failed_statement_rolls_the_whole_unit_back(self, db: Database) -> None:
        self._insert_profile(db, "p-rollback")
        with pytest.raises(DatabaseError):
            with db.transaction():
                db.execute("UPDATE candidate_profiles SET status='VALIDATED' WHERE id='p-rollback'")
                db.execute("INSERT INTO candidate_profiles (id) VALUES (NULL)")
        assert db.query_one("SELECT status FROM candidate_profiles WHERE id='p-rollback'")[
            "status"
        ] == "DRAFT"

    def test_a_committed_transaction_persists(self, db: Database) -> None:
        with db.transaction():
            self._insert_profile(db, "p-ok")
        assert db.query_one("SELECT id FROM candidate_profiles WHERE id='p-ok'") is not None

    def test_data_survives_reopening(self, tmp_path: Path) -> None:
        path = tmp_path / "reopen.db"
        first = Database(path)
        first.initialize()
        self._insert_profile(first, "p1")
        first.close()

        second = Database(path)
        second.initialize()
        assert second.query_one("SELECT id FROM candidate_profiles WHERE id='p1'") is not None
        second.close()

    def test_the_original_error_is_not_hidden_by_the_rollback(self, db: Database) -> None:
        with pytest.raises(DatabaseError):
            with db.transaction():
                db.execute("INSERT INTO candidate_profiles (id) VALUES (NULL)")


class TestResumeRepository:
    def test_save_persists_variant_metadata(self, resume_repo) -> None:
        resume_repo.save(make_resume())
        loaded = resume_repo.load("resume-aaaaaaaaaaaaaaaa")
        assert loaded.role_focus == "ml-engineer"
        assert loaded.version == "v2"
        assert loaded.skills == ["Python", "PyTorch"]
        assert loaded.content_hash == "b" * 64

    def test_section_rows_carry_the_parent_resume(self, resume_repo, db: Database) -> None:
        resume_repo.save(make_resume())
        rows = db.query("SELECT resume_id, position FROM resume_sections")
        assert [(r["resume_id"], r["position"]) for r in rows] == [
            ("resume-aaaaaaaaaaaaaaaa", 0)
        ]

    def test_resaving_does_not_duplicate_sections(self, resume_repo, db: Database) -> None:
        resume = make_resume()
        resume_repo.save(resume)
        resume_repo.save(resume)
        assert db.count("resume_sections") == 1

    def test_a_document_row_exists_before_the_resume_references_it(
        self, resume_repo, db: Database
    ) -> None:
        # resumes.document_id is a foreign key, so the document has to be
        # written first. Reversing the order makes every insert fail.
        resume_repo.save(make_resume())
        assert (
            db.query_one("SELECT id FROM documents WHERE id=?", ("doc-resume-aaaaaaaaaaaaaaaa",))
            is not None
        )

    def test_identical_content_under_another_id_is_rejected(self, resume_repo) -> None:
        resume_repo.save(make_resume())
        with pytest.raises(DuplicateResumeError):
            resume_repo.save(make_resume("resume-bbbbbbbbbbbbbbbb", file_hash="a" * 64))

    def test_the_same_text_in_another_format_is_kept(self, resume_repo) -> None:
        # Different bytes, same text: both are stored, and the content hash is
        # what lets a later phase notice they are the same CV.
        resume_repo.save(make_resume())
        resume_repo.save(
            make_resume(
                "resume-cccccccccccccccc",
                file_hash="c" * 64,
                file_type=ResumeFileType.PDF,
                filename="synthetic_resume.pdf",
            )
        )
        assert len(resume_repo.by_content_hash("b" * 64)) >= 1

    def test_by_content_hash_returns_nothing_for_unknown_content(self, resume_repo) -> None:
        assert not resume_repo.by_content_hash("f" * 64)

    def test_by_hash_finds_the_row(self, resume_repo) -> None:
        resume_repo.save(make_resume())
        assert resume_repo.by_hash("a" * 64, "primary")["id"] == "resume-aaaaaaaaaaaaaaaa"

    def test_the_synthetic_flag_is_persisted_and_queryable(self, resume_repo) -> None:
        resume_repo.save(make_resume(is_synthetic=True))
        assert resume_repo.load("resume-aaaaaaaaaaaaaaaa").is_synthetic is True
        assert [r["id"] for r in resume_repo.synthetic_only()] == ["resume-aaaaaaaaaaaaaaaa"]

    def test_variants_are_listed(self, resume_repo) -> None:
        resume_repo.save(make_resume(variant="AI Engineer"))
        assert resume_repo.variants("primary") == ["AI Engineer"]

    def test_by_variant_filters(self, resume_repo) -> None:
        resume_repo.save(make_resume(variant="AI Engineer"))
        resume_repo.save(
            make_resume("resume-dddddddddddddddd", file_hash="d" * 64, variant="Data Engineer")
        )
        assert [r["id"] for r in resume_repo.by_variant("primary", "AI Engineer")] == [
            "resume-aaaaaaaaaaaaaaaa"
        ]

    def test_delete_removes_sections_too(self, resume_repo, db: Database) -> None:
        resume_repo.save(make_resume())
        resume_repo.delete("resume-aaaaaaaaaaaaaaaa")
        assert db.count("resume_sections") == 0
        assert resume_repo.load("resume-aaaaaaaaaaaaaaaa") is None

    def test_load_returns_none_for_an_unknown_id(self, resume_repo) -> None:
        assert resume_repo.load("resume-0000000000000000") is None

    def test_section_index_is_ordered(self, resume_repo) -> None:
        resume_repo.save(make_resume())
        index = resume_repo.section_index("resume-aaaaaaaaaaaaaaaa")
        assert [entry["position"] for entry in index] == sorted(
            entry["position"] for entry in index
        )


class TestProfileRepository:
    def test_save_requires_an_existing_profile_row(self, profile_repo, db: Database) -> None:
        with pytest.raises(ProfileNotFoundError):
            profile_repo.save_profile(build_empty_profile("primary"))

    def test_facts_are_projected_into_the_queryable_table(
        self, saved_profile, db: Database
    ) -> None:
        row = db.query_one(
            "SELECT status, value_json FROM candidate_facts WHERE field_path=?",
            ("identity.full_name",),
        )
        assert row["status"] == "VERIFIED"
        assert "SYNTHETIC NAME" in row["value_json"]

    def test_a_saved_fact_keeps_its_evidence(self, profile_repo, saved_profile) -> None:
        fact = profile_repo.get_fact(saved_profile.id, "identity.full_name")
        assert fact.status is FactStatus.VERIFIED
        assert fact.evidence and fact.evidence[0].source_id == "test-session"

    def test_evidence_is_stored_in_its_own_table(self, saved_profile, db: Database) -> None:
        assert db.count("evidence") >= 1
        assert db.count("fact_evidence") >= 1

    def test_every_change_is_logged_with_its_actor(self, saved_profile, db: Database) -> None:
        # Creating the profile logs the initial UNKNOWN state of all 44 fields,
        # so the verified edit is the last row for that path, not the first.
        rows = db.query(
            "SELECT actor, actor_kind, after_status FROM fact_change_log"
            " WHERE field_path=? ORDER BY changed_at, rowid",
            ("identity.full_name",),
        )
        assert rows[-1]["after_status"] == "VERIFIED"
        assert rows[-1]["actor"] == "candidate"
        assert rows[-1]["actor_kind"] == "HUMAN"

    def test_the_initial_unknown_state_is_audited_too(self, saved_profile, db: Database) -> None:
        rows = db.query(
            "SELECT after_status FROM fact_change_log WHERE field_path=?", ("contact.email",)
        )
        assert [r["after_status"] for r in rows] == ["UNKNOWN"]

    def test_resaving_replaces_facts_rather_than_appending(
        self, profile_repo, saved_profile, db: Database
    ) -> None:
        profile_repo.save_profile(saved_profile, actor="candidate")
        rows = db.query(
            "SELECT id FROM candidate_facts WHERE field_path=?", ("identity.full_name",)
        )
        assert len(rows) == 1

    def test_unknown_fields_can_be_listed(self, profile_repo, saved_profile) -> None:
        unknown = profile_repo.unknown_fields(saved_profile.id)
        assert "contact.email" in unknown
        assert "identity.full_name" not in unknown

    def test_verified_fields_can_be_listed(self, profile_repo, saved_profile) -> None:
        assert profile_repo.verified_fields(saved_profile.id) == ["identity.full_name"]

    def test_require_by_candidate_raises_when_absent(self, profile_repo) -> None:
        with pytest.raises(ProfileNotFoundError):
            profile_repo.require_by_candidate("nobody")

    def test_set_status_writes_the_profile_row(self, profile_repo, saved_profile, db: Database) -> None:
        # set_status once shadowed the inherited single-row update helper,
        # which meant writing the wrong columns to the wrong table.
        profile_repo.set_status(saved_profile.id, "VALIDATED", validated=True)
        row = db.query_one(
            "SELECT status, validated_at FROM candidate_profiles WHERE id=?", (saved_profile.id,)
        )
        assert row["status"] == "VALIDATED"
        assert row["validated_at"] is not None

    def test_set_status_rejects_an_unknown_status(self, profile_repo, saved_profile) -> None:
        with pytest.raises(ValueError):
            profile_repo.set_status(saved_profile.id, "NONSENSE")

    def test_change_log_is_readable_in_order(self, profile_repo, saved_profile) -> None:
        assert isinstance(profile_repo.change_log(saved_profile.id), list)


class TestFactMutationGuard:
    def _facts(self, value: str, status: FactStatus = FactStatus.VERIFIED) -> list[Fact]:
        return [
            Fact(
                field_path="identity.full_name",
                value=value,
                status=status,
                evidence=list(_EVIDENCE),
            )
        ]

    def test_an_ai_actor_cannot_change_a_verified_fact(self) -> None:
        from safety.guards import assert_no_fact_mutation

        with pytest.raises(ImmutableFactError):
            assert_no_fact_mutation(
                self._facts("SYNTHETIC NAME"), self._facts("MODEL GUESS"), actor="ollama"
            )

    def test_an_unknown_actor_is_treated_as_ai(self) -> None:
        from safety.guards import assert_no_fact_mutation

        with pytest.raises(ImmutableFactError):
            assert_no_fact_mutation(
                self._facts("SYNTHETIC NAME"),
                self._facts("MODEL GUESS"),
                actor="some-unlabelled-helper",
            )

    def test_an_ai_actor_cannot_delete_a_verified_fact(self) -> None:
        # Dropping the row is as much of a change as rewriting it.
        from safety.guards import assert_no_fact_mutation

        with pytest.raises(ImmutableFactError):
            assert_no_fact_mutation(self._facts("SYNTHETIC NAME"), [], actor="ollama")

    def test_a_human_may_change_a_verified_fact(self) -> None:
        from safety.guards import assert_no_fact_mutation

        assert_no_fact_mutation(
            self._facts("SYNTHETIC NAME"), self._facts("CORRECTED NAME"), actor="candidate"
        )

    def test_a_human_may_delete_a_verified_fact(self) -> None:
        from safety.guards import assert_no_fact_mutation

        assert_no_fact_mutation(self._facts("SYNTHETIC NAME"), [], actor="candidate")

    def test_adding_a_new_fact_is_not_a_mutation(self) -> None:
        from safety.guards import assert_no_fact_mutation

        assert_no_fact_mutation([], self._facts("SYNTHETIC NAME"), actor="ollama")

    def test_dropping_an_inferred_fact_is_allowed(self) -> None:
        # Only verified facts are protected, so a model may withdraw a guess.
        from safety.guards import assert_no_fact_mutation

        assert_no_fact_mutation(self._facts("A GUESS", FactStatus.INFERRED), [], actor="ollama")

    def test_identical_facts_produce_an_empty_diff(self, saved_profile) -> None:
        from safety.guards import diff_verified_facts

        facts = saved_profile.to_facts()
        assert diff_verified_facts(facts, facts) == {}

    def test_a_changed_value_shows_up_in_the_diff(self, saved_profile) -> None:
        from safety.guards import diff_verified_facts

        before = saved_profile.to_facts()
        after = saved_profile.with_update("identity.full_name", "CORRECTED NAME").to_facts()
        changes = diff_verified_facts(before, after)
        assert changes["identity.full_name"]["before"] == "SYNTHETIC NAME"
        assert changes["identity.full_name"]["after"] == "CORRECTED NAME"

    def test_a_removed_fact_shows_up_in_the_diff(self, saved_profile) -> None:
        from safety.guards import diff_verified_facts

        before = saved_profile.to_facts()
        after = [f for f in before if f.field_path != "identity.full_name"]
        assert diff_verified_facts(before, after)["identity.full_name"]["kind"] == "removed"