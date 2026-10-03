# QUARANTINED LEGACY CODE — DO NOT RE-ACTIVATE

This directory is **not part of the canonical architecture** and must never
become the active business logic for Milestone R1 or later.

## What is in here

`express-server/` is the pre-R1 Node/TypeScript runtime that the forensic audit
found to be a **second, independent implementation** of the domain:

| File | Role in the old runtime | Canonical replacement |
|---|---|---|
| `server.ts` | Express API, in-memory state, inline matching + hard gate, mutable safety flags, hardcoded candidate PII | `src/api/` (FastAPI) over `src/assistant/app.py` |
| `ai/embeddings.ts` | Second embedding/similarity engine | `src/ai/embeddings.py` + `src/ai/huggingface.py` |
| `ai/huggingface.ts` | Second HF provider, hash-projection "semantic" fallback | `src/ai/huggingface.py` (experimental) |
| `ai/provider.ts`, `ai/registry.ts`, `ai/cache.ts` | TS AI abstraction mirroring the Python one | `src/ai/provider.py`, `registry.py`, `cache.py` |
| `ai/questionIntent.ts` | TS question classifier | `src/ai/question_intent.py` |
| `ai/smoke_test.ts`, `ai/test_hf1_suite.ts` | TS-only test harness | `pytest` suite under `tests/` |
| `jobs/matching.ts` | Second matching engine | `src/jobs/matching.py` |
| `jobs/hardGate.ts` | Second hard-gate engine | `src/jobs/hard_gate.py` |
| `jobs/relevance.ts` | Second resume-relevance engine | `src/jobs/relevance.py` |

## Why it was moved rather than deleted

The milestone instructions require quarantining legacy code instead of deleting
it, so the previous behaviour stays auditable and recoverable. Nothing here is
imported by the canonical Python core, by the FastAPI boundary, or by the React
presentation layer.

## Known defects preserved in this code (do not copy them forward)

- `server.ts` bound `0.0.0.0` with unrestricted `cors()` and no authentication.
- `PUT /api/safety` allowed any unauthenticated caller to set
  `allow_final_submission: true` and `dryRun: false`.
- `POST /api/jobs/:id/apply` set job status to `APPLIED` even in dry-run mode and
  returned a message claiming a live external submission that never happened.
- Candidate identity PII was hardcoded in source.
- `EmbeddingScorer` fell back to a **synthetic hash projection** while still
  reporting HF semantic inference.

## Rule

If a capability is missing from the canonical Python core, it is missing. It is
not a reason to re-enable anything in this directory.