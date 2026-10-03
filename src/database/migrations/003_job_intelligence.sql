-- Milestone 3: job intelligence core.
--
-- Six tables, each with one job:
--   jobs                the normalised posting itself, identity and lifecycle
--   job_requirements    structured requirements read from the description
--   job_extraction_runs every attempt to capture a description, with status
--   job_analyses        every requirement-extraction run, keyed for caching
--   job_matches         match results against one candidate, keyed for caching
--   job_state_events    audit trail of lifecycle transitions
--
-- Deliberately NOT created:
--   job_sources   source adapters are code, not data. The adapter that
--                 produced a row is recorded on jobs.source; a table would
--                 duplicate configuration and drift from the registry.
--   applications, application_*  Phase 4 territory. This milestone cannot
--                 start an application, so there is nothing to record.

CREATE TABLE IF NOT EXISTS jobs (
    id                 TEXT PRIMARY KEY,
    source             TEXT NOT NULL DEFAULT '',
    external_job_id    TEXT,
    identity_key       TEXT NOT NULL,
    canonical_url      TEXT,
    original_url       TEXT,
    company            TEXT NOT NULL DEFAULT '',
    company_normalized TEXT NOT NULL DEFAULT '',
    title              TEXT NOT NULL DEFAULT '',
    title_normalized   TEXT NOT NULL DEFAULT '',
    location           TEXT,
    workplace_type     TEXT,
    employment_type    TEXT,
    experience_level   TEXT,
    salary_min         REAL,
    salary_max         REAL,
    salary_currency    TEXT,
    salary_period      TEXT,
    description_raw    TEXT,
    description_text   TEXT,
    content_hash       TEXT,
    extraction_status  TEXT,
    status             TEXT NOT NULL,
    posted_at          TEXT,
    discovered_at      TEXT NOT NULL,
    first_seen_at      TEXT,
    last_seen_at       TEXT,
    seen_count         INTEGER NOT NULL DEFAULT 1,
    analysis_source    TEXT NOT NULL,
    source_metadata    TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

-- The dedup guarantee. One row per identity, enforced by the database rather
-- than by a check-then-insert that two runs could both pass.
CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_identity_key
    ON jobs(identity_key);

-- A platform id only identifies a job within its own source, so it is unique
-- per source and NULLs are allowed (partial index) for sources that give none.
CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_source_external
    ON jobs(source, external_job_id) WHERE external_job_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_canonical_url
    ON jobs(canonical_url) WHERE canonical_url IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_source       ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_status       ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_company      ON jobs(company_normalized);
CREATE INDEX IF NOT EXISTS idx_jobs_title        ON jobs(title_normalized);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen   ON jobs(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen    ON jobs(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_content_hash ON jobs(content_hash);

CREATE TABLE IF NOT EXISTS job_requirements (
    id                TEXT PRIMARY KEY,
    job_id            TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    kind              TEXT NOT NULL,
    priority          TEXT NOT NULL,
    text              TEXT NOT NULL,
    normalized        TEXT,
    ambiguous         INTEGER NOT NULL DEFAULT 0,
    min_years         REAL,
    source_excerpt    TEXT,
    extraction_source TEXT NOT NULL,
    analysis_source   TEXT NOT NULL,
    evidence_json     TEXT,
    confidence        REAL NOT NULL DEFAULT 1.0,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_requirements_job      ON job_requirements(job_id);
CREATE INDEX IF NOT EXISTS idx_job_requirements_priority ON job_requirements(job_id, priority);
CREATE INDEX IF NOT EXISTS idx_job_requirements_kind     ON job_requirements(job_id, kind);
-- Same requirement extracted twice for the same job is one row, not two.
CREATE UNIQUE INDEX IF NOT EXISTS ux_job_requirements
    ON job_requirements(job_id, kind, IFNULL(normalized, ''));

CREATE TABLE IF NOT EXISTS job_extraction_runs (
    id                  TEXT PRIMARY KEY,
    job_id              TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    extraction_status   TEXT NOT NULL,
    extraction_method   TEXT NOT NULL,
    raw_length          INTEGER NOT NULL DEFAULT 0,
    normalized_length   INTEGER NOT NULL DEFAULT 0,
    content_hash        TEXT,
    source              TEXT,
    error_code          TEXT,
    detail              TEXT,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_extraction_runs_job    ON job_extraction_runs(job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_extraction_runs_status ON job_extraction_runs(extraction_status);

CREATE TABLE IF NOT EXISTS job_analyses (
    id                TEXT PRIMARY KEY,
    job_id            TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    content_hash      TEXT NOT NULL,
    analyzer          TEXT NOT NULL,
    analyzer_version  TEXT NOT NULL,
    ai_provider       TEXT,
    ai_model          TEXT,
    prompt_version    TEXT,
    analysis_source   TEXT NOT NULL,
    requirement_count INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL,
    error_code        TEXT,
    model_run_id      TEXT,
    created_at        TEXT NOT NULL
);

-- Cache key for requirement extraction: same job, same description, same
-- analyzer and prompt version means the stored requirements are still valid.
-- Re-running with a changed description produces a different content_hash and
-- therefore a different row, which is what stops stale requirements surviving
-- an edited posting.
CREATE UNIQUE INDEX IF NOT EXISTS ux_job_analyses_cache
    ON job_analyses(job_id, content_hash, analyzer, analyzer_version, IFNULL(prompt_version, ''));

CREATE INDEX IF NOT EXISTS idx_job_analyses_job ON job_analyses(job_id, created_at);

CREATE TABLE IF NOT EXISTS job_matches (
    id                       TEXT PRIMARY KEY,
    job_id                   TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    candidate_id             TEXT NOT NULL,
    decision                 TEXT NOT NULL,
    hard_gate_status         TEXT NOT NULL,
    matched_count            INTEGER NOT NULL DEFAULT 0,
    mismatched_count         INTEGER NOT NULL DEFAULT 0,
    unknown_count            INTEGER NOT NULL DEFAULT 0,
    semantic_score           REAL,
    confidence               REAL,
    analysis_source          TEXT NOT NULL,
    requirements_fingerprint TEXT NOT NULL,
    candidate_fingerprint    TEXT NOT NULL,
    ai_provider              TEXT,
    ai_model                 TEXT,
    prompt_version           TEXT,
    model_run_id             TEXT,
    explanation              TEXT NOT NULL,
    evidence                 TEXT,
    review_reasons           TEXT,
    created_at               TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_matches_job        ON job_matches(job_id);
CREATE INDEX IF NOT EXISTS idx_job_matches_candidate  ON job_matches(candidate_id);
CREATE INDEX IF NOT EXISTS idx_job_matches_decision   ON job_matches(decision);

-- Cache key for matching. Reuse only when the requirements, the candidate data
-- and the job are all unchanged; anything else is a new analysis.
CREATE UNIQUE INDEX IF NOT EXISTS ux_job_matches_cache
    ON job_matches(job_id, candidate_id, requirements_fingerprint, candidate_fingerprint);

CREATE TABLE IF NOT EXISTS job_state_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,
    from_state TEXT NOT NULL,
    to_state   TEXT NOT NULL,
    actor_kind TEXT NOT NULL,
    reason     TEXT,
    detail     TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(job_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_job_state_events_job ON job_state_events(job_id, seq);
