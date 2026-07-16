-- AWS EOL Monitor — Auth tables migration (002)
-- Feature-flagged auth: users, sessions, email verification, workspace memberships.
-- Existing workspace_token flow is NOT affected by these tables.
-- Safe to run multiple times (idempotent).

-- ── Auth users ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS auth_users (
    id               TEXT    PRIMARY KEY,
    email            TEXT    NOT NULL UNIQUE,
    name             TEXT    NOT NULL DEFAULT '',
    avatar_url       TEXT    NOT NULL DEFAULT '',
    provider         TEXT    NOT NULL DEFAULT 'email',  -- email | google
    provider_subject TEXT    NOT NULL DEFAULT '',
    email_verified   BOOLEAN NOT NULL DEFAULT FALSE,
    status           TEXT    NOT NULL DEFAULT 'active', -- active | disabled
    created_at       TEXT    NOT NULL DEFAULT '',
    last_login_at    TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_auth_users_email    ON auth_users(email);
CREATE INDEX IF NOT EXISTS idx_auth_users_provider ON auth_users(provider, provider_subject);

-- ── Auth sessions (cookie-based) ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS auth_sessions (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT '',
    last_seen_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_hash    ON auth_sessions(session_hash);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user    ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires ON auth_sessions(expires_at);

-- ── Email verification tokens (one-time use, hashed) ─────────────────────────

CREATE TABLE IF NOT EXISTS auth_email_verification_tokens (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_auth_evtokens_hash    ON auth_email_verification_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_auth_evtokens_user    ON auth_email_verification_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_evtokens_expires ON auth_email_verification_tokens(expires_at);

-- ── User ↔ workspace memberships ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS auth_user_workspace_memberships (
    user_id      TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'viewer',  -- owner | editor | viewer
    created_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, workspace_id)
);
CREATE INDEX IF NOT EXISTS idx_auth_uwm_user ON auth_user_workspace_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_uwm_ws   ON auth_user_workspace_memberships(workspace_id);
