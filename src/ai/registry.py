"""Provider registry.

Business logic asks for a provider by name and receives an interface. It never
imports a concrete provider, so adding a hosted provider later is a
registration line rather than a change to every call site.
"""

from __future__ import annotations

from typing import Callable, Optional

from core.enums import AnalysisSource
from core.errors import ConfigurationError
from core.settings import AISettings
from ai.provider import AIProvider

__all__ = ["get_provider", "build_provider", "register_provider", "available_providers"]

_FACTORIES: dict[str, Callable[[AISettings], AIProvider]] = {}


def register_provider(name: str, factory: Callable[[AISettings], AIProvider]) -> None:
    """Register a provider factory under ``name``.

    Raises:
        ValueError: If ``name`` is empty or already registered.
    """
    key = (name or "").strip().lower()
    if not key:
        raise ValueError("provider name must not be empty")
    if key in _FACTORIES:
        raise ValueError(f"provider {key!r} is already registered")
    _FACTORIES[key] = factory


def available_providers() -> list[str]:
    return sorted(_FACTORIES)


def build_provider(settings: AISettings) -> AIProvider:
    """Instantiate the provider named in ``settings.ai.provider``.

    Raises:
        ConfigurationError: If the provider is not registered. This is a
            configuration mistake, not a runtime failure, so it is reported
            plainly instead of being papered over with a default.
    """
    key = (settings.provider or "").strip().lower()
    factory = _FACTORIES.get(key)
    if factory is None:
        raise ConfigurationError(
            "unknown AI provider",
            provider=settings.provider,
            registered=available_providers(),
        )
    return factory(settings)


def get_provider(settings: Optional[AISettings] = None) -> AIProvider:
    """Build a provider from configuration.

    With no argument, loads the default local provider, which needs no API key.
    """
    return build_provider(settings or AISettings())


def _register_ollama() -> None:
    from ai.ollama_provider import OllamaProvider

    register_provider("ollama", lambda settings: OllamaProvider(settings))


_register_ollama()
