-- =============================================================================
-- 007_alerts_snooze_reports.sql
-- AWS EOL Monitor — Alerts, notifications, and reports (idempotent re-affirmation)
--
-- Covers: alerts, notification_settings, notification_logs, reports
--
-- All four tables are already created in 002_core_workspace_tables.sql.
-- This migration:
--   1. Makes the alerts/notification/reporting feature set explicit in the log.
--   2. Adds alert snooze column support (snoozed_until) as an additive change
--      if the alerts table already exists but lacks the column.
--      (snooze state is currently stored in payload JSONB in the running
--       codebase — this column is provided for future indexed queries.)
--   3. Serves as the extension point for alert_rules or scheduled-report
--      tables when those features are implemented.
--
-- All CREATE TABLE / CREATE INDEX use IF NOT EXISTS.
-- All ALTER TABLE ADD COLUMN use IF NOT EXISTS.
-- No DROP, no TRUNCATE, no RENAME.
--
-- Column references validated against storage.py PostgresBackend:
--   alerts:                id, workspace_id, account_id, status, created_at, payload
--   notification_settings: workspace_id, settings, updated_at
--   notification_logs:     id, workspace_id, created_at, payload
--   reports:               id, workspace_id, created_at, payload
--
-- Safe to run multiple times (idempotent).
-- =============================================================================

BEGIN;

-- ── Alerts ────────────────────────────────────────────────────────────────────
-- One alert per resource-EOL event. Managed entirely by alert_notifier.py.
-- status: OPEN | SNOOZED | RESOLVED
-- Snooze state and expiry are stored in payload for now; snoozed_until
-- column added here for future indexed snooze-expiry queries.

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

-- Additive snooze column — allows future indexed queries for snooze expiry.
-- NULL means not snoozed. Stored as TEXT (ISO-8601) consistent with rest of schema.
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS snoozed_until TEXT DEFAULT NULL;

-- ── Notification settings ─────────────────────────────────────────────────────
-- Per-workspace notification configuration blob.

CREATE TABLE IF NOT EXISTS notification_settings (
    workspace_id TEXT PRIMARY KEY,
    settings     JSONB NOT NULL DEFAULT '{}',
    updated_at   TEXT
);

-- ── Notification logs ─────────────────────────────────────────────────────────
-- Audit trail of all outbound notifications (Slack, email, SNS, etc.).

CREATE TABLE IF NOT EXISTS notification_logs (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT  NOT NULL,
    created_at   TEXT  DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_notif_logs_ws ON notification_logs(workspace_id, created_at DESC);

-- ── Reports ───────────────────────────────────────────────────────────────────
-- Point-in-time report snapshots saved by users.

CREATE TABLE IF NOT EXISTS reports (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT  NOT NULL,
    created_at   TEXT  DEFAULT '',
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_reports_ws ON reports(workspace_id, created_at DESC);

-- ── alert_rules (reserved) ────────────────────────────────────────────────────
-- Alert rules / thresholds are not yet implemented as a separate table.
-- Rule configuration currently lives in workspace_config JSONB.
-- This table is reserved for a future structured alert-rules feature.
-- Creating it now is premature — left as a comment to document the intent.
--
-- CREATE TABLE IF NOT EXISTS alert_rules (
--     id           TEXT PRIMARY KEY,
--     workspace_id TEXT  NOT NULL,
--     rule_type    TEXT  NOT NULL DEFAULT '',
--     payload      JSONB NOT NULL DEFAULT '{}',
--     created_at   TEXT  DEFAULT ''
-- );

COMMIT;
