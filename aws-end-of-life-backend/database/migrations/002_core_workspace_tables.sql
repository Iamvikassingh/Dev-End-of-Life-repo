-- =============================================================================
-- 002_core_workspace_tables.sql
-- AWS EOL Monitor — Core workspace, account, inventory, scan, org, config,
-- alert, notification, report, api-token, audit, member, member-session,
-- and member-login-token tables.
--
-- Source of truth: backend/database/schema.sql (all columns replicated here
-- verbatim — no invented columns).
--
-- Safe to run multiple times (idempotent):
--   * All CREATE TABLE use IF NOT EXISTS
--   * All CREATE INDEX use IF NOT EXISTS
-- =============================================================================

BEGIN;

-- ── Workspaces ────────────────────────────────────────────────────────────────
-- Stores workspace metadata. token_hash is the SHA-256 of the workspace token.
-- Full workspace object is stored in payload JSONB for flexible schema.

CREATE TABLE IF NOT EXISTS workspaces (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL DEFAULT '',
    token_hash TEXT NOT NULL DEFAULT '',
    payload    JSONB NOT NULL DEFAULT '{}'
);

-- ── Connected accounts ────────────────────────────────────────────────────────
-- Each row represents one AWS account connected to a workspace.

CREATE TABLE IF NOT EXISTS connected_accounts (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_accounts_ws ON connected_accounts(workspace_id);

-- ── Inventory resources ───────────────────────────────────────────────────────
-- One row per (resource_id, workspace_id) pair.
-- Key scalar fields extracted for indexed WHERE/ORDER — full shape in payload.

CREATE TABLE IF NOT EXISTS inventory_resources (
    resource_id  TEXT  NOT NULL,
    workspace_id TEXT  NOT NULL,
    account_id   TEXT  NOT NULL DEFAULT '',
    service_type TEXT  NOT NULL DEFAULT '',
    eol_status   TEXT  NOT NULL DEFAULT '',
    region       TEXT  NOT NULL DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (resource_id, workspace_id)
);

CREATE INDEX IF NOT EXISTS idx_inv_ws        ON inventory_resources(workspace_id);
CREATE INDEX IF NOT EXISTS idx_inv_ws_acct   ON inventory_resources(workspace_id, account_id);
CREATE INDEX IF NOT EXISTS idx_inv_ws_svc    ON inventory_resources(workspace_id, service_type);
CREATE INDEX IF NOT EXISTS idx_inv_ws_status ON inventory_resources(workspace_id, eol_status);

-- ── Scan runs ─────────────────────────────────────────────────────────────────
-- Tracks per-account scan lifecycle (PENDING / RUNNING / COMPLETED / FAILED).
-- started_at stored as ISO-8601 TEXT for lexicographic ordering.

CREATE TABLE IF NOT EXISTS scan_runs (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT  NOT NULL,
    account_id   TEXT  DEFAULT '',
    status       TEXT  DEFAULT '',
    started_at   TEXT  DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_scan_ws      ON scan_runs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_scan_ws_acct ON scan_runs(workspace_id, account_id);
CREATE INDEX IF NOT EXISTS idx_scan_started ON scan_runs(started_at DESC);

-- ── Organization scan ─────────────────────────────────────────────────────────
-- org_connections: AWS Organizations management-account connections per workspace.
-- org_accounts: individual member accounts discovered under an org connection.
-- org_scan_runs: org-level scan lifecycle.

CREATE TABLE IF NOT EXISTS org_connections (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT  NOT NULL,
    status       TEXT  DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_org_conn_ws ON org_connections(workspace_id);

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

-- ── Workspace config ──────────────────────────────────────────────────────────
-- Per-workspace config blob (warn_days, enabled_services, etc.).
-- updated_at stored as ISO-8601 TEXT to match the rest of the schema.

CREATE TABLE IF NOT EXISTS workspace_config (
    workspace_id TEXT PRIMARY KEY,
    config       JSONB NOT NULL DEFAULT '{}',
    updated_at   TEXT
);

-- ── Global config ─────────────────────────────────────────────────────────────
-- Singleton config row with key='global'. Other keys reserved for future use.

CREATE TABLE IF NOT EXISTS global_config (
    key        TEXT PRIMARY KEY,
    config     JSONB NOT NULL DEFAULT '{}',
    updated_at TEXT
);

-- ── Alerts ────────────────────────────────────────────────────────────────────
-- One alert per resource-EOL event. status: OPEN / SNOOZED / RESOLVED.
-- created_at TEXT for lexicographic sorting (matches ISO-8601 sort order).

CREATE TABLE IF NOT EXISTS alerts (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT  NOT NULL,
    account_id   TEXT  DEFAULT '',
    status       TEXT  DEFAULT '',
    created_at   TEXT  DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_alerts_ws     ON alerts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_alerts_ts     ON alerts(workspace_id, created_at DESC);

-- ── Notification settings ─────────────────────────────────────────────────────
-- Per-workspace notification config (Slack webhook, email recipients, etc.).

CREATE TABLE IF NOT EXISTS notification_settings (
    workspace_id TEXT PRIMARY KEY,
    settings     JSONB NOT NULL DEFAULT '{}',
    updated_at   TEXT
);

-- ── Notification logs ─────────────────────────────────────────────────────────
-- Audit trail of sent notifications.

CREATE TABLE IF NOT EXISTS notification_logs (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT  NOT NULL,
    created_at   TEXT  DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_notif_logs_ws ON notification_logs(workspace_id, created_at DESC);

-- ── Reports ───────────────────────────────────────────────────────────────────
-- Saved report snapshots.

CREATE TABLE IF NOT EXISTS reports (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT  NOT NULL,
    created_at   TEXT  DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_reports_ws ON reports(workspace_id, created_at DESC);

-- ── API tokens ────────────────────────────────────────────────────────────────
-- Programmatic API access tokens (hashed). token_hash is SHA-256 of raw token.

CREATE TABLE IF NOT EXISTS api_tokens (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT  NOT NULL,
    token_hash   TEXT  NOT NULL DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_ws   ON api_tokens(workspace_id);
CREATE INDEX IF NOT EXISTS idx_api_tokens_hash ON api_tokens(token_hash);

-- ── Audit logs ────────────────────────────────────────────────────────────────
-- Workspace-scoped action audit trail.

CREATE TABLE IF NOT EXISTS audit_logs (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT  NOT NULL,
    action       TEXT  DEFAULT '',
    created_at   TEXT  DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_audit_ws ON audit_logs(workspace_id, created_at DESC);

-- ── Members ───────────────────────────────────────────────────────────────────
-- Workspace members (invited users). invite_token_hash is hashed invite link token.

CREATE TABLE IF NOT EXISTS members (
    id                TEXT PRIMARY KEY,
    workspace_id      TEXT NOT NULL,
    email             TEXT NOT NULL DEFAULT '',
    status            TEXT DEFAULT '',
    invite_token_hash TEXT DEFAULT '',
    payload           JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_members_ws       ON members(workspace_id);
CREATE INDEX IF NOT EXISTS idx_members_invite   ON members(invite_token_hash);
CREATE INDEX IF NOT EXISTS idx_members_ws_email ON members(workspace_id, email);

-- ── Member sessions ───────────────────────────────────────────────────────────
-- Active workspace-member sessions. token_hash is SHA-256 of session token.

CREATE TABLE IF NOT EXISTS member_sessions (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    member_id    TEXT NOT NULL DEFAULT '',
    token_hash   TEXT NOT NULL DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_msess_ws   ON member_sessions(workspace_id);
CREATE INDEX IF NOT EXISTS idx_msess_hash ON member_sessions(token_hash);

-- ── Member login tokens (magic-link, one-time use) ────────────────────────────
-- Short-lived tokens sent via email magic-link login.

CREATE TABLE IF NOT EXISTS member_login_tokens (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    token_hash   TEXT NOT NULL DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_mlogin_ws   ON member_login_tokens(workspace_id);
CREATE INDEX IF NOT EXISTS idx_mlogin_hash ON member_login_tokens(token_hash);

-- ── Upgrade guides (global, not workspace-scoped) ─────────────────────────────
-- Admin-managed upgrade guidance documents.

CREATE TABLE IF NOT EXISTS upgrade_guides (
    id      TEXT PRIMARY KEY,
    payload JSONB NOT NULL DEFAULT '{}'
);

-- ── General EOL cache ─────────────────────────────────────────────────────────
-- Cached endoflife.date API response under the singleton key 'general'.

CREATE TABLE IF NOT EXISTS general_eol_cache (
    cache_key TEXT PRIMARY KEY,
    payload   JSONB NOT NULL DEFAULT '{}'
);

COMMIT;
