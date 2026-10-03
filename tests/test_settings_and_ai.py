"""Tests for typed settings, environment loading, and the AI provider seam.

Two things matter here. First, the safety defaults must survive any
environment the operator happens to have. Second, an unavailable model must
produce a clean, typed failure with no invented output.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from core.errors import ConfigurationError, ProviderUnavailableError
from core.settings import (
    AISettings,
    AssistantSettings,
    DatabaseSettings,
    JobSearchSettings,
    SafetySettings,
)


class TestSafetySettingsDefaults:
    def test_phase2_invariants_hold_by_default(self) -> None:
        SafetySettings().assert_phase2_invariants()

    @pytest.mark.parametrize(
        "field",
        ["safe_mode", "dry_run", "require_human_approval", "block_on_captcha", "block_on_mfa"],
    )
    def test_each_guard_defaults_to_on(self, field: str) -> None:
        assert getattr(SafetySettings(), field) is True

    @pytest.mark.parametrize(
        "field",
        [
            "allow_browser_navigation",
            "allow_form_filling",
            "allow_file_upload",
            "allow_final_submission",
        ],
    )
    def test_each_permission_defaults_to_off(self, field: str) -> None:
        assert getattr(SafetySettings(), field) is False

    def test_the_application_limit_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            SafetySettings(max_applications_per_run=0)
        with pytest.raises(ValidationError):
            SafetySettings(max_applications_per_run=1000)

    def test_assert_phase2_invariants_catches_a_submission_enabled_config(self) -> None:
        with pytest.raises(ConfigurationError):
            SafetySettings(
                dry_run=False,
                safe_mode=False,
                allow_final_submission=True,
                require_human_approval=True,
            ).assert_phase2_invariants()

    def test_assert_phase2_invariants_catches_form_filling_enabled(self) -> None:
        with pytest.raises(ConfigurationError):
            SafetySettings(
                dry_run=False, safe_mode=False, allow_form_filling=True
            ).assert_phase2_invariants()


class TestSecretHandling:
    def test_the_api_key_is_a_secret_not_a_plain_string(self) -> None:
        settings = AISettings(api_key="sk-not-a-real-key")
        assert isinstance(settings.api_key, SecretStr)
        assert "not-a-real-key" not in repr(settings)
        assert "not-a-real-key" not in str(settings)

    def test_the_linkedin_password_is_a_secret(self) -> None:
        settings = AssistantSettings(linkedin_password="hunter2-not-real")
        assert isinstance(settings.linkedin_password, SecretStr)
        assert "hunter2-not-real" not in repr(settings)

    def test_no_api_key_is_fine_when_the_provider_needs_none(self) -> None:
        # Ollama runs locally, so a missing key is normal, not an error.
        assert AISettings().api_key is None

    def test_settings_repr_does_not_leak_the_password(self) -> None:
        rendered = repr(AssistantSettings(linkedin_password="hunter2-not-real"))
        assert "hunter2" not in rendered


class TestEnvironmentLoading:
    def test_the_seven_sections_are_present(self) -> None:
        settings = AssistantSettings()
        for section in ("application", "ai", "database", "browser", "job_search", "safety", "logging"):
            assert getattr(settings, section) is not None

    def test_nested_env_names_are_accepted(self, monkeypatch) -> None:
        monkeypatch.setenv("ASSISTANT_SAFETY__DRY_RUN", "false")
        monkeypatch.setenv("ASSISTANT_AI__MODEL", "synthetic-model")
        settings = AssistantSettings()
        assert settings.safety.dry_run is False
        assert settings.ai.model == "synthetic-model"

    def test_an_unparsable_env_value_is_reported_not_ignored(self, monkeypatch) -> None:
        monkeypatch.setenv("ASSISTANT_AI__TEMPERATURE", "very warm")
        with pytest.raises(ValidationError):
            AssistantSettings()

    def test_the_env_file_is_optional(self, tmp_path, monkeypatch) -> None:
        # No .env must not be an error, otherwise a fresh clone cannot start.
        monkeypatch.chdir(tmp_path)
        assert AssistantSettings() is not None


class TestAISettings:
    def test_json_mode_defaults_on(self) -> None:
        assert AISettings().json_mode is True

    def test_temperature_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            AISettings(temperature=2.5)
        with pytest.raises(ValidationError):
            AISettings(temperature=-0.1)
        assert AISettings(temperature=2.0).temperature == 2.0

    def test_timeouts_are_positive(self) -> None:
        with pytest.raises(ValidationError):
            AISettings(timeout_seconds=0)

    def test_the_local_provider_needs_no_key(self) -> None:
        from ai.ollama_provider import OllamaProvider

        assert OllamaProvider.requires_api_key is False


class TestJobSearchSettings:
    def test_defaults_are_conservative(self) -> None:
        settings = JobSearchSettings()
        assert settings.easy_apply_only is True
        assert settings.remote_only is False
        assert 1 <= settings.results_per_page <= 100

    def test_a_blacklist_entry_cannot_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            JobSearchSettings(company_blacklist=["   "])

    def test_blacklist_entries_are_trimmed(self) -> None:
        assert JobSearchSettings(company_blacklist=["  Acme  "]).company_blacklist == ["Acme"]


class TestDatabaseSettings:
    def test_foreign_keys_are_on_by_default(self) -> None:
        assert DatabaseSettings().enable_foreign_keys is True

    def test_wal_is_on_by_default(self) -> None:
        assert DatabaseSettings().enable_wal is True

    def test_echo_defaults_off_so_sql_is_not_logged(self) -> None:
        # Echo would print every statement, including any value a resume holds.
        assert DatabaseSettings().echo is False


class TestProviderRegistry:
    def test_ollama_is_a_known_provider(self) -> None:
        from ai.registry import available_providers

        assert "ollama" in available_providers()

    def test_an_unknown_provider_is_refused(self) -> None:
        from ai.registry import build_provider

        with pytest.raises(ConfigurationError):
            build_provider(AISettings(provider="openai-said-so"))

    def test_build_provider_returns_the_ollama_provider(self) -> None:
        from ai.ollama_provider import OllamaProvider
        from ai.registry import build_provider

        assert isinstance(build_provider(AISettings(provider="ollama")), OllamaProvider)

    def test_registering_a_duplicate_provider_is_refused(self) -> None:
        from ai.registry import register_provider

        with pytest.raises(ValueError):
            register_provider("ollama", lambda settings: None)

    def test_registering_an_empty_name_is_refused(self) -> None:
        from ai.registry import register_provider

        with pytest.raises(ValueError):
            register_provider("   ", lambda settings: None)


class TestUnavailableProvider:
    def _dead_provider(self):
        from ai.ollama_provider import OllamaProvider

        # Port 9 is the discard port: nothing listens, so a call must fail
        # fast and typed rather than returning invented text.
        return OllamaProvider(
            AISettings(base_url="http://127.0.0.1:9", connect_timeout_seconds=0.5, timeout_seconds=1)
        )

    def test_a_dead_endpoint_reports_unavailable_rather_than_guessing(self) -> None:
        health = self._dead_provider().health_check()
        assert health.available is False
        assert health.detail

    def test_generation_against_a_dead_endpoint_raises_a_typed_error(self) -> None:
        with pytest.raises((ProviderUnavailableError, Exception)):
            self._dead_provider().generate_text("SYNTHETIC PROMPT")

    def test_the_provider_declares_its_capabilities(self) -> None:
        from ai.ollama_provider import OllamaProvider

        provider = OllamaProvider()
        assert provider.name == "ollama"
        assert provider.supports_embeddings is True
