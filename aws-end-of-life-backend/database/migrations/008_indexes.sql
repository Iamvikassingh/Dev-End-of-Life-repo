-- =============================================================================
-- 008_indexes.sql
-- AWS EOL Monitor — Supplemental performance indexes
--
-- All primary indexes are already declared in the CREATE TABLE migrations
-- (002 through 007).  This migration adds supplemental indexes that improve
-- performance for common query patterns observed in storage.py but that
-- were not covered by the base schema.
--
-- All indexes use CREATE INDEX IF NOT EXISTS — safe to re-run.
-- No table structure is modified here.
-- =============================================================================

BEGIN;

-- ── scan_runs supplemental ────────────────────────────────────────────────────
-- Fast lookup for "is there a running scan for this account?" — called by
-- get_running_scan() which filters workspace_id + account_id + status='RUNNING'.

CREATE INDEX IF NOT EXISTS idx_scan_ws_status
    ON scan_runs(workspace_id, account_id, status);

-- Fast cleanup of stale scans (cleanup_stale_scans filters status + started_at).
CREATE INDEX IF NOT EXISTS idx_scan_status_started
    ON scan_runs(status, started_at);

-- ── alerts supplemental ───────────────────────────────────────────────────────
-- find_alert_by_resource() filters workspace_id + account_id + status.
-- The idx_alerts_status index covers (workspace_id, status) but not account_id.

CREATE INDEX IF NOT EXISTS idx_alerts_ws_acct_status
    ON alerts(workspace_id, account_id, status);

-- ── inventory_resources supplemental ─────────────────────────────────────────
-- JSONB path expression index for scan_started_at used in stale-write guard
-- inside replace_resources_for_account():
--   SELECT MAX(payload->>'scan_started_at') FROM inventory_resources
--   WHERE workspace_id = %s AND account_id = %s
-- This covers the WHERE efficiently (existing idx_inv_ws_acct already helps).
-- The JSONB extraction index is additive and improves the MAX() aggregation.

CREATE INDEX IF NOT EXISTS idx_inv_scan_started_at
    ON inventory_resources((payload->>'scan_started_at'));

-- ── members supplemental ─────────────────────────────────────────────────────
-- find_member_by_invite_token_hash() only filters invite_token_hash;
-- idx_members_invite already exists for this. No additional index needed.

-- ── auth_sessions supplemental ───────────────────────────────────────────────
-- lookup_session() joins auth_sessions → auth_users on session_hash.
-- Existing idx_auth_sessions_hash covers the WHERE clause.
-- Add a partial index for non-expired sessions to speed up the common case.

CREATE INDEX IF NOT EXISTS idx_auth_sessions_active
    ON auth_sessions(session_hash)
    WHERE expires_at > '2020-01-01';  -- broad enough to catch all live sessions

-- ── auth_email_verification_tokens supplemental ───────────────────────────────
-- Cleanup query for expired unused tokens (maintenance task).

CREATE INDEX IF NOT EXISTS idx_auth_evtokens_unused_expired
    ON auth_email_verification_tokens(expires_at)
    WHERE used_at IS NULL;

-- ── eol_overrides supplemental ────────────────────────────────────────────────
-- list_eol_overrides() does ORDER BY product, version — PK already covers this.
-- No additional index needed.

-- ── verified_lifecycle supplemental ──────────────────────────────────────────
-- get_verified_lifecycle() looks up (product, version) — PK covers this.
-- No additional index needed beyond what 003 created.

-- ── org_accounts supplemental ────────────────────────────────────────────────
-- save_org_account() uses ON CONFLICT (id) but also filters by aws_account_id.
-- idx_org_acct_aws already covers (workspace_id, aws_account_id). No addition needed.

COMMIT;
