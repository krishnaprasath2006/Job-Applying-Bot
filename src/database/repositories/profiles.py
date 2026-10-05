"""Candidate profile persistence.

A profile is stored twice on purpose:

* **JSON** is the human-editable source of truth. A person can open it, read
  it, and correct it in any text editor.
* **SQLite** is the queryable projection, one row per fact, so later phases
  can ask "which verified facts do we have about SQL?" without parsing JSON at
  query time.

Neither replaces the other. JSON is what you edit; the database is what the
code reads. Every fact write is recorded in ``fact_change_log`` with the actor
that caused it, which is how "AI cannot mutate verified facts" becomes
auditable after the fact.
"""

from __future__ import annotations

from typing import Any, Optional

from core.actors import (
    DETERMINISTIC,
    DETERMINISTIC_ACTOR_PREFIXES,
    HUMAN,
    HUMAN_ACTOR_PREFIXES,
    classify_actor,
)
from core.enums import DocumentType, EvidenceSourceType, FactStatus
from core.errors import ProfileNotFoundError, ProfilePersistenceError
from core.evidence import Evidence, Fact
from core.hashing import sha256_text, utc_now
from database.repositories.base import BaseRepository, from_json_text, to_json_text
from database.repositories.documents import DocumentRepository, EvidenceRepository
from candidate_profile.models import CandidateProfile

__all__ = [
    "DETERMINISTIC_ACTOR_PREFIXES",
    "HUMAN_ACTOR_PREFIXES",
    "ProfileRepository",
    "TRUSTED_ACTORS",
    "classify_actor",
]

#: Actors permitted to create or change a ``VERIFIED`` fact. Derived from the
#: shared classifier in :mod:`core.actors` so the change log and the safety
#: guard can never disagree about who a writer is.
TRUSTED_ACTORS = frozenset({"user", "human", "system", "candidate", "cli", "deterministic"})


class ProfileRepository(BaseRepository):
    """Stores and retrieves candidate profiles."""

    table = "candidate_profiles"
    id_prefix = "profile"

    def __init__(self, db, evidence_repo: Optional[EvidenceRepository] = None) -> None:
        super().__init__(db)
        self.evidence = evidence_repo or EvidenceRepository(db)
        self.documents = DocumentRepository(db)

    # -- writes --------------------------------------------------------------
    def create(self, profile: CandidateProfile, *, actor: str = "system") -> str:
        """Insert a new profile.

        Raises:
            ProfilePersistenceError: If a profile for this candidate already
                exists. Use :meth:`upsert` to replace it deliberately.
        """
        existing = self.by_candidate(profile.candidate_id)
        if existing is not None:
            raise ProfilePersistenceError(
                "a profile already exists for this candidate",
                candidate_id=profile.candidate_id,
                existing_profile_id=existing["id"],
                hint="use upsert() or update() to modify the existing profile",
            )
        self._write(profile, actor=actor, is_new=True)
        return profile.id

    def save_profile(self, profile: CandidateProfile, *, actor: str = "system") -> str:
        """Persist a whole profile and replace its facts and change log.

        Named ``save_profile`` rather than ``update`` because ``update`` is the
        inherited single-row column helper from
        :class:`~database.repositories.base.BaseRepository`; shadowing it with a
        different signature broke every internal call to that helper.

        Raises:
            ProfileNotFoundError: If the profile id is unknown.
        """
        if not self.exists(profile.id):
            raise ProfileNotFoundError("profile does not exist", profile_id=profile.id)
        self._write(profile, actor=actor, is_new=False)
        return profile.id

    def upsert(self, profile: CandidateProfile, *, actor: str = "system") -> str:
        """Create or replace, whichever applies."""
        self._write(profile, actor=actor, is_new=not self.exists(profile.id))
        return profile.id

    def _write(self, profile: CandidateProfile, *, actor: str, is_new: bool) -> None:
        now = utc_now().isoformat()
        previous = self._existing_facts(profile.id) if not is_new else {}
        content_hash = sha256_text(profile.to_json())

        self._upsert_by_id(
            {
                "id": profile.id,
                "candidate_id": profile.candidate_id,
                "version": profile.version,
                "status": "DRAFT",
                "completeness": profile.completeness(),
                "storage_path": None,
                "content_hash": content_hash,
                "schema_version": profile.schema_version,
                "created_at": profile.created_at.isoformat(),
                "updated_at": now,
                "validated_at": None,
            }
        )

        self.documents.create(
            document_type=DocumentType.PROFILE,
            source_id=profile.id,
            filename=f"{profile.candidate_id}.profile.json",
            content_hash=content_hash,
            char_count=len(profile.to_json()),
            metadata={"schema_version": profile.schema_version, "version": profile.version},
            doc_id=f"doc-profile-{profile.id}",
        )

        for fact in profile.to_facts():
            self._write_fact(profile, fact, actor=actor)
        self._log_changes(profile, previous, actor=actor)

    def _upsert_by_id(self, values: dict[str, Any]) -> None:
        """Insert or update this repository's own row, keyed on its primary key."""
        BaseRepository.upsert(self, values, conflict_column=self.primary_key)

    def _upsert_fact(self, values: dict[str, Any]) -> None:
        """Insert or update a ``candidate_facts`` row.

        Facts live in their own table, which is not this repository's
        ``table``, so the target table is named explicitly.
        """
        self.upsert_into("candidate_facts", values, conflict_column="id")

    def _write_fact(self, profile: CandidateProfile, fact: Fact, *, actor: str) -> None:
        evidence_ids: list[str] = []
        for evidence in fact.evidence:
            evidence_ids.append(
                self.evidence.create(
                    source_type=evidence.source_type,
                    source_id=evidence.source_id,
                    source_location=evidence.source_location,
                    text_excerpt=evidence.text_excerpt,
                    confidence=evidence.confidence,
                    evidence=evidence,
                )
            )

        section = ".".join(fact.field_path.split(".")[:2]) if fact.field_path else None
        fact_id = f"fact-{sha256_text(f'{profile.id}|{fact.field_path}')[:16]}"

        self._upsert_fact(
            {
                "id": fact_id,
                "profile_id": profile.id,
                "field_path": fact.field_path,
                "section": section,
                "field_type": "TEXT",
                "status": fact.status.value,
                "value_json": to_json_text(fact.value),
                "risk_level": "MEDIUM",
                "confidence": max((e.confidence for e in fact.evidence), default=0.0),
                "primary_evidence_id": evidence_ids[0] if evidence_ids else None,
                "note": fact.note,
                "verified_at": fact.verified_at.isoformat() if fact.verified_at else None,
                "created_at": profile.created_at.isoformat(),
                "updated_at": fact.updated_at.isoformat(),
            }
        )

        self.db.execute("DELETE FROM fact_evidence WHERE fact_id = ?", (fact_id,))
        for position, evidence_id in enumerate(evidence_ids):
            self.db.execute(
                "INSERT OR IGNORE INTO fact_evidence (fact_id, evidence_id, position) VALUES (?, ?, ?)",
                (fact_id, evidence_id, position),
            )

    def _log_changes(
        self, profile: CandidateProfile, previous: dict[str, dict[str, Any]], *, actor: str
    ) -> None:
        """Record what changed, so the "AI cannot verify" rule is auditable."""
        actor_kind = classify_actor(actor)
        current = self._existing_facts(profile.id)

        for field_path, row in current.items():
            before = previous.get(field_path)
            before_value = from_json_text(before["value_json"]) if before else None
            before_status = before["status"] if before else None
            if before is not None and (
                before_value == from_json_text(row["value_json"]) and before_status == row["status"]
            ):
                continue
            self.db.execute(
                "INSERT INTO fact_change_log "
                "(id, profile_id, field_path, actor, actor_kind, before_status, after_status, "
                " before_value_json, after_value_json, changed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.new_id(),
                    profile.id,
                    field_path,
                    actor,
                    actor_kind,
                    before_status,
                    row["status"],
                    to_json_text(before_value),
                    row["value_json"],
                    self.now(),
                ),
            )

    def set_status(
        self, profile_id: str, status: str, *, validated: bool = False
    ) -> None:
        """Update the profile-level status.

        Raises:
            ValueError: If ``status`` is not one of the allowed values.
        """
        allowed = {"DRAFT", "VALIDATED", "INCOMPLETE", "INVALID"}
        if status not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        # Explicit base-class call: `update` here must mean the inherited
        # single-row helper, not the whole-profile save.
        BaseRepository.update(
            self,
            profile_id,
            {
                "status": status,
                "updated_at": self.now(),
                "validated_at": self.now() if validated else None,
            },
        )

    # -- reads ---------------------------------------------------------------
    def by_candidate(self, candidate_id: str) -> Optional[dict[str, Any]]:
        return self.db.query_one(
            "SELECT * FROM candidate_profiles WHERE candidate_id = ?", (candidate_id,)
        )

    def require_by_candidate(self, candidate_id: str) -> dict[str, Any]:
        """Like :meth:`by_candidate` but raises when absent.

        Raises:
            ProfileNotFoundError: If no profile exists for this candidate.
        """
        row = self.by_candidate(candidate_id)
        if row is None:
            raise ProfileNotFoundError(
                "no profile found; create one before reading it",
                candidate_id=candidate_id,
            )
        return row

    def _existing_facts(self, profile_id: str) -> dict[str, dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM candidate_facts WHERE profile_id = ?", (profile_id,)
        )
        return {row["field_path"]: row for row in rows}

    def facts(self, profile_id: str, *, status: Optional[FactStatus] = None) -> list[dict[str, Any]]:
        """Return stored fact rows, optionally filtered by truth status."""
        if status is None:
            return self.db.query(
                "SELECT * FROM candidate_facts WHERE profile_id = ? ORDER BY field_path",
                (profile_id,),
            )
        return self.db.query(
            "SELECT * FROM candidate_facts WHERE profile_id = ? AND status = ? ORDER BY field_path",
            (profile_id, status.value),
        )

    def fact_row(self, profile_id: str, field_path: str) -> Optional[dict[str, Any]]:
        return self.db.query_one(
            "SELECT * FROM candidate_facts WHERE profile_id = ? AND field_path = ?",
            (profile_id, field_path),
        )

    def fact_models(self, profile_id: str) -> list[Fact]:
        """Load every fact back as :class:`Fact` models with evidence."""
        facts: list[Fact] = []
        for row in self.facts(profile_id):
            facts.append(self._to_fact(row))
        return facts

    def _to_fact(self, row: dict[str, Any]) -> Fact:
        links = self.db.query(
            "SELECT evidence_id FROM fact_evidence WHERE fact_id = ? ORDER BY position",
            (row["id"],),
        )
        ids = [link["evidence_id"] for link in links]
        if row.get("primary_evidence_id") and row["primary_evidence_id"] not in ids:
            ids.insert(0, row["primary_evidence_id"])
        evidence = list(self.evidence.many_models(ids).values())

        return Fact(
            field_path=row["field_path"],
            value=from_json_text(row["value_json"]),
            status=FactStatus(row["status"]),
            evidence=evidence,
            verified_at=row["verified_at"],
            note=row["note"],
            updated_at=row["updated_at"],
        )

    def get_fact(self, profile_id: str, field_path: str) -> Optional[Fact]:
        """Return one fact with its evidence, or ``None``."""
        row = self.fact_row(profile_id, field_path)
        return None if row is None else self._to_fact(row)

    def unknown_fields(self, profile_id: str) -> list[str]:
        return [
            row["field_path"]
            for row in self.facts(profile_id, status=FactStatus.UNKNOWN)
        ]

    def verified_fields(self, profile_id: str) -> list[str]:
        return [
            row["field_path"]
            for row in self.facts(profile_id, status=FactStatus.VERIFIED)
        ]

    def change_log(self, profile_id: str) -> list[dict[str, Any]]:
        """Return every recorded fact change, newest last."""
        return self.db.query(
            "SELECT * FROM fact_change_log WHERE profile_id = ? ORDER BY changed_at, rowid",
            (profile_id,),
        )

    def ai_attempts(self, profile_id: str) -> int:
        """How many recorded changes were made by an AI actor.

        Should always be zero for verified facts. Useful as a regression
        assertion.
        """
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM fact_change_log WHERE profile_id = ? AND actor_kind = 'AI' "
                "AND (after_status = 'VERIFIED' OR before_status = 'VERIFIED')",
                (profile_id,),
            )
            or 0
        )
