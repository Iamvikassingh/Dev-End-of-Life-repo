-- =============================================================================
-- 003_eol_override_verified_lifecycle.sql
-- AWS EOL Monitor — EOL override and verified lifecycle tables
--
-- eol_overrides:      Admin-set manual EOL dates — highest priority source.
-- verified_lifecycle: MCP-validated EOL dates   — second priority source.
--
-- IMPORTANT: The PostgresBackend in storage.py uses a DIFFERENT schema for
-- verified_lifecycle than what schema.sql defines.  storage.py dynamically
-- creates the table with (product, version) PK when save_verified_lifecycle()
-- is first called.  schema.sql uses a surrogate TEXT id PK with separate
-- service/version columns and a validationStatus column.
--
-- Resolution chosen here (additive / safest):
--   - Create the verified_lifecycle table matching what storage.py actually
--     reads/writes (product, version PK with payload JSONB).
--   - The schema.sql variant columns (id, service, validationStatus, eol_date)
--     are listed in 009_schema_drift_fixes.sql as open risks since they exist
--     in schema.sql but are NOT used by the PostgresBackend code path.
--
-- Safe to run multiple times (idempotent).
-- =============================================================================

BEGIN;

-- ── EOL overrides ─────────────────────────────────────────────────────────────
-- Admin-set manual EOL dates. Takes priority over all other EOL sources.
-- product + version form the natural key (e.g. "eks" + "1.29").
-- payload contains the full override record (eolDate, notes, updatedAt, etc.).

CREATE TABLE IF NOT EXISTS eol_overrides (
    product    TEXT NOT NULL,
    version    TEXT NOT NULL,
    payload    JSONB NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (product, version)
);

-- ── Verified lifecycle ────────────────────────────────────────────────────────
-- MCP-validated EOL dates. Second priority source after eol_overrides.
--
-- This definition matches what PostgresBackend.save_verified_lifecycle() writes:
--   INSERT INTO verified_lifecycle (product, version, payload, updated_at)
-- The _ensure_verified_lifecycle_table() helper in storage.py also creates
-- this same shape (product, version PK + payload JSONB + timestamps).
--
-- NOTE: schema.sql defined a different shape (id PK, service TEXT, eol_date TEXT,
-- validationStatus TEXT). That shape is only used if schema.sql is applied
-- directly without running these migrations. The code path (storage.py) only
-- ever writes via (product, version) primary key — see 009_schema_drift_fixes.sql
-- for the open-risk discussion.

CREATE TABLE IF NOT EXISTS verified_lifecycle (
    product    TEXT        NOT NULL,
    version    TEXT        NOT NULL,
    payload    JSONB       NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (product, version)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_vl_product  ON verified_lifecycle(product);
CREATE INDEX IF NOT EXISTS idx_vl_version  ON verified_lifecycle(version);

COMMIT;
