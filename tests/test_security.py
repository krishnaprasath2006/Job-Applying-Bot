"""Security tests: what must never be committed, logged, or printed.

These tests read the repository's own ignore rules and source files. They are
deliberately blunt: a secret in a tracked file, or a credential in a log line,
is a failure regardless of intent.
"""

from __future__ import annotations

import io
import re
import subprocess
from pathlib import Path

import pytest

TRACKED_TEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".env", ".json"}
SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules", ".pytest_cache"}

#: Values that look like credentials. Patterns are intentionally narrow so a
#: legitimate word is not flagged; the tests below assert on the matches rather
#: than trusting the pattern.
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]

PLACEHOLDER_MARKERS = ("changeme", "your-", "placeholder", "example", "not-a-real", "synthetic", "xxx")


def tracked_files(project_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return [project_root / line for line in result.stdout.splitlines() if line.strip()]


def iter_repo_text(project_root: Path):
    for path in project_root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.suffix.lower() not in TRACKED_TEXT_SUFFIXES:
            continue
        if path.name == ".env":  # the real .env is ignored; only .env.example may exist
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


class TestNoSecretsCommitted:
    def test_no_credential_shaped_string_in_tracked_files(self, project_root: Path) -> None:
        offenders = []
        for path in tracked_files(project_root):
            if path.suffix.lower() not in TRACKED_TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    offenders.append(f"{path.name}: {pattern.pattern}")
        assert offenders == []

    def test_the_real_env_file_is_ignored(self, project_root: Path) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "-q", ".env"],
            cwd=str(project_root),
            capture_output=True,
        )
        assert result.returncode == 0, ".env must be ignored"

    def test_the_real_profile_is_ignored(self, project_root: Path) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "data/profile/candidate_profile.json"],
            cwd=str(project_root),
            capture_output=True,
        )
        assert result.returncode == 0

    def test_the_example_profile_is_not_ignored(self, project_root: Path) -> None:
        # The documented example has to be committable, or nobody can see it.
        result = subprocess.run(
            ["git", "check-ignore", "-q", "data/profile/candidate_profile.example.json"],
            cwd=str(project_root),
            capture_output=True,
        )
        assert result.returncode != 0

    def test_local_databases_and_logs_are_ignored(self, project_root: Path) -> None:
        for candidate in ("data/assistant.db", "data/logs/app.log"):
            result = subprocess.run(
                ["git", "check-ignore", "-q", candidate],
                cwd=str(project_root),
                capture_output=True,
            )
            assert result.returncode == 0, f"{candidate} must be ignored"

    def test_no_env_file_is_tracked(self, project_root: Path) -> None:
        names = {p.name for p in tracked_files(project_root)}
        assert ".env" not in names
        assert "cookies.json" not in names


class TestIgnoreRules:
    def test_bytecode_is_not_tracked(self, project_root: Path) -> None:
        assert not [p for p in tracked_files(project_root) if p.suffix == ".pyc"]

    def test_the_private_data_patterns_are_present(self, project_root: Path) -> None:
        text = (project_root / ".gitignore").read_text(encoding="utf-8")
        for pattern in (".env", "data/resumes", "*.log", "__pycache__"):
            assert pattern in text

    def test_synthetic_fixtures_are_explicitly_permitted(self, project_root: Path) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "tests/fixtures/synthetic_resume.pdf"],
            cwd=str(project_root),
            capture_output=True,
        )
        assert result.returncode != 0


class TestLoggingRedaction:
    def test_a_secret_is_not_present_in_a_settings_repr(self) -> None:
        from core.settings import AssistantSettings

        rendered = repr(AssistantSettings(linkedin_password="SYNTHETIC-NOT-A-REAL-PASSWORD"))
        assert "SYNTHETIC-NOT-A-REAL-PASSWORD" not in rendered

    def test_the_log_formatter_redacts_secret_shaped_keys(self) -> None:
        from core.redaction import MASK, redact

        assert redact("password=SYNTHETIC-NOT-A-REAL-PASSWORD") == f"password={MASK}"
        assert redact("api_key: SYNTHETIC-NOT-A-REAL-PASSWORD") == f"api_key: {MASK}"
        assert redact("plain progress message") == "plain progress message"

    def test_a_registered_literal_is_scrubbed_from_any_text(self) -> None:
        from core.redaction import MASK, REDACTOR, register_secret

        register_secret("SYNTHETIC-REGISTERED-SECRET")
        try:
            scrubbed = REDACTOR.scrub("using SYNTHETIC-REGISTERED-SECRET now")
            assert "SYNTHETIC-REGISTERED-SECRET" not in scrubbed
            assert MASK in scrubbed
        finally:
            REDACTOR.unregister_all()

    def test_a_very_short_secret_is_not_registered(self) -> None:
        # Masking a two-character value would corrupt unrelated log text.
        from core.redaction import REDACTOR

        REDACTOR.register("ab")
        REDACTOR.unregister_all()
        assert REDACTOR.scrub("about") == "about"

    def test_resume_bodies_are_not_logged_by_default(self) -> None:
        from core.settings import LoggingSettings

        assert LoggingSettings().log_resume_bodies is False

    def test_model_run_metadata_rejects_secret_shaped_keys(self) -> None:
        from pydantic import ValidationError

        from core.model_run import ModelRun

        with pytest.raises(ValidationError):
            ModelRun(task="extract", provider="ollama", model="synthetic", metadata={
                "api_key": "SYNTHETIC-NOT-A-REAL"
            })


class TestNoSubmissionCode:
    def test_no_phase2_module_imports_the_browser_automation_stack(self, project_root: Path) -> None:
        # Phase 2 is a foundation. Nothing under src/ may drive a browser, and
        # the only legacy entry point stays where it was.
        offenders = []
        for path, text in iter_repo_text(project_root):
            if "src" not in path.parts:
                continue
            if re.search(r"^\s*import\s+selenium|^\s*from\s+selenium", text, re.MULTILINE):
                offenders.append(str(path.relative_to(project_root)))
        assert offenders == []

    def test_the_safety_switches_are_true_in_the_committed_example_env(self, project_root: Path) -> None:
        example = project_root / ".env.example"
        if not example.exists():
            pytest.skip("no .env.example committed")
        text = example.read_text(encoding="utf-8").lower()
        assert "dry_run=true" in text.replace(" ", "")
        assert "safe_mode=true" in text.replace(" ", "")
        assert "allow_final_submission=false" in text.replace(" ", "")


class TestSyntheticDataSeparation:
    def test_the_test_resume_declares_itself_synthetic(self, fixtures_dir: Path) -> None:
        text = (fixtures_dir / "synthetic_resume.txt").read_text(encoding="utf-8").lower()
        assert "synthetic" in text

    def test_the_job_fixture_declares_itself_synthetic(self, fixtures_dir: Path) -> None:
        text = (fixtures_dir / "synthetic_job_description.txt").read_text(encoding="utf-8").lower()
        assert "synthetic" in text

    def test_no_fixture_contains_a_plausible_personal_phone_number(self, fixtures_dir: Path) -> None:
        # A synthetic fixture should be obviously fake, not plausibly real.
        # Date ranges like "2016-06 - 2020-05" are not phone numbers, so the
        # pattern requires a leading country code or a parenthesised group.
        pattern = re.compile(r"(?:\+\d{1,3}[\s-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3,4}[\s.-]\d{3,4}")
        for path in sorted(fixtures_dir.glob("*.txt")):
            for match in pattern.findall(path.read_text(encoding="utf-8")):
                digits = re.sub(r"\D", "", match)
                assert digits.endswith("0000") or "555" in digits, f"{path.name}: {match}"

    def test_the_example_profile_uses_an_invalid_tld(self, project_root: Path) -> None:
        text = (project_root / "data" / "profile" / "candidate_profile.example.json").read_text(
            encoding="utf-8"
        )
        assert ".invalid" in text
        assert "@gmail.com" not in text and "@outlook.com" not in text

    def test_placeholders_in_env_example_are_obvious(self, project_root: Path) -> None:
        example = project_root / ".env.example"
        if not example.exists():
            pytest.skip("no .env.example committed")
        sensitive = re.compile(
            r"pass(word|wd)?|secret|token|api[_-]?key|credential|private[_-]?key", re.IGNORECASE
        )
        for line in example.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if not value or not sensitive.search(key):
                continue
            assert any(marker in value.lower() for marker in PLACEHOLDER_MARKERS), line
