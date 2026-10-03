-- Milestone 4: the match cache learns which scorer produced a verdict.
--
-- A cached decision computed with no scorer is a different decision from
-- one computed with lexical overlap or an embedding model: replaying it
-- under a different scorer would be a cache that lies. The scorer's
-- identity therefore joins the cache key.
--
-- scorer_fingerprint defaults to '' so every row written before this
-- migration stays reachable exactly as long as it is still true - the
-- pre-milestone default was matching with no scorer, which fingerprints
-- as the empty string.

ALTER TABLE job_matches ADD COLUMN scorer_fingerprint TEXT NOT NULL DEFAULT '';

-- Rebuild the unique cache index with the scorer as its fifth column.
-- Dropping and recreating an index is not a data change: no row is
-- deleted, rewritten, or hidden - only the uniqueness rule widens, and
-- the old four-column key was unique, so the five-column key is unique
-- as well for every existing row.
DROP INDEX IF EXISTS ux_job_matches_cache;

CREATE UNIQUE INDEX IF NOT EXISTS ux_job_matches_cache
    ON job_matches(job_id, candidate_id, requirements_fingerprint,
                   candidate_fingerprint, scorer_fingerprint);
