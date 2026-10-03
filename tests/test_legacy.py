"""Legacy compatibility guard.

The original bot is still importable and still runnable. Phase 2 sits beside
it, not on top of it: the assistant's settings, logging, and safety code must
not shadow or change the modules ``linkedin.py`` imports. These tests are mostly
import and identity assertions, which is the point: they fail loudly the moment
something claims the legacy names.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

LEGACY_MODULES = ("config", "constants", "utils", "linkedin")


class TestLegacyModulesImport:
    @pytest.mark.parametrize("name", LEGACY_MODULES)
    def test_the_module_imports(self, name: str) -> None:
        import importlib

        assert importlib.import_module(name) is not None

    @pytest.mark.parametrize("name", LEGACY_MODULES)
    def test_the_module_comes_from_the_repository_root(self, name: str, project_root: Path) -> None:
        import importlib

        module = importlib.import_module(name)
        # If the assistant ever ships a same-named package, this is what stops
        # the legacy bot from quietly importing the wrong file.
        assert Path(module.__file__).resolve().parent == project_root.resolve()

    @pytest.mark.parametrize("name", LEGACY_MODULES)
    def test_importing_a_legacy_module_does_not_load_the_assistant(self, name: str) -> None:
        # The bot must not start paying for the assistant's settings stack as a
        # side effect of importing its own config.
        code = (
            f"import sys; sys.path.insert(0, 'src'); "
            f"import {name}; "
            f"print(int('core.settings' in sys.modules))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0"


class TestLegacySymbolsAreIntact:
    def test_config_exposes_the_names_the_bot_reads(self) -> None:
        import config

        for name in (
            "browser",
            "email",
            "password",
            "Phone",
            "preferredCv",
            "dryRun",
            "blacklistCompanies",
            "blackListTitles",
            "followCompanies",
            "maxApplicationsPerRun",
            "displayWarnings",
            "credentialsMissing",
        ):
            assert hasattr(config, name), f"config.{name} disappeared"

    def test_constants_exposes_the_selectors_the_bot_clicks(self) -> None:
        import constants

        for name in ("jobsPageUrl", "linkJobUrl", "easyApplyButton", "botSpeed"):
            assert hasattr(constants, name)

    def test_utils_exposes_the_driver_helpers(self) -> None:
        import utils

        for name in ("createDriver", "edgeBrowserOptions", "chromeBrowserOptions", "prYellow"):
            assert hasattr(utils, name)

    def test_the_browser_helpers_are_the_only_place_a_driver_is_built(self) -> None:
        # A driver factory inside the assistant would be the first step toward
        # submitting applications, which Phase 2 forbids.
        import utils

        assert callable(utils.createDriver)
        source = Path(utils.__file__).read_text(encoding="utf-8")
        assert "def createDriver" in source


class TestEntryPointShadowing:
    def test_the_assistant_is_not_importable_as_assistant_at_the_root(self) -> None:
        # ``assistant`` must resolve to src/assistant only via the documented
        # path setup, so a stale root package cannot shadow it.
        code = (
            "import sys; sys.path.insert(0, 'src'); import assistant.cli as c; "
            "print(c.__file__)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True,
            text=True,
            check=True,
        )
        assert "src" in result.stdout.replace("\\", "/")

    def test_the_root_entry_point_is_named_job_assistant(self, project_root: Path) -> None:
        assert (project_root / "job_assistant.py").exists()
        assert not (project_root / "assistant.py").exists()

    def test_the_cli_reports_the_expected_program_name(self) -> None:
        from assistant.cli import build_parser

        assert build_parser().prog == "job_assistant.py"

    def test_the_cli_help_runs_without_credentials(self, project_root: Path) -> None:
        result = subprocess.run(
            [sys.executable, "job_assistant.py", "--help"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "usage" in result.stdout.lower()


class TestLegacySettingsAgreement:
    def test_the_assistant_reads_the_legacy_dry_run_variable(self, monkeypatch) -> None:
        from core.settings import AssistantSettings

        monkeypatch.setenv("DRY_RUN", "false")
        assert AssistantSettings().legacy_dry_run is False

    def test_the_namespaced_form_is_also_accepted(self, monkeypatch) -> None:
        from core.settings import AssistantSettings

        monkeypatch.setenv("ASSISTANT_DRY_RUN", "false")
        assert AssistantSettings().legacy_dry_run is False

    def test_the_namespaced_form_wins_when_both_are_present(self, monkeypatch) -> None:
        from core.settings import AssistantSettings

        monkeypatch.setenv("ASSISTANT_DRY_RUN", "false")
        monkeypatch.setenv("DRY_RUN", "true")
        assert AssistantSettings().legacy_dry_run is False

    def test_dry_run_defaults_to_true_with_no_environment_at_all(self, monkeypatch) -> None:
        from core.settings import AssistantSettings

        for name in ("DRY_RUN", "ASSISTANT_DRY_RUN"):
            monkeypatch.delenv(name, raising=False)
        assert AssistantSettings().legacy_dry_run is True

    def test_linkedin_credentials_are_never_defaulted(self, monkeypatch) -> None:
        from core.settings import AssistantSettings

        for name in ("LINKEDIN_PASSWORD", "ASSISTANT_LINKEDIN_PASSWORD"):
            monkeypatch.delenv(name, raising=False)
        # _env_file=None keeps this hermetic: a developer's real .env on disk
        # must not change what the test asserts about the default.
        settings = AssistantSettings(_env_file=None)
        assert settings.linkedin_password is None
        assert settings.has_linkedin_credentials is False

    def test_the_legacy_email_variable_feeds_the_assistant(self, monkeypatch) -> None:
        from core.settings import AssistantSettings

        monkeypatch.setenv("LINKEDIN_EMAIL", "synthetic@example.invalid")
        monkeypatch.setenv("LINKEDIN_PASSWORD", "synthetic-not-a-real-password")
        settings = AssistantSettings(_env_file=None)
        # config.py names this variable LINKEDIN_EMAIL; the assistant has to
        # read the same one or the two systems disagree about being logged in.
        assert settings.linkedin_username == "synthetic@example.invalid"
        assert settings.has_linkedin_credentials is True
        assert "synthetic-not-a-real-password" not in repr(settings)
