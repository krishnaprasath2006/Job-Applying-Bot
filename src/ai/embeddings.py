"""Semantic similarity, with the AI as an option rather than a requirement.

Matching asks "does this requirement resemble anything the candidate has?"
only where no fact can answer. Two scorers answer it:

* :class:`LexicalScorer` — deterministic word-set overlap. No network, no
  model, no configuration: it is the default, and what the tests use, so
  every rule around similarity is testable with the machine offline.
* :class:`EmbeddingScorer` — cosine similarity of provider embeddings, for
  when a provider and an embedding model are configured. It wraps
  :class:`ai.provider.AIProvider` rather than reaching for HTTP itself.

Both answer the same protocol, :class:`SemanticScorer`, and matching holds
only that protocol — which scorer runs is the caller's choice, injected at
the seam. Nothing in :mod:`jobs` imports this module at runtime.

Every scorer carries a ``scorer_id``: matching folds it into the match
cache key, so a verdict computed by one scorer can never be replayed as
the verdict of another. The embedding scorer keeps its vector cache keyed
by provider, model, cache-scheme version, and the content hash of the
text — changing the posting or the embedding model misses the cache by
construction rather than by invalidation bookkeeping.
"""

from __future__ import annotations

import math
import re
from typing import Callable, Optional, Protocol, runtime_checkable

from ai.provider import AIProvider
from core.hashing import sha256_text
from core.model_run import ModelRun

__all__ = [
    "EMBEDDING_CACHE_MAX_ENTRIES",
    "EMBEDDING_VERSION",
    "EmbeddingScorer",
    "LexicalScorer",
    "SemanticScorer",
    "cosine",
]


@runtime_checkable
class SemanticScorer(Protocol):
    """How two texts are compared when no fact can decide.

    Returns a similarity in ``[0, 1]``: 1 means the texts say the same
    thing, 0 means they share nothing. Implementations must be pure from
    the caller's point of view — same inputs, same number — because a
    decision that changes when the network blinks is not a decision.

    ``scorer_id`` names the algorithm and configuration a score came from;
    matching uses it as part of the cache key. Implementations without the
    attribute still work — the fingerprint falls back to the class name —
    but a scorer whose score can change without its id changing would be a
    cache that lies.
    """

    scorer_id: str

    def similarity(self, left: str, right: str) -> float: ...


# Words every English sentence carries. Left in, they would let any two
# postings look alike: "the ... of ..." sharing nothing but articles is a
# similarity of zero, not of one.
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "is", "of", "on", "or", "that", "the", "this", "to", "we",
        "with", "you", "your",
    }
)
_TOKEN_RE = re.compile(r"[a-z0-9+#]+")


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS
    )


class LexicalScorer:
    """Word-set overlap, for similarity that must work with no model near.

    The measure is the overlap coefficient — shared words divided by the
    size of the *smaller* set — not Jaccard. A requirement wraps the skills
    it names in prose ("Experience with PyTorch") while a claim names them
    bare ("PyTorch"); Jaccard would call that half a match because the
    requirement had other words to say, when the claim is in fact contained
    in it word for word. The cost is honesty about what it cannot see:
    "SQL" and "MySQL" share no tokens here, and only an embedding would
    know they are related.
    """

    #: Cache identity: the algorithm (overlap coefficient over the fixed
    #: stopword set) versioned so a future change is a different key.
    scorer_id: str = "lexical:v1"

    def similarity(self, left: str, right: str) -> float:
        left_tokens = _tokens(left)
        right_tokens = _tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        shared = len(left_tokens & right_tokens)
        return shared / min(len(left_tokens), len(right_tokens))


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine of the angle between two vectors, in ``[-1, 1]``.

    Mismatched lengths and zero-length vectors score 0: there is no angle
    to measure, and inventing one would be a similarity nobody computed.
    """
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


#: Version of the embedding cache scheme. Bump when the key structure or
#: the clamping rules change, so vectors written under the old meaning
#: are never reused under the new one.
EMBEDDING_VERSION = "v1"

#: Cap on cached vectors per scorer; the oldest entries are evicted first.
EMBEDDING_CACHE_MAX_ENTRIES = 4096


class EmbeddingScorer:
    """Cosine similarity of provider embeddings, cached per distinct text.

    One similarity call embeds each distinct text once and reuses the
    vector, so comparing a requirement against a whole profile costs two
    embeds, not two per claim.

    The cache key is the invalidation policy: provider, model, embedding
    scheme version, and the SHA-256 of the text. A changed posting hashes
    to a new key; a different model or provider shares no entries with the
    old one; bumping :data:`EMBEDDING_VERSION` retires every earlier
    vector. Entries live on the instance, so a dropped scorer drops its
    vectors with it.

    Args:
        provider: Something answering :class:`ai.provider.AIProvider` —
            the scorer never speaks HTTP itself, so any provider works.
        model: Embedding model override; ``None`` lets the provider choose.
        on_run: Called with the provider's own
            :class:`~core.model_run.ModelRun` after each *fresh* embed —
            never on a cache hit — so the caller can persist which
            embedding actually ran.
    """

    def __init__(
        self,
        provider: AIProvider,
        *,
        model: Optional[str] = None,
        on_run: Optional[Callable[[ModelRun], None]] = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._on_run = on_run
        provider_key = str(getattr(provider, "name", "") or "").strip()
        if not provider_key:
            provider_key = f"{type(provider).__qualname__}:{id(provider)}"
        model_key = str(model or getattr(provider, "model", "") or "").strip() or "-"
        self._provider_key = provider_key
        self._model_key = model_key
        self._cache: dict[tuple[str, str, str, str], list[float]] = {}
        self.scorer_id = f"embedding:{provider_key}:{model_key}:{EMBEDDING_VERSION}"

    def similarity(self, left: str, right: str) -> float:
        score = cosine(self._vector(left), self._vector(right))
        # Text embeddings are not obliged to be non-negative; a negative
        # cosine is "not similar at all" for matching's purposes, not
        # "less than nothing".
        return max(0.0, min(1.0, score))

    def _cache_key(self, text: str) -> tuple[str, str, str, str]:
        return (
            self._provider_key,
            self._model_key,
            EMBEDDING_VERSION,
            sha256_text(text.strip()),
        )

    def _vector(self, text: str) -> list[float]:
        key = self._cache_key(text)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = self._provider.embed([text.strip()], model=self._model)
        vector = result.vectors[0]
        if len(self._cache) >= EMBEDDING_CACHE_MAX_ENTRIES:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = vector
        run = getattr(result, "run", None)
        if self._on_run is not None and run is not None:
            self._on_run(run)
        return vector
