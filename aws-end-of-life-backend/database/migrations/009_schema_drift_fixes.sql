-- =============================================================================
-- 009_schema_drift_fixes.sql
-- AWS EOL Monitor — Additive schema drift corrections
--
-- Applies only ADD COLUMN IF NOT EXISTS and CREATE INDEX IF NOT EXISTS.
-- No DROP, no TRUNCATE, no RENAME, no data rewrites.
--
-- DRIFT IDENTIFIED (code expects column / behavior not in schema.sql):
--
-- 1. auth_users.updated_at (TEXT)
--    saml_handler.py _provision_user() INSERTs into auth_users with an
--    `updated_at` field:
--      INSERT INTO auth_users
--        (id, email, name, email_verified, status, created_at, updated_at)
--      VALUES (...)
--    But auth_users in 002_auth_tables.sql / 004_auth_tables.sql has no
--    `updated_at` column — only `created_at` and `last_login_at`.
--    FIX: ADD COLUMN IF NOT EXISTS updated_at TEXT DEFAULT ''
--
-- 2. verified_lifecycle schema mismatch (OPEN RISK — listed but NOT fixed here)
--    schema.sql defines verified_lifecycle with columns:
--      id, service, version, eol_date, validationStatus, payload, updated_at
--    But storage.py PostgresBackend._ensure_verified_lifecycle_table() creates:
--      product, version, payload, created_at, updated_at  (PK on product,version)
--    And save_verified_lifecycle() writes:
--      INSERT INTO verified_lifecycle (product, version, payload, updated_at) ...
--    These are INCOMPATIBLE schemas — columns named `service` vs `product`,
--    `eol_date` and `validationStatus` do not exist in the code-written variant.
--
--    Migration 003 creates the code-correct variant (product, version PK).
--    If schema.sql was applied to a live DB WITHOUT these migrations, the
--    schema.sql-variant table exists with the WRONG columns.
--
--    SAFE RESOLUTION: Run 003 first (IF NOT EXISTS ensures the correct table
--    is created if missing). If the wrong-column table already exists, a
--    destructive intervention is required (rename + recreate) — this is listed
--    as an OPEN RISK below and must be handled manually if needed.
--
-- OPEN RISKS (destructive — NOT implemented here):
--   a) If verified_lifecycle already exists with schema.sql columns (id, service,
--      eol_date, validationStatus), the app will fail to write to it.
--      Resolution requires: ALTER TABLE RENAME + CREATE TABLE (new) + data copy.
--      This is a DROP equivalent and cannot be done safely in an additive migration.
--      DETECTION QUERY:
--        SELECT column_name FROM information_schema.columns
--        WHERE table_name = 'verified_lifecycle' ORDER BY ordinal_position;
--      If you see `service` or `eol_date`, you have the wrong variant.
--
--   b) eol_overrides.updated_at column: schema.sql declares this as TEXT NOT NULL
--      DEFAULT ''. storage.py does NOT write updated_at to the eol_overrides row
--      (it stores the value only in payload JSONB). This is latent but harmless —
--      the column has a DEFAULT so INSERT without the column succeeds.
--
-- Safe to run multiple times (idempotent).
-- =============================================================================

BEGIN;

-- ── Fix 1: auth_users.updated_at ─────────────────────────────────────────────
-- saml_handler._provision_user() includes updated_at in its INSERT column list.
-- Without this column the SAML auto-provisioning INSERT will fail with:
--   "column updated_at of relation auth_users does not exist"
--
-- This is an additive ADD COLUMN — no existing data is affected.
-- Default of '' matches the TEXT NOT NULL DEFAULT '' pattern used elsewhere.

ALTER TABLE auth_users
    ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT '';

-- Update index to support queries filtering by auth_users.updated_at if needed.
-- (No index added — this column is not filtered in any current query.)

-- ── Fix 2: Verify verified_lifecycle has correct PK ───────────────────────────
-- The following SELECT can be run manually to detect the wrong-variant table.
-- It is provided as a comment — not executed — because correcting it requires
-- human review and a destructive migration step.
--
-- MANUAL CHECK (run in psql before applying migrations to an existing DB):
--
--   SELECT column_name
--   FROM information_schema.columns
--   WHERE table_name = 'verified_lifecycle'
--   ORDER BY ordinal_position;
--
-- EXPECTED OUTPUT (code-correct variant created by migration 003):
--   product | version | payload | created_at | updated_at
--
-- BAD OUTPUT (schema.sql variant — indicates mismatch):
--   id | service | version | eol_date | validationStatus | payload | updated_at
--
-- If BAD OUTPUT is seen, stop the migration run and consult the runbook's
-- "Open Risks" section before proceeding.

-- ── Fix 3: eol_overrides — confirm updated_at column exists ──────────────────
-- schema.sql declares: updated_at TEXT NOT NULL DEFAULT ''
-- If the table was created by this migration series (003) without the updated_at
-- column, add it now. The INSERT in save_eol_override() does NOT include
-- updated_at in the column list so this column is latent but harmless either way.
-- Including it here for schema completeness.

ALTER TABLE eol_overrides
    ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT '';

COMMIT;
