"""AI provider interface and the local providers."""

from ai.huggingface import HuggingFaceLocalProvider
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
    "HuggingFaceLocalProvider",
    "OllamaProvider",
    "StructuredResult",
    "TextResult",
    "available_providers",
    "build_provider",
    "get_provider",
    "register_provider",
]