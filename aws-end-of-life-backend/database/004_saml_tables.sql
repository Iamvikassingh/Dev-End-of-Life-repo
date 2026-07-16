-- 004_saml_tables.sql
-- SAML identity table for SSO/SAML 2.0 support.
-- Run this ONLY when AUTH_SAML_ENABLED=true and auth tables (002_auth_tables.sql) are already applied.
--
-- Usage:
--   psql $DATABASE_URL -f backend/database/004_saml_tables.sql
--
-- Idempotent: safe to run multiple times.

BEGIN;

-- Stores SAML identity records linked to auth_users.
-- NameID is stored as SHA-256 hash only — raw NameID is never persisted.
-- Raw assertion XML is never stored.
CREATE TABLE IF NOT EXISTS auth_saml_identities (
    id              TEXT PRIMARY KEY,
    user_id         TEXT        NOT NULL,
    idp_entity_id   TEXT        NOT NULL,
    name_id_hash    TEXT        NOT NULL,
    email           TEXT        NOT NULL,
    attributes_json JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unique constraint: one record per (IdP, NameID hash) pair
CREATE UNIQUE INDEX IF NOT EXISTS idx_saml_idp_nameid
    ON auth_saml_identities(idp_entity_id, name_id_hash);

CREATE INDEX IF NOT EXISTS idx_saml_user
    ON auth_saml_identities(user_id);

CREATE INDEX IF NOT EXISTS idx_saml_email
    ON auth_saml_identities(email);

COMMIT;
