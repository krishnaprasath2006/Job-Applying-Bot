-- Migration 001: Phase 2 foundation.
--
-- Creates the evidence backbone, profile storage, resume storage, and AI run
-- audit trail. Future tables (jobs, applications, question_memory, ...) are
-- intentionally NOT created here: each should arrive with the phase that
-- actually uses it.
--
-- Design notes:
--   * Truth status is stored as TEXT and constrained by CHECK so an invalid
--     state cannot be written even by a buggy caller.
--   * candidate_facts.value_json holds JSON because fact values are
--     heterogeneous (string, number, list, nested object). The status and
--     evidence columns are the ones that are queried, so they get real
--     columns and real indexes.

CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    document_type   TEXT NOT NULL CHECK (document_type IN
                        ('RESUME','PROFILE','JOB_DESCRIPTION','ANSWER','OTHER')),
    source_id       TEXT,
    filename        TEXT,
    file_hash       TEXT,
    content_hash    TEXT,
    char_count      INTEGER,
    storage_path    TEXT,
    metadata_json   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(document_type);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(file_hash);

CREATE TABLE IF NOT EXISTS evidence (
    id               TEXT PRIMARY KEY,
    source_type      TEXT NOT NULL CHECK (source_type IN
                        ('RESUME','PROFILE','USER_INPUT','JOB_DESCRIPTION','VERIFIED_ANSWER','SYSTEM')),
    source_id        TEXT,
    source_document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    source_location  TEXT,
    text_excerpt     TEXT,
    confidence       REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_type, source_id);

CREATE TABLE IF NOT EXISTS candidate_profiles (
    id              TEXT PRIMARY KEY,
    candidate_id    TEXT NOT NULL UNIQUE,
    version         INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','VALIDATED','INCOMPLETE','INVALID')),
    completeness    REAL NOT NULL DEFAULT 0.0,
    storage_path    TEXT,
    content_hash    TEXT,
    schema_version  TEXT NOT NULL DEFAULT 'phase2-v1',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    validated_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_profiles_candidate ON candidate_profiles(candidate_id);

CREATE TABLE IF NOT EXISTS candidate_facts (
    id              TEXT PRIMARY KEY,
    profile_id      TEXT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    field_path      TEXT NOT NULL,
    section         TEXT,
    field_type      TEXT NOT NULL DEFAULT 'TEXT',
    status          TEXT NOT NULL DEFAULT 'UNKNOWN'
                    CHECK (status IN ('VERIFIED','UNKNOWN','INFERRED')),
    value_json      TEXT,
    risk_level      TEXT NOT NULL DEFAULT 'MEDIUM'
                    CHECK (risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    confidence      REAL NOT NULL DEFAULT 0.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    primary_evidence_id TEXT REFERENCES evidence(id) ON DELETE SET NULL,
    note            TEXT,
    verified_at     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (profile_id, field_path)
);

CREATE INDEX IF NOT EXISTS idx_facts_profile_status ON candidate_facts(profile_id, status);
CREATE INDEX IF NOT EXISTS idx_facts_field ON candidate_facts(field_path);

CREATE TABLE IF NOT EXISTS fact_evidence (
    fact_id         TEXT NOT NULL REFERENCES candidate_facts(id) ON DELETE CASCADE,
    evidence_id     TEXT NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (fact_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS resumes (
    id              TEXT PRIMARY KEY,
    candidate_id    TEXT NOT NULL,
    document_id     TEXT REFERENCES documents(id) ON DELETE SET NULL,
    variant         TEXT,
    filename        TEXT NOT NULL,
    file_type       TEXT NOT NULL CHECK (file_type IN ('PDF','DOCX','TXT','MD','UNKNOWN')),
    file_hash       TEXT NOT NULL,
    file_size_bytes INTEGER,
    page_count      INTEGER,
    char_count      INTEGER,
    storage_path    TEXT,
    raw_text_path   TEXT,
    status          TEXT NOT NULL DEFAULT 'STORED'
                    CHECK (status IN ('STORED','PARSED','PARSE_FAILED','DUPLICATE','INVALID')),
    parser_name     TEXT,
    parser_version  TEXT,
    raw_text        TEXT,
    metadata_json   TEXT,
    is_synthetic    INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0,1)),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (candidate_id, file_hash)
);

CREATE INDEX IF NOT EXISTS idx_resumes_candidate ON resumes(candidate_id);
CREATE INDEX IF NOT EXISTS idx_resumes_hash ON resumes(file_hash);
CREATE INDEX IF NOT EXISTS idx_resumes_variant ON resumes(variant);

CREATE TABLE IF NOT EXISTS resume_sections (
    id              TEXT PRIMARY KEY,
    resume_id       TEXT NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    section_type    TEXT NOT NULL CHECK (section_type IN
                        ('SUMMARY','EDUCATION','EXPERIENCE','SKILLS','PROJECTS',
                         'CERTIFICATIONS','ACHIEVEMENTS','LINKS','CONTACT')),
    position        INTEGER NOT NULL DEFAULT 0,
    heading         TEXT,
    raw_text        TEXT,
    items_json      TEXT,
    char_count      INTEGER,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sections_resume ON resume_sections(resume_id, section_type);

CREATE TABLE IF NOT EXISTS model_runs (
    id              TEXT PRIMARY KEY,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    task            TEXT NOT NULL,
    input_hash      TEXT NOT NULL,
    input_chars     INTEGER NOT NULL DEFAULT 0,
    output_hash     TEXT,
    output_chars    INTEGER,
    analysis_source TEXT NOT NULL CHECK (analysis_source IN
                        ('JOB_DATA','CANDIDATE_DATA','USER_PROVIDED','AI_GENERAL')),
    created_at      TEXT NOT NULL,
    latency_ms      INTEGER,
    status          TEXT NOT NULL CHECK (status IN ('SUCCESS','FAILED','TIMEOUT','CANCELLED')),
    error           TEXT,
    temperature     REAL,
    prompt_preview  TEXT,
    prompt_tokens   INTEGER,
    completion_tokens INTEGER,
    metadata_json   TEXT
);

CREATE INDEX IF NOT EXISTS idx_model_runs_task ON model_runs(task, created_at);
CREATE INDEX IF NOT EXISTS idx_model_runs_source ON model_runs(analysis_source);

-- Records every attempt to change verified candidate data, including the
-- actor and whether it was a trusted deterministic source. This is how the
-- "AI cannot mutate verified facts" rule becomes auditable after the fact.
CREATE TABLE IF NOT EXISTS fact_change_log (
    id              TEXT PRIMARY KEY,
    profile_id      TEXT NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    field_path      TEXT NOT NULL,
    actor           TEXT NOT NULL,
    actor_kind      TEXT NOT NULL CHECK (actor_kind IN ('HUMAN','DETERMINISTIC','AI')),
    before_status   TEXT,
    after_status    TEXT,
    before_value_json TEXT,
    after_value_json  TEXT,
    changed_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_change_log_profile ON fact_change_log(profile_id, changed_at);
