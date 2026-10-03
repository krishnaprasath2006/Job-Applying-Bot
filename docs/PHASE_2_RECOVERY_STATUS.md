# Phase 2 Recovery Status

Assessment of the interrupted Phase 2 run and the work completed since.

- Project: `D:\Downloads\job_bot\EasyApplyJobsBot`
- Branch: `main`
- HEAD at this assessment: `72776f9` (Phase 2 foundation commit)
- Assessment date: 2026-09-30
- Method: working-tree inspection plus executed verification. Every number in this
  document was observed by running a command; nothing here is estimated.

---

## 1. Recovery verdict

**Phase 2 is complete.** All ten pillars named in the Phase 2 brief exist, are exercised
by tests, and pass. The interrupted run had already written the domain foundation and
committed it as `72776f9`; the assessment after that interruption found the foundation
sound but the test suite, the profile JSON files, the documentation, and the dependency
manifest incomplete.

The earlier assessment in this file (written for HEAD `3ec23e4`) described several items
as "not started" that had in fact been finished before `72776f9`. Those stale statements
have been removed rather than amended in place.

### Verified now

| Check | Result |
|---|---|
| Import sweep of `src/` | 48/48 modules import |
| `import config`, `import utils`, `import constants` | Pass |
| `import linkedin` | Pass, browser not launched |
| Full test suite | 365 passed, 0 failed |
| Acceptance CLI (17 numbered steps) | 17/17 PASS |
| `SafetySettings.assert_phase2_invariants()` | Pass on defaults |
| Credential-shaped strings in the tracked diff | None |

---

## 2. Completed work

### Safety and configuration

| Item | File | State |
|---|---|---|
| Seven-category typed settings | `src/core/settings.py` | Done |
| `ASSISTANT_` environment namespace with `__` section delimiter | `src/core/settings.py` | Done, tested |
| Legacy `DRY_RUN` / `LINKEDIN_*` aliases resolved alongside the namespace | `src/core/settings.py` | Done, tested |
| Phase 2 safety invariants asserted at startup | `src/core/settings.py` | Done |
| Action policy table, 8 actions, privileged ones blocked by default | `src/safety/policies.py` | Done |
| Single-use in-memory human approval tokens | `src/safety/policies.py` | Done |
| AI-cannot-mutate-a-verified-fact guard | `src/safety/guards.py` | Done |
| Legacy `config.py` read-only bridge | `src/core/legacy.py` | Done |

### Core primitives

| Item | File | State |
|---|---|---|
| Closed enums (status, source, analysis source, risk, 24 validation codes) | `src/core/enums.py` | Done |
| 20 domain exceptions | `src/core/errors.py` | Done |
| `Evidence`, `Fact`, `FactValue` with consistent safety semantics | `src/core/evidence.py` | Done |
| SHA-256 hashing, ISO date parsing, UTC clock | `src/core/hashing.py` | Done |
| Path resolution | `src/core/paths.py` | Done |
| Shared actor classification (human / AI / deterministic) | `src/core/actors.py` | Done |
| `ModelRun` metadata rejecting secret-shaped keys | `src/core/model_run.py` | Done |
| Secret redaction: literals, credential shapes, inline `password=` assignments | `src/core/redaction.py` | Done |
| Structured JSON/text logging with a redacting filter | `src/core/logging_config.py` | Done |

### Database

| Item | File | State |
|---|---|---|
| SQLite wrapper: WAL, foreign keys, busy timeout, explicit transactions | `src/database/connection.py` | Done |
| Migration `001_phase2_foundation.sql` — 10 tables with CHECK constraints | `src/database/migrations/` | Done, idempotent |
| Migration `002_resume_variant_metadata.sql` — additive resume columns | `src/database/migrations/` | Done, additive |
| Base repository plus profiles, resumes, documents, evidence, model-runs | `src/database/repositories/` | Done |
| Fact change log with `actor_kind` (HUMAN / DETERMINISTIC / AI) | migration 001 + `profiles.py` | Done |

Tables present: `schema_migrations`, `candidate_profiles`, `candidate_facts`,
`fact_change_log`, `fact_evidence`, `evidence`, `documents`, `resumes`,
`resume_sections`, `model_runs`.

### Candidate profile

| Item | File | State |
|---|---|---|
| 12 sections, 44 fields, all `UNKNOWN` by default | `src/profile/models.py` | Done |
| `UNKNOWN` can never carry a value | `src/core/evidence.py` | Done |
| Value without an explicit status becomes `INFERRED`, never `VERIFIED` | `src/profile/models.py` | Done |
| `with_update` for dotted and indexed paths (`entries[0].employer`) | `src/profile/models.py` | Done |
| Clearing a value drops stale source, evidence and verification metadata | `src/profile/models.py` | Done |
| `version` and `updated_at` bump only on a real change | `src/profile/models.py` | Done |
| Validator: 10 rule groups, 24 codes, report-only | `src/profile/validator.py` | Done |
| Required-for-application list (8 fields) | `src/profile/validator.py` | Done |
| Service: create / load / update / validate / get-fact / rebuild-from-db | `src/profile/service.py` | Done |
| Per-candidate JSON storage (`primary` keeps `candidate_profile.json`) | `src/profile/service.py` | Done, tested |
| `completeness()` counts application-safe facts | `src/profile/models.py` | Done |

Files: `data/profile/candidate_profile.json` (all `UNKNOWN`, `candidate_id=primary`,
git-ignored), `data/profile/candidate_profile.example.json` (two synthetic verified
fields, tracked), `data/profile/README.md`.

### Evidence model

| Item | File | State |
|---|---|---|
| `Evidence`: source_type, source_id, source_location, text_excerpt, confidence, created_at | `src/core/evidence.py` | Done |
| Six source categories as a closed enum | `src/core/enums.py` | Done |
| `VERIFIED` requires a named source | `src/core/evidence.py` | Done |
| `Fact.is_application_safe` requires `VERIFIED` **and** evidence | `src/core/evidence.py` | Done |
| `FactValue.is_application_safe` delegates to `Fact`, so the two agree | `src/core/evidence.py` | Done |
| `to_fact()` carries explicit evidence through; derives a stub only when the compact form is used | `src/core/evidence.py` | Done |
| Excerpts longer than 2000 characters are truncated, not rejected | `src/core/evidence.py` | Done |
| `update_fact(..., evidence=[...])` persists citations | `src/profile/service.py` | Done |

### Resume ingestion

| Item | File | State |
|---|---|---|
| SHA-256 identity, suffix allowlist, size limit, empty check | `src/resumes/hashing.py` | Done |
| `Resume`, `ResumeSection` models | `src/resumes/models.py` | Done |
| `role_focus` (slug), `version`, `skills` metadata | `src/resumes/models.py`, migration 002 | Done |
| PDF (pdfplumber), DOCX (python-docx, tables), TXT, MD extractors | `src/resumes/parser.py` | Done |
| TXT and MD enforce the same minimum text length as PDF and DOCX | `src/resumes/parser.py` | Done |
| Deterministic keyword section parser, no LLM | `src/resumes/parser.py` | Done |
| 8-step service: validate, hash, dedup, extract, preserve, metadata, sections, store | `src/resumes/service.py` | Done |
| Original file copied read-only, never modified or overwritten | `src/resumes/service.py` | Done |
| Metadata changes go through `model_validate()`, not `model_copy()` | `src/resumes/service.py` | Done |
| Duplicate file hash raises a typed `DuplicateResumeError` | `src/database/repositories/resumes.py` | Done |

### Jobs and AI

| Item | File | State |
|---|---|---|
| `Job`, `Requirement` with `analysis_source`; ungrounded requirements barred from scoring | `src/jobs/models.py` | Done |
| Normalizer with a reviewable alias table | `src/jobs/normalizer.py` | Done |
| Slugify produces identifier-safe output; title level ranges are stripped | `src/jobs/normalizer.py` | Done |
| Deduplicator keyed on company + posting id | `src/jobs/deduplicator.py` | Done |
| `JobIdentity.content_key()` hashes identity **and** description | `src/jobs/deduplicator.py` | Done |
| `AIProvider` ABC: `generate_text`, `generate_structured`, `embed`, `health_check` | `src/ai/provider.py` | Done |
| `OllamaProvider`, standard library only, no API key, no fallback | `src/ai/ollama_provider.py` | Done |
| Provider registry: unknown names refused, duplicates refused | `src/ai/registry.py` | Done |
| Audit events and logger | `src/audit/` | Done |

### Assembly

| Item | File | State |
|---|---|---|
| `Assistant` container wiring settings, paths, database, policy, services | `src/assistant/app.py` | Done |
| `database_path` override applied before services are built | `src/assistant/app.py` | Done, tested |
| CLI: `status`, `safety`, `profile *`, `resume *`, `db *`, `ai *`, `acceptance` | `src/assistant/cli.py` | Done |
| 17-step acceptance runner, sandboxed to a temporary directory | `src/assistant/acceptance.py` | Done, 17/17 |
| Non-shadowing entry point `job_assistant.py` | `job_assistant.py` | Done |

---

## 3. Bugs found and fixed during recovery

All are resolved; none are outstanding.

| # | Bug | Fix |
|---|---|---|
| 1 | `AssistantSettings` documented an `ASSISTANT_` namespace but configured no prefix and no nested delimiter, so `ASSISTANT_SAFETY__DRY_RUN` did nothing | Added `env_prefix` and `env_nested_delimiter="__"` |
| 2 | `config.py` reads `LINKEDIN_EMAIL`; the assistant only aliased `LINKEDIN_USERNAME`, so a shared credential could never resolve | Added `LINKEDIN_EMAIL` to the alias choices |
| 3 | Free-form log messages were not scrubbed, so `password=...` in prose reached the output | Added inline sensitive-assignment redaction to `SecretRedactor.scrub()` |
| 4 | `slugify()` kept `/`, `&`, `+`, `#`, producing identifiers that cannot be matched back | Separate slug character class plus dash collapsing |
| 5 | The title noise regex ended `)` with `\b`, so the level-range alternative was dead | Split the alternation; added `L4-L5` support |
| 6 | `JobIdentity.content_key()` hashed `normalize_text('')` — always an empty string — so it could never detect a description change | Takes the description as an argument and hashes it |
| 7 | **The acceptance run swapped `Assistant.db` after the services were built**, so synthetic facts were written to the real `data/assistant.db` and the real profile JSON | `build_assistant(database_path=...)` applies the override before construction; the run redirects every writable path into a temp sandbox |
| 8 | All candidates shared one JSON path, so a run for a synthetic candidate could read or overwrite the real candidate's file | `ProfileService.path_for(candidate_id)` with a guard that refuses a file naming a different candidate |
| 9 | `get_fact()` and `validate_profile()` required the JSON file even when the database had the answer | `get_fact()` reads the id from the row; added `load_profile_from_database()` as an explicit opt-in |
| 10 | `FactValue.to_fact()` discarded the evidence list it was given and rebuilt a stub from the source fields, losing every excerpt | Explicit evidence is carried through; a stub is derived only when no evidence was supplied |
| 11 | `FactValue.is_application_safe` disagreed with `Fact.is_application_safe` | Delegates to the `Fact` form |
| 12 | `ProfileService.update_fact()` had no `evidence` parameter, so no caller could persist a citation | Added `evidence=`, and an empty list clears stale evidence |
| 13 | `company_blacklist` accepted whitespace entries that never match anything | Entries are trimmed and blank entries refused |
| 14 | Level range `(L4-L5)` never matched in title normalization | Fixed as item 5 |

### Except-site review

Every `except` in `src/` now raises a typed exception, logs, or carries a documented
reason. Four remain as control flow, each with a comment:

| Location | Pattern | Why it is correct |
|---|---|---|
| `src/core/hashing.py:124,128` | `except ValueError: pass` | Multi-format date parsing; falls through to the next format |
| `src/core/hashing.py:158` | `except ValueError: return None` | An unparsable value is not a parse failure, it is "no date" |
| `src/profile/models.py:621` | `except (AttributeError, IndexError, KeyError, TypeError): return None` | A path that does not resolve is a non-change, documented on the method |

---

## 4. Work completed since the interrupted run

- Lazy package exports removed the circular import: **48/48 modules now import**.
- `tests/conftest.py` inserts `src` ahead of the repository root, so the `assistant`
  name resolves to `src/assistant` and never to the legacy root script.
- All synthetic fixtures exist: resume TXT, PDF and DOCX (byte-reproducible generator),
  job description, candidate JSON with evidence records, `tests/fixtures/README.md`.
- The DOCX generator pins ZIP entry timestamps so regeneration is byte-identical.
- `tests/fixtures/synthetic_candidate.json` now carries an evidence record per fact.
- `.env.example` rewritten with the full `ASSISTANT_` namespace and placeholders only.
- `requirements.txt` lists the Phase 2 dependencies.

---

## 5. Remaining work

Nothing inside the Phase 2 boundary is outstanding except the documentation and the
commit, both of which are part of this recovery:

| Item | State at this assessment |
|---|---|
| `docs/PHASE_2_IMPLEMENTATION.md` | To be written in this recovery |
| `docs/ARCHITECTURE.md` | To be written in this recovery |
| `docs/SETUP.md` | To be written in this recovery |
| Checkpoint commit | To be created in this recovery |

Deliberately untouched, as the brief requires:

```
config.py  utils.py  constants.py  linkedin.py  additionalQuestions.yaml
Dockerfile  docker-compose.yml
```

No browser behaviour, submit flow, stealth, CAPTCHA handling, MFA handling, or
rate-limit logic was modified.

---

## 6. Safety position

| Invariant | State |
|---|---|
| `dry_run` | `True` |
| `safe_mode` | `True` |
| `require_human_approval` | `True` |
| `allow_final_submission` | `False` |
| `assert_phase2_invariants()` | Pass on defaults |
| Browser automation | Unmodified |
| CAPTCHA / MFA bypass | None |
| Anti-detection | None |
| Rate-limit evasion | None |
| Fabricated candidate data | None; the real profile is entirely `UNKNOWN` |
| Synthetic acceptance data overwriting real data | Prevented and regression-tested |
