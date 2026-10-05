# Setup

Install and run the assistant: the Phase 2 foundation plus the Milestone 3 job
intelligence core. Everything here works locally with no browser and no network
access beyond an optional local Ollama.

---

## 1. Requirements

- **Python 3.11.8** — the version this project is developed and tested on.
  (`python --version`; any 3.11+ is expected to work but 3.11.8 is what was verified.)
- Windows, macOS, or Linux. Commands below are shown for Windows PowerShell; the
  `venv\Scripts\activate` path becomes `venv/bin/activate` on macOS/Linux.
- Optional, only if you want model generation: [Ollama](https://ollama.com).

---

## 2. Create the virtual environment

From the project root:

```powershell
python -m venv venv
.\venv\Scripts\activate
```

Every command below assumes the virtual environment is active. If you prefer not to
activate it, prefix commands with `.\venv\Scripts\python.exe`.

---

## 3. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` installs the project plus its `[dev]` extra. Dependencies are
declared in `pyproject.toml`:

| Group | Packages | Used by |
|---|---|---|
| Runtime | `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `pdfplumber`, `python-docx` | `src/api/`, `src/core/`, `src/candidate_profile/`, `src/resumes/` |
| `[dev]` | `pytest`, plus `selenium`, `webdriver_manager`, `selenium-stealth`, `pyyaml` | `tests/`; the Selenium packages are needed **only** by `test_legacy.py`, which proves the quarantined root bot still imports |
| `[embeddings]` | `fastembed` | optional — local Hugging Face sentence embeddings |

`pdfplumber` is needed only to ingest PDFs and `python-docx` only for DOCX; both are
optional at runtime — the parsers raise a clear `ResumeParseError` naming the missing
package rather than failing obscurely.

### Optional: local semantic embeddings

```bash
python -m pip install -e ".[embeddings]"
```

This adds the `huggingface` provider, which computes real sentence embeddings on CPU
via ONNX Runtime — no API key, no hosted inference, ₹0. It downloads
`sentence-transformers/all-MiniLM-L6-v2` (~90 MB) on first use and caches it. Select it
with `ASSISTANT_AI__PROVIDER=huggingface`, then match with `--scorer embedding`.

Without this extra everything still works: extraction is deterministic and
`--scorer lexical` is the default.

---

## 4. Configure `.env`

The repository ships `.env.example` with placeholders only. Your real `.env` is
git-ignored and must stay that way.

```powershell
Copy-Item .env.example .env
```

Then edit `.env`. The assistant reads the **namespaced** form, where a double underscore
separates the section from its field:

```dotenv
# safety — leave these as written
ASSISTANT_SAFETY__SAFE_MODE=true
ASSISTANT_SAFETY__DRY_RUN=true
ASSISTANT_SAFETY__REQUIRE_HUMAN_APPROVAL=true
ASSISTANT_SAFETY__ALLOW_BROWSER_NAVIGATION=false
ASSISTANT_SAFETY__ALLOW_FORM_FILLING=false
ASSISTANT_SAFETY__ALLOW_FILE_UPLOAD=false
ASSISTANT_SAFETY__ALLOW_FINAL_SUBMISSION=false

# application
ASSISTANT_APPLICATION__NAME=AI Job Assistant
ASSISTANT_APPLICATION__CANDIDATE_ID=primary

# AI provider (local Ollama needs no key)
ASSISTANT_AI__PROVIDER=ollama
ASSISTANT_AI__MODEL=qwen2.5:7b
ASSISTANT_AI__BASE_URL=http://localhost:11434

# database
ASSISTANT_DATABASE__PATH=data/assistant.db
```

Full reference: `.env.example`.

The three values the **legacy** bot reads are accepted in their historical flat form,
and the assistant accepts both spellings so the two cannot disagree:

```dotenv
DRY_RUN=true
LINKEDIN_EMAIL=
LINKEDIN_PASSWORD=
```

If both forms are present, the namespaced `ASSISTANT_*` name wins.

Credential fields have no default. `status` prints `api_key_present: False`-style
booleans and never the value itself.

---

## 5. Ollama (optional)

The provider is configured by default but **nothing in the assistant requires a model
to run**. Tests, the database, resume ingestion, job analysis and matching, and the
acceptance checklist all work without it.

To enable local generation:

```powershell
ollama serve
ollama pull qwen2.5:7b
```

Then check:

```powershell
python job_assistant.py ai health
python job_assistant.py ai models
```

If Ollama is not running you get a real, typed error (`ProviderUnavailableError`, or
`available=False` from the health check) naming the problem. The system does **not**
switch providers, retry forever, or invent a response.

---

## 6. Initialise the profile

```powershell
python job_assistant.py profile init            # empty, all-UNKNOWN
python job_assistant.py profile unknown         # what is still missing
python job_assistant.py profile show            # what is known
python job_assistant.py profile validate        # report, 22 validation codes
```

Set a single fact only when you actually have the value:

```powershell
python job_assistant.py profile set contact.email you@example.com ^
    --status VERIFIED --source USER_INPUT --source-id manual-entry --validate
```

`--source` is one of `RESUME`, `PROFILE`, `USER_INPUT`, `JOB_DESCRIPTION`,
`VERIFIED_ANSWER`, `SYSTEM`. A `VERIFIED` status without a source is refused.

Nothing is ever filled in for you. `data/profile/candidate_profile.json` starts with all
44 fields `UNKNOWN` and stays that way until you supply real values. The tracked
`candidate_profile.example.json` exists purely to document the shape.

---

## 7. Ingest resumes

```powershell
python job_assistant.py resume ingest C:\path\cv.pdf
python job_assistant.py resume ingest C:\path\cv.pdf C:\path\cv.docx ^
    --variant "AI Engineer" --role-focus ml-engineer --version v2 ^
    --skills python,sql --candidate-id primary
python job_assistant.py resume list
python job_assistant.py resume show <resume-id>
```

Supported formats: **PDF, DOCX, TXT, MD**. The original file is copied to
`data/resumes/raw/` and never modified. Re-ingesting the identical file raises
`DuplicateResumeError` unless you pass `--allow-duplicate`. Use `--synthetic` to mark
test data.

---

## 8. Jobs: ingest, analyze, match

Milestone 3 reads a job posting from a **saved page file** — no browser, no
scraping. The full local flow:

```powershell
python job_assistant.py job ingest C:\path\job_detail.html ^
    --source linkedin --url https://example.invalid/jobs/123
python job_assistant.py job list
python job_assistant.py job show <job-id>
python job_assistant.py job analyze <job-id>     # requirements (cached)
python job_assistant.py job match <job-id>       # verdict against your profile
python job_assistant.py job explain <job-id>     # why: row by row, with lineage
python job_assistant.py job queue                # waiting for a human
```

Every command takes `--json` for machine-readable output. `ingest` accepts any
saved HTML page containing either JSON-LD or an `<h1>`/title it can read;
`--source` is metadata you supply (it does not fetch anything).

What the commands prove, in order:

- `analyze` extracts requirements deterministically and caches them — the second
  run reports `(cache hit)` with identical output.
- `match` runs the hard gate first. A posting requiring 5+ years against a
  profile stating 3 ends in `HARD_MISMATCH` before any score is computed, and
  the output says **no application was started or submitted**.
- `explain` prints the stored match row by row: the posting's exact line, the
  candidate evidence, and the verdict (`matched`, `mismatch`, `not scored`).
- `queue` lists matches whose reason is one a human must resolve
  (`ELIGIBILITY_UNKNOWN`, `AMBIGUOUS_HARD_REQUIREMENT`, …) — undecided, never
  rejected.

A profile is needed only for `match` and `queue`; `ingest`, `list`, `show`, and
`analyze` work on an empty profile.

---

## 9. Database

```powershell
python job_assistant.py db init      # create or migrate
python job_assistant.py db tables    # list tables and columns
```

Migrations apply exactly once and are recorded in `schema_migrations`. The database is
created at `data/assistant.db` (git-ignored).

---

## 10. Run the tests

```powershell
python -m pytest -q                            # full suite: 1196 tests
python -m pytest -q tests\test_database.py     # persistence
python -m pytest -q tests\test_resumes.py      # parsers, hashing, duplicates
python -m pytest -q tests\test_security.py     # ignore rules, redaction
python -m pytest -q tests\test_legacy.py       # legacy imports
python -m pytest -q tests\test_settings_and_ai.py
python -m pytest -q tests\test_ai_providers.py     # provider contract, no model needed
# Real model inference is opt-in: it downloads ~90 MB on first run.
$env:JOB_ASSISTANT_HF_TESTS='1'; python -m pytest -q tests\test_ai_huggingface_real.py
python -m pytest -q tests\test_job_*.py        # Milestone 3: extraction,
                                               # requirements, gate, matching,
                                               # explain, review, service, CLI
```

Regenerate the binary fixtures if needed (deterministic, byte-identical):

```powershell
python tests\fixtures\make_binary_fixtures.py
```

Run the 24-step acceptance checklist:

```powershell
python job_assistant.py acceptance
python job_assistant.py acceptance --json      # machine-readable
```

Steps 1–17 cover the Phase 2 foundation; steps 18–24 cover Milestone 3 — ingest
a saved page, analyze (cache miss then hit), candidate evidence, the hard-gate
match, the explanation, the cache plus review queue, and a final safety sweep.
The checklist runs entirely inside a temporary sandbox: database, profile,
resumes, and logs are all redirected to a temp directory, so it cannot write to
your real data.

---

## 11. Safe defaults

These are active from the moment settings load:

| Setting | Value |
|---|---|
| `dry_run` | `True` |
| `safe_mode` | `True` |
| `require_human_approval` | `True` |
| `allow_browser_navigation` | `False` |
| `allow_form_filling` | `False` |
| `allow_file_upload` | `False` |
| `allow_final_submission` | `False` |
| `block_on_captcha` | `True` |
| `block_on_mfa` | `True` |

`build_assistant()` asserts these invariants and raises before starting if they are
broken. There is no flag to turn the assertions off.

Confirm at any time:

```powershell
python job_assistant.py status
python job_assistant.py safety
```

---

## 12. What is NOT enabled

No configuration below exists, and none can be turned on:

- browser automation or navigation from the assistant
- application form filling or final submission
- CAPTCHA solving or MFA handling (the action stops instead)
- job discovery, search, or live scraping (Milestone 3 reads saved page
  files from disk; it never fetches a URL)
- stealth, anti-detection, or rate-limit evasion
- answer drafting, question memory, resume selection
- embedding models — matching uses a lexical scorer with a pluggable
  `SemanticScorer` interface; no network is involved

Real application submission remains disabled. The legacy `linkedin.py` bot is untouched
and is not invoked by any command above.

---

## 13. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: assistant` | running from the project root without `job_assistant.py` | use `python job_assistant.py ...` |
| `ProfileNotFoundError` | no profile created yet | `python job_assistant.py profile init` |
| `ResumeParseError: pdfplumber is not installed` | optional PDF dependency missing | `pip install pdfplumber` |
| `ProviderUnavailableError` | Ollama not running | `ollama serve`, or ignore if you are not using models |
| Settings ignored | wrong variable name | use `ASSISTANT_<SECTION>__<FIELD>` |
