from typing import Protocol, List, runtime_checkable
from dataclasses import dataclass
from src.core.enums import ModelCapability

@dataclass
class ModelMetadata:
    provider: str
    model_id: str
    dimension: int
    device: str
    runtime: str
    model_revision: str = "v1.0.0-hf1"
    loaded: bool = False
    supports_batching: bool = True
    zero_cost: bool = True
    license: str = "Apache 2.0"

@runtime_checkable
class AIProvider(Protocol):
    id: str
    name: str

    def supports(self, capability: ModelCapability) -> bool:
        ...

    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        ...

    def get_metadata(self) -> ModelMetadata:
        ...
