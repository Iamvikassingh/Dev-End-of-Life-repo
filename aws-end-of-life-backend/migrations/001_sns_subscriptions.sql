-- AWS EOL Monitor — SNS Subscriptions Migration
-- Migration: 001_sns_subscriptions.sql
-- Run against PostgreSQL when STORAGE_BACKEND=postgres
-- Idempotent — safe to run multiple times

-- ── SNS Email Subscriptions table ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sns_email_subscriptions (
    id               TEXT        PRIMARY KEY,
    workspace_id     TEXT        NOT NULL,
    email            TEXT        NOT NULL,
    payload          JSONB       NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for workspace-scoped lookups
CREATE INDEX IF NOT EXISTS idx_sns_subs_workspace
    ON sns_email_subscriptions (workspace_id);

-- Index for email uniqueness per workspace
CREATE UNIQUE INDEX IF NOT EXISTS idx_sns_subs_ws_email
    ON sns_email_subscriptions (workspace_id, email)
    WHERE payload->>'status' != 'UNSUBSCRIBED';

-- ── SNS Notification History table ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sns_notification_history (
    id               TEXT        PRIMARY KEY,
    workspace_id     TEXT        NOT NULL,
    cooldown_key     TEXT        NOT NULL,
    sent_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status           TEXT        NOT NULL CHECK (status IN ('SENT', 'FAILED', 'SUPPRESSED')),
    payload          JSONB       NOT NULL DEFAULT '{}'
);

-- Index for workspace + cooldown dedup queries
CREATE INDEX IF NOT EXISTS idx_sns_history_workspace
    ON sns_notification_history (workspace_id);

CREATE INDEX IF NOT EXISTS idx_sns_history_cooldown
    ON sns_notification_history (workspace_id, cooldown_key, sent_at DESC);

-- TTL-style cleanup: keep only last 90 days (run manually or via pg_cron)
-- DELETE FROM sns_notification_history WHERE sent_at < NOW() - INTERVAL '90 days';
