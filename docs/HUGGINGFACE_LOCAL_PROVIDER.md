# Local Hugging Face Embedding Provider

Status: **IMPLEMENTED** (R2-C).

## 1. Purpose

`HuggingFaceLocalProvider` supplies real sentence embeddings to the job matcher, so
"does this requirement resemble anything the candidate has?" can be answered by
meaning rather than by shared words. It closes a gap the lexical scorer is
honest about but cannot cross: `LexicalScorer` compares token sets, so
*"SQL"* and *"MySQL"* share nothing, and a requirement that wraps a skill in
prose scores zero against a claim that names it bare.

It is one of two local providers, both free and both requiring no API key:

| Key | Provider | Does |
|---|---|---|
| `ollama` | `OllamaProvider` | text + structured generation, and embeddings for models that support them |
| `huggingface` | `HuggingFaceLocalProvider` | embeddings only |

## 2. The model

| Property | Value |
|---|---|
| Checkpoint | `sentence-transformers/all-MiniLM-L6-v2` |
| Runtime | ONNX Runtime on CPU, via the `fastembed` package |
| Dimensions | 384 |
| Size | ~90 MB, cached to disk after first download |
| Licence | Apache-2.0 |

Chosen because it is the smallest checkpoint in the family that still produces
embeddings competitive with far larger ones. The project compares short strings
such as *"Experience with PyTorch"*, where a 384-dimension bi-encoder is the
right tool and a larger model would only cost RAM. Override the checkpoint with
`ASSISTANT_AI__EMBEDDING_MODEL`.

Measured on the shipped model:

| Pair | Cosine |
|---|---|
| "Experience with PyTorch and Kubernetes" ↔ "Kubernetes and PyTorch experience wanted" | 0.98 |
| "Experience with PyTorch and Kubernetes" ↔ "Bake sourdough bread at home" | 0.00 |

## 3. What it does *not* do

- **It cannot generate text.** `all-MiniLM-L6-v2` is a sentence encoder.
  `generate_text` and `generate_structured` raise `AIProviderError` rather than
  pretending otherwise. Use `ollama` for generation.
- **It does not answer application questions.** `src/ai/question_intent.py` exists
  but is **disconnected** — no module imports it and no route exposes it.
- **It does not tailor résumés** and does not score ATS compatibility.
- **It never fabricates a vector.** See §5.

## 4. Safety and epistemics

- **Semantic similarity is not candidate truth.** An embedding score is a derived
  statistical distance, never a fact. `CandidateProfile` facts remain governed by
  `FactStatus.VERIFIED` plus evidence, and an `INFERRED` fact is not
  application-safe.
- **A hard-gate veto cannot be outvoted.** `HARD_MISMATCH` ends evaluation before
  any scorer runs; no similarity value can soften it.
- **No network at call time** once the model is cached, and no coupling to a
  browser or to submission of any kind.
- Selecting this provider changes nothing about safety flags:
  `dry_run=True`, `safe_mode=True`, `require_human_approval=True`,
  `allow_final_submission=False`.

## 5. Failure behaviour — no fabricated vectors

An earlier version of this module substituted a **hash-based trigram
projection** whenever the model failed to load, and returned the result as a
semantic embedding. That defect was removed in R2-C and is now guarded by tests.

It was the worst possible failure mode: the stand-in had the right shape and the
right dimension, so every consumer looked healthy while producing invented
similarity. A fabricated score is indistinguishable from a real one at the point
it is trusted.

Current behaviour:

- `fastembed` missing → `ProviderUnavailableError` naming the install command.
- Checkpoint cannot be loaded or downloaded → `ProviderUnavailableError`.
- Inference raises → `AIProviderError`. Never a substitute vector.
- Vector count or dimension disagrees with the request → `AIProviderError`.
  Vectors are never silently padded, truncated, or dropped.
- `health_check()` returns `available=False` with a diagnostic. It never reports
  available unless inference actually ran.

**Degradation is explicit, not silent.** The lexical scorer remains the default
because the *caller* chooses it via `--scorer lexical`. The provider does not
quietly switch scorers behind the caller's back.

## 6. Caching

Vectors are cached by `EmbeddingScorer`, keyed by
`(provider, model, embedding-scheme version, SHA-256 of the text)`. A changed
posting, a different model, or a different provider all miss by construction
rather than by invalidation bookkeeping. The cache lives on the scorer instance,
so it is dropped with the process.

There is no second, global embedding cache. One existed and was removed in R2-C
as an unused duplicate of this mechanism.

## 7. Usage

```bash
# Install the optional extra (pulls ~200 MB of ONNX Runtime)
pip install -e ".[embeddings]"

# Select the provider
# .env:  ASSISTANT_AI__PROVIDER=huggingface
# .env:  ASSISTANT_AI__EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# Match with real semantic similarity
python job_assistant.py job match <job-id> --scorer embedding
```

In Python:

```python
from ai import HuggingFaceLocalProvider
from ai.embeddings import EmbeddingScorer
from core.settings import AISettings

provider = HuggingFaceLocalProvider(AISettings())
scorer = EmbeddingScorer(provider)
scorer.similarity("Experience with PyTorch", "PyTorch for five years")
```

## 8. Tests

Unit tests — offline, no model, no network. These run in the default suite:

```bash
python -m pytest tests/test_ai_providers.py
```

They pin the `AIProvider` contract, registry registration, truthful capability
reporting, explicit failure when the model is unavailable, and the absence of
any fabricated-vector path.

Real-model tests — **opt-in**, because they download ~90 MB:

```bash
JOB_ASSISTANT_HF_TESTS=1 python -m pytest tests/test_ai_huggingface_real.py
```

Set `HF_HOME` to a warm cache to avoid re-downloading. These verify that the
model loads, that vectors have 384 populated dimensions, that related text scores
high and unrelated text near zero, and that a broken model name fails loudly.

The default suite never reaches the network.