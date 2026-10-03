# R1-B RECOVERY / COMPLETION STATUS

## 1. Previous State (R1-A Checkpoint)
- **HEAD**: `89b5aa6` - `feat(r1-a): restore canonical Python core, quarantine duplicate TS engines`
- **Working tree**: Clean after R1-A commit
- **Test baseline**: 1108 tests passed (0:02:03)
- **Acceptance**: 24/24 steps passed
- **Safety**: `dry_run=True`, `safe_mode=True`, `require_human_approval=True`, `allow_final_submission=False`

## 2. Current State (After R1-B Continuation)
- **HEAD**: Still `89b5aa6` (no new commits yet)
- **Working tree changes**:
  - Modified: `src/core/settings.py` (added `ApiSettings` class)
  - New: `src/api/` (complete FastAPI boundary implementation)
  - New: `tests/test_api.py` (45 API-specific tests)
- **Test results**: 1153 total tests passed (1108 core + 45 API)
- **Acceptance**: 24/24 steps still pass
- **Safety invariants**: Unchanged and enforced

## 3. R1-B Checkpoint Status

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 1 | Service boundary audit | **COMPLETE** | All services, repositories, and schemas audited |
| 2 | FastAPI application | **COMPLETE** | `src/api/app.py` with lifespan, CORS, error handling |
| 3 | API schemas | **COMPLETE** | `src/api/schemas/` - typed request/response models |
| 4 | Dependency wiring | **COMPLETE** | `src/api/dependencies.py` - Assistant injection |
| 5 | SQLite integration | **COMPLETE** | Uses canonical `Database` + migrations via lifespan |
| 6 | Candidate Truth API | **COMPLETE** | `GET/POST /api/profile`, facts, validation, completeness |
| 7 | Resume API | **COMPLETE** | `GET/POST /api/resumes`, ingest, duplicates, sections |
| 8 | Job API | **COMPLETE** | `GET/POST /api/jobs`, ingest, analysis, match, reports, reviews |
| 9 | AI API | **COMPLETE** | `GET /api/ai/status` (truthful), embedding scorer gated |
| 10 | Error handling | **COMPLETE** | Centralized envelope, typed error mapping, no stack traces |
| 11 | Security | **COMPLETE** | CORS explicit, loopback default, no secret leakage, validation |
| 12 | Safety enforcement | **COMPLETE** | `/apply` returns `SUBMISSION_DISABLED`, no safety mutation routes |
| 13 | CLI compatibility | **COMPLETE** | All 1108 core tests + 24 acceptance steps pass |
| 14 | Testing | **COMPLETE** | 45 API tests + 1108 core tests = 1153 total |
| 15 | Documentation | **PENDING** | `docs/R1B_IMPLEMENTATION.md` to be created |

## 4. Work Completed During Continuation

### Core Fixes
1. **Added `ApiSettings` to typed configuration** (`src/core/settings.py`)
   - Loopback default (`127.0.0.1:8000`)
   - Explicit CORS origins (`localhost:5173`, `127.0.0.1:5173`)
   - Credentials off by default, docs toggleable
   - CSV/JSON parsing for list env vars
   - Included in `AssistantSettings` and `redacted_summary()`

2. **FastAPI Application Factory** (`src/api/app.py`)
   - Lifespan builds `Assistant` once, validates safety invariants at startup
   - Installs CORS from `ApiSettings`, centralized exception handlers
   - Module-level `app = create_app()` for `uvicorn api.app:app`
   - OpenAPI documents error envelope on all routes

3. **Dependency Injection** (`src/api/dependencies.py`)
   - `get_assistant` from `app.state.assistant`
   - `get_candidate_id` from server-side settings only

4. **Error Handling** (`src/api/errors.py`)
   - Stable envelope: `{"error": {"code", "message", "details"}}`
   - Typed mapping: `SubmissionBlockedError→403 SUBMISSION_DISABLED`, `ProfileNotFoundError→404`, etc.
   - Validation errors filtered (no `input` echo)
   - Starlette `HTTPException` caught for 404/405
   - Generic `Exception→500 INTERNAL_ERROR` with logging only

5. **Profile Routes** (`src/api/routes/profile.py`)
   - `GET /api/profile` → empty template if absent (not 404)
   - `POST /api/profile` → auto-creates profile, sets fact with `INFERRED` default
   - `GET /api/profile/facts/{path}` → 404 if missing
   - `GET /api/profile/validation` → validator report (template if absent)
   - `GET /api/profile/completeness` → fraction
   - `GET /api/profile/unknown` → list of unknown fields
   - Catches `AttributeError` for invalid paths → `422 PROFILE_INVALID`

6. **Resume Routes** (`src/api/routes/resumes.py`)
   - `GET /api/resumes` → list with count
   - `POST /api/resumes` → ingest (path, variant, role_focus, skills, version, allow_duplicate)
   - `GET /api/resumes/duplicates?file_hash=` → check by content hash
   - `GET /api/resumes/duplicates/stored` → integrity check
   - `GET /api/resumes/{id}` → 404 if missing
   - `GET /api/resumes/{id}/sections` → indexed sections
   - `GET /api/resumes/{id}/variants` → variant names
   - `DELETE /api/resumes/{id}` → 204 or 404

7. **Job Routes** (`src/api/routes/jobs.py`)
   - `GET /api/jobs` → filter by status, source, candidate, pagination
   - `POST /api/jobs` → ingest from HTML (local only)
   - `GET /api/jobs/reviews` → queue with counts
   - `GET /api/jobs/{id}` → 404 if missing
   - `POST /api/jobs/{id}/analysis` → deterministic analysis
   - `POST /api/jobs/{id}/match` → with optional scorer (`none|lexical|embedding`)
   - `GET /api/jobs/{id}/report` → 11-dimension report
   - `GET /api/jobs/{id}/relevance` → resume recommendation
   - `GET /api/jobs/{id}/explanation` → audit record (404 if no match)
   - `GET /api/jobs/{id}/review` → status
   - `POST /api/jobs/{id}/review/resolve` → idempotent
   - `POST /api/jobs/{id}/apply` → **always 403 SUBMISSION_DISABLED**, reads job status
   - `DELETE /api/jobs/{id}` → 405 (not supported)

8. **AI Status** (`src/api/routes/status.py`)
   - `GET /health` → liveness only (no deps)
   - `GET /ready` → sqlite.readable, schema.migrated, safety.invariants
   - `GET /status` → full report including AI config (no network probes)

9. **Schemas** (`src/api/schemas/`)
   - Common: `HealthReport`, `ReadyReport`, `ErrorEnvelope`, `CountSummary`
   - Status: `ApiStatusReport`, `SafetyReport`, `DatabaseReport`, `AiStatusReport`
   - Profile: `FactUpdate`, `FactResponse`, `ProfileResponse`, `ProfileValidationResponse`, `ProfileCompletenessResponse`, `UnknownFieldsResponse`
   - Resumes: `ResumeIngestRequest`, `ResumeResponse`, `ResumeListResponse`, `ResumeSectionsResponse`, `ResumeVariantsResponse`, `DuplicateCheckResponse`
   - Jobs: `JobIngestRequest`, `MatchRequest`, `JobListResponse`, `JobResponse`, `AnalysisResponse`, `MatchResponse`, `ReportResponse`, `RelevanceResponse`, `ExplanationResponse`, `ReviewQueueResponse`, `SubmitApplicationResponse`

10. **Tests** (`tests/test_api.py` - 45 tests)
    - Application assembly (OpenAPI, prefix, error envelope)
    - Health/readiness/status (dependency checks, redaction)
    - Error envelope (404, 422, secret redaction, malformed params)
    - Safety boundary (submission refused, no state change, no safety writes, 405 delete)
    - Profile (read empty, write/read fact, 404 unknown, validation, completeness, unknown)
    - Resumes (list, ingest, duplicate 409/allow_duplicate, synthetic rejected, 404, duplicate check)
    - Jobs (list, ingest, analysis, match with lexical, unknown scorer 422, embedding gated, review queue, explanation 404, status filter)
    - Adapter discipline (no sqlite3.connect, no Database(), no build_assistant, no selenium/automation, loopback default, CORS local-only)

## 5. FastAPI Architecture

```
React (port 5173)
    ↓ HTTP (CORS: localhost:5173)
FastAPI (localhost:8000)
    ↓ Dependency Injection
Assistant (singleton per process)
    ↓ Services
ProfileService / ResumeService / JobService
    ↓ Repositories
ProfileRepository / ResumeRepository / JobRepository / ReviewRepository / ModelRunRepository / DocumentRepository / EvidenceRepository
    ↓ SQLite (WAL, FK, migrations)
```

**Key Principles Enforced**:
- FastAPI is ONLY transport - zero domain logic in routes
- All decisions delegated to canonical services
- Safety invariants enforced at service layer, not API layer
- No browser automation imported in API module
- SQLite connection lifecycle managed by lifespan
- Single `Assistant` instance shared across all requests

## 6. Service Boundary

| Service | Exposed via API | Notes |
|---------|----------------|-------|
| `ProfileService.load_profile` | `GET /api/profile` | Auto-creates empty template |
| `ProfileService.update_fact` | `POST /api/profile` | Auto-creates profile, `INFERRED` default |
| `ProfileService.get_fact_with_evidence` | `GET /api/profile/facts/{path}` | |
| `ProfileService.validate_profile` | `GET /api/profile/validation` | Returns template report if absent |
| `ProfileService.completeness` | `GET /api/profile/completeness` | |
| `ProfileService.list_unknown_fields` | `GET /api/profile/unknown` | |
| `ResumeService.list_resumes` | `GET /api/resumes` | |
| `ResumeService.ingest` | `POST /api/resumes` | Server-side path only |
| `ResumeService.check_duplicate` | `GET /api/resumes/duplicates` | By content hash |
| `ResumeService.find_duplicates` | `GET /api/resumes/duplicates/stored` | |
| `ResumeService.get_resume` | `GET /api/resumes/{id}` | |
| `ResumeService.section_index` | `GET /api/resumes/{id}/sections` | |
| `ResumeService.list_variants` | `GET /api/resumes/{id}/variants` | |
| `ResumeService.delete_resume` | `DELETE /api/resumes/{id}` | |
| `JobService.list_jobs` | `GET /api/jobs` | Filters, pagination |
| `JobService.ingest_page` | `POST /api/jobs` | Local HTML only |
| `JobService.analyze` | `POST /api/jobs/{id}/analysis` | Deterministic only |
| `JobService.match` | `POST /api/jobs/{id}/match` | Optional scorer |
| `JobService.report` | `GET /api/jobs/{id}/report` | |
| `JobService.relevance` | `GET /api/jobs/{id}/relevance` | |
| `JobService.explain` | `GET /api/jobs/{id}/explanation` | |
| `JobService.review_queue` | `GET /api/jobs/reviews` | |
| `JobService.review_status` | `GET /api/jobs/{id}/review` | |
| `JobService.resolve_review` | `POST /api/jobs/{id}/review/resolve` | |
| `SafetyPolicy.check` | `POST /api/jobs/{id}/apply` | Always refuses |

## 7. SQLite Integration

- **Lifecycle**: `build_assistant` → `Database.connect()` → `initialize()` (migrations) → lifespan `yield` → `Assistant.close()` → `Database.close()`
- **Migrations**: Canonical `001`–`005` applied via `Database.initialize()`
- **Connection**: Single `Database` instance per `Assistant`, WAL + FK enabled
- **Repositories**: All canonical repositories used (`ProfileRepository`, `JobRepository`, etc.)
- **Persistence**: Data survives process restart (file-based SQLite)

## 8. Configuration

- **Source**: `AssistantSettings` from `.env` + env vars (`ASSISTANT_` prefix, `__` delimiter)
- **ApiSettings**: `host`, `port`, `cors_origins`, `cors_allow_credentials`, `cors_allow_methods`, `cors_allow_headers`, `docs_enabled`
- **Defaults**: Loopback, local frontend origins, credentials off, docs on
- **Redaction**: `redacted_summary()` includes API config (no secrets)
- **Env parsing**: CSV or JSON for list fields

## 9. Candidate Truth

- **Read**: `GET /api/profile` → empty template if absent (not error)
- **Write**: `POST /api/profile` → auto-creates profile, fact status defaults to `INFERRED`
- **Evidence**: Optional `evidence[]` in request; `VERIFIED` requires source
- **Validation**: `GET /api/profile/validation` → reports `UNKNOWN_VALUE_FOR_REQUIRED_FIELD` as ERROR
- **Completeness**: Fraction of required fields answered
- **Unknown fields**: List with `required_for_application` flag
- **Immutable facts**: AI cannot set `VERIFIED`; human can with evidence
- **No hardcoded PII**: All fixtures synthetic

## 10. Resume API

- **Ingest**: Server-side path only (no multipart upload)
- **Duplicate detection**: By SHA-256 content hash (`check_duplicate` takes hash, not path)
- **Synthetic flag**: Not client-settable (422 if attempted)
- **Sections**: Indexed by type, available via `/resumes/{id}/sections`
- **Variants**: Named variants per candidate via `/resumes/{id}/variants`
- **Deletion**: `DELETE /api/resumes/{id}` → 204 or 404

## 11. Job API

- **Ingest**: Local HTML only (no browser fetch)
- **Analysis**: Deterministic extractor only (AI path not exposed)
- **Match**: Optional scorer (`lexical` default, `embedding` gated)
- **Reports**: 11-dimension `MatchReport`, `MatchExplanation` audit
- **Relevance**: `ResumeRelevance` from stored resumes only
- **Reviews**: Queue with `OPEN`/`RESOLVED`/`DISMISSED` states
- **Apply**: **Always 403** `SUBMISSION_DISABLED` with reason + job status
- **Deletion**: **Not supported** (405) - cascades to matches/reviews

## 12. AI API

- **Status**: `GET /api/status` → `ai` section with:
  - `configured`, `provider`, `model`, `api_key_present`
  - `providers_available` (from registry)
  - `embedding_scorer_available` (provider capability, not network probe)
  - `source_mode`, `allows_application`
- **Embedding scorer**: Only invoked when semantic similarity actually needed (non-gated requirements). Returns 500/503 if provider unavailable *and* actually needed. No silent downgrade to lexical.

## 13. Hugging Face

- **Status**: Export-only files (`src/ai/huggingface.py`, `question_intent.py`, `cache.py`) present but **not integrated**
- **Canonical provider**: `OllamaProvider` only (via registry)
- **No HF semantic embeddings**: `fastembed` not available; lexical fallback only
- **No fake vectors**: Deterministic hashes never represented as semantic

## 14. Ollama

- **Behind abstraction**: `AIProvider` registry → `OllamaProvider`
- **Not mandatory**: Deterministic matching works without Ollama
- **Health**: Reported in `/status` as `configured=true, embedding_scorer_available=false` when unreachable
- **No direct exposure**: React never talks to Ollama directly

## 15. Safety

- **Invariants enforced at startup**: `assert_phase2_invariants()` in lifespan
- **No safety mutation routes**: No PUT/PATCH/POST on `/api/safety/*`
- **Submission disabled**: `POST /api/jobs/{id}/apply` → 403 with reason
- **No state change on refusal**: Verified via `/api/status` database counts
- **Client cannot mutate**: `dry_run`, `safe_mode`, `require_human_approval`, `allow_final_submission` are server-only
- **No CAPTCHA/MFA/stealth**: Not implemented, not exposed
- **Dry-run default**: All matching/analysis runs in dry-run mode

## 16. Security

- **CORS**: Explicit origins (`localhost:5173`, `127.0.0.1:5173`), credentials off
- **Bind**: Loopback default (`127.0.0.1`), not `0.0.0.0`
- **Validation**: Pydantic `extra="forbid"` on all schemas
- **No secret leakage**: Error envelope redacts, validation errors drop `input`
- **No stack traces**: Generic 500 message, details logged only
- **No hardcoded PII**: Fixtures synthetic, acceptance uses `acceptance.json` sandbox
- **No unsafe FS access**: Server-side paths only, no upload endpoint

## 17. Error Handling

- **Envelope**: `{"error": {"code": "...", "message": "...", "details": {...}}}`
- **Codes**: `NOT_FOUND`, `VALIDATION_FAILED`, `SUBMISSION_DISABLED`, `BOUNDARY_VIOLATION`, `IMMUTABLE_FACT`, `SAFETY_VIOLATION`, `INVALID_STATE_TRANSITION`, `DUPLICATE_RESUME`, `PROFILE_NOT_FOUND`, `JOB_NOT_FOUND`, `RESUME_NOT_FOUND`, `PROFILE_INVALID`, `RESUME_INVALID`, `RESUME_PARSE_FAILED`, `JOB_EXTRACTION_FAILED`, `REQUIREMENT_EXTRACTION_FAILED`, `MISSING_EVIDENCE`, `UNSUPPORTED_CLAIM`, `AI_PROVIDER_TIMEOUT`, `AI_PROVIDER_UNAVAILABLE`, `AI_MODEL_NOT_FOUND`, `AI_RESPONSE_INVALID`, `AI_PROVIDER_ERROR`, `SOURCE_ACQUISITION_FAILED`, `MIGRATION_ERROR`, `CONFIGURATION_ERROR`, `DATABASE_ERROR`, `INTERNAL_ERROR`
- **HTTP mapping**: Typed assistant errors → proper status codes
- **Validation errors**: Filtered (location, message, type only - no `input`)
- **Starlette HTTPException**: Caught for 404/405
- **Generic Exception**: 500 with logging only

## 18. CLI Compatibility

- **All 1108 core tests pass**: No regression
- **Acceptance 24/24 passes**: `python job_assistant.py acceptance`
- **Shared services**: CLI and API use identical `Assistant` construction
- **Shared SQLite**: Same database file, same repositories
- **Commands work**: `profile init`, `profile set`, `resume ingest`, `job ingest`, `job analyze`, `job match`, `job review`, `job report`, `job explain`, `resume relevance`, `status`

## 19. React Boundary

- **Not modified**: React code untouched in R1-B
- **CORS ready**: `localhost:5173` allowed
- **API contract**: Typed schemas for all endpoints
- **No Express**: Legacy `server.ts` quarantined in `legacy/`
- **No duplicate logic**: React stays presentation-only

## 20. Tests

| Suite | Tests | Status |
|-------|-------|--------|
| Core (pre-existing) | 1108 | ✅ PASS |
| API (new) | 45 | ✅ PASS |
| **Total** | **1153** | ✅ PASS |
| Acceptance | 24 steps | ✅ PASS |

**Run commands**:
```bash
python -m pytest tests -q
python -m pytest tests/test_api.py -q
python job_assistant.py acceptance
```

## 21. Acceptance Results

```
========================================================================
24/24 steps passed, 0 failed

REAL SUBMISSION REMAINS DISABLED.
```

## 22. Files Changed

### Modified
- `src/core/settings.py` - Added `ApiSettings`, registered in `AssistantSettings`, included in `redacted_summary()`

### Added (src/api/)
- `src/api/__init__.py`
- `src/api/version.py`
- `src/api/app.py`
- `src/api/dependencies.py`
- `src/api/errors.py`
- `src/api/schemas/__init__.py`
- `src/api/schemas/common.py`
- `src/api/schemas/status.py`
- `src/api/schemas/profile.py`
- `src/api/schemas/resumes.py`
- `src/api/schemas/jobs.py`
- `src/api/routes/__init__.py`
- `src/api/routes/status.py`
- `src/api/routes/profile.py`
- `src/api/routes/resumes.py`
- `src/api/routes/jobs.py`

### Added (tests/)
- `tests/test_api.py` (45 tests)

## 23. Git Commit

**Pending commit**:
```bash
git add src/core/settings.py src/api/ tests/test_api.py
git commit -m "feat: establish FastAPI backend boundary"
```

**Expected result**:
```
git status  # clean
git log --oneline -5  # shows new commit on top of 89b5aa6
```

## 24. Remaining Limitations

1. **No real application submission**: `POST /api/jobs/{id}/apply` returns 403
2. **No browser automation**: Selenium not imported in API, no form filling
3. **No AI semantic embeddings**: `fastembed` unavailable; lexical only; Ollama optional
4. **No HF integration**: Export-only files not connected to canonical provider
5. **No React integration**: React still points to legacy Express (quarantined)
6. **Apply endpoint exists but disabled**: Returns explicit refusal, not 404
7. **No job deletion over HTTP**: 405 (destructive operation)
8. **Docs not yet written**: `docs/R1B_IMPLEMENTATION.md` pending
8. **Embedding scorer**: Only fails when actually needed (not fast-fail at startup)

## 25. R1-C Boundary

**Next milestone (R1-C) should address**:
- React ↔ FastAPI integration (replace Express)
- Real-time job discovery (browser automation layer)
- Application preparation (questions, cover letter, resume tailoring)
- Human-in-the-loop review UI
- OAuth/LinkedIn authentication
- Production hardening (auth, rate limiting, HTTPS)

**R1-C must NOT**:
- Enable real application submission
- Weaken safety invariants
- Duplicate domain logic in React or API

---

**R1-B COMPLETE. FASTAPI IS NOW THE API BOUNDARY OVER THE CANONICAL PYTHON CORE. REAL APPLICATION SUBMISSION REMAINS DISABLED.**