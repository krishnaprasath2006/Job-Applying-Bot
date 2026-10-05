# Architecture

How the system is layered, what each layer is allowed to do, and which boundaries are
enforced in code rather than by convention.

---

## 1. Overview

Two codebases sit side by side:

```
EasyApplyJobsBot/            legacy bot (Phase 0 and earlier)
├── linkedin.py              browser automation, Selenium, submitting
├── config.py                reads LINKEDIN_EMAIL, LINKEDIN_PASSWORD, dryRun
├── utils.py                 driver construction, Chromium options
└── constants.py             selectors and URLs

automation/                  browser side (Milestone 3, outside src/)
├── browser.py               headless Edge/Chrome construction, waits
└── linkedin_source.py       navigation + page capture → HTML string

src/                         assistant (Phase 2 foundation + Milestone 3)
├── core/                    primitives: settings, enums, errors, evidence, hashing
├── safety/                  policy and guards
├── candidate_profile/        candidate truth
├── resumes/                 ingestion and parsing
├── database/                SQLite, migrations, repositories
├── jobs/                    job intelligence: models, dedup, requirements,
│                            hard gate, matching, explain, review, analysis
├── ai/                      provider abstraction + embeddings/scoring
├── audit/                   events
└── assistant/               assembly: container, job service, CLI, acceptance
```

The legacy tree is **not** a dependency of `src/`, and `src/` is not a dependency of the
legacy tree. The only connection is `src/core/legacy.py`, which reads `config.py` as a
convenience and fails with `ConfigurationError` if it is missing.

`automation/` holds the only Selenium code written for the new system. `src/` never
imports it: the browser is reached solely through `jobs/source.py`'s
`SourceAdapter` protocol, whose local implementation reads files from disk. A live
adapter that drives `automation/` is a later-phase concern and is not wired in.

`job_assistant.py` is the entry point for the new code. The original `assistant.py`
entry point for the legacy bot remains, and the root file was renamed precisely so the
package name `src/assistant` cannot be shadowed.

---

## 2. Legacy LinkedIn and browser layer

Unchanged in Phase 2. It imports Selenium, builds a driver, navigates, and submits.

It stays outside every new boundary:

- `src/` never imports `selenium` (asserted by `test_security.py`).
- No module under `src/` constructs a driver, opens a page, or clicks.
- The legacy module imports without launching a browser (asserted by `test_legacy.py`).

This layer will be called in a later phase only through the safety policy.

---

## 3. Assistant foundation

`src/assistant/app.py` builds one object graph:

```
AssistantSettings ──► Paths ──► Database ──► SafetyPolicy
                              │                 │
                              ├──► ProfileService
                              ├──► ResumeService
                              └──► JobService (job_repository, analysis cache,
                                                match cache, review queue)
```

Construction order matters. `database_path` is applied *before* the services are
constructed, so every repository is on the same database. Swapping `Assistant.db`
afterwards would leave already-built services writing to the original file — a bug that
was found by the acceptance run and fixed with `build_assistant(database_path=...)`.

`assert_phase2_invariants()` runs first, inside `build_assistant()`. If configuration
violates a Phase 2 invariant, the call raises before any file or connection is opened.

Repositories are built lazily from `Assistant.db`, so they can never point elsewhere.
`JobService` is the only Milestone 3 module that may import `database` repositories —
it is the seam where the pure `jobs/` pipeline meets storage.

---

## 4. Candidate truth and evidence layer

```
CandidateProfile
 ├── sections (12)
 │    └── FactValue (44)
 │         ├── value
 │         ├── status: VERIFIED | INFERRED | UNKNOWN
 │         ├── source / source_id / source_location
 │         ├── confidence, verified_at
 │          └── evidence[]  ──► Evidence (source_type, excerpt, confidence, created_at)
 ├── validator   (report only, 22 codes)
 └── service     (the only writer)
```

Two invariants carry most of the weight:

1. **`UNKNOWN` can never carry a value.** Enforced by the model, so a field cannot be
   half-known.
2. **`VERIFIED` must be traceable.** It requires a named source, and
   `is_application_safe` additionally requires an evidence record. A value that cannot be
   shown to an examiner is not application-safe.

Writes go through `ProfileService.update_fact()`, which records the actor. The
repository writes a row per fact and an entry per change in `fact_change_log` with
`actor_kind`. Reads may go to the JSON file or, on explicit request, rebuild from the
database — but never silently prefer one over the other.

Per-candidate file resolution (`path_for`) plus a `candidate_id` check on load is what
prevents cross-candidate leakage.

---

## 5. Resume layer

```
file ─► validate ─► SHA-256 ─► duplicate check ─► extract ─► sections ─► copy ─► store
                       │                                              │
                       └── data/resumes/raw/<hash>.<ext>              └── SQLite
```

The raw copy is written once and never rewritten. Parsing is deterministic and has no
language-model dependency, so the same input always yields the same sections and
`uses_llm=False` is truthful.

`content_hash` over normalised extracted text recognises the same document in two
containers; `file_hash` recognises the identical file. Duplicate detection uses both.

---

## 6. Job intelligence layer

Milestone 3 turns a saved job page into a verdict a human can audit. The pipeline
is pure functions composed by two orchestration modules; no module under `src/jobs/`
imports `database` (asserted by `TestLayerBoundary` in `tests/test_job_analysis.py`).

```
saved HTML ─► jobs/source.py (SourceAdapter) ─► HTML string
   │
   ▼
jobs/acquisition.py   parse_job_page → JobPage (description, title, apply_url,
   │                  content_hash, extraction_status COMPLETE|PARTIAL|FAILED|UNAVAILABLE)
   ▼
jobs/requirements.py  extract_requirements → Requirement rows
   │                  (REQUIRED | PREFERRED | UNKNOWN, min_years, ambiguous, confidence)
   ▼
jobs/hard_gate.py     evaluate_hard_gate → HardGateResult (PASS | HARD_MISMATCH |
   │                  UNKNOWN | REVIEW_REQUIRED) — runs first, final;
   │                  scoring never overrides it
   ▼
jobs/matching.py      evaluate_match → MatchResult (decision: MATCH | PARTIAL_MATCH |
   │                  HARD_MISMATCH | INSUFFICIENT_EVIDENCE | REVIEW_REQUIRED)
   │                  + per-requirement RequirementScore rows
   ▼
jobs/explain.py       explain_match → MatchExplanation (row-by-row: posting line,
   │                  candidate evidence, verdict) — the stored audit record
   ▼
jobs/review.py        derive_review_reasons / ReviewQueue — only decisions whose
                      meaning requires a human, with an explicit reason each
```

Supporting modules: `jobs/models.py` (the `Job` model and `JobStatus`),
`jobs/deduplicator.py` (three-tier identity: source id → canonical URL →
company/title/location/content-hash merge), `jobs/candidate.py` (typed claims
derived from profile facts), `jobs/analysis.py` (the analysis cache:
fingerprint → stored requirements / stored match), `jobs/extraction_schema.py`.

Two rules carry the weight:

1. **The gate beats the score.** A `HARD_MISMATCH` short-circuits before any
   similarity is computed, so `scores == []` and no number exists to misread.
2. **Indecision is a first-class outcome.** `REVIEW_REQUIRED` and
   `INSUFFICIENT_EVIDENCE` queue for a human with a reason; they are never
   rounded to a rejection.

---

## 7. Persistence layer

```
connection.py      SQLite wrapper: WAL, foreign keys, busy timeout, explicit transactions
migrations/        001 (nine tables), 002 (resume variant metadata),
                   003 (job intelligence: jobs, job_requirements,
                   job_extraction_runs, job_analyses, job_matches, job_state_events)
repositories/      BaseRepository ── profiles, resumes, documents+evidence,
                   model_runs, jobs (incl. analysis + match cache)
```

Boundaries:

- Only repositories execute SQL.
- Row → domain-model translation happens in the repository, never in a caller.
- Migrations run once and are recorded; `002` and `003` are additive because
  `001` will not re-run.
- Domain modules (`candidate_profile`, `resumes`, `jobs`) do not import `database` at module scope,
  which is what keeps the layering acyclic.

---

## 8. AI provider abstraction

```
caller ─► ai.registry.build_provider(AISettings) ─► AIProvider (interface)
                                                     └── OllamaProvider
```

The caller depends on the interface and the configuration, never on a concrete class.
Model names, base URLs, and timeouts are read from `AISettings` — not hardcoded where
they would be used.

Failure behaviour is a design decision: an unreachable provider raises
`ProviderUnavailableError` (or returns `available=False` from `health_check()`). The
system never falls back to another provider and never fabricates a response.

`ModelRun` records the execution, including `analysis_source`, so a later phase can tell
grounded output from model knowledge.

---

## 9. Separation of concerns

| Concern | Owner | Cannot do |
|---|---|---|
| AI inference | `src/ai/` | choose actions, reach the browser, mutate facts |
| Browser | legacy `linkedin.py` | be reached from `src/` |
| Validation | `candidate_profile/validator.py` | modify the profile it validates |
| Human approval | `safety/policies.py` | be minted by an AI actor, reused |
| Storage | `database/repositories/` | be called directly with SQL from above |
| Mutation of verified facts | `safety/guards.py` | be bypassed by an AI actor |

The actor classification in `src/core/actors.py` is shared by the change log and the
guards, so both agree on who did something. An unknown writer is classified as AI — the
conservative direction.

---

## 10. Safe execution boundaries

Four independent protections, any one of which prevents submission:

1. **Configuration:** `allow_final_submission=False`; enabling it requires
   `safe_mode=False` *and* `dry_run=False` *and* human approval.
2. **Invariants:** `assert_phase2_invariants()` at construction time.
3. **Policy:** `SafetyPolicy` refuses `submit_application` and every other privileged
   action by default; approval tokens are single-use and in-memory only.
4. **Absence:** no code path in `src/` opens a browser or posts a form.

Rate limits, CAPTCHA, and MFA are handled by *refusing to proceed*:
`block_on_captcha=True` and `block_on_mfa=True` end the action rather than working
around it.

---

## 11. Data flow

```
human (.env, CLI) ─► Settings ─► Assistant ─► SafetyPolicy ─► approved action
                                     │
              fixtures ─► ResumeService ─┤
              profile  ─► ProfileService ┤
              saved page ─► JobService ──┤   (ingest → analyze → match → explain)
                                         ▼
                                    SQLite + JSON working copy
                                         │
                            ModelRun / audit events (redacted)
```

Reading back:

```
SQLite ─► repository ─► domain model ─► validator (report) ─► CLI display (redacted)
```

The job path is deliberately one-directional: a page file in, a stored
verdict out. `JobService` never opens a URL and never touches the state
machine; `job match` ends at a decision and a line saying no application was
started.

The acceptance runner exercises this entire path inside a temporary sandbox: every
writable path — database, profile, resumes, logs — is redirected to a temp directory, so
a test run cannot touch real data.

---

## 12. Important invariants

| # | Invariant | Enforced by |
|---|---|---|
| 1 | `dry_run`, `safe_mode`, `require_human_approval` default `True` | `SafetySettings` |
| 2 | `allow_final_submission` defaults `False` | `SafetySettings` |
| 3 | Invariants are asserted at startup | `build_assistant()` |
| 4 | Privileged actions are refused by default | `SafetyPolicy` |
| 5 | An AI actor cannot create or change a `VERIFIED` fact | `safety/guards.py` |
| 6 | `UNKNOWN` never carries a value | `FactValue` validator |
| 7 | `VERIFIED` requires a source, and application-safety requires evidence | `core/evidence.py` |
| 8 | Unqualified requirements cannot be scored | `jobs/models.py` |
| 9 | An unreachable provider raises; it never fabricates | `ai/` |
| 10 | Secrets never reach log output or `status` | `core/redaction.py` |
| 11 | One candidate's profile is never served for another | `candidate_profile/service.py` |
| 12 | A test run never writes to real candidate data | acceptance sandbox |
| 13 | The original resume is never modified | `resumes/service.py` |
| 14 | Migrations apply exactly once | `schema_migrations` |
| 15 | The hard gate runs before scoring; a veto never computes a score | `jobs/matching.py` |
| 16 | A match decision with no human-meaningful reason never queues; one with a reason always does | `jobs/review.py` |
| 17 | Every review-queue row names an explicit `ReviewReason` | `jobs/review.py` |
| 18 | `src/jobs/` imports neither `database`, `selenium`, nor `automation` | `TestLayerBoundary` |
| 19 | The stored match explanation round-trips through `MatchResult` unchanged | `jobs/analysis.py` |

---

## 13. Import layering

```
core ──────────────► (nothing)
safety ────────────► core
profile ───────────► core
resumes ───────────► core
jobs ──────────────► core            (never database, never selenium)
ai ────────────────► core
database ──────────► core
database.repositories ─► core, database.connection
database.repositories.jobs ─► jobs.models   (acyclic: model, not module)
assistant / acceptance ─► everything above
automation/ ────────► selenium        (never imported by src/)
```

Domain packages re-export through PEP 562 lazy `__getattr__`, which is what removed the
circular import between `candidate_profile` and `database.repositories` found in the first
recovery assessment. All modules import cleanly.
