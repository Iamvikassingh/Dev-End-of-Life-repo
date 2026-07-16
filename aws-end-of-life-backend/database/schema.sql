-- AWS EOL Monitor — PostgreSQL Schema
-- Idempotent: safe to run multiple times.
-- Applied by: python3 backend/scripts/setup_postgres.py
-- Or directly: psql -d eol_monitor -f database/schema.sql
--
-- Design notes:
--   * Full object stored as JSONB payload — preserves exact API shapes.
--   * Key fields extracted into indexed columns for efficient WHERE/ORDER.
--   * No FK constraints — app code handles workspace isolation.
--   * created_at TEXT stores ISO 8601 UTC strings (sort lexicographically).

-- ── Workspaces ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS workspaces (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL DEFAULT '',
    token_hash TEXT NOT NULL DEFAULT '',
    payload    JSONB NOT NULL DEFAULT '{}'
);

-- ── Connected accounts ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS connected_accounts (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    payload      JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_accounts_ws ON connected_accounts(workspace_id);

-- ── Inventory resources ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS inventory_resources (
    resource_id  TEXT    NOT NULL,
    workspace_id TEXT    NOT NULL,
    account_id   TEXT    NOT NULL DEFAULT '',
    service_type TEXT    NOT NULL DEFAULT '',
    eol_status   TEXT    NOT NULL DEFAULT '',
    region       TEXT    NOT NULL DEFAULT '',
    payload      JSONB   NOT NULL DEFAULT '{}',
    PRIMARY KEY (resource_id, workspace_id)
);
CREATE INDEX IF NOT EXISTS idx_inv_ws        ON inventory_resources(workspace_id);
CREATE INDEX IF NOT EXISTS idx_inv_ws_acct   ON inventory_resources(workspace_id, account_id);
CREATE INDEX IF NOT EXISTS idx_inv_ws_svc    ON inventory_resources(workspace_id, service_type);
CREATE INDEX IF NOT EXISTS idx_inv_ws_status ON inventory_resources(workspace_id, eol_status);

-- ── Scan runs ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scan_runs (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    account_id   TEXT DEFAULT '',
    status       TEXT DEFAULT '',
    started_at   TEXT DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_scan_ws        ON scan_runs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_scan_ws_acct   ON scan_runs(workspace_id, account_id);
CREATE INDEX IF NOT EXISTS idx_scan_started   ON scan_runs(started_at DESC);

-- ── Organization scan ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS org_connections (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    status       TEXT DEFAULT '',
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
CREATE INDEX IF NOT EXISTS idx_org_acct_ws      ON org_accounts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_org_acct_conn    ON org_accounts(workspace_id, org_connection_id);
CREATE INDEX IF NOT EXISTS idx_org_acct_aws     ON org_accounts(workspace_id, aws_account_id);

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

CREATE TABLE IF NOT EXISTS workspace_config (
    workspace_id TEXT PRIMARY KEY,
    config       JSONB NOT NULL DEFAULT '{}',
    updated_at   TEXT
);

-- ── Global config ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS global_config (
    key        TEXT PRIMARY KEY,
    config     JSONB NOT NULL DEFAULT '{}',
    updated_at TEXT
);

-- ── Alerts ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS alerts (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    account_id   TEXT DEFAULT '',
    status       TEXT DEFAULT '',
    created_at   TEXT DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_alerts_ws     ON alerts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_alerts_ts     ON alerts(workspace_id, created_at DESC);

-- ── Notification settings ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS notification_settings (
    workspace_id TEXT PRIMARY KEY,
    settings     JSONB NOT NULL DEFAULT '{}',
    updated_at   TEXT
);

-- ── Notification logs ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS notification_logs (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    created_at   TEXT DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_notif_logs_ws ON notification_logs(workspace_id, created_at DESC);

-- ── Reports ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS reports (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    created_at   TEXT DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_reports_ws ON reports(workspace_id, created_at DESC);

-- ── API tokens ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS api_tokens (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    token_hash   TEXT NOT NULL DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_ws   ON api_tokens(workspace_id);
CREATE INDEX IF NOT EXISTS idx_api_tokens_hash ON api_tokens(token_hash);

-- ── Audit logs ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS audit_logs (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    action       TEXT DEFAULT '',
    created_at   TEXT DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_ws ON audit_logs(workspace_id, created_at DESC);

-- ── Members ───────────────────────────────────────────────────────────────────

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

CREATE TABLE IF NOT EXISTS member_login_tokens (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    token_hash   TEXT NOT NULL DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_mlogin_ws   ON member_login_tokens(workspace_id);
CREATE INDEX IF NOT EXISTS idx_mlogin_hash ON member_login_tokens(token_hash);

-- ── Upgrade guides (global, not workspace-scoped) ─────────────────────────────

CREATE TABLE IF NOT EXISTS upgrade_guides (
    id      TEXT PRIMARY KEY,
    payload JSONB NOT NULL DEFAULT '{}'
);

-- ── EOL overrides (admin-set manual EOL dates — highest priority source) ──────

CREATE TABLE IF NOT EXISTS eol_overrides (
    product    TEXT NOT NULL,
    version    TEXT NOT NULL,
    payload    JSONB NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (product, version)
);

-- ── Verified lifecycle (MCP-validated EOL dates — second priority source) ─────
-- Schema matches PostgresBackend.save_verified_lifecycle() in storage.py:
--   INSERT INTO verified_lifecycle (product, version, payload, updated_at) ...
-- The earlier schema.sql variant used (id, service, eol_date, validationStatus)
-- which is incompatible with the storage layer. Migration 010 handles existing
-- wrong-variant tables on live databases.

CREATE TABLE IF NOT EXISTS verified_lifecycle (
    product    TEXT        NOT NULL,
    version    TEXT        NOT NULL,
    payload    JSONB       NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (product, version)
);
CREATE INDEX IF NOT EXISTS idx_vl_product ON verified_lifecycle(product);
CREATE INDEX IF NOT EXISTS idx_vl_version ON verified_lifecycle(version);

-- ── General EOL cache ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS general_eol_cache (
    cache_key TEXT PRIMARY KEY,
    payload   JSONB NOT NULL DEFAULT '{}'
);
