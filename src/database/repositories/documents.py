"""Evidence and document storage.

Documents are the files the assistant has read. Evidence records point at a
document plus a location inside it. Separating the two means a citation can
name both the file and the place within it, and it means deleting a document
does not silently orphan the facts derived from it: the foreign key is
``ON DELETE SET NULL`` and the facts remain, marked as lacking a source.
"""

from __future__ import annotations

from typing import Any, Optional

from core.enums import DocumentType, EvidenceSourceType
from core.evidence import Evidence
from database.repositories.base import BaseRepository, from_json_text, to_json_text

__all__ = ["DocumentRepository", "EvidenceRepository"]


class DocumentRepository(BaseRepository):
    """Stores source documents: resumes, profile exports, job descriptions."""

    table = "documents"
    id_prefix = "doc"

    def create(
        self,
        *,
        document_type: DocumentType,
        source_id: Optional[str] = None,
        filename: Optional[str] = None,
        file_hash: Optional[str] = None,
        content_hash: Optional[str] = None,
        char_count: Optional[int] = None,
        storage_path: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        doc_id: Optional[str] = None,
        replace: bool = False,
    ) -> str:
        """Insert or refresh a document row and return its id.

        ``doc_id`` makes a document deterministic, which is what lets a resume
        be re-saved after parsing. ``replace=False`` (the default) updates the
        row in place when that id already exists, so re-running an ingestion
        cannot fail on the primary key. Pass ``replace=True`` only to force a
        clean insert, which will raise if the id is taken.
        """
        now = self.now()
        identifier = doc_id or self.new_id()
        values = {
            "id": identifier,
            "document_type": document_type.value,
            "source_id": source_id,
            "filename": filename,
            "file_hash": file_hash,
            "content_hash": content_hash,
            "char_count": char_count,
            "storage_path": storage_path,
            "metadata_json": to_json_text(metadata or {}),
            "created_at": now,
            "updated_at": now,
        }
        if replace or not self.exists(identifier):
            self.insert(values)
        else:
            # Keep the original created_at: this document has existed since the
            # first time it was recorded.
            self.update(
                identifier,
                {k: v for k, v in values.items() if k not in ("id", "created_at")},
            )
        return identifier

    def find_by_file_hash(self, file_hash: str) -> Optional[dict[str, Any]]:
        return self.db.query_one(
            "SELECT * FROM documents WHERE file_hash = ? ORDER BY rowid LIMIT 1",
            (file_hash,),
        )

    def of_type(self, document_type: DocumentType) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM documents WHERE document_type = ? ORDER BY created_at",
            (document_type.value,),
        )


class EvidenceRepository(BaseRepository):
    """Stores :class:`~core.evidence.Evidence` records."""

    table = "evidence"
    id_prefix = "evidence"

    def create(
        self,
        *,
        source_type: EvidenceSourceType,
        source_id: Optional[str] = None,
        source_document_id: Optional[str] = None,
        source_location: Optional[str] = None,
        text_excerpt: Optional[str] = None,
        confidence: float = 1.0,
        evidence: Optional[Evidence] = None,
        evidence_id: Optional[str] = None,
    ) -> str:
        """Insert one evidence row and return its id.

        Accepts either an :class:`Evidence` model or loose fields; the model is
        preferred because it validates the source-id requirement.
        """
        if evidence is not None:
            source_type = evidence.source_type
            source_id = evidence.source_id
            source_location = evidence.source_location
            text_excerpt = evidence.text_excerpt
            confidence = evidence.confidence
            created_at = evidence.created_at.isoformat()
        else:
            created_at = self.now()

        identifier = evidence_id or self.new_id()
        self.insert(
            {
                "id": identifier,
                "source_type": source_type.value,
                "source_id": source_id,
                "source_document_id": source_document_id,
                "source_location": source_location,
                "text_excerpt": text_excerpt,
                "confidence": confidence,
                "created_at": created_at,
            }
        )
        return identifier

    def get_model(self, evidence_id: str) -> Optional[Evidence]:
        """Load an evidence row back into the model."""
        row = self.get(evidence_id)
        return None if row is None else self._to_model(row)

    def many_models(self, evidence_ids: list[str]) -> dict[str, Evidence]:
        """Load several evidence rows at once, keyed by id."""
        if not evidence_ids:
            return {}
        placeholders = ", ".join("?" for _ in evidence_ids)
        rows = self.db.query(
            f"SELECT * FROM evidence WHERE id IN ({placeholders})",  # noqa: S608
            tuple(evidence_ids),
        )
        return {row["id"]: self._to_model(row) for row in rows}

    def _to_model(self, row: dict[str, Any]) -> Evidence:
        return Evidence(
            source_type=EvidenceSourceType(row["source_type"]),
            source_id=row["source_id"],
            source_location=row["source_location"],
            text_excerpt=row["text_excerpt"],
            confidence=row["confidence"],
            created_at=row["created_at"],
        )
