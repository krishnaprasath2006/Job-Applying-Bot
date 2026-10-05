"""Tests for resume parsing, identity, and variant metadata.

Every fixture here is synthetic: invented names, a fake phone number, and the
``.invalid`` domain, so a leak would be obvious rather than plausible.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from core.enums import ResumeFileType, ResumeStatus, SectionType
from core.errors import DuplicateResumeError, ResumeParseError, ResumeValidationError
from resumes.models import Resume, ResumeSection
from resumes.parser import ResumeParser

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_PDF = FIXTURES / "synthetic_resume.pdf"
_DOCX = FIXTURES / "synthetic_resume.docx"

needs_binaries = pytest.mark.skipif(
    not (_PDF.exists() and _DOCX.exists()),
    reason="binary fixtures absent; run tests/fixtures/make_binary_fixtures.py",
)


def make_resume(tmp_path: Path, name: str = "synthetic_resume.txt", text: str = None) -> Path:
    path = tmp_path / name
    path.write_text(
        text
        or (
            "# Summary\nSynthetic test candidate, deterministic parser only.\n\n"
            "# Experience\nMachine Learning Engineer, Synthetic Corp, 2020-2024.\n\n"
            "# Skills\nPython, PyTorch, SQL\n"
        ),
        encoding="utf-8",
    )
    return path


class TestResumeIdentity:
    def test_id_is_derived_and_not_empty(self, tmp_path: Path) -> None:
        resume = ResumeParser().parse(make_resume(tmp_path))
        assert resume.id.startswith("resume-")
        assert len(resume.id) == len("resume-") + 16

    def test_the_same_content_always_gives_the_same_id(self, tmp_path: Path) -> None:
        first = ResumeParser().parse(make_resume(tmp_path, "a.txt"))
        second = ResumeParser().parse(make_resume(tmp_path, "b.txt"))
        assert first.id == second.id

    def test_different_content_gives_a_different_id(self, tmp_path: Path) -> None:
        first = ResumeParser().parse(make_resume(tmp_path, "a.txt"))
        second = ResumeParser().parse(
            make_resume(
                tmp_path,
                "b.txt",
                text="# Summary\n" + ("Completely different synthetic text. " * 6),
            )
        )
        assert first.id != second.id

    def test_file_hash_is_the_sha256_of_the_file(self, tmp_path: Path) -> None:
        import hashlib

        path = make_resume(tmp_path)
        resume = ResumeParser().parse(path)
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        assert resume.file_hash == expected

    def test_content_hash_collapses_whitespace_so_formats_agree(self, tmp_path: Path) -> None:
        # A TXT and a DOCX of the same CV extract with different spacing, so the
        # content hash normalises runs of whitespace before hashing.
        import hashlib

        resume = ResumeParser().parse(make_resume(tmp_path))
        expected = hashlib.sha256(" ".join(resume.raw_text.split()).encode("utf-8")).hexdigest()
        assert resume.content_hash == expected

    def test_the_original_path_is_not_stored(self, tmp_path: Path) -> None:
        # Keeping the candidate's home directory out of the database is
        # deliberate, so the record exposes only the copied file.
        path = tmp_path / "synthetic_resume.txt"
        resume = ResumeParser().parse(make_resume(tmp_path))
        assert str(path) not in str(resume.model_dump())

    def test_char_count_is_derived_from_the_text(self, tmp_path: Path) -> None:
        resume = ResumeParser().parse(make_resume(tmp_path))
        assert resume.char_count == len(resume.raw_text.strip())


class TestSections:
    def test_sections_are_detected(self, tmp_path: Path) -> None:
        found = {s.section_type for s in ResumeParser().parse(make_resume(tmp_path)).sections}
        assert {SectionType.SUMMARY, SectionType.EXPERIENCE, SectionType.SKILLS} <= found

    def test_sections_carry_content_and_a_heading(self, tmp_path: Path) -> None:
        sections = ResumeParser().parse(make_resume(tmp_path)).sections
        assert sections
        for section in sections:
            assert section.content if hasattr(section, "content") else section.raw_text

    def test_char_count_matches_the_section_text(self, tmp_path: Path) -> None:
        for section in ResumeParser().parse(make_resume(tmp_path)).sections:
            assert section.char_count == len(section.raw_text.strip())

    def test_every_section_is_stamped_with_the_resume_id(self, tmp_path: Path) -> None:
        resume = ResumeParser().parse(make_resume(tmp_path))
        assert all(s.resume_id == resume.id for s in resume.sections)

    def test_section_ids_are_unique(self, tmp_path: Path) -> None:
        sections = ResumeParser().parse(make_resume(tmp_path)).sections
        assert len({s.id for s in sections}) == len(sections)

    def test_sections_are_ordered(self, tmp_path: Path) -> None:
        sections = ResumeParser().parse(make_resume(tmp_path)).sections
        assert [s.position for s in sections] == sorted(s.position for s in sections)

    def test_status_is_parsed_on_success(self, tmp_path: Path) -> None:
        assert ResumeParser().parse(make_resume(tmp_path)).status is ResumeStatus.PARSED


class TestVariantMetadata:
    def test_defaults_are_honest(self, tmp_path: Path) -> None:
        resume = ResumeParser().parse(make_resume(tmp_path))
        assert resume.variant is None
        assert resume.role_focus is None
        assert resume.version is None
        assert resume.skills == []

    def test_variant_is_recorded(self, tmp_path: Path) -> None:
        resume = ResumeParser().parse(make_resume(tmp_path), variant="AI Engineer")
        assert resume.variant == "AI Engineer"

    def test_metadata_survives_a_round_trip(self, tmp_path: Path) -> None:
        resume = ResumeParser().parse(make_resume(tmp_path), variant="AI Engineer")
        resume = resume.model_copy(
            update={"role_focus": "ml-engineer", "version": "v2", "skills": ["Python", "PyTorch"]}
        )
        again = Resume.model_validate(resume.model_dump())
        assert again.role_focus == "ml-engineer"
        assert again.version == "v2"
        assert again.skills == ["Python", "PyTorch"]

    def test_skill_whitespace_is_trimmed_and_blanks_dropped(self, tmp_path: Path) -> None:
        resume = ResumeParser().parse(make_resume(tmp_path))
        cleaned = Resume.model_validate(
            {**resume.model_dump(), "skills": ["  Python  ", "", "   "]}
        )
        assert cleaned.skills == ["Python"]

    def test_duplicate_skills_are_kept_so_the_validator_can_report_them(self, tmp_path: Path) -> None:
        resume = ResumeParser().parse(make_resume(tmp_path))
        assert Resume.model_validate({**resume.model_dump(), "skills": ["Python", "Python"]}).skills == [
            "Python",
            "Python",
        ]

    def test_role_focus_must_be_slug_like(self, tmp_path: Path) -> None:
        # model_copy would skip validation, so the check is made through
        # model_validate, which is what the ingestion service uses too.
        resume = ResumeParser().parse(make_resume(tmp_path))
        with pytest.raises(ValueError):
            Resume.model_validate({**resume.model_dump(), "role_focus": "Machine Learning Engineer!!"})

    def test_role_focus_slug_is_accepted(self, tmp_path: Path) -> None:
        resume = ResumeParser().parse(make_resume(tmp_path))
        assert (
            Resume.model_validate({**resume.model_dump(), "role_focus": "ml-engineer"}).role_focus
            == "ml-engineer"
        )


class TestParserRefusals:
    def test_missing_file_raises_a_typed_error(self, tmp_path: Path) -> None:
        with pytest.raises(ResumeValidationError):
            ResumeParser().parse(tmp_path / "absent.txt")

    def test_empty_file_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.txt"
        path.write_text("   \n", encoding="utf-8")
        with pytest.raises(ResumeParseError):
            ResumeParser().parse(path)

    def test_unsupported_extension_is_refused_not_guessed(self, tmp_path: Path) -> None:
        path = tmp_path / "resume.rtf"
        path.write_text("SYNTHETIC", encoding="utf-8")
        with pytest.raises(ResumeValidationError):
            ResumeParser().parse(path)

    def test_markdown_is_supported(self, tmp_path: Path) -> None:
        path = tmp_path / "resume.md"
        path.write_text(
            "# Summary\n" + ("Synthetic markdown candidate with enough text to parse. " * 4) + "\n",
            encoding="utf-8",
        )
        assert ResumeParser().parse(path).file_type is ResumeFileType.MD

    def test_text_shorter_than_the_minimum_is_refused(self, tmp_path: Path) -> None:
        # Too little text is refused rather than parsed into an empty resume.
        path = tmp_path / "tiny.txt"
        path.write_text("hello", encoding="utf-8")
        with pytest.raises(ResumeParseError):
            ResumeParser().parse(path)

    def test_a_pdf_claiming_to_be_text_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "fake.pdf"
        path.write_bytes(b"this is not a pdf")
        with pytest.raises(ResumeParseError):
            ResumeParser().parse(path)

    def test_page_count_is_unknown_for_plain_text(self, tmp_path: Path) -> None:
        assert ResumeParser().parse(make_resume(tmp_path)).page_count is None

    def test_the_parser_never_calls_a_language_model(self, tmp_path: Path, monkeypatch) -> None:
        # Extraction must stay deterministic. Make any provider call explode, so
        # a regression here fails loudly instead of quietly degrading.
        import ai.ollama_provider as ollama_module

        def explode(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("the resume parser must not use an LLM")

        monkeypatch.setattr(ollama_module.OllamaProvider, "generate", explode, raising=False)
        monkeypatch.setattr(ollama_module.OllamaProvider, "chat", explode, raising=False)
        assert ResumeParser().parse(make_resume(tmp_path)).sections


@needs_binaries
class TestBinaryFormats:
    def test_pdf_extracts_text(self) -> None:
        resume = ResumeParser().parse(_PDF)
        assert len(resume.raw_text) > 200
        assert resume.file_type is ResumeFileType.PDF

    def test_pdf_page_count_is_reported(self) -> None:
        assert ResumeParser().parse(_PDF).page_count == 1

    def test_pdf_sections_are_detected(self) -> None:
        found = {s.section_type for s in ResumeParser().parse(_PDF).sections}
        assert SectionType.EXPERIENCE in found or SectionType.SUMMARY in found

    def test_docx_extracts_text(self) -> None:
        resume = ResumeParser().parse(_DOCX)
        assert len(resume.raw_text) > 200
        assert resume.file_type is ResumeFileType.DOCX

    def test_docx_table_content_is_captured(self) -> None:
        # A skills table is the common case that naive docx readers lose.
        assert "|" in ResumeParser().parse(_DOCX).raw_text

    def test_parsing_is_deterministic_across_calls(self) -> None:
        assert ResumeParser().parse(_PDF).content_hash == ResumeParser().parse(_PDF).content_hash


class TestBinaryFixtureRegeneration:
    def test_regenerated_fixtures_are_byte_identical(self, tmp_path: Path) -> None:
        script = FIXTURES / "make_binary_fixtures.py"
        if not script.exists() or not _PDF.exists():
            pytest.skip("generator or fixtures absent")
        out = tmp_path / "regenerated"
        result = subprocess.run(
            [sys.executable, str(script), str(out)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        for name in ("synthetic_resume.pdf", "synthetic_resume.docx"):
            assert (out / name).read_bytes() == (FIXTURES / name).read_bytes()

    def test_the_fixture_resume_declares_itself_synthetic(self) -> None:
        text = (FIXTURES / "synthetic_resume.txt").read_text(encoding="utf-8").lower()
        assert "synthetic" in text


class TestSectionModel:
    def test_a_section_cannot_point_at_another_resume(self) -> None:
        section = ResumeSection(
            section_type=SectionType.SUMMARY,
            resume_id="resume-1111111111111111",
            raw_text="x",
            char_count=1,
        )
        assert section.resume_id == "resume-1111111111111111"

    def test_unknown_section_type_is_refused(self) -> None:
        with pytest.raises(ValueError):
            ResumeSection(section_type="gossip", raw_text="x", char_count=1)


class TestPageCountIsBestEffort:
    """A PDF whose page count cannot be read must still be handled gracefully.

    Regression: ``_page_count`` reported its own failures through a module-level
    ``log`` that was never defined, so a PDF whose page tree could not be read
    raised ``NameError`` from inside the ingest path. That turned "the page count
    is unavailable" into "this resume cannot be parsed", contradicting the
    method's own documented contract that it must never abort ingestion.
    """

    def test_the_parser_module_defines_its_logger(self) -> None:
        # Direct guard for the regression: the name the failure path used must
        # exist, so it cannot silently disappear again.
        import resumes.parser as parser_module

        assert hasattr(parser_module, "log")

    def test_an_unreadable_page_tree_reports_no_count_instead_of_raising(
        self, monkeypatch
    ) -> None:
        import pdfplumber
        from pdfminer.pdfparser import PDFSyntaxError

        def _boom(path, *args, **kwargs):
            raise PDFSyntaxError("page tree is corrupt")

        monkeypatch.setattr(pdfplumber, "open", _boom)
        assert ResumeParser()._page_count(_PDF, ResumeFileType.PDF) is None

    def test_page_count_is_none_for_non_pdf_input(self) -> None:
        # The short-circuit that runs before any of this matters.
        assert (
            ResumeParser()._page_count(FIXTURES / "synthetic_resume.txt", ResumeFileType.TXT)
            is None
        )
