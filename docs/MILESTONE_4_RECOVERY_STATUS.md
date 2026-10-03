# Milestone 4 — Recovery Status

Generated 2026-10-01 from the live repository state. This document reflects
what is actually on disk, not what was planned.

## 1. Last known commit

| Commit | Message |
|---|---|
| `10bc6ff` | `feat: build job intelligence core` (Milestone 3 — committed) |
| `7633fab` | `feat: complete phase 2 assistant foundation` (Phase 2 — committed) |

Milestone 4 has **no commit yet**. All Milestone 4 work lives in the working
tree (11 modified files, 9 new files), uncommitted by design: the milestone
ships as one commit at CP16.

## 2. Current git state

- Branch `main`, ahead of `origin/main` by 5 commits (pre-existing).
- Modified: `src/assistant/{app,cli,job_service}.py`, `src/core/{enums,errors,settings}.py`,
  `src/database/repositories/jobs.py`, `src/jobs/{analysis,deduplicator,review}.py`,
  `tests/test_job_cli.py`.
- New (untracked): `src/jobs/{discovery,interpret,reconcile,records}.py`,
  `tests/test_job_{discovery_service,interpret,reconcile,records,source_ingest}.py`.
- `git diff --check`: clean (only CRLF conversion warnings).

## 3. Test baseline (recorded this session, before new changes)

| Check | Result |
|---|---|
| `python -m pytest -q` | **1034 passed, 1 warning** (~2 min) |
| Warning | pre-existing, `tests/test_job_requirements.py::TestSavedJobDescription` (class-scoped fixture deprecation; untouched) |
| `python job_assistant.py acceptance` | **24/24 passed, 0 failed** |
| Safety invariants | **OK** — `dry_run=True safe_mode=True require_human_approval=True allow_final_submission=False source_mode=DISCOVERY_ONLY` |
| Import sweep (all new M4 modules) | OK |
| `git diff --check` | OK |

## 4. Checkpoint status map

| CP | Name | Status | Evidence |
|---|---|---|---|
| CP1 | Source adapter integration | **COMPLETE** | `src/jobs/records.py` (`SourceMode`, `RetrievalInfo`, provenance, `enforce_source_mode` fail-closed), boundary enums/errors, settings assertion; `tests/test_job_records.py` (33). Legacy-browser wrap itself is tracked under CP16/CP12. |
| CP2 | Read-only real-source discovery | **COMPLETE** | `src/jobs/discovery.py` (typed `DiscoveryResult`, listing parse, error codes), `JobService.discover/discover_listing`, CLI `job discover`; discovery-only enforced at every entry; `tests/test_job_discovery_service.py`. |
| CP3 | Normalized ingestion | **COMPLETE** | `JobService.ingest_page` / `ingest_from_source` (extraction status + `SAVED_PAGE`/fetch provenance), `merge_discovery` provenance adoption; `tests/test_job_source_ingest.py`. |
| CP4 | AI requirement interpretation | **COMPLETE** | `src/jobs/interpret.py` (schema validation, evidence must exist in JD, prompt versioning, typed AI error codes, model-run sink), `analyze(ai=True)` with cache/fallback, CLI `job analyze --ai [--model]` (exit 78 misuse); AI rows carry category/normalized/priority/confidence/source excerpt/extraction source `AI`; `tests/test_job_interpret.py` + CLI AI tests. |
| CP5 | Requirement reconciliation | **PARTIAL (90%)** | `src/jobs/reconcile.py` (pairing, `ConflictIssue`, `ReconciliationReport`, `apply_conflicts`, `conflict_count`), `match_job(conflicts=)` promotion + `EXTRACTION_CONFLICT` reason, metadata written with its rows and cleared on replacement, CLI `job show` cross-check line; `tests/test_job_reconcile.py` (41). **Gap:** the deterministic reading is preserved only as counts/conflict issues — the spec requires preserving the full deterministic result alongside the AI result and the final result. |
| CP6 | Embedding scorer | **NOT STARTED** (design decided) | `EmbeddingScorer` exists but is unused (`docs/IMPLEMENTATION_PLAN.md` phase-7 note). Needs: activation behind `SemanticScorer`, `scorer_id` identity, `scorer_fingerprint` in the match cache key (migration), embedding cache keyed by content/model/provider/version, `EMBED` model runs. |
| CP7 | Hybrid match engine | **PARTIAL** | Gate-first veto and UNKNOWN semantics shipped in M3 (`evaluate_match`, `_decision_from_gate`); semantic-is-one-input ordering holds by construction. Missing: explicit precedence tests for "semantic cannot repair a hard mismatch" once CP6 wires a scorer, and scorer-aware cache keys. |
| CP8 | Eleven-dimension report | **NOT STARTED** | `DimensionStatus` enum ready (CP1). Dimension list fixed by `docs/IMPLEMENTATION_PLAN.md` (skill/experience/education/location/workplace/seniority/must_have/nice_to_have/authorization/domain/resume_evidence_coverage); each needs status/evidence/source/confidence/explanation. |
| CP9 | Resume relevance | **NOT STARTED** | Needs `recommended_resume_id` + reason from existing resume/candidate evidence only. |
| CP10 | Review queue strengthening | **PARTIAL** | Reasons (`ReviewReason`) + queue membership + `EXTRACTION_CONFLICT` (CP5) live; missing persisted review lifecycle (status/supporting evidence/timestamps) and a `suspicious/inconsistent analysis` capture path. |
| CP11 | Cache / model-run registry | **PARTIAL** | Analysis + match fingerprints and FAILED-not-cached AI rows shipped (M3/CP4); `ModelRunRepository` sink wired in CP4. Missing: embedding model/version in keys (CP6) and hit/miss tests for the new key dimensions. |
| CP12 | CLI/API integration | **PARTIAL** | `job discover`, `job ingest`, `job analyze --ai`, `job show` provenance + cross-check shipped. Missing: `main(argv, *, source_factory=None)` DI, live discovery wiring in root `job_assistant.py`, and report/relevance commands. |
| CP13 | Integration tests | **PARTIAL** | 5 new M4 test files (141 new tests total this milestone). Missing: the end-to-end Milestone 4 acceptance suite (STEP 20 flow). |
| CP14 | Security + regression | **PENDING** | `tests/test_security.py`, `test_safety.py`, `test_legacy.py` green in the baseline; final sweep runs at CP16. |
| CP15 | Documentation | **NOT STARTED** | No `docs/MILESTONE_4_*.md` implementation doc yet (this recovery doc excepted). |
| CP16 | Final acceptance | **NOT STARTED** | Final full-suite run, safety sweep, git review, single commit. |

## 5. Completed checkpoints

CP1, CP2, CP3, CP4 (full), CP5 (implementation complete; one preservation
requirement outstanding — see gap above).

## 6. Partial checkpoints

- **CP5** — add full deterministic-row preservation to the report block.
- **CP7** — precedence tests around a real scorer; depends on CP6.
- **CP10** — review lifecycle persistence.
- **CP11** — scorer/embedding key dimensions.
- **CP12** — source-factory DI + live discovery wiring.
- **CP13** — M4 acceptance suite.

## 7. Not-started checkpoints

CP6 (embedding activation), CP8 (eleven-dimension report), CP9 (resume
relevance), CP15 (docs), CP16 (final acceptance).

## 8. Broken components

None. The working tree is green: 1034/1034 tests, acceptance 24/24, no
failing imports, no safety regressions.

## 9. Existing tests (Milestone 4 additions)

| File | Tests | Covers |
|---|---|---|
| `tests/test_job_records.py` | 33 | normalization, provenance, source-mode boundary |
| `tests/test_job_discovery_service.py` | 15 | read-only discovery, listing parse, storage split |
| `tests/test_job_source_ingest.py` | 19 | ingestion + provenance + extraction status |
| `tests/test_job_interpret.py` | 19 | AI schema validation, cache, typed failures |
| `tests/test_job_reconcile.py` | 41 | cross-check, promotion, reason, service wiring |
| `tests/test_job_cli.py` (extended) | 24 | discover/ingest/show/analyze --ai CLI |

## 10. Current failures

None.

## 11. Safety status

- Invariants: `dry_run=True`, `safe_mode=True`, `require_human_approval=True`,
  `allow_final_submission=False` — asserted programmatically, green.
- `source_mode=DISCOVERY_ONLY`; `SourceMode.allows_application` is False and
  `build_assistant` refuses a configuration that would allow it.
- Application actions fail closed via `ApplicationBoundaryError` (unrecognised
  actions fail closed too).
- Acceptance output: "REAL SUBMISSION REMAINS DISABLED."

## 12. Exact next implementation task

1. **Finish CP5 preservation:** store the full deterministic requirement rows
   inside the `reconciliation` metadata block (alongside counts and issues)
   so neither reading overwrites the other; extend `tests/test_job_reconcile.py`.
2. Then **CP6:** scorer identity + `scorer_fingerprint` in the match cache
   key (migration `004`), `EmbeddingScorer` activation with a cache keyed by
   content hash + model + provider + embedding version, `EMBED` model runs,
   deterministic offline tests with a fake provider.

## 13. Files likely to be touched next

- `src/jobs/reconcile.py`, `src/assistant/job_service.py`, `tests/test_job_reconcile.py` (CP5 finish)
- `src/ai/embeddings.py`, `src/jobs/analysis.py`, `src/database/repositories/jobs.py`,
  `src/database/migrations/004_*.sql`, `src/assistant/{app,cli,job_service}.py`,
  `tests/test_ai_embeddings.py`, `tests/test_job_analysis.py` (CP6)
- Later: `src/jobs/dimensions.py` (CP8), `src/jobs/relevance.py` (CP9),
  `src/database/migrations/005_*.sql` + `src/database/repositories/reviews.py` (CP10),
  `src/assistant/acceptance_m4.py` (CP13), `docs/MILESTONE_4_IMPLEMENTATION.md` (CP15).

## 14. Deferred work (explicitly out of Milestone 4)

Resume rewriting/tailoring, cover letters, application question answering,
form filling, submission, post-application verification, interview
automation, outcome prediction — all future milestones. Real submission
remains disabled.
