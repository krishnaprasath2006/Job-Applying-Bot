# TARGET ARCHITECTURE

**Status:** design proposal. **Milestone 3 implemented §7 (job schema,
deduplication) and the §6 evidence chain for job analysis**; everything else
is still design. Where this document and the code disagree, the code wins —
see `docs/ARCHITECTURE.md` §6 for the delivered job pipeline.
**Date:** 2026-09-30
**Authority:** this document describes the *intended* end state. Where it
conflicts with the code, the code is the truth and this document is a plan.
Sections marked **[PENDING]** are declared interfaces, not working features.

---

## 1. DESIGN NORTH STAR

> Build a system that helps me APPLY BETTER, not merely APPLY MORE.

Every architectural decision below is filtered through one question: *does this
make the system more truthful, more verifiable, more recoverable, or more
controllable?* If it only makes it faster or higher-volume, it is out.

The system is a **career assistant with a browser execution layer**, not a bot.

---

## 2. THE EXISTING SYSTEM'S ONE IRREPLACEABLE ASSET

The audit found the upstream project is a fragile scraper with one genuinely
hard-won capability: **it drives LinkedIn's Easy Apply DOM in a logged-in
session**. Twenty-five selector literals, `data-test-*` component attributes,
`aria-label` buttons, an `ember14` session probe — learned the hard way by
whoever wrote it.

**This must not be rewritten. It must be wrapped, guarded, and made
observable.**

Therefore: `linkedin.py` survives as **provider #1**, and the entire new
system is built *around* it, not *instead of* it.

---

## 3. LAYER MAP

```
┌──────────────────────────────────────────────────────────────────────┐
│  PRESENTATION                                                       │
│  dashboard (React+TS+Vite) · CLI · review queue UI                  │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  HTTP/JSON (FastAPI, 127.0.0.1 only)
┌───────────────────────────────▼──────────────────────────────────────┐
│  API  api/                                                          │
│  health · profile · resumes · jobs · matches · applications         │
│  review · analytics · export                                        │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  ORCHESTRATION  pipeline/                                           │
│  runner · step results · partial-failure reporting · resume/recovery │
└──┬────────┬─────────┬──────────┬──────────┬─────────┬──────────┬────┘
   │        │         │          │          │         │          │
   ▼        ▼         ▼          ▼          ▼         ▼          ▼
┌──────┐ ┌──────┐ ┌───────┐ ┌────────┐ ┌────────┐ ┌───────┐ ┌────────┐
│PROF. │ │MATCH │ │QUEST. │ │BROWSER │ │VERIFY  │ │STATE  │ │GUARD   │
│layer │ │layer │ │layer  │ │layer   │ │layer   │ │machine│ │layer   │
└──┬───┘ └──┬───┘ └───┬───┘ └───┬────┘ └───┬────┘ └───┬───┘ └───┬────┘
   │        │         │         │          │          │         │
   ▼        ▼         ▼         ▼          ▼          ▼         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  INTELLIGENCE  ai/  ·  retrieval/  ·  prompts/                       │
│  provider (openai|ollama|gemini) · embeddings · RAG · guards         │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  PERSISTENCE  db/                                                   │
│  sqlite · migrations · repositories · events · tracker · analytics   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  FOUNDATION  config/  ·  core/ (schemas, errors, logging, paths)     │
└──────────────────────────────────────────────────────────────────────┘
```

**The single rule that keeps this from becoming spaghetti:** arrows only point
down. The AI layer never imports Selenium. The database layer never imports
FastAPI. The browser layer never imports the LLM. Every layer is testable in
isolation, which is the whole point.

---

## 4. FOUR-WAY RESPONSIBILITY SPLIT

This is the load-bearing constraint of the entire design.

### 4.1 AI — understand, extract, classify, match, draft, explain, recommend, generate

The LLM **reads**. It never navigates, never clicks, never types into a field,
never decides that a submission succeeded.

Permitted: JD structuring, requirement extraction, semantic matching,
cover-letter drafting, answer *phrasing* from retrieved evidence,
explanation generation, contradiction explanation, tailoring *wording*.

Forbidden: inventing a fact, deciding a field is answered, choosing a resume
without a score, deciding an application succeeded.

### 4.2 Automation — navigate, inspect, fill verified values, upload, click non-destructive controls

The browser layer **acts**. It receives a fully-resolved, typed instruction
set and executes it. It may not decide what the correct value is. It may not
submit (§4.4).

It *may* click: `Continue`, `Review your application`, dropdown options,
radio labels, pagination, file upload. It may *not* click: `Submit
application` without the guard (§8.2).

### 4.3 Validation — verify identity, source, confidence, requiredness, state

A separate layer exists purely to answer "is this claim true?" — independent
of both the AI that produced it and the automation that would enter it.

Checks: field identity · answer source · answer confidence · required fields
present · current job identity · current application state · selected resume ·
review status · final state confirmation.

### 4.4 Human — approve

Mandatory human involvement at five gates:

1. **High-risk answers** — sponsorship, work authorization, legal eligibility,
   background/criminal, disability, veteran, demographic, salary commitment,
   years of experience, degree requirement, relocation promise
2. **Unknown answers** — anything below the confidence threshold
3. **Materially edited resumes** — any tailoring that changes claims
4. **Final submission** — always, every time, per §8.3
5. **Anything the platform challenges** — CAPTCHA, MFA, checkpoint

### 4.5 Database — remember

Jobs, applications, answers, decisions, failures, events, model runs,
evidence. If a decision is not in the database, it did not happen.

---

## 5. DATA FLOW — THE HAPPY PATH

```
 1  COLLECT      LinkedInProvider.search(urls) → [RawJob]
 2  NORMALIZE    → [Job] unified schema, content_hash
 3  DEDUPE       → merged, first-seen preserved
 4  EXTRACT      JobDescriptionParser → JobRequirements
 5  QUALITY      JobQualityFilter → flags (spam, vague, expired…)
 6  GATE         HardRequirementGate → hard_blockers[]
 7  MATCH        MatchEngine → dimension_scores + explanations
 8  SELECT       ResumeSelector → resume_id + reason + confidence
 9  TAILOR       ResumeTailor → draft + change_log  [human review if material]
10  LETTER       CoverLetterService → draft + evidence[]  [human review]
11  QUESTIONS    ApplicationQuestionEngine → [FormField]
12  ANSWER       AnswerPipeline (7 levels) → [Answer{evidence, confidence, risk}]
13  GATE         HumanReviewGate → approved / review / reject
14  PLAN         ApplicationPlan = frozen instruction set
15  GUARD        SubmitGuard.validate() → 6 independent checks
16  EXECUTE      BrowserExecutor (Edge/Chrome) with SubmitGuard armed
17  VERIFY       VerificationLayer → SUBMITTED | SUBMISSION_UNVERIFIED | FAILED
18  RECORD       events + answers + tracker + analytics
```

Steps 1–14 are **fully testable with zero browser and zero network** by
injecting fixtures. Only 15–17 touch Selenium. This is why the mock browser
layer (§10.2) is a hard requirement, not a nicety.

---

## 6. THE EVIDENCE CHAIN — NON-NEGOTIABLE

Every generated answer carries its provenance. This is the system's spine.

```
LEVEL 1  exact match in answer_memory        → confidence 0.99
LEVEL 2  normalized + fuzzy match (≥0.90)    → confidence 0.95
LEVEL 3  candidate profile field lookup      → confidence 0.90
LEVEL 4  resume evidence retrieval          → confidence 0.85
LEVEL 5  RAG over candidate documents       → confidence 0.70
LEVEL 6  LLM synthesis from retrieved ctx   → confidence 0.60
LEVEL 7  HUMAN REVIEW                       → confidence 1.00 (human)
───────── below any threshold, or any HIGH/CRITICAL risk ─────────
         → UNANSWERABLE → review queue. Never guessed.
```

**Level 6 is capped at 0.60 and may never satisfy a required field on its own.**
A required field answered only at Level 6 goes to review. Period.

A representative answer record:

```json
{
  "field_id": "f_8a3c",
  "question": "Do you have 2 years of React experience?",
  "field_type": "YES_NO",
  "answer": "No",
  "confidence": 0.96,
  "level": 4,
  "evidence": [
    {"kind": "skill", "source": "candidate.json", "ref": "skills.react",
     "quote": "React — 8 months (project: dashboard-ui, 2025-03..2025-11)"},
    {"kind": "resume", "source": "resume_hash:9f2c…", "ref": "experience[1]",
     "quote": "Built internal dashboards with React"}
  ],
  "source": "resume_evidence",
  "evidence_source": "retrieved",
  "risk_level": "LOW",
  "reason": "React is present but total duration is 8 months, below the 24-month threshold."
}
```

`evidence_source` is required on every artifact (borrowed from GPT-Jobhunter's
`analysis_source`). It is one of: `retrieved` · `profile` · `derived` ·
`model_prior`. **A `model_prior` answer on a HIGH/CRITICAL field is
automatically blocked**, because model priors are exactly the fabrication risk.

### 6.1 Verifiability labels

Every fact in the profile carries one of:

- `VERIFIED` — the user stated it, or it is provable from a document
- `INFERRED` — derived by the system from verified facts (e.g. "React is
  likely familiar, given a React project and a JS-heavy role")
- `UNKNOWN` — absent

`INFERRED` may inform a suggestion. **`INFERRED` may never satisfy a required
field and may never appear as a confident answer.** This is target §5 and it
is the mechanism that prevents the profile from slowly filling up with
plausible-sounding fiction.

---

## 7. THE JOB SCHEMA

> **Implemented (Milestone 3).** The delivered shape is a Pydantic model in
> `src/jobs/models.py` (not the dataclass below): the description is split
> into `description_raw` (byte-preserved), `description_text` (normalised),
> and `description_hash`, with identity and status fields alongside. The
> requirement lists live in the `job_requirements` table rather than on the
> model. Fields in the sketch below that have no counterpart yet are noted.

One internal shape, all providers conform. LinkedIn is provider #1; the
interface exists so a second provider is a new class, not a rewrite (§9.1).

```python
@dataclass(frozen=True)
class Job:
    id: UUID
    source: str                    # "linkedin"
    source_job_id: str             # stable platform ID
    title: str
    company: str
    location: str
    workplace_type: str | None     # Remote | Hybrid | On-site
    employment_type: str | None    # Full-time | Internship | Contract ...
    salary: str | None
    posted_date: date | None
    description: str               # FULL text — new; the old bot never read this
    requirements: list[Requirement]
    preferred_requirements: list[Requirement]
    url: str
    canonical_url: str
    easy_apply_available: bool
    application_method: str
    recruiter: str | None
    company_size: str | None
    raw_source_data: dict
    fetched_at: datetime
    content_hash: str
```

Adding `description` is the single most important schema change. Without it
there is no matching, no ATS, no cover letter, no question answering.

### 7.1 Deduplication — multi-signal

> **Implemented (Milestone 3).** `src/jobs/deduplicator.py` runs exactly
> these three tiers, and `tests/test_job_persistence.py` covers merge
> behaviour (`seen_count`, earliest `fetched_at`, longest description).

```
tier 1   (source, source_job_id)              exact platform identity  → hard reject
tier 2   canonical_url                         normalized URL          → hard reject
tier 3   (normalized_company, normalized_title,
          normalized_location, content_hash)   same job, reformatted    → merge
```

Normalization: lowercase, strip legal suffixes (`Inc`, `Ltd`, `LLC`, ` Pvt`,
`Technologies`, whitespace, punctuation), collapse whitespace.

On a tier-3 hit the records **merge** — earliest `fetched_at` and the longest
`description` win, `seen_count` increments, and the first sighting is never
lost. A job must not be applied to twice because a URL gained a tracking
parameter, the search keyword changed, or the pagination offset differed.

**This directly closes audit finding C4** (no duplicate suppression across
runs) and is stronger than every reference implementation: repo 3 used a pickle
of job IDs, repo 4 used `"{company} - {title}"`.

---

## 8. BROWSER SAFETY — THE FOUR INDEPENDENT GATES

### 8.1 Defence in depth

Real submission requires **all seven** to agree. Any single disagreement
blocks. One bug must not become one real application.

```
 1  SAFE_MODE                    static, default true
 2  DRY_RUN                      default true
 3  human confirmation           explicit, per-application, in the UI
 4  current-job identity          company + title + job id match the plan
 5  application-state validity    state ∈ {READY_TO_APPLY, APPLICATION_STARTED}
 6  answer completeness          0 unresolved required fields, 0 HIGH-risk unapproved
 7  SubmitGuard.validate()        composite of 1-6, evaluated at the last moment
```

Gates 1–2 are configuration. 3 is human. 4–6 are validation. 7 is the single
call site the execution layer is permitted to use. **The raw CSS selector for
the submit button does not exist anywhere else in the codebase** — it is
reachable only through the guard.

This is strictly stronger than the current `submitApplication()` method, which
is a good dry-run check but a single point of failure.

### 8.2 The challenge wall

If a CAPTCHA, MFA, `/checkpoint/`, or rate-limit page appears:

**PAUSE · RECORD STATE · REQUIRE HUMAN.** Never bypass, never solve, never
retry into it. Emit `CAPTCHA_REQUIRED` or `AUTH_REQUIRED`, persist the
application as `APPLICATION_PAUSED`, surface the job URL so a human can finish
by hand. This is a hard stop, not a retry.

*(Note: `selenium_stealth` and the `--disable-blink-features=AutomationControlled`
flags already in the codebase are **kept unchanged** — they are pre-existing
user behaviour and removing them may break login. They are simply **not
extended, not added to, and not relied upon**. See audit §16.1.)*

### 8.3 Submission is never silent

Before the click:

```
Application ready for <Company> — <Role>
  resume    : ai_engineer_resume.pdf  (confidence 0.88)
  match     : 0.81  [must_have 0.95 · skills 0.88 · seniority 0.62]
  answers   : 6 verified · 1 needs review · 0 unverified
  blockers  : none
Submit?  [y] yes   [e] edit   [s] skip   [q] quit
```

Only `y` proceeds. `config.dryRun` being `False` is **not** sufficient on its
own. The current codebase requires only `dryRun`; the new one requires this.

### 8.4 Verification after submit

Clicking Submit proves nothing. After the click:

1. Wait for a terminal state: application-confirmation UI, a "Submitted"
   marker, or a return to the job list
2. If confirmed → `APPLICATION_VERIFIED`
3. If the form is still open, or an error is present, or the page is
   unrecognized → **`SUBMISSION_UNVERIFIED`** → human follow-up
4. **Never** write "Just Applied" without a verification record

This closes audit finding **C2**, where the current code writes
`🥳 Just Applied` after a blind click and a 1–5 s sleep.

---

## 9. PROVIDER ARCHITECTURE

### 9.1 The interface

```python
class JobProvider(Protocol):
    name: str
    def search(self, criteria: SearchCriteria) -> Iterator[RawJob]: ...
    def fetch_detail(self, ref: str) -> RawJob: ...
    def can_apply(self, job: Job) -> bool: ...
```

Implementations: `LinkedInProvider` (wraps the existing Selenium code),
`FutureProvider` **[PENDING — interface only, no second implementation
claimed]**.

`JobProvider` is a declared seam, not a claimed capability. Per §74 and audit
§7.9, we do not pretend a second provider exists.

### 9.2 JobQualityFilter

Flags before matching: missing company · contradictory salary range ·
impossible requirements ("20 years experience, entry level") · extreme
vagueness · spam-like repetition (n-gram repetition score) · missing
application link · expired indicators. Flagged jobs still enter the database
with their flags visible — the filter informs, it does not silently delete.

---

## 10. TESTABILITY ARCHITECTURE

### 10.1 Layer isolation

| Layer | Network | Browser | LLM | DB |
|---|---|---|---|---|
| `profile/` | no | no | no | in-memory |
| `resumes/` | no | no | no | in-memory |
| `jobs/` (normalize, dedupe) | no | no | no | in-memory |
| `jd/` (parser) | no | no | mocked | no |
| `matching/` | no | no | mocked | in-memory |
| `questions/` | no | no | mocked | in-memory |
| `automation/` | no | **mock** | no | in-memory |
| `api/` | no | mock | mocked | temp file |
| `pipeline/` | no | mock | mocked | temp file |

Only `LinkedInProvider` and the real `ExecutionLayer` ever touch a browser.

### 10.2 The mock browser

`automation/testing/` provides:

- `FakeDriver` implementing the subset of the WebDriver API we use
- `FakeElement` with an attribute bag and configurable states
- Recorded HTML fixtures of LinkedIn search, job, and Easy Apply pages
  (synthetic or captured-and-anonymized — never a real candidate's data)
- Scriptable page sequences: "login → challenge → search → job → form → review
  → submitted" and every failure variant

Test 11 (browser crash → resume) and TEST 17 (unknown layout → recoverable
manual path) are only possible with this layer.

**No automated test may ever reach LinkedIn. No test may ever submit.**

---

## 11. AI ARCHITECTURE

### 11.1 Provider interface

```python
class LLMProvider(Protocol):
    name: str
    def complete(self, req: CompletionRequest) -> CompletionResult: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Implementations: `OpenAIProvider`, `OllamaProvider` (local, default when no API
key), `GeminiProvider`. Selected by config; swappable at runtime. Every call
records `provider`, `model`, `prompt_version`, `token_in`, `token_out`,
`cost`, `latency`, `timestamp` in `model_runs`.

**A missing API key is a typed setup error with instructions — not a stack
trace** (TEST 14), following GPT-Jobhunter's `_is_placeholder_key` pattern.

### 11.2 Prompt versioning

`prompts/<name>_v<N>.txt`. The version string is stored with every output. A
prompt edit without a version bump is a bug, because it destroys the audit
trail. Templates use strict delimiters and JSON-schema output contracts,
validated after generation (never trusted).

### 11.3 Hallucination guard — post-generation

Runs on **every** generated artifact:

```
1  extract factual claims (entities, numbers, dates, tech, orgs)
2  load the claim set from VERIFIED profile + retrieved evidence
3  for each claim not in the allow-set  →  UNSUPPORTED_CLAIM
4  also check: invented employer · invented metric · inflated years
             invented certification · invented authorization
             invented salary · off-list option value
5  any UNSUPPORTED_CLAIM  →  REJECT, or route to human review
```

Complements repo 2's *pre*-storage placeholder repair: we repair before and
validate after.

### 11.4 Cost control

| Control | Mechanism |
|---|---|
| Question cache | answer_memory keyed on normalized question + profile version. **Never ask the LLM the same question twice.** |
| JD cache | keyed on `content_hash`; a re-collected identical JD costs zero |
| Embedding cache | content-hash → vector, on disk |
| Per-task model routing | classification/extraction → cheap; generation → strong; `risk_level=HIGH` → no LLM at all |
| Token budget | hard per-run and per-day ceilings; exceeded → stop with a clear message |
| Jittered backoff | on rate limit **and** on message-sniffed 429s; hard cap, no global mutation |
| Local option | Ollama by default when no API key is configured — private resumes never leave the machine unless the user opts in |

---

## 12. PERSISTENCE

SQLite via stdlib `sqlite3`. No ORM, no Docker dependency, one file, trivially
backed up and deleted. WAL mode for concurrent dashboard reads during a run.

```sql
users · candidate_profiles · resumes · documents
jobs · job_requirements · job_matches
applications · application_answers · application_events
application_reviews · application_failures
question_memory · model_runs
```

Migrations are numbered, forward-only, tracked in `schema_migrations`, and
**never hidden inside `try/except`** (GPT-Jobhunter conflates "already
migrated" with "failed" — we do not).

### 12.1 The event log is the source of truth

Application state is **never inferred from logs or from the UI**. Every
transition is a row:

```
event_id · application_id · job_id · seq · from_state · to_state
actor (AI|SYSTEM|USER) · timestamp · duration_ms
error_code · detail (redacted) · prompt_version · model_run_id
```

`seq` is monotonic per application, so the timeline is replayable and a crash
is visible as a missing terminal transition.

### 12.2 Text output is preserved

`data/Applied Jobs DATA - YYYYMMDD.txt` continues to be written, byte-compatible
with existing tooling, alongside the database. **Backward compatibility is a
requirement, not a courtesy** (§67).

---

## 13. THE 16 STATES

```
DISCOVERED → NORMALIZED → MATCHED → REJECTED
                        ↓
                     SELECTED → RESUME_SELECTED → RESUME_TAILORED
                        ↓         ↓
                   COVER_LETTER_READY → QUESTIONS_ANALYZED
                        ↓
                 WAITING_FOR_REVIEW ──(approved)──→ READY_TO_APPLY
                        │                                    ↓
                        │                        APPLICATION_STARTED
                        ↓                                    ↓
              APPLICATION_PAUSED ──(resume)──→      SUBMITTED → VERIFIED
                        │                                    ↓
                        │                            SUBMISSION_UNVERIFIED
                        ↓
              NEEDS_MANUAL_ACTION  →  APPLICATION_FAILED
```

Terminal: `REJECTED`, `APPLICATION_VERIFIED`, `SUBMISSION_UNVERIFIED`,
`APPLICATION_FAILED`. Every transition is validated against an adjacency
matrix; an illegal transition raises a typed error and is logged, never
guessed. `SUBMISSION_UNVERIFIED` is a **first-class terminal state** — it is
the honest answer to "we clicked Submit and cannot confirm it worked"
(TEST 13).

### 13.1 Recoverable, not restartable

Persisted per application: the plan, the resolved answers, the current form
step, the resume ID, the browser position, the last verified state.

On restart the system lists resumable applications, and it **checks the
database before re-submitting anything that reached `SUBMITTED` or
`SUBMISSION_UNVERIFIED`**. A verified submission is never repeated. An
unverified one is surfaced for a human, not blindly retried.

---

## 14. HUMAN REVIEW

One queue, four item types: `UNANSWERED_QUESTION` · `HIGH_RISK_ANSWER` ·
`MATERIAL_RESUME_CHANGE` · `UNVERIFIED_SUBMISSION`.

Each item carries: job (company, title, URL) · the question or change · field
type and options · the suggested answer · confidence · evidence · risk level ·
a screenshot path when available.

Per item: **Approve · Edit · Skip Question · Mark Manual · Skip Job**.

"Mark Manual" hands the whole application to the human with the browser opened
at the right step and the verified answers pre-filled. The system never blocks
a human from finishing by hand.

---

## 15. CONFIGURATION

```
.env                  secrets only — never committed, never logged
config/application.yaml   run mode, safety, paths, limits
config/matching.yaml      weights, thresholds, hard-blocker rules
config/ai.yaml            providers, models, budgets, cache policy
config/browser.yaml       browser, profile, timeouts, selector overrides
```

Typed settings objects, validated at startup by one call, with a human-readable
report of every problem — extending the existing `utils.validateConfig()`.
**No setting lives in two places.** The existing `config.py` becomes a
compatibility shim that reads the new settings and preserves
`config.dryRun`, `config.maxApplicationsPerRun`, `config.blackListTitles`, and
the rest, so nothing that depends on the old names breaks.

---

## 16. OBSERVABILITY AND ERRORS

### 16.1 Structured logging

`logging` with two handlers: a human-readable console, and a JSON-lines file.
Every record: `ts · level · component · job_id · application_id · event ·
duration_ms · error_code`.

**Never logged:** passwords · session cookies · API keys · full resume text ·
PII field values. A redaction filter runs on the formatter, not on call sites,
so a careless `logger.info(user_data)` cannot leak.

### 16.2 Error codes

`AUTH_REQUIRED` · `CAPTCHA_REQUIRED` · `PAGE_CHANGED` · `SELECTOR_NOT_FOUND` ·
`JOB_NOT_FOUND` · `APPLICATION_STATE_UNKNOWN` · `UNKNOWN_FIELD` ·
`ANSWER_NOT_VERIFIED` · `UPLOAD_FAILED` · `NETWORK_ERROR` · `TIMEOUT` ·
`ALREADY_APPLIED` · `SUBMISSION_BLOCKED` · `VERIFICATION_FAILED` ·
`MALFORMED_RESUME` · `PROFILE_CONTRADICTION` · `CONFIDENCE_TOO_LOW` ·
`UNSUPPORTED_CLAIM` · `BUDGET_EXCEEDED` · `UNSAFE_BROWSER_STATE`

Each carries a user-facing message and a suggested action. No code path that
decides whether a field got filled may use `except: pass` (§53).

---

## 17. HUMAN-READABLE OUTPUT — THE MOST IMPORTANT SECTION

The user must always be able to answer *"why is this system recommending this
job?"*

Every job card:

```
AI Engineer · Zeta Corp · Bengaluru, India · Remote
──────────────────────────────────────────────────
MATCH 0.81   [grounded_in: resume + profile + jd]

  must-have skills   0.95  ✓ Python  ✓ ML  ✓ SQL  ✗ Kubernetes
  skills             0.88  12/14 matched
  experience         0.62  JD asks 2 yrs; you have 8 months
  seniority          0.62  JD is mid; entry-level resume
  authorization      1.00  ✓ Indian citizen, no sponsorship needed
  location           1.00  ✓ Remote, India
  resume evidence    0.83

  STRONG     Python, scikit-learn, pandas, SQL, REST
  MISSING    Kubernetes (must-have), Airflow (nice-to-have)
  TRANSFER   PyTorch → TensorFlow (same paradigm)
  RISK ⚠️     2-year requirement vs 8 months actual

RESUME   ai_engineer_resume.pdf  (0.88)  — 3 changes, all wording
LETTER   cover_letter_zeta.md    (preview · edit · regenerate)
ANSWERS  6 verified · 1 needs review ⚠️
STATUS   To Review
```

Every dimension scored separately. **No single magic number.** A 0.95
semantic cosine similarity with a missing must-have certification is a
**rejection**, not a strong match.

---

## 18. TECHNOLOGY CHOICES AND WHY

| Choice | Rationale | Rejected alternative |
|---|---|---|
| **SQLite** (stdlib) | single file, zero ops, trivially deletable, matches repo 4's proven scale | Postgres — server to run for one user |
| **FastAPI** | typed, auto-docs, trivially testable with `TestClient` | Flask — no native typing; raw `http.server` — no ecosystem |
| **Pydantic v2** | schema validation at every boundary, free JSON | dataclasses alone — no runtime validation of external input |
| **React + TS + Vite** | the requested stack; fast HMR for a dashboard | Next.js — SSR complexity unused for a localhost tool |
| **pdfplumber** | best-in-class text extraction, already proven in repo 4 | PyPDF2 — worse on complex layouts |
| **python-docx** | stdlib-adjacent, reliable | docx2txt — less structure |
| **Ollama default** | private by default; no key needed | mandatory cloud API — sends resumes to a third party |
| **No ORM** | explicit SQL is inspectable and matches the 14-table scope | SQLAlchemy — indirection with no benefit here |
| **No LangChain** | we need a provider interface and a retrieval layer, not a framework; the whole point is to *not* hide the evidence chain | LangChain/LlamaIndex — abstracted-away provenance is the opposite of the goal |
| **No Docker for the main path** | user is on Windows + Edge | Docker as primary — see audit §16.2 |

**Every dependency added is justified by a named requirement.** No framework
is introduced "for structure".

---

## 19. WHAT EXISTING BEHAVIOUR IS PRESERVED

| Existing behaviour | Disposition |
|---|---|
| `config.dryRun` | **preserved** — compat shim; `SAFE_MODE` added alongside, never instead |
| `maxApplicationsPerRun` | **preserved** — now also bounds dry-run (already fixed) |
| `blackListTitles`, `blacklistCompanies` | **preserved** — loaded from the new config into the old names |
| Search URL builder | **preserved** — same params, same output; wrapped in `LinkedInProvider` |
| `data/Applied Jobs DATA - *.txt` | **preserved** — still written, byte-compatible |
| `data/urlData.txt` | **preserved** |
| `cookies/<md5>.pkl` | **preserved** — format unchanged so existing sessions keep working |
| Phone filling | **preserved** — same 7 CSS + 4 XPath selectors, now with evidence tracking |
| Resume selection | **preserved** — positional `preferredCv` still works; *additionally* a scored selector can choose |
| `chooseResume` no-op-on-missing behaviour | **changed deliberately** — now raises a typed `UPLOAD_FAILED` instead of silently submitting the wrong resume. This is audit finding H5-adjacent and a real correctness bug. |
| Selenium driver setup | **preserved** — `utils.createDriver()` Chrome↔Edge fallback retained verbatim |
| `selenium_stealth` | **preserved unchanged**, not extended |
| `additionalQuestions.yaml` | **deprecated, not deleted** — the free code only ever read one key from it. New `answers.json` is the source of truth. Migration documented. |
| Everything else in the Pro settings | **left alone** — still dead, still clearly labelled. Not our scope to remove paid-feature placeholders from an open-source repo. |

**Nothing in the existing automation is deleted.**

---

## 20. WHAT IS EXPLICITLY **[PENDING]**

Declared interfaces, not claims:

- `FutureProvider` — no second job source
- Multi-resume **upload** automation (LinkedIn file upload already works via
  the existing resume picker; uploading a *tailored* file programmatically is
  not implemented)
- DOCX/HTML **export** of tailored resumes — the change log and draft are
  produced; PDF export is not built
- Any second LLM provider beyond Ollama + OpenAI (Gemini is a protocol
  implementation, untested against the live API)
- Analytics beyond counts and distributions (no predictive modelling, no
  success-probability score — §59 forbids it)
- Automatic profile updates from application outcomes — §33 requires insights
  to be suggestions only

Each of these appears in the implementation plan as a numbered item marked
`PENDING`, and is excluded from "Definition of Done".

---

## 21. ARCHITECTURAL INVARIANTS

Enforceable, and checked by tests. If one of these breaks, the build fails.

1. `ai/` never imports `selenium`, `fastapi`, or `sqlite3`
2. `db/` never imports `selenium`, `fastapi`, or `llm`
3. `automation/` never imports `ai/` or `db/`
4. The submit-button CSS selector exists in exactly one file
5. `SubmitGuard.validate()` is called on every code path that submits
6. Every state transition writes an `application_events` row
7. Every generated artifact carries `evidence` + `evidence_source`
8. No LLM output reaches a form field without passing the hallucination guard
9. No test performs a network call or touches a real browser
10. `.env`, `cookies/`, `data/profile/`, `data/resumes/`, `*.db` are
    git-ignored, and a test asserts it
11. No prompt without a version suffix
12. No `except: pass` in any path that decides whether a field was filled —
    enforced by an AST-based lint test
