-- =============================================================================
-- 005_saml_tables.sql
-- AWS EOL Monitor — SAML SSO tables
--
-- Covers: auth_saml_identities
--         (auth_saml_configs reserved — not yet implemented in codebase)
--
-- Run ONLY when AUTH_SAML_ENABLED=true and migration 004_auth_tables.sql
-- has already been applied (auth_users must exist).
--
-- Source: backend/database/004_saml_tables.sql (promoted verbatim into
-- this numbered migration series). All SQL validated against saml_handler.py
-- column references.
--
-- saml_handler.py column references verified:
--   auth_saml_identities: id, user_id, idp_entity_id, name_id_hash, email,
--                         attributes_json, created_at, last_login_at
--
-- Safe to run multiple times (idempotent).
-- =============================================================================

BEGIN;

-- ── SAML identity records ─────────────────────────────────────────────────────
-- Stores the link between an IdP assertion and an auth_users row.
-- Security invariants (enforced by application + this schema):
--   * Raw NameID is NEVER stored — only its SHA-256 hash (name_id_hash).
--   * Raw SAMLResponse XML is NEVER stored.
--   * Certificates and private keys are NEVER stored here.
--
-- The UNIQUE constraint on (idp_entity_id, name_id_hash) ensures one record
-- per (IdP, user) pair, enabling efficient upsert in saml_handler.py.

CREATE TABLE IF NOT EXISTS auth_saml_identities (
    id              TEXT        PRIMARY KEY,
    user_id         TEXT        NOT NULL,
    idp_entity_id   TEXT        NOT NULL,
    name_id_hash    TEXT        NOT NULL,
    email           TEXT        NOT NULL,
    attributes_json JSONB,                      -- safe attributes only (no secrets)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One record per (IdP, NameID hash) pair
CREATE UNIQUE INDEX IF NOT EXISTS idx_saml_idp_nameid
    ON auth_saml_identities(idp_entity_id, name_id_hash);

CREATE INDEX IF NOT EXISTS idx_saml_user
    ON auth_saml_identities(user_id);

CREATE INDEX IF NOT EXISTS idx_saml_email
    ON auth_saml_identities(email);

-- ── SAML configs (reserved) ───────────────────────────────────────────────────
-- auth_saml_configs is NOT yet referenced in saml_handler.py — SAML IdP
-- configuration is currently read entirely from environment variables.
-- This table is reserved for future per-workspace IdP config support.
-- Creating it now to claim the namespace without blocking the current release.
--
-- (No application code reads or writes this table yet.)

CREATE TABLE IF NOT EXISTS auth_saml_configs (
    id           TEXT        PRIMARY KEY,
    workspace_id TEXT        NOT NULL,
    idp_entity_id TEXT       NOT NULL DEFAULT '',
    idp_sso_url  TEXT        NOT NULL DEFAULT '',
    idp_x509_cert TEXT       NOT NULL DEFAULT '',
    status       TEXT        NOT NULL DEFAULT 'active',  -- active | disabled
    payload      JSONB       NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saml_configs_ws
    ON auth_saml_configs(workspace_id);

COMMIT;
