# Phase 2 Implementation

What was built in Phase 2, how it behaves, and where it stops.

- Status: **complete**
- HEAD: `72776f9` plus the recovery checkpoint
- Entry point: `job_assistant.py`
- Test suite: 365 tests, all passing
- Acceptance checklist: 17/17 steps passing

This document describes only behaviour that exists in the code today. Anything Phase 3
will add is listed in the final section and is **not** implemented.

---

## 1. Phase 2 goals

Phase 2 is a foundation. It establishes typed configuration, a candidate truth and
evidence model, resume ingestion, a SQLite persistence layer, a provider-agnostic AI
interface, and a test suite — before any browser or application logic exists.

It deliberately does not fetch jobs, open a browser, or submit anything.

---

## 2. Completed components

| Component | Location | Tests |
|---|---|---|
| Typed configuration | `src/core/settings.py` | `test_settings_and_ai.py` (39) |
| Safety policy and guards | `src/safety/` | `test_safety.py` (31) |
| Core enums, errors, hashing | `src/core/` | `test_core_enums_hashing.py` (26) |
| Evidence and truth model | `src/core/evidence.py` | `test_core_evidence.py` (21) |
| Candidate profile | `src/profile/` | `test_profile.py` (38) |
| Resume ingestion | `src/resumes/` | `test_resumes.py` (39) |
| SQLite foundation | `src/database/` | `test_database.py` (49) |
| AI provider abstraction | `src/ai/` | `test_settings_and_ai.py` |
| Jobs vocabulary | `src/jobs/` | `test_jobs.py` (47) |
| Security posture | `.gitignore`, redaction | `test_security.py` (22) |
| Legacy compatibility | `config.py`, `utils.py`, `constants.py`, `linkedin.py` | `test_legacy.py` (26) |
| Acceptance runner | `src/assistant/acceptance.py` | `test_acceptance.py` (27) |

---

## 3. Typed configuration

`src/core/settings.py` declares every setting once with a type, a default, and a
validator. Nothing in `src/` reads `os.environ` directly.

Seven categories, each its own model:

`ApplicationSettings`, `AISettings`, `DatabaseSettings`, `BrowserSettings`,
`JobSearchSettings`, `SafetySettings`, `LoggingSettings`.

They are aggregated by `AssistantSettings`, which reads:

- the `.env` file (`env_file=".env"`),
- the environment, under the `ASSISTANT_` prefix with `__` separating section from
  field — `ASSISTANT_SAFETY__DRY_RUN=false` sets `safety.dry_run`,
- flat legacy names for the three values the original bot also reads:
  `DRY_RUN`, `LINKEDIN_USERNAME` / `LINKEDIN_EMAIL`, `LINKEDIN_PASSWORD`.

Both forms are accepted so the assistant and the original bot cannot disagree about
being in dry-run mode. Where both are present, the namespaced name wins.

Credential fields are `SecretStr` and never receive a default. `AssistantSettings.secret_values()`
feeds them to the redactor at startup, and `redacted_summary()` is what `status` prints.

Validated bounds include `temperature ∈ [0, 2]`, `timeout_seconds > 0`, and
`results_per_page ∈ [1, 100]`.

`SafetySettings.assert_phase2_invariants()` runs during `build_assistant()` and raises
`ConfigurationError` before any work starts if an invariant is broken. There is no flag
to disable it.

---

## 4. Security and safety defaults

Defaults on `SafetySettings`:

| Setting | Default |
|---|---|
| `dry_run` | `True` |
| `safe_mode` | `True` |
| `require_human_approval` | `True` |
| `allow_browser_navigation` | `False` |
| `allow_form_filling` | `False` |
| `allow_file_upload` | `False` |
| `allow_final_submission` | `False` |
| `max_applications_per_run` | `5` |
| `confirm_before_each_application` | `True` |
| `block_on_captcha` | `True` |
| `block_on_mfa` | `True` |
| `record_screenshots` | `False` |

Turning on `allow_final_submission` requires `safe_mode=False`, `dry_run=False`, and
`require_human_approval=True` together — the validator refuses a configuration that
enables submission while still claiming protection.

`SafetyPolicy` exposes eight actions and refuses every privileged one by default:
`navigate`, `read_page`, `fill_form`, `click`, `upload_file`, `submit_application`,
`answer_question`, `use_verified_fact`. Approval tokens are single-use and held only in
memory.

`assert_no_fact_mutation(before, after, actor)` rejects an AI actor changing or removing
a verified fact while allowing the human owner to do the same.

Redaction (`src/core/redaction.py`) scrubs registered literals, credential shapes
(JWT, `sk-`/`ghp_`/`xoxb-` prefixes, AWS access keys), sensitive context keys, and
inline `password=...` / `token=...` assignments in message text.

---

## 5. Candidate profile

`src/profile/models.py` defines 12 sections and 44 fact fields. `build_empty_profile()`
fills every one with `UNKNOWN` — nothing is inferred, defaulted, or guessed.

Sections: `identity` (7), `contact` (4), `location` (7), `education` (1), `experience` (2),
`skills` (5), `projects`, `certifications`, `links` (list sections), `preferences` (8),
`authorization` (5), `availability` (5).

`FactStatus` has exactly three values: `VERIFIED`, `INFERRED`, `UNKNOWN`.

Rules enforced by the model:

- `UNKNOWN` can never carry a value.
- Setting a value without an explicit status becomes `INFERRED`, never `VERIFIED`.
- `VERIFIED` must name a source.
- Clearing a value drops its source, evidence, confidence, and `verified_at`.
- `version` and `updated_at` advance only when the update actually changes something.

`with_update(path, value, ...)` accepts dotted and indexed paths
(`experience.entries[0].employer`) and returns a new model; the original is never
mutated.

`src/profile/validator.py` runs 10 rule groups producing 22 validation codes as a report
— it never modifies the profile. It detects contradictions: duplicate skills,
overlapping employment, impossible date ranges, experience totals that do not add up,
malformed email, bad URL. Eight fields are required for a real application:

```
identity.full_name, contact.email, contact.phone, location.current_country,
experience.total_years_experience, education.highest_level,
authorization.requires_sponsorship, availability.available_from
```

An all-`UNKNOWN` profile is structurally valid and simply incomplete: `is_valid` reflects
schema errors, while `missing_required` lists what is still unknown.

Storage (`src/profile/service.py`):

- `primary` keeps the documented `data/profile/candidate_profile.json`.
- Any other candidate id gets its own `<candidate_id>.json` beside it.
- `load_profile()` refuses a file whose embedded `candidate_id` differs from the one
  requested, so one candidate's data can never be served for another.
- `load_profile_from_database()` is an explicit opt-in to rebuild from SQLite when no
  JSON copy exists; it is never used as a silent fallback.

`completeness()` reports the fraction of facts that are application-safe.

---

## 6. Evidence model

`Evidence` in `src/core/evidence.py` carries `source_type`, `source_id`,
`source_location`, `text_excerpt`, `confidence`, `created_at`. Excerpts over 2000
characters are truncated rather than rejected.

Six source categories (`EvidenceSourceType`): `RESUME`, `PROFILE`, `USER_INPUT`,
`JOB_DESCRIPTION`, `VERIFIED_ANSWER`, `SYSTEM`.

Four analysis sources (`AnalysisSource`) on generated artefacts: `JOB_DATA`,
`CANDIDATE_DATA`, `USER_PROVIDED`, `AI_GENERAL`.

`Fact.is_application_safe` requires all three: a value, `VERIFIED` status, and at least
one evidence record. `FactValue.is_application_safe` delegates to the same check, so the
JSON shape and the internal shape cannot disagree.

`FactValue.to_fact()` carries explicit evidence through with excerpts intact; it derives
a single record from the compact `source`/`source_id` pair only when no evidence was
supplied, so a cited value is never left with nothing to point at.

`ProfileService.update_fact(..., evidence=[...])` persists citations to `evidence` and
`fact_evidence`. Passing no evidence clears any evidence describing a value that has
just been replaced.

---

## 7. Resume ingestion

Pipeline in `src/resumes/service.py`, eight steps:

file validation → SHA-256 file hash → duplicate check → text extraction → metadata →
structured sections → copy original → store.

Supported inputs: **PDF** (pdfplumber), **DOCX** (python-docx, paragraphs and tables),
**TXT**, **MD**. All four enforce the same minimum text length, so a stub file is
rejected consistently regardless of format.

Section detection (`src/resumes/parser.py`) is a deterministic keyword pass over nine
section types — `SUMMARY`, `EDUCATION`, `EXPERIENCE`, `SKILLS`, `PROJECTS`,
`CERTIFICATIONS`, `ACHIEVEMENTS`, `LINKS`, `CONTACT`. It uses no language model and
records `uses_llm=False` in metadata. When no heading matches, no section is invented.

The original file is copied to `data/resumes/raw/` with its permissions preserved; the
source is never modified or overwritten. Hashing normalises whitespace first, so the
same content produces the same hash across line-ending differences.

Duplicate file hashes raise a typed `DuplicateResumeError`. The same content in a
different container is still detected through `content_hash`, computed over the
normalised extracted text.

---

## 8. Multi-resume storage

The `resumes` table stores one row per file, keyed by `resume_id`, with `filename`,
`file_type`, `file_hash`, `content_hash`, `candidate_id`, `raw_text`, `metadata`,
`status`, and timestamps.

Migration `002_resume_variant_metadata.sql` adds variant metadata, all additive and
idempotent:

- `role_focus` — a lowercase slug naming what the variant targets.
- `version` — a human label such as `v2`.
- `skills_json` — skills this variant emphasises.
- `content_hash` — text-level dedup across formats.

The CLI accepts `--role-focus`, `--skills`, and `--version` on `resume ingest`.
Metadata is written through `Resume.model_validate()`, so the stored object is validated
on the way in.

Resume selection — choosing which variant to send — is Phase 3 and is not implemented.

---

## 9. SQLite schema and migrations

SQLite is the structured persistence layer. Connection configuration
(`src/database/connection.py`): WAL journal, foreign keys enabled, a busy timeout, and
explicit transactions with `isolation_level=None` so `execute()` commits reliably.

Two migrations in `src/database/migrations/`, recorded in `schema_migrations` and applied
exactly once:

`001_phase2_foundation.sql` creates nine tables:

```
documents, evidence, candidate_profiles, candidate_facts, fact_evidence,
resumes, resume_sections, model_runs, fact_change_log
```

`002_resume_variant_metadata.sql` adds the resume columns listed above.

Ten tables exist in a migrated database. `fact_change_log` records every change with an
`actor_kind` of `HUMAN`, `DETERMINISTIC`, or `AI`, which is what lets the immutability
guard reason about who did what.

Repositories live in `src/database/repositories/`: a shared `BaseRepository` plus
profiles, resumes, documents (including evidence), and model runs. Each repository
translates rows into domain models; no caller writes SQL.

Not created yet, because Phase 2 does not need them:
`jobs`, `job_requirements`, `job_matches`, `applications`, `application_answers`,
`application_events`, `application_reviews`, `question_memory`.

---

## 10. AI provider interface

`src/ai/provider.py` defines the `AIProvider` abstract interface:

```
generate_text()      generate_structured()
embed()              health_check()
```

plus declarative properties `name`, `requires_api_key`, `supports_embeddings`.

`src/ai/ollama_provider.py` implements it with the standard library only — no API key,
no third-party client. All URLs, models, and timeouts come from `AISettings`; model
names are never hardcoded in business logic.

`src/ai/registry.py` maps a provider key to a factory. `build_provider()` raises
`ConfigurationError` for an unknown name; `register_provider()` refuses an empty or
duplicate name.

When Ollama is unreachable, `health_check()` returns `available=False` with an
actionable message, and `generate_text()` raises `ProviderUnavailableError`. There is no
silent fallback to another provider and no fabricated output.

`ModelRun` (`src/core/model_run.py`) records `provider`, `model`, `prompt_version`,
`task`, `input_hash`, `output_hash`, `analysis_source`, `created_at`, `latency_ms`,
`status`. Keys shaped like secrets are rejected by the model.

---

## 11. Tests

365 tests across 11 files, synthetic data only.

| File | Tests | Covers |
|---|---|---|
| `test_core_enums_hashing.py` | 26 | Enum completeness, hashing, date parsing |
| `test_core_evidence.py` | 21 | Evidence, `Fact`, `FactValue`, safety semantics |
| `test_profile.py` | 38 | Schema, `UNKNOWN`, validation, contradictions |
| `test_resumes.py` | 39 | PDF, DOCX, TXT, MD, hashing, duplicates, metadata |
| `test_database.py` | 49 | Migrations, transactions, repositories, change log |
| `test_settings_and_ai.py` | 39 | Settings, env vars, bounds, registry, provider |
| `test_safety.py` | 31 | Policy, guards, approval tokens, invariants |
| `test_security.py` | 22 | Ignore rules, redaction, no submission code |
| `test_legacy.py` | 26 | Legacy imports, symbols, settings agreement |
| `test_jobs.py` | 47 | Normalisation, identity, deduplication |
| `test_acceptance.py` | 27 | Checklist, sandboxing, per-candidate storage |

`tests/fixtures/` holds synthetic files marked `TEST DATA ONLY`: resume TXT, PDF, DOCX
(byte-reproducible via `make_binary_fixtures.py`), a job description, and a candidate
JSON with an evidence record per fact.

---

## 12. Known limitations

- **No browser.** Nothing in `src/` imports Selenium. The browser layer is untouched
  legacy code.
- **No job fetching.** `src/jobs/` defines vocabulary and rules; no module downloads or
  parses a real posting.
- **Ollama must be running for generation.** The suite verifies the unavailable path;
  it never invents model output.
- **No document classification or answer drafting.**
- **Profile files are per-candidate but co-located**, not yet versioned on disk.
- **Resume selection is not implemented.**
- **Only one profile has a JSON copy by default** — `primary`. Other candidates are
  stored in SQLite and can be exported on demand.

---

## 13. Phase 2 boundary

Implemented here: configuration, safety policy, evidence and truth, profile, resume
ingestion and storage, SQLite, AI provider interface, tests, documentation.

**Not implemented, and deliberately so:**

- job discovery, search, or scraping
- browser automation of any kind
- application form filling or submission
- CAPTCHA or MFA handling (beyond refusing to proceed)
- answer drafting or question memory
- resume selection
- embedding search or vector storage
- anti-detection, stealth, or rate-limit behaviour

Real application submission remains disabled. See `docs/ARCHITECTURE.md` for how the
boundaries are enforced.
