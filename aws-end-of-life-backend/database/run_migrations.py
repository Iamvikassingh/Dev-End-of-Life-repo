#!/usr/bin/env python3
"""
run_migrations.py — PostgreSQL migration runner for AWS EOL Monitor (VersionWatch).

Usage:
    # Standard run (reads DATABASE_URL from environment):
    export DATABASE_URL='postgresql://eol_app:password@host:5432/eol_monitor'
    python3 backend/database/run_migrations.py

    # Override database URL on the command line:
    python3 backend/database/run_migrations.py \
        --database-url 'postgresql://eol_app:password@host:5432/eol_monitor'

    # Dry run — show pending migrations without applying them:
    python3 backend/database/run_migrations.py --dry-run

    # Run migrations from a different directory:
    python3 backend/database/run_migrations.py \
        --migrations-dir /path/to/migrations

How it works:
    1. Connects to the database using DATABASE_URL (same env var as storage.py).
    2. Creates the schema_migrations tracking table if it doesn't exist yet
       (this ensures migration 001 is always self-bootstrapping).
    3. Scans the migrations directory for *.sql files in alphabetical order.
    4. Skips files already recorded in schema_migrations.
    5. Applies each pending file in order inside its own transaction.
    6. Records the applied migration in schema_migrations with a SHA-256 checksum.
    7. Stops immediately on the first failure (does not continue to later files).

Exit codes:
    0 — all migrations applied (or already up to date)
    1 — error (connection failure, SQL error, missing DATABASE_URL, etc.)

Security notes:
    * DATABASE_URL is never printed or logged.
    * Passwords embedded in DATABASE_URL remain hidden.
    * The runner connects with the same credentials as the application.
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Directory containing *.sql migration files (relative to this script's dir)
_DEFAULT_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Schema tracking table name — must match 001_create_migration_tracking.sql
_TRACKING_TABLE = "schema_migrations"

# Minimal DDL to bootstrap the tracking table before migration 001 runs.
# This is intentionally minimal; the full table definition lives in 001.
_BOOTSTRAP_DDL = f"""
CREATE TABLE IF NOT EXISTS {_TRACKING_TABLE} (
    id          SERIAL      PRIMARY KEY,
    version     TEXT        NOT NULL UNIQUE,
    filename    TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum    TEXT
);
CREATE INDEX IF NOT EXISTS idx_schema_migrations_version
    ON {_TRACKING_TABLE}(version);
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(content: str) -> str:
    """Return the SHA-256 hex digest of a string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _redact_url(url: str) -> str:
    """Return a redacted DATABASE_URL safe for printing (password replaced with ****)."""
    try:
        # postgresql://user:password@host:port/db  →  postgresql://user:****@host:port/db
        at_pos = url.rfind("@")
        if at_pos == -1:
            return url
        scheme_end = url.index("://") + 3
        credentials = url[scheme_end:at_pos]
        if ":" in credentials:
            user = credentials.split(":")[0]
            return f"{url[:scheme_end]}{user}:****@{url[at_pos+1:]}"
        return url
    except Exception:
        return "<DATABASE_URL>"


def _collect_migration_files(migrations_dir: Path) -> list:
    """
    Return a sorted list of Path objects for *.sql files in migrations_dir.
    Files are sorted alphabetically (numeric prefix ensures correct order).
    """
    if not migrations_dir.exists():
        print(f"[ERROR] Migrations directory not found: {migrations_dir}", file=sys.stderr)
        sys.exit(1)
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        print(f"[WARN]  No *.sql files found in {migrations_dir}")
    return files


def _get_applied_versions(cursor) -> set:
    """Return a set of version strings already recorded in schema_migrations."""
    cursor.execute(f"SELECT version FROM {_TRACKING_TABLE}")
    return {row[0] for row in cursor.fetchall()}


def _record_migration(cursor, version: str, filename: str, checksum: str) -> None:
    """Insert a migration record into the tracking table."""
    cursor.execute(
        f"""
        INSERT INTO {_TRACKING_TABLE} (version, filename, checksum)
        VALUES (%s, %s, %s)
        ON CONFLICT (version) DO NOTHING
        """,
        (version, filename, checksum),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="PostgreSQL migration runner for AWS EOL Monitor (VersionWatch)."
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="Override DATABASE_URL environment variable.",
    )
    parser.add_argument(
        "--migrations-dir",
        default=str(_DEFAULT_MIGRATIONS_DIR),
        help=f"Path to *.sql migrations directory (default: {_DEFAULT_MIGRATIONS_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print pending migrations without applying them.",
    )
    args = parser.parse_args()

    # ── Resolve DATABASE_URL ──────────────────────────────────────────────────
    database_url = (args.database_url or os.environ.get("DATABASE_URL", "")).strip()
    if not database_url:
        print(
            "[ERROR] DATABASE_URL is not set.\n"
            "        Set it in the environment or pass --database-url.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[INFO]  Database: {_redact_url(database_url)}")

    # ── Import psycopg2 ───────────────────────────────────────────────────────
    try:
        import psycopg2
    except ImportError:
        print(
            "[ERROR] psycopg2-binary is not installed.\n"
            "        Run: pip install psycopg2-binary",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Collect migration files ───────────────────────────────────────────────
    migrations_dir = Path(args.migrations_dir)
    migration_files = _collect_migration_files(migrations_dir)
    print(f"[INFO]  Migrations directory: {migrations_dir}")
    print(f"[INFO]  Migration files found: {len(migration_files)}")

    # ── Connect ───────────────────────────────────────────────────────────────
    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = False
    except psycopg2.OperationalError as exc:
        print(f"[ERROR] Cannot connect to database: {type(exc).__name__}", file=sys.stderr)
        # Never print exc directly — it may include the password
        sys.exit(1)

    try:
        # ── Bootstrap tracking table ──────────────────────────────────────────
        # This ensures schema_migrations exists even before migration 001 runs.
        # Migration 001 is then applied as a normal migration (idempotent DDL).
        with conn.cursor() as cur:
            cur.execute(_BOOTSTRAP_DDL)
        conn.commit()

        # ── Determine applied versions ────────────────────────────────────────
        with conn.cursor() as cur:
            applied = _get_applied_versions(cur)

        # ── Process each migration file ───────────────────────────────────────
        pending_count = 0
        applied_count = 0

        for filepath in migration_files:
            filename = filepath.name
            version  = filepath.stem   # filename without .sql

            if version in applied:
                print(f"[SKIP]  {filename}  (already applied)")
                continue

            # Read migration content
            try:
                content = filepath.read_text(encoding="utf-8")
            except OSError as exc:
                print(f"[ERROR] Cannot read {filepath}: {exc}", file=sys.stderr)
                conn.close()
                sys.exit(1)

            checksum = _sha256(content)
            pending_count += 1

            if args.dry_run:
                print(f"[PEND]  {filename}  (checksum: {checksum[:12]}...)")
                continue

            # ── Apply the migration ───────────────────────────────────────────
            print(f"[APPLY] {filename} ... ", end="", flush=True)
            try:
                with conn.cursor() as cur:
                    cur.execute(content)
                    _record_migration(cur, version, filename, checksum)
                conn.commit()
                applied_count += 1
                print("OK")
            except Exception as exc:
                conn.rollback()
                print(f"FAILED")
                print(
                    f"[ERROR] Migration {filename} failed: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                print(
                    "[ERROR] Stopping. Subsequent migrations were NOT applied.",
                    file=sys.stderr,
                )
                conn.close()
                sys.exit(1)

        # ── Summary ───────────────────────────────────────────────────────────
        if args.dry_run:
            if pending_count == 0:
                print("[INFO]  Database is up to date — no pending migrations.")
            else:
                print(f"[INFO]  {pending_count} migration(s) pending (dry-run — not applied).")
        else:
            if applied_count == 0 and pending_count == 0:
                print("[INFO]  Database is up to date — no migrations to apply.")
            else:
                print(f"[INFO]  Applied {applied_count} migration(s) successfully.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
