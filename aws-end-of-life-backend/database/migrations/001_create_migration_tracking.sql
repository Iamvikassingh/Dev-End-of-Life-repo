-- =============================================================================
-- 001_create_migration_tracking.sql
-- AWS EOL Monitor — Migration tracking table
--
-- This MUST be the first migration applied.
-- Creates the schema_migrations table that the migration runner uses to track
-- which migrations have been applied.
--
-- Safe to run multiple times (idempotent).
-- =============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    id          SERIAL      PRIMARY KEY,
    version     TEXT        NOT NULL UNIQUE,
    filename    TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum    TEXT
);

-- Index for fast version lookups (runner checks this on every migration)
CREATE INDEX IF NOT EXISTS idx_schema_migrations_version
    ON schema_migrations(version);

-- Comment for visibility in pg_description
COMMENT ON TABLE schema_migrations IS
    'Migration tracking table — managed by run_migrations.py. Do not edit manually.';
