-- =============================================================================
-- 010_fix_verified_lifecycle_schema.sql
-- AWS EOL Monitor — Fix verified_lifecycle schema drift on existing databases
--
-- Problem:
--   schema.sql (prior to this fix) defined verified_lifecycle with columns:
--     id, service, version, eol_date, validationStatus, payload, updated_at
--   storage.py PostgresBackend.save_verified_lifecycle() writes:
--     INSERT INTO verified_lifecycle (product, version, payload, updated_at)
--   These are incompatible.  If schema.sql was applied without migrations 003+,
--   the wrong-column table exists and all save_verified_lifecycle() calls fail.
--
-- Detection:
--   If the 'service' column exists → wrong variant (schema.sql origin).
--   If the 'product' column exists → correct variant (migration 003 origin).
--
-- Fix:
--   Rename the wrong-variant table to verified_lifecycle_old_schema (safe backup).
--   Create the correct table (product, version PK + payload JSONB + timestamps).
--   Only runs if the wrong variant is detected — idempotent.
--
-- Data safety:
--   verified_lifecycle holds admin-entered MCP-validated EOL dates.
--   The old (wrong-variant) table had no foreign-key dependents.
--   Renaming to _old_schema preserves the data for manual inspection.
--   No customer scan data is stored in this table.
--
-- Safe to run multiple times (condition guard ensures idempotency).
-- =============================================================================

DO $$
BEGIN
    -- Only act when the wrong variant (schema.sql origin) is present.
    -- Identifying marker: column named 'service' which does not exist in the
    -- correct (code-matching) variant that uses 'product' instead.
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'verified_lifecycle'
          AND column_name  = 'service'
    ) THEN
        RAISE NOTICE '010: wrong-variant verified_lifecycle detected (has service column). Fixing.';

        -- Rename wrong variant so existing data is not lost.
        ALTER TABLE verified_lifecycle RENAME TO verified_lifecycle_old_schema;

        -- Create correct variant matching storage.py and migration 003.
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

        RAISE NOTICE '010: verified_lifecycle recreated with correct schema. Old table saved as verified_lifecycle_old_schema.';

    ELSIF NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name   = 'verified_lifecycle'
    ) THEN
        -- Table does not exist at all (e.g. migration 003 not applied yet).
        RAISE NOTICE '010: verified_lifecycle table missing, creating.';

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

    ELSE
        RAISE NOTICE '010: verified_lifecycle already has correct schema (product column present). No action needed.';
    END IF;
END $$;
