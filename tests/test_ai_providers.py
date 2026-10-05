"""Provider-registry and provider-contract tests.

Two kinds of test live here and they are deliberately kept apart:

* **Unit tests** run with no model and no network. They pin the contract every
  provider must satisfy, that the registry can build each one, and — the
  important one — that the Hugging Face provider contains no fabricated-vector
  fallback. Those must pass on a machine that has never downloaded a model.
* **Real-model tests** live in ``test_ai_huggingface_real.py`` and are opt-in
  via ``JOB_ASSISTANT_HF_TESTS=1``, so the default suite never reaches the
  network.

The no-fake-vector test is a source-level assertion on purpose. The defect it
guards against was silent and invisible from the outside: a provider that
substituted hash-based vectors still returned vectors of the right shape, so
every consumer looked healthy while producing invented similarity.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from ai import AIProvider, HuggingFaceLocalProvider, OllamaProvider
from ai.huggingface import DEFAULT_HF_MODEL_ID
from ai.registry import available_providers, build_provider, register_provider
from core.errors import AIProviderError, ConfigurationError, ProviderUnavailableError
from core.settings import AISettings

AI_DIR = Path(__file__).resolve().parent.parent / "src" / "ai"


@pytest.fixture()
def hf() -> HuggingFaceLocalProvider:
    return HuggingFaceLocalProvider(AISettings())


# ---------------------------------------------------------------------------
# The module must import at all
# ---------------------------------------------------------------------------


class TestModuleImports:
    def test_the_module_imports(self) -> None:
        import ai.huggingface as module

        assert module.HuggingFaceLocalProvider is HuggingFaceLocalProvider

    def test_it_imports_without_fastembed_installed(self) -> None:
        # The optional extra must not be required to import the package, so a
        # missing extra degrades to "provider unavailable", never to an
        # ImportError at startup.
        source = (AI_DIR / "huggingface.py").read_text(encoding="utf-8")
        top_level = [
            line
            for line in source.splitlines()
            if line.startswith(("import ", "from ")) and "fastembed" in line
        ]
        assert top_level == [], "fastembed must be imported lazily, not at module scope"


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


class TestProviderContract:
    def test_it_is_an_ai_provider(self, hf: HuggingFaceLocalProvider) -> None:
        assert isinstance(hf, AIProvider)

    def test_it_is_concrete(self) -> None:
        # ABCMeta blocks instantiation while an abstract method is unimplemented,
        # so this is what proves the class is actually usable.
        assert HuggingFaceLocalProvider.__abstractmethods__ == frozenset()

    @pytest.mark.parametrize(
        "method", ["health_check", "generate_text", "generate_structured", "embed"]
    )
    def test_it_implements_every_abstract_method(
        self, hf: HuggingFaceLocalProvider, method: str
    ) -> None:
        assert callable(getattr(hf, method))

    def test_embed_matches_the_abc_signature(self) -> None:
        expected = inspect.signature(AIProvider.embed)
        actual = inspect.signature(HuggingFaceLocalProvider.embed)
        assert list(actual.parameters) == list(expected.parameters)

    def test_capabilities_are_truthful(self, hf: HuggingFaceLocalProvider) -> None:
        assert hf.name == "huggingface"
        assert hf.requires_api_key is False
        assert hf.supports_embeddings is True

    def test_it_reports_the_real_default_model(self, hf: HuggingFaceLocalProvider) -> None:
        assert hf.model == DEFAULT_HF_MODEL_ID
        assert hf.dimension == 384


# ---------------------------------------------------------------------------
# No fabricated vectors. Ever.
# ---------------------------------------------------------------------------


class TestNoFakeVectorFallback:
    """The defect this milestone exists to remove."""

    @staticmethod
    def _code() -> str:
        """The module's code with comments and docstrings stripped.

        Parsed as an AST rather than scanned as text: the module's own
        docstring describes the hash-based fallback it removed, and a text
        search would flag that explanation as if it were the defect.
        """
        import ast

        tree = ast.parse((AI_DIR / "huggingface.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if (
                isinstance(body, list)
                and body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body.pop(0)
        return ast.unparse(tree)

    def test_the_fixture_vector_generator_is_gone(self) -> None:
        source = (AI_DIR / "huggingface.py").read_text(encoding="utf-8")
        assert "_generate_test_fixture_vector" not in source

    def test_it_never_hashes_text_into_a_vector(self) -> None:
        code = self._code()
        # A fabricated embedding would need a hash to spread tokens over
        # dimensions. Only a real encoder may map text to a vector.
        assert "hash(" not in code.replace("sha256", "")

    def test_no_synthetic_vector_helper_survives(self) -> None:
        code = self._code()
        for marker in ("trigram", "pseudo", "fixture", "synthetic", "dummy", "fallback_vector"):
            assert marker not in code.lower(), marker

    def test_it_reports_the_real_model_not_a_stand_in(self, hf: HuggingFaceLocalProvider) -> None:
        assert hf.model == "sentence-transformers/all-MiniLM-L6-v2"
        assert hf.dimension == 384

    def test_an_unavailable_model_fails_instead_of_substituting(self) -> None:
        import sys

        provider = HuggingFaceLocalProvider(AISettings())
        provider._model = None
        provider._loaded = False

        # Absent the optional extra, `from fastembed import ...` raises, and the
        # provider must surface that rather than invent a vector.
        with pytest.MonkeyPatch.context() as patch:
            patch.setitem(sys.modules, "fastembed", None)
            with pytest.raises(ProviderUnavailableError, match="not installed"):
                provider.embed(["anything"])

    def test_a_dimension_mismatch_is_an_error_not_a_pad(self) -> None:
        provider = HuggingFaceLocalProvider(AISettings())

        class _Wrong:
            def embed(self, texts: list[str]) -> list[list[float]]:
                return [[0.0, 1.0] for _ in texts]

        provider._model, provider._loaded = _Wrong(), True
        with pytest.raises(AIProviderError, match="dimensions"):
            provider.embed(["a"])

    def test_a_short_response_is_an_error_not_a_silent_drop(self) -> None:
        provider = HuggingFaceLocalProvider(AISettings())

        class _Short:
            def embed(self, texts: list[str]) -> list[list[float]]:
                return [[0.0] * 384]  # one vector for two inputs

        provider._model, provider._loaded = _Short(), True
        with pytest.raises(AIProviderError, match="vectors"):
            provider.embed(["a", "b"])


# ---------------------------------------------------------------------------
# It is embedding-only, and says so
# ---------------------------------------------------------------------------


class TestGenerationIsRefusedNotFaked:
    def test_generate_text_raises(self, hf: HuggingFaceLocalProvider) -> None:
        with pytest.raises(AIProviderError, match="embedding-only"):
            hf.generate_text("hello")

    def test_generate_structured_raises(self, hf: HuggingFaceLocalProvider) -> None:
        with pytest.raises(AIProviderError, match="embedding-only"):
            hf.generate_structured("hello", dict)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_both_local_providers_are_registered(self) -> None:
        assert "ollama" in available_providers()
        assert "huggingface" in available_providers()

    def test_it_builds_huggingface_by_key(self) -> None:
        built = build_provider(AISettings(provider="huggingface"))
        assert isinstance(built, HuggingFaceLocalProvider)
        assert built.name == "huggingface"

    def test_it_still_builds_ollama(self) -> None:
        built = build_provider(AISettings(provider="ollama"))
        assert isinstance(built, OllamaProvider)
        assert built.name == "ollama"

    def test_an_unknown_provider_is_still_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            build_provider(AISettings(provider="not-a-provider"))

    def test_duplicate_registration_is_refused(self) -> None:
        with pytest.raises(ValueError):
            register_provider("ollama", lambda settings: OllamaProvider(settings))

    def test_the_provider_list_is_stable(self) -> None:
        # Import order must not change what is offered.
        assert available_providers() == sorted(available_providers())


# ---------------------------------------------------------------------------
# The retired duplicate cache
# ---------------------------------------------------------------------------


class TestDuplicateCacheRemoved:
    def test_the_second_embedding_cache_is_gone(self) -> None:
        # EmbeddingScorer already caches vectors keyed by provider, model,
        # scheme version and text hash. A second global cache was an
        # independent abstraction that nothing used.
        assert not (AI_DIR / "cache.py").exists()

    def test_nothing_imports_the_retired_module(self) -> None:
        for path in (AI_DIR.parent).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            assert "ai.cache" not in source, path
            assert "global_embedding_cache" not in source, path