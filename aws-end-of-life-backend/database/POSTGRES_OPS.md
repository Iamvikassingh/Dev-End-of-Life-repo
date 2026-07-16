# PostgreSQL Operations Guide — AWS EOL Monitor

This document covers initial setup, production migration, database changes,
and day-to-day operations for the PostgreSQL storage backend.

---

## Table of Contents

1. [Current Setup](#current-setup)
2. [Initial Setup from Scratch](#initial-setup-from-scratch)
3. [Switching Storage Backend](#switching-storage-backend)
4. [Migrating to a New Database Host](#migrating-to-a-new-database-host)
5. [Migrating File Data to PostgreSQL](#migrating-file-data-to-postgresql)
6. [Database User Management](#database-user-management)
7. [Backup and Restore](#backup-and-restore)
8. [Production Checklist](#production-checklist)
9. [Rollback: Postgres → File](#rollback-postgres--file)
10. [Troubleshooting](#troubleshooting)

---

## Current Setup

| Item | Value |
|------|-------|
| Database | `eol_monitor` |
| Host | Private PostgreSQL endpoint recommended. Temporary public EC2 DB hosts must be closed before launch. |
| App user | `eol_app` |
| Schema file | `database/schema.sql` |
| Setup script | `backend/scripts/setup_postgres.py` |
| Migration script | `backend/scripts/migrate_file_to_postgres.py` |
| PM2 config | `ecosystem.config.js` |
| Tables | Core workspace/account/inventory/report/member tables plus org-scan foundation tables |

---

## Initial Setup from Scratch

### 1. Install dependency

```bash
pip install psycopg2-binary
pip freeze > requirements.txt
```

### 2. Create DB user and database (run once as postgres superuser)

```sql
-- Connect as postgres superuser
sudo -u postgres psql

CREATE USER eol_app WITH PASSWORD 'your_strong_password';
CREATE DATABASE eol_monitor OWNER eol_app;
GRANT ALL PRIVILEGES ON DATABASE eol_monitor TO eol_app;
\q
```

### 3. Apply schema

```bash
export DATABASE_URL='postgresql://postgres:superuser_pass@host:5432/eol_monitor'
python3 backend/scripts/setup_postgres.py
```

### 4. Grant table permissions to app user

```sql
sudo -u postgres psql -d eol_monitor

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO eol_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO eol_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO eol_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO eol_app;
```

### 5. Set environment variables

```bash
# backend/.env
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://eol_app:your_password@host:5432/eol_monitor
```

### 6. Migrate existing file data (if any)

```bash
# Dry run first
python3 backend/scripts/migrate_file_to_postgres.py \
  --data-dir /home/ubuntu/eol-data --dry-run

# Real migration
python3 backend/scripts/migrate_file_to_postgres.py \
  --data-dir /home/ubuntu/eol-data
```

### 7. Restart backend

```bash
pm2 restart eol-backend --update-env
curl http://127.0.0.1:3001/health
# Expected: "storage_backend": "postgres"
```

---

## Switching Storage Backend

Edit `ecosystem.config.js` (or `.env`) and restart:

```js
// ecosystem.config.js
env: {
  STORAGE_BACKEND: 'postgres',   // postgres | file | s3 | dynamodb
  DATABASE_URL: 'postgresql://eol_app:password@host:5432/eol_monitor',
}
```

```bash
pm2 restart eol-backend --update-env
pm2 save
```

Accepted values for `STORAGE_BACKEND`:
- `postgres` / `postgresql` / `db` — PostgreSQL
- `file` — local JSON files (uses `EOL_DATA_DIR`)
- `s3` — AWS S3 (uses `EOL_BUCKET`)
- `dynamodb` — AWS DynamoDB (default in Lambda)

---

## Migrating to a New Database Host

Use this when moving to AWS RDS, a different EC2 instance, or any new PostgreSQL server.

### Step 1 — Dump current database

```bash
# From old server
pg_dump -h OLD_HOST -U eol_app -d eol_monitor -F c -f eol_monitor_backup.dump
# Enter password when prompted
```

### Step 2 — Create database on new server

```bash
# On new server
sudo -u postgres psql -c "CREATE USER eol_app WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "CREATE DATABASE eol_monitor OWNER eol_app;"
sudo -u postgres psql -d eol_monitor -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO eol_app;"
```

### Step 3 — Apply schema on new server

```bash
export DATABASE_URL='postgresql://postgres:superpass@NEW_HOST:5432/eol_monitor'
python3 backend/scripts/setup_postgres.py
```

### Step 4 — Restore dump to new server

```bash
pg_restore -h NEW_HOST -U eol_app -d eol_monitor -F c eol_monitor_backup.dump
```

### Step 5 — Update ecosystem.config.js

```bash
# On EC2 app server
nano /home/ubuntu/aws-end-of-life-backend/ecosystem.config.js

# Change DATABASE_URL to new host:
# DATABASE_URL: 'postgresql://eol_app:password@NEW_HOST:5432/eol_monitor',
```

### Step 6 — Restart and verify

```bash
pm2 restart eol-backend --update-env
pm2 save
curl http://127.0.0.1:3001/health
curl http://127.0.0.1:3001/eol/general/summary
```

### Step 7 — Verify data

```bash
python3 -c "
import psycopg2
conn = psycopg2.connect('postgresql://eol_app:password@NEW_HOST:5432/eol_monitor')
cur = conn.cursor()
for t in ['workspaces','connected_accounts','inventory_resources','scan_runs']:
    cur.execute(f'SELECT COUNT(*) FROM {t}')
    print(f'{t}: {cur.fetchone()[0]}')
conn.close()
"
```

---

## Migrating File Data to PostgreSQL

```bash
# Always dry-run first
python3 backend/scripts/migrate_file_to_postgres.py \
  --data-dir /home/ubuntu/eol-data \
  --dry-run

# If counts look correct, run real migration
python3 backend/scripts/migrate_file_to_postgres.py \
  --data-dir /home/ubuntu/eol-data

# To point at a different DB (override DATABASE_URL)
python3 backend/scripts/migrate_file_to_postgres.py \
  --data-dir /home/ubuntu/eol-data \
  --database-url 'postgresql://eol_app:password@host:5432/eol_monitor'
```

Migration is **idempotent** — safe to run multiple times. Uses `ON CONFLICT DO UPDATE`.

File → Table mapping:

| JSON File | PostgreSQL Table |
|-----------|-----------------|
| `workspaces.json` | `workspaces` |
| `accounts.json` | `connected_accounts` |
| `inventory.json` | `inventory_resources` |
| `scan_runs.json` | `scan_runs` |
| `alerts.json` | `alerts` |
| `notification_settings.json` | `notification_settings` |
| `notification_logs.json` | `notification_logs` |
| `reports.json` | `reports` |
| `api_tokens.json` | `api_tokens` |
| `audit_logs.json` | `audit_logs` |
| `members.json` | `members` |
| `member_sessions.json` | `member_sessions` |
| `member_login_tokens.json` | `member_login_tokens` |
| `org_connections.json` | `org_connections` |
| `org_accounts.json` | `org_accounts` |
| `org_scan_runs.json` | `org_scan_runs` |
| `upgrade_guides.json` | `upgrade_guides` |
| `general_eol_cache.json` | `general_eol_cache` |
| `workspace_config.json` | `workspace_config` |
| `config.json` | `global_config` |

---

## Database User Management

### Create dedicated app user (recommended for production)

```sql
CREATE USER eol_app WITH PASSWORD 'strong_password';
CREATE DATABASE eol_monitor OWNER eol_app;
GRANT ALL PRIVILEGES ON DATABASE eol_monitor TO eol_app;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO eol_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO eol_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO eol_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO eol_app;
```

### Change user password

```sql
ALTER USER eol_app WITH PASSWORD 'new_strong_password';
```

Then update `DATABASE_URL` in `ecosystem.config.js` and restart:

```bash
nano ecosystem.config.js   # update password in DATABASE_URL
pm2 restart eol-backend --update-env
pm2 save
```

### Rotate postgres superuser password

```sql
ALTER USER postgres WITH PASSWORD 'new_superuser_password';
```

> After rotating: update any scripts that use the superuser URL.

---

## Backup and Restore

### Backup (run on app server or DB server)

```bash
# Full backup
pg_dump -h DB_PRIVATE_HOST -U eol_app -d eol_monitor \
  -F c -f /tmp/eol_monitor_$(date +%Y%m%d_%H%M%S).dump

# Plain SQL backup (human-readable)
pg_dump -h DB_PRIVATE_HOST -U eol_app -d eol_monitor \
  -F p -f /tmp/eol_monitor_$(date +%Y%m%d_%H%M%S).sql
```

### Restore

```bash
# Restore from custom format
pg_restore -h HOST -U eol_app -d eol_monitor -F c /tmp/eol_monitor_backup.dump

# Restore from SQL
psql -h HOST -U eol_app -d eol_monitor -f /tmp/eol_monitor_backup.sql
```

### Automated daily backup (cron)

```bash
crontab -e

# Add this line — daily backup at 2 AM, keep last 7 days
0 2 * * * pg_dump -h DB_PRIVATE_HOST -U eol_app -d eol_monitor -F c \
  -f /home/ubuntu/backups/eol_monitor_$(date +\%Y\%m\%d).dump \
  && find /home/ubuntu/backups/ -name "*.dump" -mtime +7 -delete
```

---

## Production Checklist

Before going to production, complete the following:

### Security

- [ ] Move PostgreSQL to **private/internal IP** — remove public 5432 access from Security Group
- [ ] Security group allows port `5432` only from the app EC2 private IP or app security group
- [ ] Use **dedicated `eol_app` user** — never use `postgres` superuser for the app
- [ ] Rotate `postgres` superuser password (was shared in setup)
- [ ] Rotate `eol_app` password if it was used in chat/logs/testing
- [ ] Rotate `ADMIN_PORTAL_TOKEN` if it was ever exposed
- [ ] Set `ALLOWED_ORIGIN` to exact frontend domain (remove `*`)
- [ ] Enable SSL on PostgreSQL connection: append `?sslmode=require` to `DATABASE_URL`

### Reliability

- [ ] Set up automated daily backups (see Backup section above)
- [ ] Store backups on S3 or separate volume
- [ ] Test restore from backup at least once
- [ ] Consider migrating to **AWS RDS** for managed failover + backups
- [ ] Run the current schema idempotently after deploy: `python3 backend/scripts/setup_postgres.py`

### PM2 / Server

- [ ] `pm2 save` done — process list persists across reboots
- [ ] `pm2 startup` done — systemd service enabled
- [ ] `ecosystem.config.js` has correct `DATABASE_URL`
- [ ] Verify `pm2 resurrect` works after reboot test

### Verification commands

```bash
# Storage backend check
curl http://127.0.0.1:3001/health
# Expected: "storage_backend": "postgres"

# Data accessible
curl http://127.0.0.1:3001/eol/general/summary

# DB row counts
python3 -c "
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
for t in ['workspaces','connected_accounts','inventory_resources',
          'scan_runs','alerts','members','api_tokens']:
    cur.execute(f'SELECT COUNT(*) FROM {t}')
    print(f'  {t}: {cur.fetchone()[0]}')
conn.close()
"
```

---

## Rollback: Postgres → File

If you need to switch back to file storage temporarily:

```bash
# Edit ecosystem.config.js
nano /home/ubuntu/aws-end-of-life-backend/ecosystem.config.js

# Change:
#   STORAGE_BACKEND: 'file',
#   EOL_DATA_DIR: '/home/ubuntu/eol-data',
# Comment out DATABASE_URL

pm2 restart eol-backend --update-env
pm2 save
curl http://127.0.0.1:3001/health
# Expected: "storage_backend": "file"
```

> Note: Any data written to PostgreSQL while using postgres backend will NOT
> be visible in file mode (and vice versa). Always migrate before switching.

---

## Troubleshooting

### Backend shows `"storage_backend": "file"` even after setting postgres

PM2 did not pick up the new env vars. Fix:

```bash
# Export all vars to current shell first
export $(grep -v '^#' .env | grep -v '^\s*$' | xargs)
pm2 restart eol-backend --update-env
pm2 save
```

Or use `ecosystem.config.js` which always sets env vars correctly.

### `password authentication failed`

```bash
# Test connection manually
python3 -c "
import psycopg2
conn = psycopg2.connect(host='HOST', port=5432, dbname='eol_monitor',
                        user='eol_app', password='YOUR_PASSWORD')
print('OK')
conn.close()
"
# Note: use keyword args if password contains special chars like @ # %
```

### `could not translate host name` error in DATABASE_URL

Password contains special characters (`@`, `#`, `%`). URL-encode them:

| Character | Encoded |
|-----------|---------|
| `@` | `%40` |
| `#` | `%23` |
| `%` | `%25` |
| `!` | `%21` |

Example: `Password@123` → `Password%40123` in the URL.

### `relation "workspaces" does not exist`

Schema not applied. Run:

```bash
export DATABASE_URL='postgresql://postgres:superpass@host:5432/eol_monitor'
python3 backend/scripts/setup_postgres.py
# Then grant privileges to eol_app
sudo -u postgres psql -d eol_monitor -c \
  "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO eol_app;"
```

### Connection refused on port 5432

Check PostgreSQL is listening:

```bash
# On DB server
sudo systemctl status postgresql
sudo ss -tlnp | grep 5432

# Check pg_hba.conf allows remote connections
sudo nano /etc/postgresql/*/main/pg_hba.conf
# Add: host all all 0.0.0.0/0 md5  (restrict to app IP in production)

sudo systemctl reload postgresql
```

### Schema changes (adding new columns/tables)

Always use `IF NOT EXISTS` / `IF EXISTS` — the schema is designed to be idempotent:

```bash
# Add new table or column to database/schema.sql
# Then re-run setup (safe, won't drop existing data)
python3 backend/scripts/setup_postgres.py
```

---

*Last updated: June 2026*
