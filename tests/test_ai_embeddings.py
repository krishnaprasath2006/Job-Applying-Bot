"""Similarity scorers, tested with the machine offline.

The lexical scorer is the default and the only one the test suite trusts:
its arithmetic is here, in full, with no model in the loop. The embedding
scorer is exercised through a fake provider, so the caching, the cosine,
and the clamping are proven without a socket ever opening — a test that
needed a running Ollama would be a test nobody could run.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai.embeddings import (
    EMBEDDING_VERSION,
    EmbeddingScorer,
    LexicalScorer,
    SemanticScorer,
    cosine,
)
from core.enums import AnalysisSource, ModelRunTask
from core.model_run import ModelRun


class FakeProvider:
    """Embeds each text with a canned vector, and records what it was asked."""

    def __init__(
        self, table: dict[str, list[float]], *, run: ModelRun | None = None
    ) -> None:
        self._table = table
        self._run = run
        self.calls: list[str] = []
        self.models: list[str | None] = []

    def embed(
        self, texts: list[str], *, model: str | None = None, prompt_version: str = ""
    ) -> SimpleNamespace:
        self.calls.extend(texts)
        self.models.append(model)
        return SimpleNamespace(
            vectors=[self._table[text] for text in texts],
            model=model or "fake",
            run=self._run,
        )


@pytest.fixture()
def scorer() -> LexicalScorer:
    return LexicalScorer()


# ---------------------------------------------------------------------------
# The lexical scorer
# ---------------------------------------------------------------------------
class TestLexicalScorer:
    def test_identical_texts_score_one(self, scorer: LexicalScorer) -> None:
        assert scorer.similarity("Python", "Python") == 1.0

    def test_a_claim_inside_a_requirement_scores_one(
        self, scorer: LexicalScorer
    ) -> None:
        # The requirement wraps the skill in prose; the claim names it.
        assert scorer.similarity("Experience with PyTorch", "PyTorch") == 1.0

    def test_texts_sharing_nothing_score_zero(self, scorer: LexicalScorer) -> None:
        assert scorer.similarity("Kubernetes", "COBOL") == 0.0

    def test_partial_overlap_scores_the_shared_fraction(
        self, scorer: LexicalScorer
    ) -> None:
        assert scorer.similarity("Python and Java", "Python and Rust") == 0.5

    def test_articles_and_prepositions_carry_no_similarity(
        self, scorer: LexicalScorer
    ) -> None:
        assert scorer.similarity("the and of", "of and the") == 0.0

    def test_case_and_punctuation_do_not_matter(
        self, scorer: LexicalScorer
    ) -> None:
        assert scorer.similarity("PYTHON!", "python") == 1.0

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("Python", "Kubernetes"),
            ("Experience with databases", "SQL"),
            ("", "Python"),
            ("Remote", "Remote (India)"),
        ],
    )
    def test_the_answer_is_always_a_similarity(
        self, scorer: LexicalScorer, left: str, right: str
    ) -> None:
        score = scorer.similarity(left, right)
        assert 0.0 <= score <= 1.0

    def test_the_lexical_scorer_answers_the_protocol(
        self, scorer: LexicalScorer
    ) -> None:
        assert isinstance(scorer, SemanticScorer)


# ---------------------------------------------------------------------------
# Cosine
# ---------------------------------------------------------------------------
class TestCosine:
    def test_identical_vectors_score_one(self) -> None:
        assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self) -> None:
        assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors_score_minus_one(self) -> None:
        assert cosine([1.0, -1.0], [-1.0, 1.0]) == pytest.approx(-1.0)

    def test_a_zero_vector_has_no_angle(self) -> None:
        assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_mismatched_lengths_have_no_angle(self) -> None:
        assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# The embedding scorer
# ---------------------------------------------------------------------------
class TestEmbeddingScorer:
    def test_similarity_is_the_cosine_of_the_two_vectors(self) -> None:
        provider = FakeProvider({"left": [1.0, 0.0], "right": [0.0, 1.0]})
        assert EmbeddingScorer(provider).similarity("left", "right") == 0.0

    def test_aligned_vectors_score_one(self) -> None:
        provider = FakeProvider({"left": [3.0, 4.0], "right": [3.0, 4.0]})
        assert EmbeddingScorer(provider).similarity("left", "right") == 1.0

    def test_a_negative_cosine_is_clamped_to_zero(self) -> None:
        provider = FakeProvider({"left": [1.0, -1.0], "right": [-1.0, 1.0]})
        assert EmbeddingScorer(provider).similarity("left", "right") == 0.0

    def test_each_distinct_text_is_embedded_once(self) -> None:
        provider = FakeProvider({"left": [1.0, 0.0], "right": [0.0, 1.0]})
        embedding = EmbeddingScorer(provider)
        embedding.similarity("left", "right")
        embedding.similarity("left", "right")
        embedding.similarity("right", "left")
        assert provider.calls == ["left", "right"]

    def test_the_model_name_is_passed_through(self) -> None:
        provider = FakeProvider({"x": [1.0]})
        EmbeddingScorer(provider, model="embed-v1").similarity("x", "x")
        assert provider.models == ["embed-v1"]


# ---------------------------------------------------------------------------
# Scorer identity: the name that joins the match cache key
# ---------------------------------------------------------------------------
class TestScorerIdentity:
    def test_the_lexical_scorer_names_itself(self) -> None:
        assert LexicalScorer().scorer_id == "lexical:v1"

    def test_the_embedding_scorer_names_provider_model_and_version(self) -> None:
        scorer = EmbeddingScorer(FakeProvider({}), model="embed-v2")
        assert scorer.scorer_id.startswith("embedding:")
        assert "embed-v2" in scorer.scorer_id
        assert EMBEDDING_VERSION in scorer.scorer_id

    def test_a_different_model_is_a_different_identity(self) -> None:
        provider = FakeProvider({})
        one = EmbeddingScorer(provider, model="model-a").scorer_id
        two = EmbeddingScorer(provider, model="model-b").scorer_id
        assert one != two

    def test_both_scorers_answer_the_protocol(self) -> None:
        assert isinstance(LexicalScorer(), SemanticScorer)
        assert isinstance(EmbeddingScorer(FakeProvider({})), SemanticScorer)


# ---------------------------------------------------------------------------
# Cache keys: which vectors may be reused, and for how long
# ---------------------------------------------------------------------------
class TestEmbeddingCacheKeys:
    def test_a_changed_text_misses_the_cache(self) -> None:
        provider = FakeProvider({"left": [1.0], "right": [0.0]})
        scorer = EmbeddingScorer(provider)
        scorer.similarity("left", "left")
        scorer.similarity("right", "right")
        assert provider.calls == ["left", "right"]

    def test_a_different_model_reembeds_instead_of_reusing(self) -> None:
        provider = FakeProvider({"x": [1.0, 0.0]})
        EmbeddingScorer(provider, model="m1").similarity("x", "x")
        EmbeddingScorer(provider, model="m2").similarity("x", "x")
        assert provider.calls == ["x", "x"]
        assert provider.models == ["m1", "m2"]

    def test_vectors_do_not_leak_between_scorer_instances(self) -> None:
        # Entries live on the instance: a dropped scorer drops its vectors,
        # so a fresh scorer proves itself by embedding again.
        provider = FakeProvider({"x": [1.0]})
        EmbeddingScorer(provider).similarity("x", "x")
        EmbeddingScorer(provider).similarity("x", "x")
        assert provider.calls == ["x", "x"]

    def test_whitespace_variants_share_one_vector(self) -> None:
        provider = FakeProvider({"x": [1.0]})
        scorer = EmbeddingScorer(provider)
        scorer.similarity("x", "x")
        scorer.similarity("  x  ", "x")
        assert provider.calls == ["x"]

    def test_the_cache_is_capped_and_the_oldest_entry_gives_way(self) -> None:
        provider = FakeProvider({chr(ord("a") + i): [1.0] for i in range(3)})
        scorer = EmbeddingScorer(provider)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr("ai.embeddings.EMBEDDING_CACHE_MAX_ENTRIES", 2)
            for letter in "abca":
                scorer.similarity(letter, letter)
        # "a" was evicted after the cap filled, so asking for it again embeds.
        assert provider.calls == ["a", "b", "c", "a"]


# ---------------------------------------------------------------------------
# Model runs: which embedding actually happened, filed exactly once
# ---------------------------------------------------------------------------
class TestEmbeddingRuns:
    @staticmethod
    def _run() -> ModelRun:
        return ModelRun(
            provider="fake",
            model="fake",
            task=ModelRunTask.EMBED,
            input_hash="hash-of-the-prompt",
            analysis_source=AnalysisSource.AI_GENERAL,
        )

    def test_a_fresh_embed_files_its_run(self) -> None:
        run = self._run()
        provider = FakeProvider({"x": [1.0]}, run=run)
        seen: list[ModelRun] = []
        EmbeddingScorer(provider, on_run=seen.append).similarity("x", "x")
        assert seen == [run]

    def test_a_cache_hit_files_nothing_new(self) -> None:
        provider = FakeProvider({"x": [1.0]}, run=self._run())
        seen: list[ModelRun] = []
        scorer = EmbeddingScorer(provider, on_run=seen.append)
        scorer.similarity("x", "x")
        scorer.similarity("x", "x")
        assert provider.calls == ["x"]
        assert len(seen) == 1

    def test_a_provider_that_reports_no_run_still_scores(self) -> None:
        # Compatibility: a provider built before runs existed, or one whose
        # embed simply carries none, must not break scoring or the callback.
        provider = FakeProvider({"x": [1.0]})
        seen: list[ModelRun] = []
        scorer = EmbeddingScorer(provider, on_run=seen.append)
        assert scorer.similarity("x", "x") == 1.0
        assert seen == []
