-- Migration 007: Application audit events table
-- Creates the application_audit_events table for tracking status transitions

CREATE TABLE IF NOT EXISTS application_audit_events (
    id              TEXT PRIMARY KEY,
    application_id  TEXT NOT NULL,
    from_status     TEXT NOT NULL,
    to_status       TEXT NOT NULL,
    changed_at      TEXT NOT NULL DEFAULT (datetime('now')),
    actor           TEXT NOT NULL DEFAULT 'user',
    note            TEXT
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_audit_app_id ON application_audit_events(application_id);
CREATE INDEX IF NOT EXISTS idx_audit_from_status ON application_audit_events(from_status);
CREATE INDEX IF NOT EXISTS idx_audit_to_status ON application_audit_events(to_status);
