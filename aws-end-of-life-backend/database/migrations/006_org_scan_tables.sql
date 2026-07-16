-- =============================================================================
-- 006_org_scan_tables.sql
-- AWS EOL Monitor — Organization scan tables (idempotent re-affirmation)
--
-- Covers: org_connections, org_accounts, org_scan_runs
--
-- These three tables are already created in 002_core_workspace_tables.sql.
-- This migration exists to:
--   1. Make the org-scan feature set explicit in the migration log.
--   2. Add any future org-scan-specific constraints or columns in a
--      dedicated migration without touching the monolithic 002 file.
--   3. Serve as a natural extension point when ENABLE_ORG_SCAN=true is
--      activated in production.
--
-- All CREATE TABLE / CREATE INDEX statements use IF NOT EXISTS — running
-- this after 002 is fully safe and produces no changes.
--
-- Column references validated against storage.py PostgresBackend:
--   org_connections:  id, workspace_id, status, payload
--   org_accounts:     id, workspace_id, org_connection_id, aws_account_id, payload
--   org_scan_runs:    id, workspace_id, org_connection_id, status, started_at, payload
--
-- Safe to run multiple times (idempotent).
-- =============================================================================

BEGIN;

-- ── org_connections ───────────────────────────────────────────────────────────
-- Represents an AWS Organizations management-account connection per workspace.
-- status: pending | active | error | disconnected

CREATE TABLE IF NOT EXISTS org_connections (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT  NOT NULL,
    status       TEXT  DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_org_conn_ws ON org_connections(workspace_id);

-- ── org_accounts ──────────────────────────────────────────────────────────────
-- Individual member accounts discovered within an org connection.
-- aws_account_id is the 12-digit AWS account number.

CREATE TABLE IF NOT EXISTS org_accounts (
    id                TEXT PRIMARY KEY,
    workspace_id      TEXT NOT NULL,
    org_connection_id TEXT NOT NULL,
    aws_account_id    TEXT NOT NULL DEFAULT '',
    payload           JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_org_acct_ws   ON org_accounts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_org_acct_conn ON org_accounts(workspace_id, org_connection_id);
CREATE INDEX IF NOT EXISTS idx_org_acct_aws  ON org_accounts(workspace_id, aws_account_id);

-- ── org_scan_runs ─────────────────────────────────────────────────────────────
-- Tracks org-level scan lifecycle (scans across all member accounts).
-- started_at TEXT for lexicographic ordering (ISO-8601).

CREATE TABLE IF NOT EXISTS org_scan_runs (
    id                TEXT PRIMARY KEY,
    workspace_id      TEXT NOT NULL,
    org_connection_id TEXT NOT NULL,
    status            TEXT DEFAULT '',
    started_at        TEXT DEFAULT '',
    payload           JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_org_scan_ws      ON org_scan_runs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_org_scan_conn    ON org_scan_runs(workspace_id, org_connection_id);
CREATE INDEX IF NOT EXISTS idx_org_scan_started ON org_scan_runs(started_at DESC);

COMMIT;
