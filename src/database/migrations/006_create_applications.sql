-- Migration 006: Application lifecycle tracking
-- Creates the applications table for tracking job application lifecycle

CREATE TABLE IF NOT EXISTS applications (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'SAVED',
    application_date TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    next_followup   DATE,
    interviewer_name TEXT,
    interviewer_contact TEXT,
    notes           TEXT,
    resume_id       TEXT,
    cover_letter_draft_id TEXT,
    source_url      TEXT,
    source_job_metadata TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE RESTRICT
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_job_id ON applications(job_id);
CREATE INDEX IF NOT EXISTS idx_applications_next_followup ON applications(next_followup) WHERE next_followup IS NOT NULL;
