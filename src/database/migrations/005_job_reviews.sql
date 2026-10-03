-- Milestone 4: the review queue gains a lifecycle of its own.
--
-- Until now a "review" existed only as columns on the newest job_matches
-- row: whatever the match said, whenever it said it, with no way to
-- record that a human has since looked. This table is that missing
-- record - one row per posting and candidate, carrying the doubt as it
-- stood (decision, reasons, supporting facts), when it arrived, and
-- whether someone has resolved it.
--
-- job_id + candidate_id is unique: one open question per posting per
-- person. A re-match with a new doubt updates the existing row (or
-- reopens a resolved one); a re-match that repeats a resolved doubt
-- leaves the resolution standing.

CREATE TABLE IF NOT EXISTS job_reviews (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]',
    supporting TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_job_reviews_job_candidate
    ON job_reviews(job_id, candidate_id);

CREATE INDEX IF NOT EXISTS ix_job_reviews_status
    ON job_reviews(status, candidate_id);
