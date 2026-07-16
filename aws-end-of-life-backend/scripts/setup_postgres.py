#!/usr/bin/env python3
"""
Create the eol_monitor database and apply the schema.

Usage:
    export DATABASE_URL='postgresql://postgres:<PASSWORD>@18.222.7.3:5432/eol_monitor'
    python3 backend/scripts/setup_postgres.py

Idempotent — safe to run multiple times.
Does NOT log or print the database password.
"""
import os
import sys

# schema.sql lives two levels up from this script
_HERE       = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(_HERE, "..", "database", "schema.sql")
SCHEMA_PATH = os.path.abspath(SCHEMA_PATH)

def main():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        sys.exit("ERROR: DATABASE_URL is not set.\n"
                 "Example: export DATABASE_URL='postgresql://eol_app:<password>@host:5432/eol_monitor'")

    try:
        import psycopg2
    except ImportError:
        sys.exit("ERROR: psycopg2-binary is not installed.\n"
                 "Run: pip install psycopg2-binary")

    # Parse database name from URL (last path segment, before any query string)
    try:
        db_name  = database_url.rsplit("/", 1)[1].split("?")[0].strip()
        base_url = database_url.rsplit("/", 1)[0]
    except IndexError:
        sys.exit("ERROR: DATABASE_URL must end with a database name, e.g. .../eol_monitor")

    if not db_name:
        sys.exit("ERROR: Could not parse database name from DATABASE_URL.")

    # Step 1: Connect to the default 'postgres' database and create eol_monitor if absent
    admin_url = base_url + "/postgres"
    print(f"Connecting to PostgreSQL (database: postgres) ...")
    try:
        conn = psycopg2.connect(admin_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if cur.fetchone():
                print(f"  Database '{db_name}' already exists — skipping CREATE.")
            else:
                cur.execute(f'CREATE DATABASE "{db_name}"')
                print(f"  Created database '{db_name}'.")
        conn.close()
    except psycopg2.OperationalError as exc:
        # Never print the URL (it may contain the password)
        sys.exit(f"ERROR: Cannot connect to PostgreSQL: {type(exc).__name__}: {exc}")

    # Step 2: Apply schema to the target database
    if not os.path.exists(SCHEMA_PATH):
        sys.exit(f"ERROR: Schema file not found at {SCHEMA_PATH}\n"
                 "Make sure you are running from the project root.")

    with open(SCHEMA_PATH) as f:
        schema_sql = f.read()

    print(f"Applying schema to '{db_name}' ...")
    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
        conn.close()
        print("  Schema applied successfully (all tables and indexes are up to date).")
    except Exception as exc:
        sys.exit(f"ERROR: Failed to apply schema: {exc}")

    print(f"\nDone. Next steps:")
    print(f"  1. Update backend/.env:")
    print(f"       STORAGE_BACKEND=postgres")
    print(f"       DATABASE_URL=<your-url>")
    print(f"  2. Migrate existing data (optional):")
    print(f"       python3 backend/scripts/migrate_file_to_postgres.py --data-dir /home/ubuntu/eol-data --dry-run")
    print(f"  3. Restart the server:")
    print(f"       pm2 restart eol-backend --update-env")


if __name__ == "__main__":
    main()
