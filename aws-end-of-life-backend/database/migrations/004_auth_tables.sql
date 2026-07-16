-- =============================================================================
-- 004_auth_tables.sql
-- AWS EOL Monitor — Feature-flagged auth tables
--
-- Covers: auth_users, auth_sessions, auth_email_verification_tokens,
--         auth_user_workspace_memberships
--
-- These tables are required only when AUTH_EMAIL_SIGNUP_ENABLED=true or
-- AUTH_GOOGLE_SIGNUP_ENABLED=true.  The existing workspace-token auth flow
-- does NOT use these tables and is unaffected.
--
-- Source: backend/database/002_auth_tables.sql (promoted verbatim into
-- this numbered migration series). All SQL validated against auth_handler.py
-- column references.
--
-- auth_handler.py column references verified:
--   auth_users:  id, email, name, avatar_url, provider, provider_subject,
--                email_verified, status, created_at, last_login_at
--   auth_sessions: id, user_id, session_hash, expires_at, created_at,
--                  last_seen_at
--   auth_email_verification_tokens: id, user_id, token_hash, expires_at,
--                                    used_at, created_at
--   auth_user_workspace_memberships: user_id, workspace_id, role, created_at
--
-- saml_handler.py also INSERTs into auth_users with an `updated_at` field —
-- see 009_schema_drift_fixes.sql for the ALTER TABLE ADD COLUMN fix.
--
-- Safe to run multiple times (idempotent).
-- =============================================================================

BEGIN;

-- ── Auth users ────────────────────────────────────────────────────────────────
-- Central user record shared by email signup and Google OAuth flows.
-- provider: 'email' | 'google'
-- status:   'active' | 'disabled'

CREATE TABLE IF NOT EXISTS auth_users (
    id               TEXT    PRIMARY KEY,
    email            TEXT    NOT NULL UNIQUE,
    name             TEXT    NOT NULL DEFAULT '',
    avatar_url       TEXT    NOT NULL DEFAULT '',
    provider         TEXT    NOT NULL DEFAULT 'email',   -- email | google
    provider_subject TEXT    NOT NULL DEFAULT '',
    email_verified   BOOLEAN NOT NULL DEFAULT FALSE,
    status           TEXT    NOT NULL DEFAULT 'active',  -- active | disabled
    created_at       TEXT    NOT NULL DEFAULT '',
    last_login_at    TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_auth_users_email
    ON auth_users(email);

CREATE INDEX IF NOT EXISTS idx_auth_users_provider
    ON auth_users(provider, provider_subject);

-- ── Auth sessions (cookie-based) ──────────────────────────────────────────────
-- Session records backed by the eolm_session HTTP-only cookie.
-- Only the SHA-256 hash of the session token is stored (never the raw token).

CREATE TABLE IF NOT EXISTS auth_sessions (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT '',
    last_seen_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_hash
    ON auth_sessions(session_hash);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user
    ON auth_sessions(user_id);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires
    ON auth_sessions(expires_at);

-- ── Email verification tokens (one-time use, hashed) ─────────────────────────
-- Short-lived tokens for email address verification during signup.
-- used_at is NULL until the token is consumed (one-time use enforced by app).

CREATE TABLE IF NOT EXISTS auth_email_verification_tokens (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT,                            -- NULL = not yet used
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_auth_evtokens_hash
    ON auth_email_verification_tokens(token_hash);

CREATE INDEX IF NOT EXISTS idx_auth_evtokens_user
    ON auth_email_verification_tokens(user_id);

CREATE INDEX IF NOT EXISTS idx_auth_evtokens_expires
    ON auth_email_verification_tokens(expires_at);

-- ── User ↔ workspace memberships ──────────────────────────────────────────────
-- Maps auth_users to workspaces with a role.
-- role: 'owner' | 'editor' | 'viewer'
-- Composite PK prevents duplicate membership rows.

CREATE TABLE IF NOT EXISTS auth_user_workspace_memberships (
    user_id      TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'viewer',  -- owner | editor | viewer
    created_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, workspace_id)
);

CREATE INDEX IF NOT EXISTS idx_auth_uwm_user
    ON auth_user_workspace_memberships(user_id);

CREATE INDEX IF NOT EXISTS idx_auth_uwm_ws
    ON auth_user_workspace_memberships(workspace_id);

COMMIT;
