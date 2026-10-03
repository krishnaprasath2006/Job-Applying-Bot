import hashlib
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class ModelCacheFingerprint:
    provider: str
    model_id: str
    model_revision: str
    dimension: int
    input_hash: str

class ModelEmbeddingCache:
    def __init__(self):
        self._cache: Dict[str, List[float]] = {}

    def compute_fingerprint(
        self,
        provider: str,
        model_id: str,
        model_revision: str,
        dimension: int,
        text: str
    ) -> ModelCacheFingerprint:
        input_hash = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
        return ModelCacheFingerprint(
            provider=provider,
            model_id=model_id,
            model_revision=model_revision,
            dimension=dimension,
            input_hash=input_hash
        )

    def get_cache_key(self, fp: ModelCacheFingerprint) -> str:
        return f"{fp.provider}::{fp.model_id}::{fp.model_revision}::{fp.dimension}::{fp.input_hash}"

    def get(self, fp: ModelCacheFingerprint) -> Optional[List[float]]:
        key = self.get_cache_key(fp)
        return self._cache.get(key)

    def set(self, fp: ModelCacheFingerprint, vector: List[float]) -> None:
        key = self.get_cache_key(fp)
        self._cache[key] = vector

    def size(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()

global_embedding_cache = ModelEmbeddingCache()
