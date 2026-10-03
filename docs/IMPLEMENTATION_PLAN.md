# IMPLEMENTATION PLAN

**Status:** proposal. **No implementation code has been written for the upgrade.**
**Date:** 2026-09-30
**Base commit:** `4717b55`

---

## 1. HOW TO READ THIS PLAN

20 phases. Each has:

- **Goal** — the one thing the phase delivers
- **Files** — created / modified
- **Depends on** — the phase that must land first
- **Tests** — what must pass before the phase is called done
- **Risk** — what could break, and the rollback
- **Verifiable now** — can we prove it works without credentials or a browser?

**Rules for every phase:**

1. The project imports and runs after every phase
2. `python linkedin.py --dry-run` still works after every phase
3. `config.dryRun` stays `True` for the entire upgrade
4. No commit contains `.env`, `cookies/`, resumes, or application data
5. Existing behaviour is preserved unless a change is documented in §19 of
   TARGET_ARCHITECTURE.md
6. If something cannot be built reliably, ship a documented `PENDING`
   interface — never a stub that looks like a working feature

**Estimated dependency additions** (each justified, no framework-for-its-own-sake):

```
pydantic>=2          schema validation at every boundary
fastapi>=0.110       local API
uvicorn              ASGI server
pdfplumber           PDF resume parsing
python-docx          DOCX resume parsing
pytest               tests
pytest-asyncio       async test support
httpx                TestClient transport
numpy                similarity math
```
Plus, optional and config-gated: `openai` (or plain HTTP), Ollama via HTTP.
`selenium`, `webdriver_manager`, `selenium-stealth`, `pyyaml`,
`python-dotenv` are already present and stay.

---

## 2. PHASE MAP

| Phase | Name | Depends on | Risk |
|---|---|---|---|
| 1 | Audit | — | **DONE** |
| 2 | Project structure | 1 | **DONE** (Phase 2 foundation, commit `7633fab`) |
| 3 | Security & configuration | 2 | Medium (safety core done in Phase 2) |
| 4 | Candidate profile + resume ingestion | 3 | **DONE** (Phase 2) |
| 5 | Job schema + database | 4 | **DONE in Milestone 3** (003 migration, JobRepository, dedup) |
| 6 | JD extraction | 4, 5 | **DONE in Milestone 3** (deterministic; LLM pass later) |
| 7 | Hybrid matching | 4, 5, 6 | **DONE in Milestone 3** (gate + lexical scorer; embeddings pluggable) |
| 8 | Resume selection + ATS | 7 | Medium |
| 9 | Cover letter generation | 7, 8 | Low |
| 10 | Question engine + evidence | 4, 6 | **High** |
| 11 | Unknown-question review queue | 10 | Low (job-level review queue shipped in Milestone 3) |
| 12 | Application state machine | 5, 11 | Medium |
| 13 | Browser automation abstraction | 12 | **High** |
| 14 | Human review UI (API first) | 11, 12 | Low |
| 15 | Application tracker | 12, 14 | Low |
| 16 | Analytics | 15 | Low |
| 17 | Tests | continuous | Low |
| 18 | Hardening | all | Medium |
| 19 | Dry-run integration | 13, 18 | Medium |
| 20 | Documentation | all | Low |

---

## PHASE 1 — AUDIT ✅ COMPLETE

**Deliverable:** `docs/CURRENT_SYSTEM_AUDIT.md`

**Findings that directly shape the plan:**

| Finding | Phase that fixes it |
|---|---|
| C1 step count from `math.floor(100/pct) - 2` | 13 |
| C2 submission never verified | 13, 18 |
| C3 broad `except` around the whole apply attempt | 13, 18 |
| C4 no cross-run duplicate suppression | 5, 12 |
| C5 no CAPTCHA/MFA handling | 13 |
| H1 `loadCookies` crashes on a corrupt pickle | 13 |
| H2 `cookies/` not git-ignored | 3 |
| H4 18 `time.sleep`, 0 `WebDriverWait` | 13 |
| H5 `ember14` login probe | 13 |
| H7 company blacklist matched the title *(fixed in checkpoint)* | — |
| H8 `Intership` typo *(fixed in checkpoint)* | — |
| H11 no tests | 17 |
| H13 `python-dotenv` undeclared | 3 |
| §263 dead YAML answers | 4 |

---

## PHASE 2 — PROJECT STRUCTURE

**Goal:** create the package skeleton and the `core/` primitives everything
else depends on. **No behaviour change.**

**Create**

```
core/
  __init__.py
  errors.py         ErrorCode enum + AssistantError hierarchy + typed errors
  logging.py        structured logger, JSONL handler, redaction filter
  paths.py          pathlib-based project paths (Windows-first)
  ids.py            uuid4 helpers, content_hash(), normalize_* helpers
  types.py          FieldType, RiskLevel, EvidenceLevel, ApplicationState enums
  clock.py          injectable time source (testability)
config/
  __init__.py
  settings.py       Pydantic settings; loads .env + config/*.yaml; one validator
  application.yaml  matching.yaml  ai.yaml  browser.yaml
  compat.py         maps new settings → old config.py names
  .env.example updates
```

**Modify:** `config.py` — becomes a compat shim; `dryRun`,
`maxApplicationsPerRun`, `blackListTitles`, `blacklistCompanies` still readable.
`requirements.txt` — add `pydantic`, `python-dotenv` (was undeclared).

**Depends on:** 1. **Risk:** low — additive, shim keeps old names working.

**Tests:** `test_config.py` — settings load; a missing key produces a
human-readable report; old `config.dryRun` still reads `True`; `.env` is
git-ignored.

**Verifiable now:** yes.

---

## PHASE 3 — SECURITY & CONFIGURATION

**Goal:** finish the security work begun in the checkpoint, and add the
safeguard layer.

**Modify**
- `.gitignore` — add `cookies/`, `data/profile/`, `data/resumes/`, `data/ai_cache/`,
  `data/review_queue/*.png`, `*.db`, `*.db-wal`, `*.db-shm`, `data/letter/`,
  `data/tailored/`
- `.dockerignore` — mirror
- `linkedin.py` — credentials come from settings; no hardcoded fallback
- `Dockerfile` — mark **deprecated** in a header comment; keep building

**Create**
- `core/redaction.py` — PII/secret redaction, shared by logging and exports
- `automation/guards.py` — `SubmitGuard` with the 7 independent checks
- `core/safety.py` — `SAFE_MODE`, `DRY_RUN`, `assert_can_submit()`

**Tests:** `.env` is ignored; `cookies/` is ignored; `SubmitGuard` returns
`False` when any one of the 7 checks fails; the submit selector appears in
exactly one file (AST scan).

**Verifiable now:** yes.

---

## PHASE 4 — CANDIDATE PROFILE + RESUME INGESTION

**Goal:** the truth store. **The most important phase in the project** —
everything downstream is only as truthful as this.

**Create**

```
profile/
  __init__.py
  schema.py         Pydantic models with VERIFIED/INFERRED/UNKNOWN labels
  store.py          load/save/validate; contradiction detection
  migrate.py        one-time import from additionalQuestions.yaml (opt-in)
data/profile/
  candidate.json  personal.json  education.json  experience.json
  skills.json     preferences.json  authorization.json  achievements.json
  projects.json   links.json       answers.json
  candidate_profile.yaml         # single-file alternative
  SCHEMA.md                      # documented format
resumes/
  __init__.py
  ingest.py        PDF/DOCX/TXT/MD → text
  parser.py        → structured {education, experience, skills, projects, …}
  store.py         content-hash dedup; never overwrite an original
  schema.py
data/resumes/      # git-ignored, user-owned
```

**Key rules**
- Every profile field carries `value`, `status` (VERIFIED/INFERRED/UNKNOWN),
  `source`, `verified_at`
- Contradictions (resume says 1 yr React, profile says 3 yr) →
  `PROFILE_CONTRADICTION`, **never** auto-resolved
- The 263 dead YAML answers are **not** auto-imported. `migrate.py` is
  opt-in, dry-run by default, and requires explicit per-field confirmation
- `Phone Number: 1234567890` / `Canada (+1)` from the upstream template are
  **not** imported. The user sets `APPLICANT_PHONE` in `.env`
- Resume ingestion is hash-deduplicated; a malformed file raises
  `MALFORMED_RESUME`, not a stack trace

**Tests:** `test_profile.py` (load/save round-trip, status labels preserved,
contradiction detected, missing file → clear error),
`test_resume_parser.py` (TXT/DOCX/MD fixtures, empty extraction,
duplicate hash, malformed file, PDF skipped gracefully if `pdfplumber` absent).

**Verifiable now:** yes — fixture resumes only, no LinkedIn.

**This phase requires the user's real data.** I will build and test the
schema and the parser, and ship an **empty, clearly-marked template**. I will
**not** invent name, email, phone, degree, university, GPA, employer, dates,
projects, or skills. Those fields stay `UNKNOWN` until you fill them in.

---

## PHASE 5 — JOB SCHEMA + DATABASE

> **Status: delivered in Milestone 3.** Implemented as
> `src/database/migrations/003_job_intelligence.sql` (six tables: `jobs`,
> `job_requirements`, `job_extraction_runs`, `job_analyses`, `job_matches`,
> `job_state_events`), `src/database/repositories/jobs.py`, and
> `src/jobs/deduplicator.py` (the three tiers below, tier 3 merging). The
> planned file layout under `db/` was realised as `src/database/` in Phase 2;
> this section describes the intent.

**Goal:** SQLite persistence, the unified `Job` schema, and deduplication.

**Create**

```
db/
  __init__.py
  connection.py     WAL, row factory, context manager, TEST_DATABASE override
  migrations.py     numbered, forward-only, tracked in schema_migrations
  schema.sql        14 tables
  repositories/
    jobs.py  applications.py  answers.py  events.py  resumes.py
    profile.py  question_memory.py  model_runs.py
  models.py         row <-> dataclass mappers
data/assistant.db
```

**Tables:** `users · candidate_profiles · resumes · documents · jobs ·
job_requirements · job_matches · applications · application_answers ·
application_events · application_reviews · application_failures ·
question_memory · model_runs`

**Deduplication** — `JobDeduplicator` implementing the three tiers from
TARGET_ARCHITECTURE §7.1: `(source, source_job_id)` → `canonical_url` →
`(normalized_company, normalized_title, normalized_location, content_hash)`.
Tier 3 **merges**, preserving the earliest `fetched_at` and the longest
description, incrementing `seen_count`.

**Tests:** `test_deduplication.py` — same job via different keyword, different
pagination offset, URL with a tracking param, reformatted description, a
genuinely different job at the same company, merge preserves first sighting,
`content_hash` stability, empty-JD handling.

**Verifiable now:** yes.

---

## PHASE 6 — JD EXTRACTION

> **Status: delivered in Milestone 3 (deterministic layer).**
> `src/jobs/acquisition.py` parses a saved page into a `JobPage`
> (description + `extraction_status`), and `src/jobs/requirements.py`
> extracts requirements with heading/tone/confidence rules — no LLM involved.
> The LLM structuring pass (`extractor.py` above) is deliberately deferred:
> `AnalysisSource.AI_GENERAL` exists in the schema and the `ai/` provider
> interface is wired, but nothing in Milestone 3 calls a model.

**Goal:** read the job description. **This is the capability the current bot
has never had** — without it nothing else is possible.

**Create**

```
jd/
  __init__.py
  schema.py     JobRequirements: must_have, nice_to_have, years, education,
                certifications, languages, work_authorization, sponsorship,
                relocation, responsibilities, keywords, red_flags
  extractor.py  LLM structuring with the original text preserved verbatim
  parser.py     deterministic regex/heuristic pre-pass (free, fast, no LLM)
  gates.py      HardRequirementGate
  quality.py    JobQualityFilter
```

**Design**
1. **Deterministic pre-pass first** (free): years-of-experience regex, degree
   keywords, certification names, salary ranges, sponsorship phrases, remote
   signals. Most requirements are extractable without an LLM.
2. **LLM only for what regex cannot do**, to control cost
3. `original_text` is stored unmodified. The AI restructures; it never edits
   the source
4. `HardRequirementGate` produces `hard_blockers[]`. **A high semantic score
   must not override a blocker** — the gate runs before matching and its
   verdict is final
5. `JobQualityFilter` flags; it never silently deletes

**Tests:** `test_jd_parser.py` — empty description, no requirements,
contradictory requirements ("20 years, entry level"), sponsorship present/absent,
degree required/absent, salary parsing, original text preserved byte-for-byte,
LLM failure → deterministic result, never an exception.

**Verifiable now:** yes, with fixture JDs. Ollama for a live run; no API key
needed.

---

## PHASE 7 — HYBRID MATCH ENGINE

> **Status: delivered in Milestone 3 (gate + lexical layer).**
> `src/jobs/hard_gate.py` implements rule 4 (the gate runs first and its
> verdict is final — `scores == []` on a veto), `src/jobs/matching.py` +
> `src/ai/embeddings.py` implement scoring with a pluggable `SemanticScorer`
> (the shipped `LexicalScorer` is deterministic and offline; `EmbeddingScorer`
> is available but unused), and `src/jobs/explain.py` renders the per-row
> explanation. The eleven-dimension report and `data/matching.yaml` weights
> are future work; the milestone's dimension set is requirement-level, not
> dimension-level.

**Goal:** explain *why* a job matches. Not a single number.

**Create**

```
matching/
  __init__.py
  rules.py       deterministic gates and filters (free, runs first)
  skills.py      skill taxonomy, aliases, synonyms, normalization
  semantic.py    embeddings + cosine; NOT_SCORED sentinel
  dimensions.py  per-dimension scorers
  engine.py      orchestration → MatchReport
  report.py      MatchReport model + human-readable renderer
data/matching.yaml  weights, thresholds, blocker rules
```

**Dimensions, each scored independently:** `skill_match · experience_match ·
education_match · location_match · workplace_match · seniority_match ·
must_have_match · nice_to_have_match · authorization_match · domain_match ·
resume_evidence_coverage`

**Output:** `overall_match` (a *weighted summary*, not a truth) +
`dimension_scores` + `matched_requirements` + `missing_requirements` +
`uncertain_requirements` + `hard_blockers` + `explanations` + `confidence` +
`evidence_source` + `grounded_in`.

**Rules**
- Deterministic filters run first and are free
- Semantic similarity is one input among eleven, never the arbiter
- Every dimension carries a per-dimension explanation
- `NOT_SCORED` is distinct from `0.0` — an unscored job is not a zero match
- Scores are clamped to `[0, 1]`; all-zero results raise an alarm, following
  GPT-Jobhunter's guard

**Tests:** `test_matching.py` — all 11 dimensions present; blocker beats a
high semantic score; empty skills; contradictory profile; NOT_SCORED ≠ 0.0;
deterministic and identical across runs; clamping; explanations non-empty.

**Verifiable now:** yes.

---

## PHASE 8 — RESUME SELECTION + ATS ANALYSIS

**Goal:** pick the right resume, and analyse it honestly.

**Create**

```
resumes/selector.py   scored selection
resumes/ats.py        ATS-oriented analysis
resumes/tailor.py     tailoring + change_log  [PENDING: DOCX/PDF export]
resumes/schema.py     metadata: role_focus, skills, experience_focus,
                      location, version, created_at
```

**Selection inputs:** job title · must-have skills · preferred skills ·
experience · role family · industry · seniority · location. Returns
`{selected_resume, selection_reason, confidence, runner_up}`.

`config.preferredCv` still works as an explicit override — backward
compatibility preserved.

**ATS analysis** measures: keyword coverage · skills alignment · section
completeness · job-title alignment · formatting readability · measurable
achievements present · duplicate keywords · irrelevant content · missing
requirements.

**Hard rule (non-negotiable):** tailoring may improve **wording, ordering,
emphasis, and keyword alignment** of *genuine* experience. It may **never**
fabricate experience, employers, dates, technologies, certifications, or
metrics. `change_log` must explain every change. The original is stored
immutable; a tailored draft never overwrites it.

**Tests:** multiple resumes, correct selection per role, override honoured,
`test_matching` reuse for ATS — tailoring cannot invent a technology absent
from the original (assert with an AST/string check on the change log).

**Verifiable now:** yes.

---

## PHASE 9 — COVER LETTER GENERATION

**Goal:** a specific, evidence-grounded letter — not a template.

**Create**

```
letters/
  __init__.py
  service.py     CoverLetterService
  schema.py      CoverLetter + evidence[] + versions
  templates/     3 base structures (concise / technical / career-changer)
  export.py      TXT (works) · MD (works) · PDF/DOCX [PENDING]
data/letter/
```

**Input:** profile + selected resume + JD + company + role + real experience +
preferences. **Output:** letter + `evidence[]` + `job_id` + `generated_at` +
`prompt_version` + `model_run_id` + `evidence_source`.

**Rules:** concise · natural · specific to this company and role · no fake
claims · no fake experience · no enthusiasm about unknown facts · **no
cross-application repetition** (a similarity check against recent letters is
recorded as `originality_score`, and a low score is surfaced, not hidden).

Preview · regenerate · edit · save versions. **[PENDING]** PDF/DOCX export.

**Tests:** `test_cover_letter.py` — no invented employer; no invented metric;
no claim absent from evidence; every factual sentence traceable to evidence;
regeneration differs; cross-letter similarity below threshold; empty profile
→ clear error, not a fabricated letter.

**Verifiable now:** yes, with Ollama.

---

## PHASE 10 — QUESTION ENGINE + EVIDENCE PIPELINE ★ HIGHEST RISK

**Goal:** answer application questions with evidence, or refuse to.

**Create**

```
questions/
  __init__.py
  schema.py       FormField, FieldType(14), Answer, RiskLevel
  extractor.py    DOM → [FormField] with question_text, field_type, required,
                  options, current_value, section, job_id
  normalizer.py   question normalization for exact + fuzzy matching
  evidence.py     the 7-level resolver
  memory.py       question_memory: source, verified_by, verified_at,
                  confidence, applies_to, use_count
  risk.py         risk classification
retrieval/
  __init__.py
  store.py        document store + metadata filtering
  embedder.py     provider-backed, content-hash cached
  rag.py          retrieve(question, doc_types, resume_id)
ai/
  __init__.py
  provider.py     LLMProvider protocol, CompletionRequest/Result
  ollama_provider.py   openai_provider.py   gemini_provider.py [UNTESTED]
  registry.py     config-driven selection
  guard.py        post-generation hallucination guard
  budget.py       per-run / per-day token ceilings
prompts/
  jd_extraction_v1.txt   matching_v1.txt   cover_letter_v1.txt
  question_answer_v1.txt  resume_analysis_v1.txt  ats_v1.txt
  tailoring_v1.txt       contradiction_v1.txt
```

**FieldType:** `TEXT · LONG_TEXT · YES_NO · RADIO · SELECT · CHECKBOX · PHONE ·
EMAIL · NUMBER · DATE · FILE_UPLOAD · URL · UNKNOWN`

**The 7 levels** (TARGET_ARCHITECTURE §6) with the caps:
L1 exact 0.99 · L2 fuzzy 0.95 · L3 profile 0.90 · L4 resume 0.85 ·
L5 RAG 0.70 · **L6 LLM 0.60** · L7 human 1.00

**Non-negotiable rules**
1. **L6 may never satisfy a required field alone.** → review queue
2. `risk_level ∈ {HIGH, CRITICAL}` → **no auto-fill** unless explicitly
   configured as verified. HIGH-risk: sponsorship, work authorization, legal
   eligibility, background/criminal, disability, veteran, demographic, salary
   commitment, years of experience, degree, relocation
3. Insufficient evidence → `UNANSWERABLE`. Never a guess.
4. `evidence_source == "model_prior"` on a HIGH/CRITICAL field → **blocked**
5. Every answer stores `evidence[]` with `quote` + `ref` + `source`
6. **Answer memory is never written back from an unverified LLM answer.** A
   cache entry requires `risk_level=LOW` **and** retrieved evidence
7. The same normalized question is never sent to the LLM twice
   (following repo 1's `qna_engine` write-back, with repo 1's flaw fixed)

**Tests:** `test_question_engine.py` — all 14 field types; every risk
category; required + L6-only → review; UNANSWERABLE on thin evidence; no
invention of years/certification/authorization/salary/employer;
`test_answer_validator.py` — unsupported claim rejected; invented technology
rejected; inflated years rejected; invented certification rejected; off-list
option rejected.

**Verifiable now:** yes, with the mock browser and a fixture form.

---

## PHASE 11 — UNKNOWN-QUESTION REVIEW QUEUE

**Goal:** an unknown field must never break an application, and must never be
guessed.

**Create**

```
review/
  __init__.py
  queue.py     ReviewItem CRUD, priority, status
  service.py   pause/review/answer/resume
  screenshots.py
data/review_queue/
  pending_questions.json
  screenshots/
```

Each item: `job_id · company · job_title · question · field_type · options ·
page · timestamp · screenshot_path · suggested_answer · confidence · evidence ·
risk_level · status`

**Actions:** `Review · Edit Answer · Continue · Open Application · Mark Manual
· Skip Job`. "Mark Manual" opens the browser at the right step with verified
answers pre-filled.

**Guarantee:** the application is persisted **before** the pause, so no job is
ever lost because of one unknown field (TEST 8).

**Tests:** unknown question → pause → queue item → state persisted → resume
completes; persistence survives a simulated restart; the queue is idempotent.

**Verifiable now:** yes.

---

## PHASE 12 — APPLICATION STATE MACHINE

**Goal:** explicit, persisted, replayable state. Never inferred from logs.

**Create**

```
applications/
  __init__.py
  states.py      16 states + adjacency matrix
  machine.py     transition(), validates, writes application_events
  planner.py     ApplicationPlan = frozen instruction set
  dedup.py       ALREADY_APPLIED check (source, job id, canonical URL,
                 company, title, history, timestamp)
  recovery.py    resumable applications
```

**16 states:** `DISCOVERED · NORMALIZED · MATCHED · REJECTED · SELECTED ·
RESUME_SELECTED · RESUME_TAILORED · COVER_LETTER_READY · QUESTIONS_ANALYZED ·
WAITING_FOR_REVIEW · READY_TO_APPLY · APPLICATION_STARTED · APPLICATION_PAUSED ·
APPLICATION_SUBMITTED · APPLICATION_VERIFIED · APPLICATION_FAILED` plus the
terminal `SUBMISSION_UNVERIFIED` (TEST 13) and `NEEDS_MANUAL_ACTION`.

**Rules:** every transition validated against the adjacency matrix; illegal →
typed error + logged, never guessed. `actor ∈ {AI, SYSTEM, USER}` on every
event. `seq` monotonic per application.

**Deduplication** before any submit: `(source, source_job_id)`, canonical URL,
company + title + location, and full application history. Already applied →
**never** submit again.

**Recovery** (TEST 11): persisted plan, answers, form step, resume ID, last
verified state. On restart, resumable applications are listed — and anything
already at `SUBMITTED`/`SUBMISSION_UNVERIFIED` is **never** re-submitted.

**Tests:** `test_state_machine.py` — every legal transition; every illegal one
raises; monotonic `seq`; crash mid-transition leaves a detectable gap;
already-applied blocked; recovery after a simulated browser crash;
`SUBMISSION_UNVERIFIED` is terminal.

**Verifiable now:** yes.

---

## PHASE 13 — BROWSER AUTOMATION ABSTRACTION ★ HIGHEST RISK

**Goal:** wrap the existing Selenium code, keep it working, add waits, guards,
challenge detection, and verification. **Do not delete the working automation.**

**Create**

```
automation/
  __init__.py
  browser.py     driver lifecycle; wraps the existing utils.createDriver()
  waits.py       WebDriverWait helpers replacing fixed sleeps
  selectors.py   every selector, with fallbacks
  challenges.py  CAPTCHA / MFA / checkpoint / rate-limit detection
  fields.py      DOM → [FormField]
  testing/
    fake_driver.py   fake_element.py   fixtures/   sequences.py
automation/linkedin/
  __init__.py
  login.py       session + challenge detection
  search.py      job discovery      (wraps the existing logic)
  job_page.py    job detail parsing
  application.py form progression    (replaces the percentage arithmetic)
  verification.py post-submit verification
  execution.py   the only SubmitGuard caller
```

**Migrations from the current code**

| Current | New | Note |
|---|---|---|
| `math.floor(100/percentage) - 2` | `application.py` reads real form state | Audit C1. Loop until the submit button is present, exactly as repo 1 does, but **persisted** |
| 18 × `time.sleep` | `waits.py` explicit waits | Fixed sleeps replaced where the wait is knowable; randomised pacing retained as an explicit `PacingPolicy`, not a substitute for waiting |
| `//*[@id="ember14"]` | `login.py` multi-selector + challenge check | Audit H5 |
| `//small` job count | scoped selector | Audit H9 |
| `chooseResume` silent no-op | typed `UPLOAD_FAILED` | Deliberate change, documented in §19 |
| `loadCookies` unguarded pickle | validated load; corrupt → re-login | Audit H1 |
| blind Submit click | `SubmitGuard` + verification | Audit C2 |

**Selector policy:** semantic attributes and accessible labels first,
multiple fallbacks per target, all centralized in `selectors.py` with a
documented override hook in `config/browser.yaml`. Every critical action gets a
timeout, a retry policy, and a descriptive typed error.

**Challenge wall:** detect → `CAPTCHA_REQUIRED` / `AUTH_REQUIRED` → persist
state → notify → **stop**. Never bypass, never solve, never retry into it.

**Preserved unchanged:** `utils.createDriver()` Chrome↔Edge fallback, the
working selector set, the search URL builder, `cookies/<md5>.pkl` format,
`additionalQuestions.yaml`'s single phone key, the text output file, and
`selenium_stealth` (kept, not extended).

**Tests:** `tests/test_browser_mock.py` — every flow on `FakeDriver`:
happy path, CAPTCHA mid-form, unknown field, stale element, timeout, wrong
layout, verify-failure. No network. No real browser. **No test submits
anything.**

Browser integration tests are a separate, opt-in marker
(`@pytest.mark.browser`), never run by default.

**Verifiable now:** partially — the mock layer yes; real LinkedIn needs the
user's session.

**Rollback:** `linkedin.py` stays runnable. This phase adds a layer; it does
not remove the original entry point.

---

## PHASE 14 — HUMAN REVIEW UI (API first)

**Goal:** the review gate, exposed over HTTP. UI comes in phase 20's frontend
work alongside the tracker.

**Create** `api/routes/review.py` · `api/schemas.py` ·
`api/deps.py` — the review endpoints from §49, plus
`POST /applications/{id}/answers` and `POST /questions/{id}/answer`.

**Rules:** localhost-only binding by default. Every review action writes an
`application_events` row with `actor=USER`. No endpoint can bypass
`SubmitGuard`.

**Tests:** approval without required fields → 409; submitting without
approval → 409; review actions are idempotent; audit rows are written.

**Verifiable now:** yes, with `TestClient`.

---

## PHASE 15 — APPLICATION TRACKER

**Goal:** move from text logs to a queryable tracker, keeping the text file.

**Create** `api/routes/applications.py` · `tracker/service.py` ·
`tracker/statuses.py` · `tracker/export.py` (CSV + JSON).

**Statuses** (user-facing, layered on the 16 machine states):
`Discovered · Matched · To Review · Ready · Applied · Under Review ·
Interview · Rejected · Offer · Withdrawn`

Manual status changes are always allowed. Export fields per §62.

**Tests:** `test_application_tracker.py` — status transition validation,
manual override, export contents, text file still written byte-compatibly.

**Verifiable now:** yes.

---

## PHASE 16 — ANALYTICS

**Goal:** honest counts. No invented statistics, no success-probability score
(§59 forbids it).

**Create** `analytics/queries.py` · `api/routes/analytics.py`

**Metrics:** discovered · matched · rejected · prepared · submitted · failed ·
needs-review · interviews · offers · match distribution · application
conversion · top titles · top companies · **top missing skills** · resume
versions used · common rejection patterns.

**Every metric states its own provenance.** A count from the database is
labelled as such. Nothing is extrapolated. The feedback loop (§33) produces
**suggestions only** and never mutates the candidate profile.

**Tests:** counts match seeded rows; empty DB → zeros, not an error; no
fabricated field; suggestions do not write to the profile.

**Verifiable now:** yes.

---

## PHASE 17 — TESTS (continuous, formalized here)

**Create** `tests/` with the 11 required modules plus
`test_deduplication.py`, `test_browser_mock.py`, `test_guards.py`,
`test_api.py`, `test_analytics.py`, `test_lint_invariants.py`.

**Infrastructure:** `TEST_DATABASE` env override (borrowed from repo 4);
`conftest.py` fixtures; `pytest.ini` with markers
(`unit`, `llm`, `browser`, `integration`).

**Two-tier strategy** (borrowed from repo 4's `CLAUDE.md`):
- `pytest -m "not llm and not browser"` — always runs, no network, no cost
- `pytest -m llm` — gated on a real provider, recorded not asserted
- `pytest -m browser` — opt-in, never in the default run

**The 17 acceptance tests** map as follows:

| Test | Phase | Module |
|---|---|---|
| 1 resume → profile | 4 | `test_resume_parser.py` |
| 2 job → Job object | 5, 6 | `test_jd_parser.py` |
| 3 match explanation | 7 | `test_matching.py` |
| 4 multi-resume selection | 8 | `test_resume_parser.py` |
| 5 tailored, no invented facts | 8 | `test_resume_parser.py` |
| 6 cover letter, no invented claims | 9 | `test_cover_letter.py` |
| 7 known question → verified answer | 10 | `test_question_engine.py` |
| 8 unknown → pause → queue → persisted | 10, 11 | `test_question_engine.py` |
| 9 contradiction detected | 4 | `test_profile.py` |
| 10 already applied blocked | 12 | `test_state_machine.py` |
| 11 crash → resumable | 12, 13 | `test_state_machine.py` |
| 12 dry run cannot submit | 3, 13 | `test_guards.py` |
| 13 verification missing → UNVERIFIED | 13 | `test_browser_mock.py` |
| 14 missing API key → clear error | 2, 10 | `test_config.py` |
| 15 malformed resume → graceful | 4 | `test_resume_parser.py` |
| 16 network timeout → retry + recovery | 6, 10, 12 | `test_answer_validator.py` |
| 17 unknown layout → recoverable/manual | 13 | `test_browser_mock.py` |

---

## PHASE 18 — HARDENING

**Goal:** enforce the architectural invariants as tests, not as intentions.

**Create** `tests/test_lint_invariants.py` — AST-based checks for all 12
invariants in TARGET_ARCHITECTURE §21, especially:

- `ai/` imports nothing from `selenium`, `fastapi`, `sqlite3`
- `db/` imports nothing from `selenium`, `fastapi`
- `automation/` imports nothing from `ai/` or `db/`
- the submit selector literal exists in exactly one file
- no `except: pass` / bare `except` in any module that decides whether a field
  was filled
- every prompt file has a `_v<N>` suffix
- `.env`, `cookies/`, `*.db`, `data/profile/`, `data/resumes/` are git-ignored

Also: structured logging wired in with the redaction filter; error codes
emitted from every failure path; graceful shutdown; retry policy centralised.

---

## PHASE 19 — DRY-RUN INTEGRATION

**Goal:** prove, end to end, that nothing can be submitted.

**Create** `tests/test_dry_run_integration.py` plus a `Makefile` target.

**Assert:** with `DRY_RUN=True`, the full pipeline runs to
`READY_TO_APPLY` → `WAITING_FOR_REVIEW` and **stops**. `SubmitGuard` refuses.
`Submit application` is never clicked. No state reaches `SUBMITTED` or
`VERIFIED`. The data file contains DRY RUN lines. The session summary reports
0 applied.

**Then, with the user's explicit instruction, a single real run is prepared
and stopped before the confirmation prompt.** I will not click submit.

---

## PHASE 20 — PRODUCTION DOCUMENTATION + FRONTEND

**Create**

```
README.md                        rewritten: what exists, how to run on Windows
docs/ARCHITECTURE.md
docs/SETUP.md                    venv → install → configure → run (PowerShell)
docs/CONFIGURATION.md            every setting, every env var
docs/AI_PIPELINE.md              providers, prompts, budgets, caching
docs/APPLICATION_FLOW.md         states, guards, verification
docs/SECURITY.md                 what is stored, what is never logged
docs/TROUBLESHOOTING.md          error codes → causes → fixes
docs/MIGRATION.md                old config → new settings, field by field
docs/CURRENT_SYSTEM_AUDIT.md     ✅ exists
docs/REFERENCE_RESEARCH.md       ✅ exists
docs/TARGET_ARCHITECTURE.md      ✅ exists
docs/IMPLEMENTATION_PLAN.md      ✅ this file
web/                             React + TS + Vite dashboard
```

**Dashboard views** (§31): Dashboard · Jobs · Matched Jobs · Application Queue
· Applications · Review Queue · Failed · Resumes · Profile · Analytics ·
Settings.

**Documentation rule:** every documented feature must exist and be tested.
Anything unbuilt is listed in a visible **"Not implemented"** section rather
than quietly described as if it works.

---

## 4. GAP ANALYSIS

### 4.1 Capability gaps

| Capability | Current | Required | Files to create | Files to change | Tests |
|---|---|---|---|---|---|
| Structured config | flat `config.py` | typed + YAML + validation | `config/*` | `config.py` (shim) | `test_config.py` |
| Secret handling | `.env` (checkpoint) | + redaction + gitignore | `core/redaction.py` | `.gitignore`, `requirements.txt` | `test_config.py` |
| Candidate profile | **absent** | VERIFIED/INFERRED/UNKNOWN store | `profile/*` | — | `test_profile.py` |
| Resume ingestion | **absent** | PDF/DOCX/TXT/MD + hash dedup | `resumes/*` | — | `test_resume_parser.py` |
| Job schema | ad-hoc strings | unified `Job` dataclass | `jobs/schema.py` | `linkedin.py` | `test_deduplication.py` |
| Database | text file only | SQLite, 14 tables, migrations | `db/*` | `utils.writeResults` (kept) | `test_application_tracker.py` |
| Dedup | per-page "Applied" text match | 3-tier multi-signal merge | `jobs/dedup.py` | `linkedin.py` | `test_deduplication.py` |
| JD extraction | **absent** | structured requirements | `jd/*` | — | `test_jd_parser.py` |
| Hard-blocker gate | **absent** | blockers beat similarity | `jd/gates.py` | — | `test_jd_parser.py` |
| Hybrid matching | title blacklist only | 11 scored dimensions | `matching/*` | — | `test_matching.py` |
| Resume selection | positional index | scored + reason | `resumes/selector.py` | `linkedin.chooseResume` | `test_resume_parser.py` |
| ATS analysis | **absent** | 9 measures, no fabrication | `resumes/ats.py` | — | `test_resume_parser.py` |
| Resume tailoring | **absent** | draft + change_log | `resumes/tailor.py` | — | `test_resume_parser.py` |
| Cover letters | **absent** | evidence-grounded | `letters/*` | — | `test_cover_letter.py` |
| Question engine | **absent** | 14 field types | `questions/schema.py` | — | `test_question_engine.py` |
| Evidence pipeline | **absent** | 7 levels, capped | `questions/evidence.py` | — | `test_question_engine.py` |
| Answer memory | **absent** | persisted, verified-only | `questions/memory.py` | — | `test_question_engine.py` |
| Answer validation | **absent** | hallucination guard | `ai/guard.py` | — | `test_answer_validator.py` |
| Unknown handling | **absent** | pause + queue + resume | `review/*` | — | `test_question_engine.py` |
| Human review | **absent** | 4 gates | `api/routes/review.py` | — | `test_api.py` |
| State machine | **absent** | 16 states, persisted | `applications/*` | — | `test_state_machine.py` |
| Resumable applications | **absent** | crash recovery | `applications/recovery.py` | — | `test_state_machine.py` |
| SubmitGuard | single dry-run check | 7 independent gates | `automation/guards.py` | `linkedin.py` | `test_guards.py` |
| Challenge detection | **absent** | CAPTCHA/MFA → pause | `automation/challenges.py` | `linkedin.py` | `test_browser_mock.py` |
| Verification | **absent** | post-submit confirm | `automation/linkedin/verification.py` | `linkedin.py` | `test_browser_mock.py` |
| LLM abstraction | **absent** | pluggable providers | `ai/*` | — | `test_answer_validator.py` |
| RAG | **absent** | metadata-filtered retrieval | `retrieval/*` | — | `test_answer_validator.py` |
| Prompt versioning | **absent** | `_v<N>` + recorded | `prompts/*` | — | `test_lint_invariants.py` |
| Cost control | **absent** | caches + budgets | `ai/budget.py` | — | `test_config.py` |
| Logging | `print()` + ANSI | structured + redacted | `core/logging.py` | `utils.pr*` (kept) | `test_lint_invariants.py` |
| Error codes | **absent** | 20 typed codes | `core/errors.py` | every layer | `test_lint_invariants.py` |
| Mock browser | **absent** | no-network tests | `automation/testing/*` | — | `test_browser_mock.py` |
| API | **absent** | FastAPI routes | `api/*` | — | `test_api.py` |
| Tracker | text file | SQLite + views | `tracker/*` | — | `test_application_tracker.py` |
| Analytics | **absent** | honest counts | `analytics/*` | — | `test_analytics.py` |
| Dashboard | **absent** | 11 views | `web/` | — | manual |
| Tests | **absent** | 15+ modules | `tests/*` | — | all |

### 4.2 What already exists and is reused

| Existing | Reused as |
|---|---|
| `utils.createDriver()` Chrome↔Edge | `automation/browser.py` — kept verbatim |
| `utils.chromeBrowserOptions()` / `edgeBrowserOptions()` | `automation/browser.py` |
| `utils.validateConfig()` / `printRunBanner()` | `config/settings.py` |
| `utils.writeResults()` append fix | `tracker/export.py` |
| `utils.getUrlDataFile()` | `LinkedInProvider.search` |
| `utils.LinkedinUrlGenerate` | `LinkedInProvider` search-URL builder |
| `LinkedinUrlGenerate` filters | `config/matching.yaml` defaults |
| `linkedin.py` search/apply loop | `automation/linkedin/search.py` + `application.py` |
| `linkedin.py.fillPhoneNumber()` | `automation/linkedin/fields.py` |
| `linkedin.py.submitApplication()` dry-run guard | `automation/guards.py` (superseded) |
| `linkedin.py` cookies format | `automation/linkedin/login.py` |
| `config.dryRun`, `maxApplicationsPerRun` | `core/safety.py` |
| `config.blackListTitles`, `blacklistCompanies` | `matching/rules.py` |
| `config.preferredCv` | `resumes/selector.py` override |
| `constants.py` selector literals | `automation/selectors.py` |
| `data/urlData.txt`, `Applied Jobs DATA` | preserved for compatibility |
| `data/review_queue/pending_questions.json` (new format) | replaces YAML answers |

### 4.3 Dependency delta

**Add:** `pydantic>=2`, `fastapi>=0.110`, `uvicorn`, `pdfplumber`,
`python-docx`, `pytest`, `pytest-asyncio`, `httpx`, `numpy`.
**Optional/config-gated:** `openai`.
**Already present, now declared:** `python-dotenv`.
**Never added:** any agent framework, any ORM, any vector database.

### 4.4 Explicitly out of scope

Not building, and not claiming: a second job provider · automatic profile
updates from outcomes · a success-probability score · retraining or fine-tuning
· multi-user support · cloud deployment · CAPTCHA solving or any challenge
bypass · mobile.

---

## 5. WHAT I NEED FROM YOU

| # | Item | Blocks | Notes |
|---|---|---|---|
| 1 | **Approve this plan** | everything | especially the phase order and the `PENDING` list |
| 2 | Confirm **safe defaults**: `SAFE_MODE=true`, `DRY_RUN=true` | 3 | I will not enable real submission |
| 3 | Your real **profile facts** | 4 | I will not invent any. Ships as an empty template |
| 4 | Your real **resumes** (PDF/DOCX) | 4, 8 | local files only; git-ignored |
| 5 | Whether to **deprecate `additionalQuestions.yaml`** | 4 | recommend: deprecate, migrate one field, never auto-import the 263 |
| 6 | **LLM provider** | 6, 9, 10 | Ollama (private, no key) or an API key in `.env` |
| 7 | Whether to **keep or retire Docker** | 3 | recommend: keep the file, mark deprecated, Windows-first |
| 8 | Confirm the **7 submit gates** | 3, 13 | including mandatory per-application human confirmation |

---

## 6. STOPPING HERE

Per §77, the audit and the four planning documents are complete and **no
implementation code has been written for the upgrade**.

Before phase 2 begins, two things must be settled:

1. **The plan is approved** (or amended).
2. **The personal-facts question is answered honestly.** The system's entire
   value rests on not inventing anything about you. A template full of
   `UNKNOWN` is correct and useful; a template full of plausible guesses is
   worse than no template at all, because the system would then be confidently
   wrong about you in an employer's inbox.

Nothing here changes the current state of the project. The bot still runs with
`dryRun = True`, the last checkpoint is committed, and the four documents are
the only additions.
