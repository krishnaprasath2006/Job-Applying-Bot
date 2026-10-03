"""AI provider interface and the default local provider."""

from ai.ollama_provider import OllamaProvider
from ai.provider import (
    AIProvider,
    EmbeddingResult,
    GenerationOptions,
    HealthStatus,
    StructuredResult,
    TextResult,
)
from ai.registry import available_providers, build_provider, get_provider, register_provider

__all__ = [
    "AIProvider",
    "EmbeddingResult",
    "GenerationOptions",
    "HealthStatus",
    "OllamaProvider",
    "StructuredResult",
    "TextResult",
    "available_providers",
    "build_provider",
    "get_provider",
    "register_provider",
]