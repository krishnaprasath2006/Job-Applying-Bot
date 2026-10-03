"""Resume ingestion service.

Orchestrates the full pipeline:

1. validate the file
2. hash it (SHA-256 of the bytes)
3. check for duplicates
4. extract text
5. preserve the raw text
6. build metadata
7. produce structured sections
8. store everything

The original file is opened read-only and never modified, moved, or renamed.
Extracted text is written to a separate location so the original and the
extraction can be compared later.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional, Sequence

from core.enums import ResumeFileType, ResumeStatus
from core.errors import DuplicateResumeError, ResumeParseError, ResumeValidationError
from core.hashing import utc_now
from core.logging_config import get_logger, log_event
from core.paths import Paths, get_paths
from database.connection import Database
from database.repositories.resumes import ResumeRepository
from resumes.hashing import DuplicateCheck, ensure_ingestable, hash_file, hash_text
from resumes.models import Resume
from resumes.parser import ResumeParser

__all__ = ["ResumeService"]

_log = get_logger("resumes.service")


class ResumeService:
    """Ingests, stores, and retrieves resumes."""

    def __init__(
        self,
        db: Database,
        *,
        paths: Optional[Paths] = None,
        copy_originals: bool = True,
        store_text: bool = True,
    ) -> None:
        self.db = db
        self.paths = paths or get_paths()
        self.repository = ResumeRepository(db)
        self.copy_originals = copy_originals
        self.store_text = store_text

    # -- ingest --------------------------------------------------------------
    def ingest(
        self,
        path: Path | str,
        *,
        variant: Optional[str] = None,
        candidate_id: str = "primary",
        is_synthetic: bool = False,
        allow_duplicate: bool = False,
        role_focus: Optional[str] = None,
        skills: Optional[Sequence[str]] = None,
        version: Optional[str] = None,
    ) -> Resume:
        """Run the full ingestion pipeline for one file.

        Args:
            path: The resume file. Read only.
            variant: Intended use, e.g. ``AI Engineer``. Stored and indexed,
                never used to select anything.
            candidate_id: Whose resume this is.
            is_synthetic: Mark as test data. Synthetic resumes are flagged in
                the database so they can never be mistaken for real ones.
            allow_duplicate: Return the existing record instead of raising when
                the same content was already ingested.
            role_focus: Slug naming the role this variant targets, e.g.
                ``machine-learning-engineer``. Recorded for later selection in
                a later phase; nothing here chooses or reorders anything.
            skills: Skills this variant emphasises, in the candidate's order.
            version: Variant version number. Defaults to 1 on first ingest.

        Returns:
            The stored :class:`Resume`.

        Raises:
            ResumeValidationError: The file is missing, unsupported, or empty.
            DuplicateResumeError: The content is already stored and
                ``allow_duplicate`` is false.
            ResumeParseError: Text could not be extracted.
        """
        started = utc_now()
        target, file_type, size = ensure_ingestable(path)
        file_hash = hash_file(target)

        duplicate = self.check_duplicate(file_hash, candidate_id)
        if duplicate.is_duplicate and not allow_duplicate:
            duplicate.raise_if_duplicate()

        parser = ResumeParser(candidate_id=candidate_id, is_synthetic=is_synthetic)
        resume = parser.parse(target, variant=variant)
        if role_focus or skills or version:
            # Variant metadata is recorded, not acted on. Rebuilding through
            # validation rather than model_copy matters here: model_copy skips
            # validation, so an unusable role_focus or version would be stored
            # without complaint.
            changes: dict[str, Any] = {}
            if role_focus:
                changes["role_focus"] = role_focus
            if skills:
                changes["skills"] = list(skills)
            if version:
                changes["version"] = version
            resume = Resume.model_validate({**resume.model_dump(), **changes})

        if duplicate.is_duplicate and allow_duplicate:
            # Same bytes: point at the stored record rather than creating a
            # second copy of identical content.
            existing = self.repository.by_hash(file_hash, candidate_id)
            log_event(
                _log,
                "resume.duplicate_detected",
                duration_ms=int((utc_now() - started).total_seconds() * 1000),
                file_hash=file_hash[:12],
                existing_resume_id=(existing or {}).get("id"),
                action="reused_existing",
            )
            return self.repository.load((existing or {}).get("id", resume.id)) or resume

        content_duplicate = self.repository.by_content_hash(resume.content_hash or "")
        if content_duplicate and content_duplicate["id"] != resume.id:
            resume.metadata["same_content_other_format_as"] = content_duplicate["id"]
            resume.metadata["file_type_differs_from"] = content_duplicate["file_type"]

        self._persist_original(resume, target)
        self._persist_text(resume)
        self.repository.save(resume)

        log_event(
            _log,
            "resume.ingested",
            duration_ms=int((utc_now() - started).total_seconds() * 1000),
            resume_id=resume.id,
            file_type=resume.file_type.value,
            variant=variant,
            chars=resume.char_count,
            sections=len(resume.sections),
            is_synthetic=is_synthetic,
            file_hash=file_hash[:12],
        )
        return resume

    def ingest_many(
        self, paths: list[Path | str], *, candidate_id: str = "primary", is_synthetic: bool = False
    ) -> dict[str, Any]:
        """Ingest several files, reporting per-file outcomes.

        One bad file does not abort the batch. Each outcome is returned so the
        caller can see exactly which file failed and why.
        """
        results: list[dict[str, Any]] = []
        for candidate in paths:
            try:
                resume = self.ingest(
                    candidate, candidate_id=candidate_id, is_synthetic=is_synthetic
                )
                results.append(
                    {
                        "path": str(candidate),
                        "ok": True,
                        "resume_id": resume.id,
                        "status": resume.status.value,
                    }
                )
            except (DuplicateResumeError, ResumeParseError, ResumeValidationError) as exc:
                results.append(
                    {
                        "path": str(candidate),
                        "ok": False,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                )
        return {
            "requested": len(paths),
            "succeeded": sum(1 for r in results if r["ok"]),
            "failed": sum(1 for r in results if not r["ok"]),
            "results": results,
        }

    # -- duplicates ----------------------------------------------------------
    def check_duplicate(self, file_hash: str, candidate_id: str = "primary") -> DuplicateCheck:
        """Return whether this content was already ingested."""
        row = self.repository.by_hash(file_hash, candidate_id)
        if row is None:
            return DuplicateCheck(file_hash=file_hash, is_duplicate=False)
        return DuplicateCheck(
            file_hash=file_hash,
            is_duplicate=True,
            existing_resume_id=row["id"],
            existing_filename=row["filename"],
        )

    def find_duplicates(self, candidate_id: str = "primary") -> list[dict[str, Any]]:
        """List content hashes stored more than once.

        The unique constraint should make this impossible; this exists so a
        regression is visible rather than silent.
        """
        rows = self.db.query(
            "SELECT file_hash, COUNT(*) AS n FROM resumes WHERE candidate_id = ? "
            "GROUP BY file_hash HAVING n > 1",
            (candidate_id,),
        )
        return rows

    # -- retrieval -----------------------------------------------------------
    def get_resume(self, resume_id: str) -> Optional[Resume]:
        return self.repository.load(resume_id)

    def get_resume_by_hash(self, file_hash: str, candidate_id: str = "primary") -> Optional[Resume]:
        row = self.repository.by_hash(file_hash, candidate_id)
        return None if row is None else self.repository.load(row["id"])

    def list_resumes(self, candidate_id: str = "primary") -> list[dict[str, Any]]:
        return self.repository.for_candidate(candidate_id)

    def list_variants(self, candidate_id: str = "primary") -> list[str]:
        return self.repository.variants(candidate_id)

    def section_index(self, candidate_id: str = "primary") -> dict[str, list[dict[str, Any]]]:
        return self.repository.section_index(candidate_id)

    def delete_resume(self, resume_id: str) -> int:
        """Delete a resume row and its sections."""
        return self.repository.delete(resume_id)

    # -- storage -------------------------------------------------------------
    def _persist_original(self, resume: Resume, source: Path) -> None:
        """Copy the original into the managed directory. Never overwrites."""
        if not self.copy_originals:
            return
        target_dir = self.paths.resume_dir / "raw" / resume.candidate_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{resume.id}{source.suffix.lower()}"
        if not target.exists():
            shutil.copy2(source, target)
        resume.storage_path = str(target)
        resume.raw_text_path = None

    def _persist_text(self, resume: Resume) -> None:
        """Write extracted text to its own file, next to the original."""
        if not self.store_text or not resume.raw_text:
            return
        target_dir = self.paths.resume_dir / "parsed" / resume.candidate_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{resume.id}.txt"
        target.write_text(resume.raw_text, encoding="utf-8")
        resume.raw_text_path = str(target)
