-- Phase 2 migration 002: resume variant metadata and text-hash dedup.
--
-- 001 created the resumes table without these columns. Migrations are applied
-- once and recorded, so a database created before this file will never be
-- re-run through 001. Every statement below is therefore additive and
-- idempotent: ADD COLUMN has no IF NOT EXISTS in SQLite, so each column is
-- guarded by a column check performed in Python before it is added.

-- content_hash: SHA-256 of the normalised extracted text. Lets the same CV be
-- recognised across formats (a DOCX and its exported PDF), which a file-hash
-- comparison cannot do.
ALTER TABLE resumes ADD COLUMN content_hash TEXT;

-- role_focus: what this variant is aimed at. Metadata that travels with the
-- resume so a later selection phase can reason about fit without re-parsing.
ALTER TABLE resumes ADD COLUMN role_focus TEXT;

-- version: human-meaningful revision label such as "v2". Ordering continues to
-- use created_at; this is for a human choosing between labelled drafts.
ALTER TABLE resumes ADD COLUMN version TEXT;

-- skills_json: skills this variant emphasises, as a JSON array. Metadata only;
-- the resume parser never adds an entry here on its own.
ALTER TABLE resumes ADD COLUMN skills_json TEXT;

CREATE INDEX IF NOT EXISTS idx_resumes_content_hash ON resumes(content_hash);
CREATE INDEX IF NOT EXISTS idx_resumes_role_focus ON resumes(role_focus);
CREATE INDEX IF NOT EXISTS idx_resumes_version ON resumes(version);
