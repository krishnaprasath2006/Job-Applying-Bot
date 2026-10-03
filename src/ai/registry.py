from typing import Dict, List, Optional
from src.ai.provider import AIProvider
from src.core.enums import ModelCapability
from src.ai.huggingface import HuggingFaceLocalProvider

class ModelRegistry:
    def __init__(self):
        self._providers: Dict[str, AIProvider] = {}
        self._default_embedding_id = "huggingface_local"

        # Register default HF Local Provider
        hf_provider = HuggingFaceLocalProvider()
        self.register_provider(hf_provider)

    def register_provider(self, provider: AIProvider) -> None:
        self._providers[provider.id] = provider

    def get_provider(self, provider_id: str) -> Optional[AIProvider]:
        return self._providers.get(provider_id)

    def list_providers(self) -> List[AIProvider]:
        return list(self._providers.values())

    def get_embedding_provider(self) -> AIProvider:
        provider = self._providers.get(self._default_embedding_id)
        if provider and provider.supports(ModelCapability.EMBEDDINGS):
            return provider
        for p in self._providers.values():
            if p.supports(ModelCapability.EMBEDDINGS):
                return p
        raise RuntimeError("No registered provider supports embeddings capability.")

    def get_provider_for_capability(self, capability: ModelCapability) -> Optional[AIProvider]:
        for p in self._providers.values():
            if p.supports(capability):
                return p
        return None

global_model_registry = ModelRegistry()
