"""Resume hashing and duplicate detection.

Content identity is the SHA-256 of the file bytes, not the filename. Renaming
``resume.pdf`` to ``final_resume_v2.pdf`` does not create a new resume, and
re-exporting the same CV does not either. Filenames are recorded as metadata
but never used as identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.errors import ConfigurationError, DuplicateResumeError, ResumeValidationError
from core.hashing import sha256_file, sha256_text
from core.enums import ResumeFileType

__all__ = [
    "SUPPORTED_SUFFIXES",
    "detect_file_type",
    "hash_file",
    "hash_text",
    "DuplicateCheck",
    "ensure_ingestable",
    "MAX_RESUME_BYTES",
]

#: Explicit allowlist. Anything else is refused rather than guessed at.
SUPPORTED_SUFFIXES: dict[str, ResumeFileType] = {
    ".pdf": ResumeFileType.PDF,
    ".docx": ResumeFileType.DOCX,
    ".txt": ResumeFileType.TXT,
    ".md": ResumeFileType.MD,
}

#: 25 MB. Large enough for any real resume, small enough that a mistaken
#: selection of a huge file fails fast instead of exhausting memory.
MAX_RESUME_BYTES = 25 * 1024 * 1024

#: A document with almost no extractable text is not a resume. This catches
#: scanned-image PDFs and empty files, both of which would otherwise ingest as
#: a "successful" parse with zero content.
MIN_TEXT_CHARS = 80


@dataclass(frozen=True)
class DuplicateCheck:
    """Result of checking whether content has been ingested before."""

    file_hash: str
    is_duplicate: bool
    existing_resume_id: Optional[str] = None
    existing_filename: Optional[str] = None

    def raise_if_duplicate(self) -> None:
        """Raise :class:`DuplicateResumeError` when this is a duplicate."""
        if self.is_duplicate:
            raise DuplicateResumeError(
                "this exact file content has already been ingested",
                file_hash=self.file_hash,
                resume_id=self.existing_resume_id,
            )


def detect_file_type(path: Path | str) -> ResumeFileType:
    """Return the resume type implied by a file's suffix.

    Raises:
        ResumeValidationError: If the suffix is not in the allowlist.
    """
    suffix = Path(path).suffix.lower()
    detected = SUPPORTED_SUFFIXES.get(suffix)
    if detected is None:
        raise ResumeValidationError(
            "unsupported resume file type",
            path=str(path),
            suffix=suffix,
            supported=sorted(SUPPORTED_SUFFIXES),
        )
    return detected


def hash_file(path: Path | str) -> str:
    """Return the SHA-256 of a file's bytes."""
    return sha256_file(path)


def hash_text(text: str) -> str:
    """Return the SHA-256 of normalised text.

    Used to detect the *same content* arriving in a different container, e.g.
    a DOCX and a TXT of the same resume. Whitespace is collapsed first
    because PDF and DOCX extraction differ in spacing.
    """
    return sha256_text(" ".join(text.split()))


def ensure_ingestable(path: Path | str) -> tuple[Path, ResumeFileType, int]:
    """Validate a file before parsing.

    Checks existence, regular-file status, supported suffix, and size.

    Returns:
        ``(path, file_type, size_bytes)``

    Raises:
        ResumeValidationError: If the file cannot be ingested, with the reason.
    """
    target = Path(path)
    if not target.exists():
        raise ResumeValidationError("resume file does not exist", path=str(target))
    if not target.is_file():
        raise ResumeValidationError("resume path is not a regular file", path=str(target))

    file_type = detect_file_type(target)

    try:
        size = target.stat().st_size
    except OSError as exc:
        raise ResumeValidationError(
            "could not stat resume file", path=str(target), cause=str(exc)
        ) from exc

    if size == 0:
        raise ResumeValidationError("resume file is empty", path=str(target))
    if size > MAX_RESUME_BYTES:
        raise ResumeValidationError(
            "resume file exceeds the maximum allowed size",
            path=str(target),
            size_bytes=size,
            max_bytes=MAX_RESUME_BYTES,
        )
    return target, file_type, size
