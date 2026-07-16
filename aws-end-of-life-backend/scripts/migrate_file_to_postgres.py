#!/usr/bin/env python3
"""
Migrate data from FileBackend JSON files to PostgreSQL.

Usage:
    export DATABASE_URL='postgresql://postgres:<PASSWORD>@18.222.7.3:5432/eol_monitor'

    # Dry run — shows counts, writes nothing:
    python3 backend/scripts/migrate_file_to_postgres.py --data-dir /home/ubuntu/eol-data --dry-run

    # Real migration:
    python3 backend/scripts/migrate_file_to_postgres.py --data-dir /home/ubuntu/eol-data

File → Table mapping:
    workspaces.json              → workspaces
    accounts.json                → connected_accounts
    inventory.json               → inventory_resources
    scan_runs.json               → scan_runs
    alerts.json                  → alerts
    notification_settings.json   → notification_settings
    notification_logs.json       → notification_logs
    reports.json                 → reports
    api_tokens.json              → api_tokens
    audit_logs.json              → audit_logs
    members.json                 → members
    member_sessions.json         → member_sessions
    member_login_tokens.json     → member_login_tokens
    upgrade_guides.json          → upgrade_guides
    general_eol_cache.json       → general_eol_cache
    workspace_config.json        → workspace_config
    config.json                  → global_config

Notes:
    - Raw token values are NEVER stored (file backend only stores hashes).
    - Duplicate (workspace_id, email) member pairs are deduplicated (first wins).
    - All inserts use ON CONFLICT ... DO UPDATE — safe to run multiple times.
    - Run setup_postgres.py first to ensure the schema exists.
"""
import argparse
import json
import os
import sys


def _read(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _flatten_dict_of_lists(d: dict) -> list:
    """{'ws-a': [item, ...], 'ws-b': [...]} → [item, ...]"""
    result = []
    if isinstance(d, dict):
        for items in d.values():
            if isinstance(items, list):
                result.extend(items)
    return result


def migrate(data_dir: str, database_url: str, dry_run: bool):
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        sys.exit("ERROR: psycopg2-binary required.\nRun: pip install psycopg2-binary")

    if not database_url:
        sys.exit("ERROR: DATABASE_URL is not set.")

    # ── Load all JSON files ───────────────────────────────────────────────────

    def path(name):
        return os.path.join(data_dir, name)

    workspaces        = _read(path("workspaces.json"),              [])
    accounts          = _read(path("accounts.json"),                [])
    inventory         = _read(path("inventory.json"),               [])
    scan_runs         = _read(path("scan_runs.json"),               [])
    alerts            = _read(path("alerts.json"),                  [])
    notif_settings    = _read(path("notification_settings.json"),   {})
    notif_logs        = _read(path("notification_logs.json"),       [])
    reports           = _read(path("reports.json"),                 [])
    api_tokens_raw    = _read(path("api_tokens.json"),              {})
    audit_logs_raw    = _read(path("audit_logs.json"),              {})
    members_raw       = _read(path("members.json"),                 {})
    member_sess_raw   = _read(path("member_sessions.json"),         {})
    login_toks_raw    = _read(path("member_login_tokens.json"),     {})
    guides            = _read(path("upgrade_guides.json"),          [])
    eol_cache         = _read(path("general_eol_cache.json"),       None)
    ws_config         = _read(path("workspace_config.json"),        {})
    global_cfg        = _read(path("config.json"),                  {})

    # Flatten dict-of-lists collections
    api_tokens     = _flatten_dict_of_lists(api_tokens_raw)
    audit_logs     = _flatten_dict_of_lists(audit_logs_raw)
    members        = _flatten_dict_of_lists(members_raw)
    member_sessions = _flatten_dict_of_lists(member_sess_raw)
    login_tokens   = _flatten_dict_of_lists(login_toks_raw)

    # ── Print summary ─────────────────────────────────────────────────────────

    print("=" * 55)
    print("Migration summary (data to migrate):")
    print("=" * 55)
    print(f"  Workspaces           : {len(workspaces)}")
    print(f"  Accounts             : {len(accounts)}")
    print(f"  Inventory resources  : {len(inventory)}")
    print(f"  Scan runs            : {len(scan_runs)}")
    print(f"  Alerts               : {len(alerts)}")
    print(f"  Notif. settings      : {len(notif_settings)} workspaces")
    print(f"  Notification logs    : {len(notif_logs)}")
    print(f"  Reports              : {len(reports)}")
    print(f"  API tokens           : {len(api_tokens)}")
    print(f"  Audit logs           : {len(audit_logs)}")
    print(f"  Members              : {len(members)}")
    print(f"  Member sessions      : {len(member_sessions)}")
    print(f"  Login tokens         : {len(login_tokens)}")
    print(f"  Upgrade guides       : {len(guides)}")
    print(f"  General EOL cache    : {'yes' if eol_cache else 'no'}")
    print(f"  Workspace configs    : {len(ws_config)} workspaces")
    print(f"  Global config        : {'yes' if global_cfg else 'no'}")
    print("=" * 55)

    if dry_run:
        print("\n[DRY RUN] No data was written. Remove --dry-run to migrate.")
        return

    # ── Connect ───────────────────────────────────────────────────────────────

    print("\nConnecting to PostgreSQL ...")
    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = False
    except psycopg2.OperationalError as exc:
        sys.exit(f"ERROR: Cannot connect: {type(exc).__name__}: {exc}")

    J = psycopg2.extras.Json
    errors = 0

    def _exec(cur, sql, params, label="row"):
        nonlocal errors
        try:
            cur.execute(sql, params)
        except Exception as exc:
            print(f"  WARNING [{label}]: {type(exc).__name__}: {exc} — skipped")
            errors += 1
            conn.rollback()

    # ── Migrate each collection ───────────────────────────────────────────────

    try:
        # Workspaces first (other tables reference workspace_id)
        print(f"  Migrating {len(workspaces)} workspaces ...")
        with conn.cursor() as cur:
            for ws in workspaces:
                _exec(cur, """
                    INSERT INTO workspaces (id, name, token_hash, payload)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name, token_hash = EXCLUDED.token_hash,
                        payload = EXCLUDED.payload
                """, (ws.get("id",""), ws.get("name",""), ws.get("token_hash",""), J(ws)),
                    label=f"workspace:{ws.get('id','?')}")
        conn.commit()

        print(f"  Migrating {len(accounts)} accounts ...")
        with conn.cursor() as cur:
            for a in accounts:
                _exec(cur, """
                    INSERT INTO connected_accounts (id, workspace_id, payload)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        workspace_id = EXCLUDED.workspace_id, payload = EXCLUDED.payload
                """, (a.get("id",""), a.get("workspace_id",""), J(a)),
                    label=f"account:{a.get('id','?')}")
        conn.commit()

        print(f"  Migrating {len(inventory)} inventory resources ...")
        with conn.cursor() as cur:
            for r in inventory:
                ws_id   = r.get("workspace_id") or r.get("workspaceId","")
                acct_id = r.get("account_id") or r.get("accountId","")
                _exec(cur, """
                    INSERT INTO inventory_resources
                        (resource_id, workspace_id, account_id, service_type, eol_status, region, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (resource_id, workspace_id) DO UPDATE SET
                        account_id = EXCLUDED.account_id, service_type = EXCLUDED.service_type,
                        eol_status = EXCLUDED.eol_status, region = EXCLUDED.region,
                        payload = EXCLUDED.payload
                """, (r.get("resource_id",""), ws_id, acct_id,
                      r.get("service_type",""), r.get("eol_status",""), r.get("region",""), J(r)),
                    label=f"resource:{r.get('resource_id','?')}")
        conn.commit()

        print(f"  Migrating {len(scan_runs)} scan runs ...")
        with conn.cursor() as cur:
            for run in scan_runs:
                _exec(cur, """
                    INSERT INTO scan_runs (id, workspace_id, account_id, status, started_at, payload)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status, started_at = EXCLUDED.started_at,
                        payload = EXCLUDED.payload
                """, (run.get("scanId",""), run.get("workspaceId",""), run.get("accountId",""),
                      run.get("status",""), run.get("startedAt", run.get("createdAt","")), J(run)),
                    label=f"scan:{run.get('scanId','?')}")
        conn.commit()

        print(f"  Migrating {len(alerts)} alerts ...")
        with conn.cursor() as cur:
            for al in alerts:
                _exec(cur, """
                    INSERT INTO alerts (id, workspace_id, account_id, status, created_at, payload)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status, created_at = EXCLUDED.created_at,
                        payload = EXCLUDED.payload
                """, (al.get("id",""), al.get("workspaceId",""), al.get("accountId",""),
                      al.get("status",""), al.get("createdAt",""), J(al)),
                    label=f"alert:{al.get('id','?')}")
        conn.commit()

        print(f"  Migrating notification settings ({len(notif_settings)} workspaces) ...")
        with conn.cursor() as cur:
            for ws_id, sett in (notif_settings.items() if isinstance(notif_settings, dict) else []):
                _exec(cur, """
                    INSERT INTO notification_settings (workspace_id, settings, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (workspace_id) DO UPDATE SET
                        settings = EXCLUDED.settings, updated_at = NOW()
                """, (ws_id, J(sett)), label=f"notif_settings:{ws_id}")
        conn.commit()

        print(f"  Migrating {len(notif_logs)} notification logs ...")
        with conn.cursor() as cur:
            for lg in notif_logs:
                _exec(cur, """
                    INSERT INTO notification_logs (id, workspace_id, created_at, payload)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        created_at = EXCLUDED.created_at, payload = EXCLUDED.payload
                """, (lg.get("id",""), lg.get("workspaceId",""), lg.get("createdAt",""), J(lg)),
                    label=f"notif_log:{lg.get('id','?')}")
        conn.commit()

        print(f"  Migrating {len(reports)} reports ...")
        with conn.cursor() as cur:
            for rpt in reports:
                _exec(cur, """
                    INSERT INTO reports (id, workspace_id, created_at, payload)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        created_at = EXCLUDED.created_at, payload = EXCLUDED.payload
                """, (rpt.get("id",""), rpt.get("workspaceId",""), rpt.get("createdAt",""), J(rpt)),
                    label=f"report:{rpt.get('id','?')}")
        conn.commit()

        print(f"  Migrating {len(api_tokens)} API tokens ...")
        with conn.cursor() as cur:
            for tok in api_tokens:
                _exec(cur, """
                    INSERT INTO api_tokens (id, workspace_id, token_hash, payload)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        token_hash = EXCLUDED.token_hash, payload = EXCLUDED.payload
                """, (tok.get("id",""), tok.get("workspaceId",""), tok.get("tokenHash",""), J(tok)),
                    label=f"api_token:{tok.get('id','?')}")
        conn.commit()

        print(f"  Migrating {len(audit_logs)} audit log entries ...")
        with conn.cursor() as cur:
            for lg in audit_logs:
                _exec(cur, """
                    INSERT INTO audit_logs (id, workspace_id, action, created_at, payload)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        action = EXCLUDED.action, created_at = EXCLUDED.created_at,
                        payload = EXCLUDED.payload
                """, (lg.get("id",""), lg.get("workspaceId",""),
                      lg.get("action",""), lg.get("createdAt",""), J(lg)),
                    label=f"audit:{lg.get('id','?')}")
        conn.commit()

        print(f"  Migrating {len(members)} members ...")
        seen_ws_email: set = set()
        with conn.cursor() as cur:
            for m in members:
                key = (m.get("workspaceId",""), m.get("email","").lower())
                if key in seen_ws_email:
                    print(f"  SKIP duplicate member email '{m.get('email','')}' in workspace '{key[0]}'")
                    continue
                seen_ws_email.add(key)
                _exec(cur, """
                    INSERT INTO members (id, workspace_id, email, status, invite_token_hash, payload)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        email = EXCLUDED.email, status = EXCLUDED.status,
                        invite_token_hash = EXCLUDED.invite_token_hash, payload = EXCLUDED.payload
                """, (m.get("id",""), m.get("workspaceId",""), m.get("email",""),
                      m.get("status",""), m.get("inviteTokenHash","") or "", J(m)),
                    label=f"member:{m.get('id','?')}")
        conn.commit()

        print(f"  Migrating {len(member_sessions)} member sessions ...")
        with conn.cursor() as cur:
            for s in member_sessions:
                _exec(cur, """
                    INSERT INTO member_sessions (id, workspace_id, member_id, token_hash, payload)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        member_id = EXCLUDED.member_id, token_hash = EXCLUDED.token_hash,
                        payload = EXCLUDED.payload
                """, (s.get("id",""), s.get("workspaceId",""), s.get("memberId",""),
                      s.get("tokenHash",""), J(s)), label=f"session:{s.get('id','?')}")
        conn.commit()

        print(f"  Migrating {len(login_tokens)} login tokens ...")
        with conn.cursor() as cur:
            for t in login_tokens:
                _exec(cur, """
                    INSERT INTO member_login_tokens (id, workspace_id, token_hash, payload)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        token_hash = EXCLUDED.token_hash, payload = EXCLUDED.payload
                """, (t.get("id",""), t.get("workspaceId",""), t.get("tokenHash",""), J(t)),
                    label=f"login_tok:{t.get('id','?')}")
        conn.commit()

        print(f"  Migrating {len(guides)} upgrade guides ...")
        with conn.cursor() as cur:
            for g in guides:
                _exec(cur, """
                    INSERT INTO upgrade_guides (id, payload) VALUES (%s, %s)
                    ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload
                """, (g.get("id",""), J(g)), label=f"guide:{g.get('id','?')}")
        conn.commit()

        if eol_cache:
            print("  Migrating general EOL cache ...")
            with conn.cursor() as cur:
                _exec(cur, """
                    INSERT INTO general_eol_cache (cache_key, payload)
                    VALUES ('general', %s)
                    ON CONFLICT (cache_key) DO UPDATE SET payload = EXCLUDED.payload
                """, (J(eol_cache),), label="eol_cache")
            conn.commit()

        if isinstance(ws_config, dict) and ws_config:
            print(f"  Migrating workspace configs ({len(ws_config)}) ...")
            with conn.cursor() as cur:
                for ws_id, cfg in ws_config.items():
                    _exec(cur, """
                        INSERT INTO workspace_config (workspace_id, config, updated_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (workspace_id) DO UPDATE SET
                            config = EXCLUDED.config, updated_at = EXCLUDED.updated_at
                    """, (ws_id, J(cfg), cfg.get("updated_at","")),
                        label=f"ws_config:{ws_id}")
            conn.commit()

        if global_cfg:
            print("  Migrating global config ...")
            with conn.cursor() as cur:
                _exec(cur, """
                    INSERT INTO global_config (key, config, updated_at)
                    VALUES ('global', %s, %s)
                    ON CONFLICT (key) DO UPDATE SET
                        config = EXCLUDED.config, updated_at = EXCLUDED.updated_at
                """, (J(global_cfg), global_cfg.get("updated_at","")), label="global_config")
            conn.commit()

    except Exception as exc:
        conn.rollback()
        conn.close()
        sys.exit(f"\nFATAL ERROR during migration: {exc}")

    conn.close()

    print("\n" + "=" * 55)
    if errors:
        print(f"Migration complete with {errors} skipped row(s) — see warnings above.")
    else:
        print("Migration complete — 0 errors.")
    print("=" * 55)
    print("\nNext steps:")
    print("  1. Update backend/.env:")
    print("       STORAGE_BACKEND=postgres")
    print("       DATABASE_URL=<your-url>")
    print("  2. pm2 restart eol-backend --update-env")
    print("  3. curl http://127.0.0.1:3001/health")
    print("  4. curl http://127.0.0.1:3001/eol/general/summary")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate FileBackend JSON files to PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data-dir",     default="/home/ubuntu/eol-data",
                        help="Path to EOL_DATA_DIR containing JSON files (default: /home/ubuntu/eol-data)")
    parser.add_argument("--database-url", default="",
                        help="PostgreSQL URL (default: reads DATABASE_URL env var)")
    parser.add_argument("--dry-run",      action="store_true",
                        help="Show migration counts but do not write anything")
    args = parser.parse_args()

    url = args.database_url or os.environ.get("DATABASE_URL", "")
    migrate(args.data_dir, url, args.dry_run)


if __name__ == "__main__":
    main()
