"""Resume persistence.

The ``(candidate_id, file_hash)`` unique constraint is what makes duplicate
detection a database guarantee rather than a hopeful check, so two concurrent
ingestions of the same file cannot both succeed.
"""

from __future__ import annotations

from typing import Any, Optional

from core.enums import DocumentType, ResumeFileType, ResumeStatus, SectionType
from core.errors import DuplicateResumeError
from database.repositories.base import (
    BaseRepository,
    from_json_text,
    row_get,
    to_json_text,
)
from database.repositories.documents import DocumentRepository
from resumes.models import Resume

__all__ = ["ResumeRepository"]


class ResumeRepository(BaseRepository):
    """Stores resumes and their structured sections."""

    table = "resumes"
    id_prefix = "resume"

    def __init__(self, db, documents: Optional[DocumentRepository] = None) -> None:
        super().__init__(db)
        self.documents = documents or DocumentRepository(db)

    # -- writes --------------------------------------------------------------
    def save(self, resume: Resume) -> str:
        """Insert or update a resume and replace its sections.

        Raises:
            DuplicateResumeError: If this candidate already has a resume with
                the same ``file_hash`` under a different id. The unique index on
                ``(candidate_id, file_hash)`` is the last line of defence, and
                the violation is translated here so callers see the typed error
                instead of a generic database failure.
            DatabaseError: If the write fails for any other reason.
        """
        existing = self.by_hash(resume.file_hash, resume.candidate_id)
        if existing is not None and existing["id"] != resume.id:
            raise DuplicateResumeError(
                "this content is already stored for this candidate",
                file_hash=resume.file_hash,
                resume_id=existing["id"],
            )

        now = utc_now_text()
        document_id = f"doc-{resume.id}"

        # The document row must exist before the resume row references it:
        # resumes.document_id is a foreign key, and SQLite checks it on insert.
        # Creating the document first keeps both the constraint satisfied and
        # the two rows consistent when a save is repeated.
        self.documents.create(
            document_type=DocumentType.RESUME,
            source_id=resume.id,
            filename=resume.filename,
            file_hash=resume.file_hash,
            content_hash=resume.content_hash,
            char_count=resume.char_count,
            storage_path=resume.storage_path,
            metadata={
                "variant": resume.variant,
                "role_focus": resume.role_focus,
                "version": resume.version,
                "is_synthetic": resume.is_synthetic,
            },
            doc_id=document_id,
        )

        self._upsert_by_id(
            {
                "id": resume.id,
                "candidate_id": resume.candidate_id,
                "document_id": document_id,
                "variant": resume.variant,
                "role_focus": resume.role_focus,
                "version": resume.version,
                "skills_json": to_json_text(resume.skills),
                "filename": resume.filename,
                "file_type": resume.file_type.value,
                "file_hash": resume.file_hash,
                "file_size_bytes": resume.file_size_bytes,
                "page_count": resume.page_count,
                "char_count": resume.char_count,
                "content_hash": resume.content_hash,
                "storage_path": resume.storage_path,
                "raw_text_path": resume.raw_text_path,
                "status": resume.status.value,
                "parser_name": resume.parser_name,
                "parser_version": resume.parser_version,
                "raw_text": resume.raw_text,
                "metadata_json": to_json_text(resume.metadata),
                "is_synthetic": 1 if resume.is_synthetic else 0,
                "created_at": resume.created_at.isoformat(),
                "updated_at": now,
            }
        )

        self._save_sections(resume)
        return resume.id

    def _upsert_by_id(self, values: dict[str, Any]) -> None:
        """Insert or update this row, keyed on its primary key."""
        BaseRepository.upsert(self, values, conflict_column=self.primary_key)

    def _save_sections(self, resume: Resume) -> None:
        self.db.execute("DELETE FROM resume_sections WHERE resume_id = ?", (resume.id,))
        for index, section in enumerate(resume.sections):
            self.db.execute(
                "INSERT INTO resume_sections "
                "(id, resume_id, section_type, position, heading, raw_text, items_json, "
                " char_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    section.id or f"{resume.id}-sec-{index}",
                    resume.id,
                    section.section_type.value,
                    index,
                    section.heading,
                    section.raw_text,
                    to_json_text(section.items),
                    section.char_count or len(section.raw_text),
                    section.created_at.isoformat(),
                ),
            )

    def set_status(self, resume_id: str, status: ResumeStatus, *, error: Optional[str] = None) -> None:
        """Update a resume's lifecycle status, recording any error."""
        values: dict[str, Any] = {"status": status.value, "updated_at": utc_now_text()}
        if error:
            values["metadata_json"] = to_json_text({"error": error})
        self.update(resume_id, values)

    # -- reads ---------------------------------------------------------------
    def by_hash(self, file_hash: str, candidate_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Look up an existing resume by content hash."""
        if candidate_id:
            return self.db.query_one(
                "SELECT * FROM resumes WHERE file_hash = ? AND candidate_id = ?",
                (file_hash, candidate_id),
            )
        return self.db.query_one(
            "SELECT * FROM resumes WHERE file_hash = ? ORDER BY rowid LIMIT 1",
            (file_hash,),
        )

    def by_content_hash(self, content_hash: str) -> Optional[dict[str, Any]]:
        """Look up by normalised text hash, catching the same CV in another format."""
        return self.db.query_one(
            "SELECT * FROM resumes WHERE content_hash = ? ORDER BY rowid LIMIT 1",
            (content_hash,),
        )

    def for_candidate(self, candidate_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM resumes WHERE candidate_id = ? ORDER BY created_at, rowid",
            (candidate_id,),
        )

    def by_variant(self, candidate_id: str, variant: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM resumes WHERE candidate_id = ? AND variant = ? ORDER BY created_at",
            (candidate_id, variant),
        )

    def variants(self, candidate_id: str) -> list[str]:
        rows = self.db.query(
            "SELECT DISTINCT variant FROM resumes WHERE candidate_id = ? "
            "AND variant IS NOT NULL ORDER BY variant",
            (candidate_id,),
        )
        return [r["variant"] for r in rows]

    def load(self, resume_id: str) -> Optional[Resume]:
        """Load a resume with its sections back into a model."""
        row = self.get(resume_id)
        if row is None:
            return None
        sections = self.db.query(
            "SELECT * FROM resume_sections WHERE resume_id = ? ORDER BY position",
            (resume_id,),
        )
        return Resume(
            id=row["id"],
            candidate_id=row["candidate_id"],
            document_id=row["document_id"],
            variant=row["variant"],
            role_focus=row_get(row, "role_focus"),
            version=row_get(row, "version"),
            skills=from_json_text(row_get(row, "skills_json"), []) or [],
            filename=row["filename"],
            file_type=ResumeFileType(row["file_type"]),
            file_hash=row["file_hash"],
            file_size_bytes=row["file_size_bytes"],
            page_count=row["page_count"],
            char_count=row["char_count"],
            content_hash=row_get(row, "content_hash"),
            storage_path=row["storage_path"],
            raw_text_path=row["raw_text_path"],
            raw_text=row["raw_text"] or "",
            status=ResumeStatus(row["status"]),
            parser_name=row["parser_name"],
            parser_version=row["parser_version"],
            metadata=from_json_text(row["metadata_json"], {}) or {},
            is_synthetic=bool(row["is_synthetic"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            sections=[
                {
                    "id": s["id"],
                    "resume_id": s["resume_id"],
                    "section_type": SectionType(s["section_type"]),
                    "position": s["position"],
                    "heading": s["heading"],
                    "raw_text": s["raw_text"] or "",
                    "items": from_json_text(s["items_json"], []) or [],
                    "char_count": s["char_count"],
                }
                for s in sections
            ],
        )

    def section_index(self, candidate_id: str) -> dict[str, list[dict[str, Any]]]:
        """Return every section grouped by section type.

        This is the index a later retrieval phase queries. Phase 2 only builds
        it; nothing here selects or ranks anything.
        """
        rows = self.db.query(
            "SELECT r.id AS resume_id, r.variant, s.section_type, s.heading, s.char_count "
            "FROM resume_sections s JOIN resumes r ON r.id = s.resume_id "
            "WHERE r.candidate_id = ? ORDER BY s.section_type, s.position",
            (candidate_id,),
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["section_type"], []).append(row)
        return grouped

    def synthetic_only(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM resumes WHERE is_synthetic = 1")


def utc_now_text() -> str:
    from core.hashing import utc_now

    return utc_now().isoformat()
