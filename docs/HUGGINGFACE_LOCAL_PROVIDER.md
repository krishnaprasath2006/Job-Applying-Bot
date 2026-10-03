# Hugging Face Local Embedding Provider (Milestone HF-1)

## 1. Overview & Purpose
The `HuggingFaceLocalProvider` integrates in-process local semantic embeddings into the Apllie Job Assistant architecture. It resolves the semantic disconnect inherent in pure lexical keyword matching while maintaining the system's strict **₹0-cost** and **zero-hallucination** boundaries.

### Target Model
- **Model ID:** `sentence-transformers/all-MiniLM-L6-v2` (ONNX target: `Xenova/all-MiniLM-L6-v2`)
- **Architecture:** 6-layer BERT mini transformer
- **Output Dimension:** 384-dimensional dense vectors
- **Normalized Metric:** Cosine similarity
- **License:** Apache 2.0 (Permissive for local and commercial usage)

---

## 2. Core Technical Responsibilities
1. **Requirement ↔ Candidate Claim Semantic Similarity:**
   Computes vector distance between extracted job requirements (e.g. *"Build REST APIs using Python FastAPI"*) and candidate profile claims or skills (e.g. *"Built FastAPI backend"*), bridging terminology gaps without guessing.
2. **Resume Variant Relevance:**
   Calculates semantic alignment scores between job requirements and individual resume sections (Skills, Experience, Summary).
3. **Application Question Intent Foundation:**
   Provides dense vector projections against canonical taxonomy centroids (`SPONSORSHIP`, `WORK_AUTHORIZATION`, `YEARS_EXPERIENCE`, `EDUCATION`, `COMPENSATION`) without generating or modifying candidate answers.

---

## 3. Epistemological & Safety Guardrails
- **Semantic Similarity is NOT Candidate Truth:**
  An embedding score is a derived statistical distance, **never** an authoritative fact. Candidate facts remain strictly governed by `CandidateProfile` with `FactStatus.VERIFIED` and evidence snippet backing.
- **Hard Gate Veto is Inviolable:**
  If a job fails the non-negotiable Hard Gate (visa sponsorship restrictions or minimum experience deficits), the match decision is immediate `HARD_MISMATCH`. **High semantic similarity can never outvote or soften a Hard Gate veto.**
- **No Browser or Submission Coupling:**
  The provider operates strictly offline. It cannot launch a browser, inspect live external pages, or submit application forms.
- **Safe Mode Enforced:**
  `dry_run=True`, `safe_mode=True`, `require_human_approval=True`, `allow_final_submission=False`.

---

## 4. Local Execution & ₹0 Cloud Cost
- **Runtime:** ONNX Runtime via `@xenova/transformers` (Hugging Face Transformers.js).
- **Compute:** 100% CPU inference. No GPU or CUDA required.
- **Dependencies:** In-process Node.js execution. Zero paid APIs (no OpenAI, Gemini, or remote hosted inference).
- **Cache Location:** `data/models/cache` (configurable via `AIProviderConfig.cacheDir`).

---

## 5. Architectural Degradation & Fallback Strategy
If the local ONNX model is uninitialized, missing, or runs in an air-gapped CI environment, the provider never crashes:
1. `EmbeddingScorer` catches model errors and logs a structured warning.
2. The system automatically falls back to `LexicalScorer` (deterministic token overlap / Jaccard similarity).
3. The system remains 100% functional with zero unhandled exceptions.

---

## 6. Model Fingerprinting & Cache Invalidation
To guarantee cache freshness and reproducibility, all embeddings are fingerprinted:
$$\text{CacheKey} = \text{provider} + \text{model\_id} + \text{model\_revision} + \text{dimension} + \text{SHA256}(\text{input\_text})$$
If the model ID or dimension changes, existing cached entries are automatically invalidated.

---

## 7. Running Tests & Smoke Test

### Deterministic Offline Test Suite
Runs completely offline without external network access:
```bash
npm run test:hf
# or
npx tsx src/ai/test_hf1_suite.ts
```

### Optional Live Model Smoke Test
For environments where model weights can be downloaded once from Hugging Face:
```bash
npm run test:hf-smoke
# or
npx tsx src/ai/smoke_test.ts
```
