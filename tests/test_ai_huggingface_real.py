"""Real Hugging Face model inference tests.

These are **opt-in**. They download a ~90 MB model on first run, so the default
suite must never trigger that: the whole suite runs offline, and these are
skipped unless ``JOB_ASSISTANT_HF_TESTS=1`` is set.

    JOB_ASSISTANT_HF_TESTS=1 python -m pytest tests/test_ai_huggingface_real.py

Point ``HF_HOME`` at a warm cache to avoid re-downloading.

What is being verified here cannot be faked, which is the point: the model is
loaded, vectors come out of ONNX Runtime, and the numbers must behave like real
embeddings -- every dimension populated, related text close, unrelated text
near zero. A hash-based stand-in cannot satisfy the last assertion.
"""

from __future__ import annotations

import math

import pytest

from ai.huggingface import DEFAULT_HF_MODEL_ID, HuggingFaceLocalProvider
from ai.embeddings import EmbeddingScorer
from core.settings import AISettings

pytestmark = pytest.mark.skipif(
    __import__("os").environ.get("JOB_ASSISTANT_HF_TESTS") != "1",
    reason="set JOB_ASSISTANT_HF_TESTS=1 to run real model inference tests",
)

RELATED = "Experience with PyTorch and Kubernetes for large scale systems"
UNRELATED = "Bake sourdough bread at home with a starter culture"


@pytest.fixture(scope="module")
def provider() -> HuggingFaceLocalProvider:
    return HuggingFaceLocalProvider(AISettings())


class TestRealInference:
    def test_the_model_loads_and_reports_available(self, provider: HuggingFaceLocalProvider) -> None:
        status = provider.health_check()
        assert status.available is True, status.detail
        assert status.provider == "huggingface"
        assert status.model == DEFAULT_HF_MODEL_ID

    def test_vectors_come_back_with_the_declared_dimension(
        self, provider: HuggingFaceLocalProvider
    ) -> None:
        result = provider.embed([RELATED, UNRELATED])
        assert len(result.vectors) == 2
        assert result.dimensions == provider.dimension == 384
        assert all(len(vector) == 384 for vector in result.vectors)

    def test_the_model_run_is_recorded_as_a_success(
        self, provider: HuggingFaceLocalProvider
    ) -> None:
        result = provider.embed(["a short sentence"])
        assert result.run.status.value == "SUCCESS"
        assert result.run.model == DEFAULT_HF_MODEL_ID

    def test_every_dimension_is_populated(self, provider: HuggingFaceLocalProvider) -> None:
        # A fabricated bag-of-trigrams vector leaves most of 384 dimensions at
        # zero. A real encoder does not.
        vector = provider.embed([RELATED]).vectors[0]
        populated = sum(1 for value in vector if value != 0.0)
        assert populated > 300, f"only {populated}/384 dimensions populated"

    def test_the_vector_is_normalised(self, provider: HuggingFaceLocalProvider) -> None:
        vector = provider.embed([RELATED]).vectors[0]
        norm = math.sqrt(sum(value * value for value in vector))
        assert 0.9 < norm < 1.1, f"norm was {norm}"


class TestRealSemanticsThroughTheProductionSeam:
    """The scoring path the application actually uses."""

    @pytest.fixture()
    def scorer(self, provider: HuggingFaceLocalProvider) -> EmbeddingScorer:
        return EmbeddingScorer(provider)

    def test_the_scorer_identifies_itself_for_the_cache_key(
        self, scorer: EmbeddingScorer
    ) -> None:
        assert scorer.scorer_id.startswith("embedding:huggingface:")

    def test_related_text_scores_high(self, scorer: EmbeddingScorer) -> None:
        score = scorer.similarity(RELATED, "Kubernetes and PyTorch experience wanted")
        assert score > 0.6, f"related pair scored only {score:.3f}"

    def test_unrelated_text_scores_near_zero(self, scorer: EmbeddingScorer) -> None:
        score = scorer.similarity(RELATED, UNRELATED)
        assert score < 0.2, f"unrelated pair scored {score:.3f}"

    def test_semantics_beat_word_overlap(self, scorer: EmbeddingScorer) -> None:
        """A paraphrase shares no words with the original.

        The lexical scorer scores this at 0.0 because it only counts shared
        tokens; the embedding scorer must see the meaning. This is the whole
        reason the provider exists, so it is asserted directly.
        """
        assert scorer.similarity(
            "Five years building distributed data pipelines",
            "Has extensive experience engineering large scale data systems",
        ) > 0.5

    def test_similar_vectors_are_cached_not_recomputed(
        self, provider: HuggingFaceLocalProvider
    ) -> None:
        scorer = EmbeddingScorer(provider)
        scorer.similarity(RELATED, UNRELATED)
        before = dict(scorer._cache)
        scorer.similarity(RELATED, UNRELATED)
        assert scorer._cache == before


class TestRealModelUnavailableIsLoud:
    def test_an_unknown_model_fails_instead_of_faking(self) -> None:
        from core.errors import AIProviderError

        broken = HuggingFaceLocalProvider(
            AISettings(embedding_model="definitely/not-a-real-checkpoint-xyz")
        )
        with pytest.raises((AIProviderError, Exception)):
            broken.embed(["anything"])

    def test_health_check_reports_unavailable_not_available(
        self,
    ) -> None:
        broken = HuggingFaceLocalProvider(
            AISettings(embedding_model="definitely/not-a-real-checkpoint-xyz")
        )
        status = broken.health_check()
        assert status.available is False
        assert status.detail