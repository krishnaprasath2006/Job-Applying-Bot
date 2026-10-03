# REFERENCE RESEARCH

**Date:** 2026-09-30
**Purpose:** extract *architectural patterns* from existing AI-assisted
LinkedIn-apply and job-matching projects, so this upgrade borrows proven ideas
instead of inventing them.

**Method:** each repository was shallow-cloned and its AI/automation path, data
model, config surface, and tests were read at the commit below. Findings are
read from source, not inferred from the README. No code is copied.

| # | Repository | Branch | Commit inspected |
|---|---|---|---|
| 1 | `ganeshraj-k/linkedin_easyapply_bot_RAG` | `main` | `36bd0f15` |
| 2 | `JorgeFrias/LinkedIn-GPT-EasyApplyBot` | `master` | `9a710bbf` |
| 3 | `srikar-kodakandla/linkedin-easyapply-using-AI` | `main` | `9e3a8842` |
| 4 | `espin086/GPT-Jobhunter` | `main` | `69d202a3` |

> **One UNVERIFIED item:** the internals of repo 1's `gpt35_rag_api.py`. Its
> existence and role as the GPT-3.5-only variant are confirmed; its body was
> not re-read. Nothing in our design depends on it.

> **Runtime behaviour was not executed** for any repository. Claims about which
> code paths trigger are inferred from control flow, not observation.

---

## 1. THE LANDSCAPE, BRIEFLY

The four projects split into two families, and **this distinction drives the
whole architecture**:

- **Repos 1–3 are apply bots.** They scrape LinkedIn, answer forms, submit.
  Their AI is a *form-filling* component. None of them extracts a job
  description into structured requirements.
- **Repo 4 is not an apply bot.** It is a job-discovery, resume-matching and
  ATS-optimizer product with a real backend, a real database, a real frontend,
  and 13 test modules. It has **no browser automation and no apply flow at all.**

Repo 4 is therefore the reference for **everything except the browser layer**,
and repos 1–3 are the reference for **the browser layer only** — specifically
for how they scrape LinkedIn form fields.

The target architecture needs both halves. No single reference project has both.

---

## 2. REPO 1 — `linkedin_easyapply_bot_RAG`

### 2.1 What it is

A Jupyter-notebook Selenium bot plus a separate FastAPI RAG service, joined by
a single HTTP call.

```
bot_sep21.ipynb  (Selenium + Edge)
   └─ qna_engine()
        1. exact key hit in questions.json
        2. fuzzy  fuzz.WRatio >= 90, top 3
        3. RAG fallback
        4. WRITE THE RAG ANSWER BACK into questions.json
   →  POST /resume_qa  →  uvicorn (LlamaIndex RouterQueryEngine)
                              ├─ summary_tool  GPT-3.5 + text-embedding-ada-002
                              └─ vector_tool   local phi3 + BAAI/bge-small-en-v1.5
   →  applied_jobs.xlsx
```

Stack: Python 3.12, Selenium (Edge), FastAPI/Uvicorn, `llama_index.core`,
`OpenAI` (gpt-3.5, ada-002), `Ollama` (`phi3:3.8b-mini-4k-instruct-q4_K_M`),
`HuggingFaceEmbeddings` (`BAAI/bge-small-en-v1.5`), `torch`, `python-dotenv`,
`fuzzywuzzy`, OpenPyXL.

### 2.2 Patterns worth borrowing

**★ A — Cascading answer resolution with write-back caching.** Notebook cell 9,
`qna_engine`. Exact match → fuzzy match (threshold 90) → RAG. The RAG answer
is then **inserted into the dictionary**. Cost per *unique* question is paid
once, ever; cost per *repeat* is a dict lookup. This is the single most
valuable idea in the apply-bot family, and it maps directly onto target §19
(LEVEL 1 exact → LEVEL 2 fuzzy → …) and §56 (answer memory).

*Limitation:* the cache is an in-memory dict and is never reloaded, so the
learning dies on restart. It also cannot distinguish "the LLM answered this
correctly" from "the LLM hallucinated this once" — and it will then reuse the
hallucination forever.

**★ B — Two-tier LLM routing by answer length, encoded in tool descriptions.**
`agentic_rag_api.py:173`, `RouterQueryEngine` + `LLMSingleSelector`. The
`summary_tool` description says *"Use only for long answer and summary based
questions… do not use otherwise"*; the `vector_tool` description says *"Useful
for short questions about the profile. Use this tool always until specifically
requested for long form answers"*. A local 3.8B model absorbs the common
short-answer path; a paid frontier model handles the rare long-form.

*Limitation:* the routing policy is English prose that the LLM is asked to
respect. Nothing asserts the router chose correctly, and there is no fallback
when it misclassifies. We will adopt the *tiering* but implement the *dispatch*
deterministically.

**C — Form state machine driven by DOM button presence.** `apply_job`, cell 11.
Loops `while not theresubmit(driver)`, dispatching to handlers keyed on
LinkedIn's `data-test-*` component attributes: `select_resume`,
`radio_select`, `dropdown_select`, `fill_single_line_text_field`,
`fill_multiline_text_field`, `checkbox_select`, `autofill_answer`.
`attempt_click_next` retries Continue and, on failure, prints "Manually fill
this page" and sleeps 20 s.

This is the correct *shape* for our application state machine (§23): the
progress indicator is the DOM, not a percentage scraped through a positional
XPath and turned into `math.floor(100/pct) - 2`. It directly fixes audit finding
**C1**.

*Limitation:* a 20-second sleep is not a review queue. The state is never
persisted, so the 20 seconds are lost on crash.

**D — Prompt-level answer shaping.** The phi3 prompt hardcodes rules like
*"always return values greater than 1"* for years of experience and *"always
return 'Yes'"* for experience and relocation questions.

**This is adopted as an explicit anti-pattern.** See §7.1.

### 2.3 Weaknesses

- **Real PII committed to git**: `all_data/docs/questions.json` holds a real
  name, phone number and email; `ganeshrajk_resume_Sept.pdf` is committed;
  both persisted LlamaIndex vector stores are committed.
- **Hardcoded absolute Windows paths** in `all_paths.json`,
  `agentic_rag_api.py:23-29`, and notebook cell 2, all pointing at
  `C:\Users\localadmin\Desktop\...`. The repo cannot run anywhere else.
- **Import-time side effects**: `agentic_rag_api.py:39-43` opens a JSON file and
  sets `os.environ` at module scope; both indexes are constructed at module
  scope. Importing the module for a test has side effects.
- **No error taxonomy**: `except Exception: pass` / bare `return` on ~20
  handlers. A failed fill is indistinguishable from an unfillable field.
- **Double-written tracking**: `append_row_to_excel()` is called at the *start*
  of `apply_job` and again on dismiss — every job yields two rows, one of them
  a false positive.
- No tests, no linting, no dependency pinning, no CI.

---

## 3. REPO 2 — `LinkedIn-GPT-EasyApplyBot`

### 3.1 What it is

A linear pipeline with a central orchestrator. No services, no HTTP, no
database. All state is attributes of one `LinkedinEasyApply` instance.

Stack: Python, `argparse` CLI, Selenium Chrome + `webdriver_manager`,
`pyautogui`, `langchain == 0.0.175` (`PromptTemplate`, `OpenAI`, `ChatOpenAI`,
`ConversationChain`, `LLMChain`, `LLMRouterChain`, `RouterOutputParser`,
`MultiPromptChain`), `gpt-3.5-turbo-0613` (cheap) + `text-davinci-003`
(expensive), `python-Levenshtein`, `PyYAML`, `validate-email`, `python-dotenv`,
`unittest`.

```
main.py ─ validate_data_folder() / validate_yaml() / init_browser()
       └─ LinkedinEasyApply
            ├─ login()            5-10 s randomised pauses
            ├─ security_check()   BLOCKING input() on /checkpoint/challenge/
            └─ start_applying()   cartesian(positions, locations), shuffled
                 └─ apply_to_job() extract → blacklist → GPT filter → fill/next loop
```

### 3.2 Patterns worth borrowing

**★ A — Levenshtein snapping of every closed-vocabulary answer.** This is the
strongest output-grounding guard in the entire set, and it is *deterministic*,
not a prompt instruction.

- `answer_question_from_options` (`gpt.py:554`): if the LLM returns a string
  not in `options`, snap to `min(options, key=lambda o: distance(output, o))`
- `job_title_passes_filters` / `job_description_passes_filters`
  (`gpt.py:657`, `gpt.py:701`): snap to `['yes','no']` before casting to bool
- `answer_question_numeric` (`gpt.py:502-506`): `int()` with a fallback

The model **cannot escape the legal answer set**, whatever it emits. This maps
onto target §18 (`SELECT`, `RADIO`, `YES_NO` field types) and §37
(hallucination guard). We adopt it and extend it: a snapped value is recorded
as `source="option_snapping"`, never as a confident profile lookup.

**★ B — Form-error-driven self-correction.** `textbox_gpt_handle_form_errors`
(`linkedineasyapply.py:676`) reads LinkedIn's own
`artdeco-inline-feedback--error` element and calls
`try_fix_answer(question, answer, error)` (`gpt.py:707`) with a domain hint
baked in: *"Please enter a valid answer"* → shorten below a tweet; *"Enter a
whole number between 0 and 30"* → return just the number.

The bot reads its own validation errors and repairs against them rather than
aborting. This is target §21 (unknown handling) done well, and it is the
natural companion to the review queue: a field the form rejects should
generate a *typed* recovery record, not a silent `except`.

**★ C — Routing decision by the strong model, execution by the weak model.**
`GPTAnswerer.__init__` (`gpt.py:119-130`) builds `llm_cheap`
(gpt-3.5-turbo-0613) and `llm_expensive` (text-davinci-003). Every task uses
cheap **except** the router at `gpt.py:408`, which carries an explicit
`# TODO: This is expensive.` This is the correct split, and it is a cleaner
form of repo 1's idea B because the dispatch is in code, not prose.

**D — Placeholder repair loop.** `_contains_placeholder` / `_remove_placeholders`
(`gpt.py:569-621`) detect `[[placeholder]]` markers and iteratively re-prompt,
capped at `max_iterations = 5`, instructing the model to delete unfillable
placeholders. Every routed answer passes through this.

Adopted as a **generation-time** guard, complementing our
**post-generation** guard (§37). The distinction matters: repo 2 repairs before
the text is stored; we validate after.

**E — Answer provenance logging.** `record_gpt_answer()` writes every answer to
`gpt_answers.csv`; `LLMLogger.log_request` writes full prompt+response to
`open_ai_calls.log`. Plus `skipped_jobs.csv` with a `skipped_stage` column
distinguishing *Title Filtering* from *Description Filtering*.

*Limitation:* `gpt_answers.csv` is write-only — nothing ever reads it back. We
adopt the audit trail but store it in SQLite where it is queryable (§30, §47).

**F — Dry-run as a first-class switch.** `EnvironmentKeys`
(`linkedineasyapply.py:14`) exposes `SKIP_APPLY`,
`DISABLE_DESCRIPTION_FILTER`, `SKIP_JOB_SUMMARIZATION`. `SKIP_APPLY=True` runs
the whole pipeline up to the click without clicking. This matches our existing
`config.dryRun`; we keep ours and add `SAFE_MODE` on top.

**G — Security-check halt.** `security_check()` blocks on
`input()` when the URL contains `/checkpoint/challenge/`. This is the minimum
bar for target §27's "if a challenge appears: PAUSE, RECORD STATE, REQUIRE USER
ACTION". We need this, and we need it to be *typed* (→ `CAPTCHA_REQUIRED`).

### 3.3 Weaknesses

- **No durable state.** `self.seen_jobs` is an in-memory list reset each run;
  `is_blacklisted` relies on `link in self.seen_jobs`
  (`linkedineasyapply.py:336`). Restart → re-apply.
- **Dead code as design intent.** `unprepared_questions_file_name` and
  `unprepared_questions_gpt_file_name` (`linkedineasyapply.py:85-86`) are
  declared and **never referenced anywhere** (verified by full-tree grep). The
  human-review-for-unknown-questions feature is announced and unimplemented.
  Useful lesson: we must not let "the interface exists" stand in for "the
  behaviour exists".
- **Title blacklist is broken.** `job_title.lower().split(' ')` produces a
  `list`; the comparison list holds `strings`. It can never match.
- **Guaranteed `AttributeError`.** `get_answer` / `get_checkbox_answer`
  (`linkedineasyapply.py:539-556`) reference `self.checkboxes`, never assigned.
- **Config key ignored.** `get_base_search_url` does
  `parameters.get('experienceLevel', [])` (`linkedineasyapply.py:955`) for
  `job_types`; `jobTypes` is validated in `main.py` and then never used.
- **Exception constructed, never raised.** `Exception(f"Could not extract job
  information…")` at `linkedineasyapply.py:362` discards the error.
- **~25 bare `except:` / `except Exception: pass`** in the form-fill path —
  silent partial application.
- **`pdb` imported** at `linkedineasyapply.py:1`.
- **Tests hit the live OpenAI API** with no mocks — non-deterministic, cost
  money on every run. Two of the nine assert nothing at all.
- Plaintext credentials expected in `Templates/config.yaml`.

---

## 4. REPO 3 — `linkedin-easyapply-using-AI`

### 4.1 What it is

One 783-line file, `apply.py`. No package, no modules, no tests. Config JSON is
injected into module globals:

```python
with open(f'{sys.argv[1]}.json') as f: data = json.load(f)
for key in data: globals()[key] = data[key]        # apply.py:32-33
```

Stack: `undetected_chromedriver` (`uc.Chrome()`), Selenium,
`webdriver_manager`, `gpt4_openai.GPT4OpenAI` (automates the **ChatGPT web UI**
with a session cookie token), `google.generativeai` (`gemini-pro`),
`demjson3` (lenient JSON), `re`, `telebot`, `concurrent.futures`, `pickle`.
Last commit 2024-04-13.

### 4.2 Patterns worth borrowing

**★ A — Durable cross-run dedup keyed on a stable platform ID.**
`applied_job_id_{name}.pickle` holds a list of ints parsed from `data-job-id`
attributes (`apply.py:506-513`). Checked at the top of the per-job loop
(`apply.py:518`) and appended on **every** terminal branch: fast-path success,
role mismatch skip, deep-path success, "Already applied", and every
percentage-threshold branch.

This is strictly better than repos 1 and 2, which re-apply on restart. The
whole idea costs ten lines. We adopt the concept and implement it properly in
SQLite with a `UNIQUE` constraint and a transactional upsert (§10, §25).

*Limitation:* the pickle is double-appended on the fast path
(`apply.py:566-574`) and the same ID is written twice. Pickle also means no
querying, no multi-key matching, and an arbitrary code-execution risk on load.

**★ B — Application complexity ceiling with escalating shortcuts.**
`apply.py:665-729`. After 5 failed attempts the bot reads the completion
percentage and branches: `<25%` abandon + notify; `<30%` click through to
submit; `<40%` skip the first Continue; `<60%` Review then Submit; else give
up.

**It refuses to answer long forms rather than fabricating a 20-question
application.** That is a sane quality bound and the only one in any of the
four repos. Maps onto target §21/§61: a bounded, typed escalation instead of
unbounded guessing. We adopt the *principle* (a documented maximum question
count / application length above which the bot stops and escalates) but
**replace the percentage ladder** with real application state, per audit
finding C1.

**★ C — Validator-error harvesting as prompt content.** `apply.py:281-282`. For
text inputs the bot first clears all fields and clicks *Continue* purely to
force LinkedIn to render `artdeco-inline-feedback--error`, then scrapes those
messages and concatenates each onto its question:
`question + ".Answer this question in this format: " + box_options[i]`.

It converts the platform's own complaints into a format constraint. Same family
as repo 2's idea B. We adopt both, behind one `FieldValidationError` type.

**★ D — Out-of-band human escalation carrying the actionable URL.**
`message(t)` (`apply.py:111`) prints and sends via Telegram. Used for
verification notices, per-category counts, and — critically — **the job URL
when a human should look at it** (`message(job_page)`).

Our equivalent is the review queue (§21) plus a dashboard view (§31), and the
URL must always be present in the record so a human can open the application
and finish it by hand (§61).

**E — Four-tier LLM provider failover.** `ask_gpt` (`apply.py:65-108`):
gemini → ChatGPT-web → `text-davinci-002-render-sha` (retried up to
`max_retries = 30`) → gemini. `run_with_timeout` (`apply.py:55`) uses
`ThreadPoolExecutor` + `future.result(timeout=…)` to bound a library with no
native timeout.

The *shape* is right for target §34 (pluggable providers). The *execution* is
not: the ladder mutates the global `max_retries` to `1` to break out of the
retry loop — a control-flow hack — and `max_retries = 30` around a
web-session-scraped client is an unbounded loop. We adopt provider
abstraction and timeouts; we do not adopt the mutation hack, and we cap
retries hard.

**F — Two-stage extract-then-compress prompting.** Per question family, two
LLM calls: `make_prompt` (resume + all questions, reason step by step,
markdown out) then `make_prompt2` (receive stage-1 prose, emit a bare
`{index: answer}` dict). Stage 1 reasons cheaply; stage 2 only extracts.

The parser (`apply.py:146-178`) is correspondingly defensive: fenced ```json
extraction → strip newlines → strip whitespace outside quotes → truncate to
first `{`…last `}` → normalize `True/False` → `demjson3.decode` (lenient),
with strict `json.loads` present but commented out. **Choosing a tolerant
parser when the producer is an LLM is the right call.** We adopt the
robust-parse helper.

### 4.3 Weaknesses

- **Deliberate hallucination instructions, repeated throughout** (`apply.py:191-194`,
  `207-209`, `233`, `247`): *"use creative thinking to provide an approximate
  answer"*, *"**always remember you should not say Not specified or
  provided**"*, *"estimate it creatively"*, *"highlight positive and
  advantageous characteristics"*. There is no grounding, no refusal path, and
  the prompts actively forbid the model admitting uncertainty.
  **This is the single most damaging pattern in the set** (§7.1).
- **Committed credentials**: `kodakandlasrikar99.json:11` appears to contain a
  real Telegram bot token; `username` is a real address; the `.txt` is a real
  resume.
- **Hardcoded personal URL** at `apply.py:127` containing a real
  `currentJobId`, `geoId`, and private search keywords.
- **Global-namespace config injection** with no schema and no validation.
- **`pdb.set_trace()` as a review mechanism** (`apply.py:140`) on LinkedIn
  verification — requires an attached debugger; there is no `input()`.
- Duplicate append + double `pickle.dump` on the fast path.
- **Silent failure at the worst place**: `try/except Exception: pass` around
  text, radio, and dropdown filling (`apply.py:301`, `347`, `388`) means a
  question can go unanswered **and the bot proceeds to submit**.
- Unmaintained since 2024-04-13; depends on ChatGPT web-session cookies via a
  third-party library — fragile and a ToS risk.
- No tests, no logging framework, no error taxonomy.

---

## 5. REPO 4 — `GPT-Jobhunter`

### 5.1 What it is

**The only genuinely layered, multi-tenant, tested project in the set.**

```
Streamlit (8501)
      │  HTTP/JSON + JWT Bearer
      ▼
FastAPI (8000)  ── jobhunter/backend/api.py      ~30 endpoints + global exception handler
      │
      ├── services.py (1,964 lines, 10 service classes)
      │     JobSearchService · ResumeService · JobDataService · DatabaseService
      │     AIService · JobTrackingService · ResumeOptimizerService
      │     AuthService · OnboardingService
      │
      ├── auth_service.py / AuthHandler.py    users + password_reset_tokens, bcrypt
      │
      └── extract.py ──▶ dataTransformer.py ──▶ load.py ──▶ SQLiteHandler.py
                                                     │
                                       textAnalysis.py ◀┘
                                              │
                                      text_similarity.py
```

Stack: FastAPI + Uvicorn, Streamlit, stdlib `sqlite3` + `pandas.read_sql`,
`numpy` + `sklearn.metrics.pairwise.cosine_similarity`, `openai` v1
(`text-embedding-3-small`, `gpt-4o`, `gpt-4o-mini`), RapidAPI JSearch,
`pdfplumber`, `python-docx`, `beautifulsoup4`, `python-jose` (JWT HS256),
`passlib` (bcrypt), `secrets`/`hashlib`, `Makefile`, Docker, `pytest`.

### 5.2 Patterns worth borrowing

**★ A — A validated, ownership-scoped status state machine.** `job_tracking`
table with statuses `['apply','hr_screen','round_1','round_2','rejected']`
(`services.py:696`, `services.py:730`), rendered as a Kanban board.

- `save_job` — `INSERT OR IGNORE … VALUES (?, ?, 'apply')`; idempotent via
  `UNIQUE(user_id, job_id)`
- `update_job_status` — validates membership in the allow-list **before**
  writing, then `UPDATE … WHERE job_id = ? AND user_id = ?`, and **treats
  `rowcount == 0` as "not found or not owned"**
- `remove_from_tracking` — the same ownership-scoped rowcount pattern

This is the only persisted, validated state machine in the set, and it is
almost exactly target §23 + §25. We adopt: status column, allow-list checked
before write, ownership scoping, rowcount-as-absence, `INSERT OR IGNORE` for
idempotency.

*We explicitly do NOT port two of its bugs:*
- `pass_job` writes the **shared** `jobs_new.hidden = 1`, hiding the job for
  every user (its own docstring at `services.py:618-625` admits this)
- `JobDataService.get_jobs` filters with
  `id NOT IN (SELECT job_id FROM job_tracking)` (`services.py:240`) —
  **not scoped by `user_id`**, so one user's saved jobs disappear from every
  other user's list

We are single-user, so multi-tenancy is not required — but the
*ownership-scoping discipline* is, because it forces every read and write to
name its owner, which is what makes "did I already apply to this?" answerable.

**★ B — Derived-data validation before use.** `_calculate_similarity_for_job`
(`SQLiteHandler.py:565` path) validates, in order: is it a `list`? is
`len >= 100`? is it all-zero? then `cosine_similarity`, then **clamps to
`[0.0, 1.0]`**. The batch function logs min/avg/max and raises an explicit
alarm *"All similarity scores are zero!"* when `max == 0.0`.

Embeddings fail silently. This is how you find out. Every derived number our
match engine produces gets the same treatment (§42 `error_code` taxonomy,
§59 "descriptive, not predictive").

**★ C — Disclosing whether an analysis was evidence-based.**
`ResumeOptimizerService.optimize_resume` sets
`analysis_source = "job_database"` when it used the user's own saved jobs, and
`analysis_source = "ai_general"` when it fell back to a general prompt.

**The single most honest design decision in the set.** Any analysis our system
produces must state whether it is grounded in retrieved data or in model priors.
This becomes a required field on every match report, cover letter, and generated
answer: `grounded_in: [...]` + `evidence_source: "retrieved" | "profile" | "model_prior"`.

**★ D — Per-step results with partial-failure reporting.**
`OnboardingService.process_onboarding` (`services.py:1780`) runs four steps,
records an `OnboardingStepResult` per step, degrades title suggestions to
`["Software Engineer","Data Analyst","Product Manager"]` on step-1 failure, and
sets overall success from the **critical** step (`job_search`) alone.

"Not everything has to succeed; we must know *which* thing didn't." Adopted
directly for the pipeline runner and the acceptance tests (§70).

**★ E — Search-term degradation ladder.** `extract.py:280-348`. When a query
returns nothing, progressively generalize: original
`"{position} jobs in {location}"` → strip seniority qualifiers (`senior`,
`principal`, `lead`, `staff`, `head`, `chief`, `vp`, `vice president`,
`director`) → extract the domain (`machine learning`, `data science`) → the
bare role (`engineer`, `developer`, `data`) → generic defaults.

A real recall mechanism, not a config toggle. For a fresher searching India
this matters a lot, because "Senior AI Engineer" returns nothing while
"AI Engineer" returns 1,000+. Adopted as a **discovery** concern, distinct from
blacklisting.

**★ F — Cost control, concretely.**

| Control | Value | Location |
|---|---|---|
| Embedding batch | 100 | `textAnalysis.py:28` |
| DB batch / commit interval | 100 / 50 | `SQLiteHandler.py:17-19` |
| Similarity concurrency | 8 workers | `SQLiteHandler.py:21` |
| Retry caps | `MAX_RETRIES=5`, delay 1.0→60.0 s | `textAnalysis.py:24-26` |
| Backoff **with jitter** | on `RateLimitError` *and* on `APIError` whose message contains `429`/`rate limit`/`too many requests` | `textAnalysis.py:164-202`, `276-304` |
| Cheap model for cheap work | `gpt-4o-mini`, `temperature=0.7`, `max_tokens=150` for title suggestions | `services.py:550-558` |
| Prompt truncation | 8,000 chars, logged | `textAnalysis.py:132-135` |
| **Placeholder-key rejection** | substring blacklist (`your`,`demo`,`example`,…), `< 20` chars, must start with `sk-` | `textAnalysis.py:73-100` |
| Context bounding | top-10 jobs, 500-char excerpts | `services.py:1007-1012` |
| API pagination cap | `PAGES = 3` | `config.py:104` |
| **Key masking in logs** | `f"{key[:4]}...{key[-4:]}"` | `textAnalysis.py:47,55,66`; `extract.py:191,227` |

The placeholder-key rejection is a direct model for our TEST 14
("API key missing → clear setup error, not stack-trace chaos"). The key
masking is a direct model for §38 "never log API keys".

**★ G — Test infrastructure, not just tests.** 13 pytest modules.
`TEST_DATABASE` env override threaded through *every* `SQLiteHandler` function
(`os.environ.get('TEST_DATABASE', config.DATABASE)`) for true DB isolation.
`CLAUDE.md:170` — *"`make test` runs core tests first, then full suite if API
keys are present."* A two-tier strategy: deterministic tests always, paid-API
tests gated. The only documented test strategy in the set, and the direct model
for our §44/§45.

**★ H — Resume parsing with real validation.** Two paths: plain-text body, and
`POST /resumes/upload-file` accepting only `application/pdf` and `text/plain`,
extracting per page via `pdfplumber.open(...).pages[i].extract_text()`, and
**rejecting when `not content.strip()`** (`api.py:532-608`). Genuine validation,
not a stub. Model for our §7 and TEST 15 (malformed resume → graceful error).

**★ I — Batched embedding with non-fatal degradation.** Batch 100; on failure
store `embeddings = NULL` and keep going (`SQLiteHandler.py:161`).

*Critical subtlety we improve on:* it cannot distinguish "zero similarity" from
"not scored" — `resume_similarity > 0` is used as a proxy for "scored"
throughout. We store a distinct `NOT_SCORED` sentinel so a legitimately
low-match job is never confused with an unscored one.

### 5.3 Weaknesses

- **UI coupling inside the data layer.** `SQLiteHandler.py` imports `streamlit`
  and calls `st.error` / `st.warning` / `st.empty` / `st.progress` inside
  `update_similarity_in_db`, which the FastAPI backend calls at
  `services.py:342`. The data layer cannot be used headlessly. Direct model for
  our own §4 rule: *do not mix LLM / database / browser / UI logic in one file.*
- **Weak dedup key.** `"{company} - {title}"` (`load.py:19-36`) conflates the
  same role at the same company across cities, re-postings and recruiters. No
  location, no date, no apply link. We use a multi-signal key (§10).
- **`applications` table declared and never used.** `config.py:30` defines
  `TABLE_APPLICATIONS` with no corresponding `CREATE TABLE`. Anti-pattern: dead
  config that implies a feature exists.
- **CORS `allow_origins=["*"]` with `allow_credentials=True`** (`api.py:51-52`)
  — invalid per spec and unsafe.
- **Hardcoded JWT fallback secret** `os.getenv("JWT_SECRET_KEY",
  "fallback-secret-key-change-in-production")` (`auth_service.py:28`), **and
  the secret is logged** truncated on every verification (`auth_service.py:77`).
- **Reset tokens logged in plaintext** (`services.py:1734-1735`).
- **Committed `temp/data`** — ~22,278 of the repo's 22,348 files.
- **SQL assembled by string concatenation** for the WHERE clause
  (`services.py:279-288`); values are parameterized so it is not injectable, but
  the count query is parsed back out by `find("WHERE")` and `split("ORDER BY")`.
- **Double password-hash implementations** coexist (`auth_service` and
  `AuthHandler`).
- **Broad `except:` in the migration path** (`services.py:426`, `449`) — a
  failed migration is indistinguishable from "already migrated".

---

## 6. CROSS-CUTTING SYNTHESIS

### 6.1 Capability matrix

| Capability | Repo 1 | Repo 2 | Repo 3 | Repo 4 |
|---|---|---|---|---|
| Resume parsing | unstructured dir reader | markdown/txt, no PDF | raw txt | **PDF via pdfplumber, stored, owner-scoped** |
| Job matching | LLM-routed RAG, no score | two LLM yes/no filters | substring match | **embeddings + cosine, persisted, clamped** |
| Question answering | exact→fuzzy→RAG + write-back | MultiPromptChain, 4 destinations | two-stage reason→dict | n/a (no apply flow) |
| Unknown questions | RAG fallback, then cached | `[[placeholder]]` repair loop | "use creative thinking" | n/a |
| Unknown escalation | `input()` + 20 s sleep | `input()` + `SKIP_APPLY` | **Telegram with job URL** | full Kanban + `pass_job` |
| State persistence | LlamaIndex `persist` | **none** (in-memory list) | **pickle of job IDs** | **SQLite, FKs, unique, scoped** |
| Tracking | xlsx, double-written | 4 CSVs with `skipped_stage` | counters + Telegram | **validated status Kanban** |
| Human in the loop | 2 console prompts | 2 prompts + dry-run | out-of-band Telegram | **total** |
| Tests | none | 9 live-API, unasserted | none | **13 modules, DB-isolated, two-tier** |

### 6.2 Patterns appearing in multiple projects (proven)

1. **Cheap/expensive model tiering** — all four, three valid implementations.
2. **Prose-encoded routing policy** — repos 1 and 2 put dispatch in tool
   descriptions. Cheap, but unverifiable.
3. **Read the question text off the DOM, don't assume a schema** — all three
   apply bots.
4. **Platform validation errors as a feedback signal** — repos 2 and 3.
5. **Two-stage prompting for structured output** — repo 3 explicitly, repo 2
   implicitly.
6. **Local/demo-safe configuration** — repo 2's `EnvironmentKeys`, repo 4's
   `TEST_DATABASE` + `_is_placeholder_key`.

### 6.3 The best single idea from each

| Repo | Best idea | Why it matters here |
|---|---|---|
| 1 | cascading answer resolution **with write-back caching** | turns a per-question LLM call into a per-unique-question call, permanently — target §19/§56 |
| 2 | **Levenshtein snapping** of every closed-vocabulary answer | deterministic; the model cannot produce an illegal option — target §18/§37 |
| 3 | **complexity ceiling** + escalation carrying the job URL | refuses long forms instead of fabricating them — target §21/§61 |
| 4 | **validated, ownership-scoped status machine** + `analysis_source` disclosure | the only persisted state machine; the only honest provenance flag — target §23/§60 |

---

## 7. ANTI-PATTERNS TO AVOID

### 7.1 Prompt-level fabrication — the worst offender

Repos 1 and 3 both instruct the model to never admit uncertainty and to
answer affirmatively or creatively:

- repo 1: *"always return 'Yes'"*, *"always return values greater than 1"*
- repo 3: *"use creative thinking to provide an approximate answer"*,
  *"always remember you should not say Not specified or provided"*,
  *"estimate it creatively"*

This converts a retrieval system into a **confident-lying system**, and it is
unrecoverable because nothing downstream can detect it. It is also a direct
violation of the user's target §6, §20, §37 and §55.

**Our replacement, stated as a hard rule:** an LLM may only *phrase* an answer.
It may never *originate* a fact. Every answer carries `evidence[]` and a
`confidence`, and insufficient evidence yields an explicit `UNANSWERABLE`
sentinel that the caller converts into a human-review item — never a guess.

### 7.2 Silent `except: pass` in the form-fill path

All three apply bots. A bot that cannot distinguish "question answered" from
"handler crashed" **will submit incomplete applications**. Repo 3 is the worst
case: text, radio, and dropdown handlers all swallow, and submission proceeds.

Directly forbidden by target §53. In our design, a failed fill **must** update
application state (→ `APPLICATION_PAUSED` / `NEEDS_MANUAL_ACTION`).

### 7.3 No durable dedup

Repos 1 and 2 re-apply on restart. Repo 3 shows the fix costs ten lines.

### 7.4 No error taxonomy

Every project uses exceptions, not typed outcomes. Closest to a taxonomy
anywhere: repo 4's `(success: bool, message: str)` convention and
`OnboardingStepResult` list. We adopt repo 4's shape and extend it into the
§43 error-code catalogue.

### 7.5 Secrets and PII in git

Repo 1 (`questions.json` with real phone/email, resume PDF, both index
stores), repo 3 (Telegram token, real username, real resume), repo 4 (22k job
JSONs). Note that **our own upstream repo already has this problem**:
`additionalQuestions.yaml` is tracked and contains a real person's phone
number and address. See audit §16.3.

### 7.6 Config injected into globals

Repo 3's `globals()[key] = data[key]`; repo 1's absolute paths. Both
unvalidatable. Our `config/` YAML + typed settings (§51) exists specifically to
avoid this.

### 7.7 Computation in setters and module import scope

Repo 2's `job_description` setter silently performs a paid LLM call
(`gpt.py:136-142`); repo 1 builds two vector indexes at module import
(`agentic_rag_api.py:23-29`). Both make cost and failure unpredictable and
make the module untestable.

### 7.8 Tests that call paid APIs

Repo 2's nine `unittest` cases hit live OpenAI with no mocks: unusable in CI,
non-deterministic, and they cost money on every run. Two assert nothing.

Adopted countermeasure: repo 4's two-tier strategy — deterministic tests always,
LLM tests gated behind an explicit marker and a recorded/replayed fixture mode.

### 7.9 Dead interfaces announced as features

Repo 2 declares `unprepared_questions_file_name` and never uses it. Repo 4
defines `TABLE_APPLICATIONS` and never creates the table. Both create the
impression of a capability that does not exist.

**Our rule** (target §74): if something cannot be implemented reliably, ship a
documented interface explicitly marked `PENDING` and excluded from
"Definition of Done", rather than leaving a stub that implies it works.

### 7.10 Unbounded retry

Repo 3's `max_retries = 30` around a web-session-scraped client, with the
global `max_retries` mutated to `1` as a control-flow escape hatch. We cap
retries hard and use jittered exponential backoff (repo 4's pattern).

---

## 8. WHAT WE ADOPT, AND WHAT WE CHANGE

Direct answers to the "what did we change / improve" question for each
borrowed idea.

| Borrowed from | Pattern | We adopt | We change / improve |
|---|---|---|---|
| Repo 1 | Answer cascade | 7-level cascade (target §19) | Persist the cache to `question_memory` with `verified_by`/`verified_at`; **never** write back an unverified LLM answer as verified — a write-back requires `risk_level=LOW` **and** retrieved evidence |
| Repo 1 | Two-tier routing | Cheap model for short/structured, strong model for long-form | Deterministic dispatch in code (task type + field type + risk level), not prose in a tool description; explicit token budget per task |
| Repo 1 | DOM-driven form loop | Loop until the submit button is present | Replace percentage arithmetic with an explicit persisted state machine (§23); every transition stored, resumable |
| Repo 1 | Local model for privacy/cost | Ollama provider (§34) | Per-task routing; embeddings cached to disk so repeated JD parsing costs nothing |
| Repo 2 | Levenshtein snapping | Snap LLM output to the legal option set | Record `source="option_snapping"`, never as a profile fact; if the distance exceeds a threshold, do **not** snap — escalate to review |
| Repo 2 | Form-error self-correction | Read the platform's validation error and retry | Typed `FieldValidationError` → recovery record in `application_failures`; bounded retries, then `NEEDS_MANUAL_ACTION` |
| Repo 2 | Strong-model routing, weak-model execution | Same split | Deterministic routing; cost accounting per call |
| Repo 2 | Placeholder repair loop | Pre-storage generation guard | Add a *post*-storage validation guard (repo 2 has only the pre-guard) |
| Repo 2 | Provenance logging | Full decision audit | Store in queryable SQLite (`application_answers`, `application_events`, `model_runs`) rather than a write-only CSV; redact PII before writing |
| Repo 2 | Dry-run switch | Keep `config.dryRun` | Add independent `SAFE_MODE` + `SubmitGuard`; both must agree (§52) |
| Repo 2 | Challenge-page halt | Pause and require a human | Typed `CAPTCHA_REQUIRED`; persist state; never bypass (§27) |
| Repo 3 | Durable dedup on platform ID | Multi-signal dedup key (§10) | SQLite `UNIQUE` + transactional upsert, not pickle; merge records rather than drop them |
| Repo 3 | Complexity ceiling | A documented maximum question count above which the bot stops | Replace the `<25% / <30% / <40% / <60%` ladder with real application state (§23); ceiling is a config value, not a constant |
| Repo 3 | Validator-error harvesting | Use platform complaints as constraints | Same typing and bounded-retry treatment as repo 2 |
| Repo 3 | Out-of-band escalation with URL | Review queue + dashboard | Job URL is a required field on every review item so a human can finish manually (§61) |
| Repo 3 | Provider failover | Pluggable providers (§34) | No global mutation; hard retry caps; every attempt recorded in `model_runs` |
| Repo 3 | Two-stage prompting | Reason-then-extract for structured output | Shared robust-parse helper; schema validation after parse; both stages logged with `prompt_version` (§36) |
| Repo 4 | Validated status machine | Allow-list checked before write, rowcount-as-absence, `INSERT OR IGNORE` | Fix its two ownership bugs by construction (single-user, but every read/write names its owner); expand to the 16 states of §23 |
| Repo 4 | Derived-data validation | Validate type/dimension/zero-vector before using any embedding; clamp scores | Distinct `NOT_SCORED` sentinel so "zero similarity" ≠ "unscored" |
| Repo 4 | `analysis_source` disclosure | Required `evidence_source` on every generated artifact | Mandatory on match reports, cover letters, tailored resumes, and answers |
| Repo 4 | Per-step partial-failure reporting | `StepResult` per pipeline stage | Overall success determined by declared critical steps; every non-critical failure is visible, never silent |
| Repo 4 | Search-term degradation | Discovery-side ladder (strip seniority qualifiers when a query is empty) | Distinct from blacklisting; per-keyword recall reporting so the user can see which queries were widened |
| Repo 4 | Cost controls | Batching, jittered backoff, cheap/strong split, context bounding, key masking, placeholder-key rejection | All adopted, plus a hard per-run and per-day token budget (§40) and a hard **"never ask the LLM the same question twice"** cache |
| Repo 4 | Test infrastructure | `TEST_DATABASE` isolation; two-tier `make test` | Deterministic suite always; LLM tests gated; no network in unit tests (§45) |
| Repo 4 | PDF/text resume parsing with real validation | `pdfplumber` + DOCX + TXT + MD; reject empty extractions | Hash-based duplicate ingestion; malformed input → typed error, not a crash (TEST 15) |
| Repo 4 | Batched embedding, non-fatal | Batch + `NULL` on failure | `NOT_SCORED` sentinel as above |

---

## 9. WHAT WE DELIBERATELY DO NOT COPY

| Not copied | From | Why |
|---|---|---|
| `selenium_stealth` / `undetected_chromedriver` | repo 3, and upstream itself | Target §27 prohibits evasion techniques. Upstream code is **kept** (it is the user's existing behaviour and removing it may break login) but **not extended** and **not added to**. New automation must not use it. |
| ChatGPT web-UI automation via session cookie | repo 3 | Fragile third-party dependency, ToS risk, and a browser-scraped credential. Our providers are official APIs plus local Ollama. |
| Fabrication-encouraging prompts | repo 1, repo 3 | §7.1 above. Directly violates the target's truthfulness requirement. |
| `globals()[key] = data[key]` config injection | repo 3 | Unvalidatable; typed settings instead (§51). |
| Absolute hardcoded paths | repo 1 | Target §65: Windows-first, `pathlib`. |
| `st.*` calls inside the data layer | repo 4 | Target §4: never mix UI into data/logic layers. |
| `"{company} - {title}"` dedup key | repo 4 | Conflates same role across cities and re-postings. |
| `"{}".format(key[:4], key[-4:])` log masking for *user* data | repo 4 | Adopted for API keys; **not** adopted for PII, which is excluded from logs entirely rather than masked. |
| Live-API unit tests | repo 2 | Non-deterministic, costly, unusable in CI. |
| `max_retries = 30` with global mutation | repo 3 | Unbounded loop + control-flow hack. |
| Dead config/interface stubs | repo 2, repo 4 | §7.9. Mark `PENDING` explicitly instead. |

---

## 10. SUMMARY

Four projects, four different answers to "how do I make a job bot smarter", and
**none of them is complete**:

- repos 1–3 are competent browser drivers wrapped around an LLM that is
  actively encouraged to guess
- repo 4 is a competent data platform with no browser at all

Our target architecture is the union: **repo 4's discipline** (persistence,
validation, tests, provenance disclosure, cost control) applied to
**repos 1–3's browser layer** (LinkedIn form field extraction, DOM-driven form
progression, platform-error harvesting) with **repo 1's cascade** and
**repo 2's answer snapping** underneath — and with every fabrication prompt,
every silent `except`, and every durable-state gap explicitly rejected.

The most important borrowed idea is not any single technique. It is
**repo 4's `analysis_source` disclosure**: the system must always say whether
an output came from retrieved evidence or from model priors. Everything in the
target design that generates text exists to make that distinction reliable.
