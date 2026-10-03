import math
import logging
from abc import ABC, abstractmethod
from typing import List, Tuple, Set
from src.ai.provider import AIProvider

logger = logging.getLogger(__name__)

def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a, b in zip(vec_a, vec_b))
    norm_b = sum(b * b for a, b in zip(vec_a, vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    score = dot_product / (math.sqrt(norm_a) * math.sqrt(norm_b))
    return max(0.0, min(1.0, score))

class SemanticScorer(ABC):
    @abstractmethod
    def similarity(self, text1: str, text2: str) -> float:
        pass

    @abstractmethod
    def similarity_batch(self, pairs: List[Tuple[str, str]]) -> List[float]:
        pass

class LexicalScorer(SemanticScorer):
    name: str = "LexicalScorer (Token Overlap / Jaccard)"

    def similarity(self, text1: str, text2: str) -> float:
        tokens_a = self._tokenize(text1)
        tokens_b = self._tokenize(text2)

        if not tokens_a or not tokens_b:
            return 0.0

        intersection = tokens_a.intersection(tokens_b)
        union = tokens_a.union(tokens_b)
        return len(intersection) / len(union) if union else 0.0

    def similarity_batch(self, pairs: List[Tuple[str, str]]) -> List[float]:
        return [self.similarity(t1, t2) for t1, t2 in pairs]

    def _tokenize(self, text: str) -> Set[str]:
        cleaned = "".join(c if c.isalnum() else " " for c in text.lower())
        words = [w for w in cleaned.split() if len(w) > 2]
        stop_words = {"the", "and", "for", "with", "that", "this", "from", "have", "are"}
        return set(w for w in words if w not in stop_words)

class EmbeddingScorer(SemanticScorer):
    name: str = "EmbeddingScorer (Hugging Face Dense Semantic)"

    def __init__(self, provider: AIProvider):
        self.provider = provider
        self.fallback_scorer = LexicalScorer()

    def similarity(self, text1: str, text2: str) -> float:
        try:
            embeddings = self.provider.get_embeddings([text1, text2])
            if len(embeddings) == 2:
                return cosine_similarity(embeddings[0], embeddings[1])
            raise ValueError(f"Expected 2 embeddings, got {len(embeddings)}")
        except Exception as e:
            logger.warning(
                f"[EmbeddingScorer] Model provider '{self.provider.id}' failed: {e}. "
                "Safely degrading to LexicalScorer fallback."
            )
            return self.fallback_scorer.similarity(text1, text2)

    def similarity_batch(self, pairs: List[Tuple[str, str]]) -> List[float]:
        if not pairs:
            return []
        try:
            unique_texts = list({text for pair in pairs for text in pair})
            text_to_idx = {text: i for i, text in enumerate(unique_texts)}
            embeddings = self.provider.get_embeddings(unique_texts)

            return [
                cosine_similarity(embeddings[text_to_idx[t1]], embeddings[text_to_idx[t2]])
                for t1, t2 in pairs
            ]
        except Exception as e:
            logger.warning(
                f"[EmbeddingScorer] Batch inference failed: {e}. Safely degrading to LexicalScorer fallback."
            )
            return self.fallback_scorer.similarity_batch(pairs)
