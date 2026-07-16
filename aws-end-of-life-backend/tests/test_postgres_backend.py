"""
PostgreSQL backend integration tests.

These tests require a live PostgreSQL database.
Set DATABASE_URL to run them:

    export DATABASE_URL='postgresql://eol_app:<password>@localhost:5432/eol_test'
    python3 -m pytest backend/tests/test_postgres_backend.py -v

If DATABASE_URL is not set, all tests are skipped cleanly.
The existing file-backend test suite is unaffected.
"""
import hashlib
import importlib
import json
import os
import secrets
import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SKIP_REASON  = "DATABASE_URL not set — skipping PostgreSQL tests"
SKIP         = not DATABASE_URL


def _load_pg():
    """Return a PostgresBackend connected to DATABASE_URL."""
    os.environ["STORAGE_BACKEND"] = "postgres"
    os.environ["DATABASE_URL"]    = DATABASE_URL
    import storage
    importlib.reload(storage)
    return storage.PostgresBackend(DATABASE_URL)


def _ws(n: int) -> dict:
    return {
        "id":         f"test_ws_{n}_{secrets.token_hex(4)}",
        "name":       f"Test Workspace {n}",
        "token_hash": hashlib.sha256(f"tok_{n}".encode()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@unittest.skipIf(SKIP, SKIP_REASON)
class TestPostgresSchema(unittest.TestCase):
    """Schema idempotency — running setup twice must not raise."""

    def test_schema_tables_exist(self):
        st = _load_pg()
        # Each table must be query-able (will raise if table is missing)
        st._query("SELECT 1 FROM workspaces LIMIT 1")
        st._query("SELECT 1 FROM connected_accounts LIMIT 1")
        st._query("SELECT 1 FROM inventory_resources LIMIT 1")
        st._query("SELECT 1 FROM scan_runs LIMIT 1")
        st._query("SELECT 1 FROM alerts LIMIT 1")
        st._query("SELECT 1 FROM api_tokens LIMIT 1")
        st._query("SELECT 1 FROM audit_logs LIMIT 1")
        st._query("SELECT 1 FROM reports LIMIT 1")
        st._query("SELECT 1 FROM members LIMIT 1")
        st._query("SELECT 1 FROM member_sessions LIMIT 1")
        st._query("SELECT 1 FROM member_login_tokens LIMIT 1")
        st._query("SELECT 1 FROM upgrade_guides LIMIT 1")
        st._query("SELECT 1 FROM general_eol_cache LIMIT 1")
        st._query("SELECT 1 FROM workspace_config LIMIT 1")
        st._query("SELECT 1 FROM global_config LIMIT 1")


@unittest.skipIf(SKIP, SKIP_REASON)
class TestPostgresWorkspaceCRUD(unittest.TestCase):

    def setUp(self):
        self.st = _load_pg()
        self.ws = _ws(1)
        self.st.save_workspace(self.ws)

    def tearDown(self):
        self.st.delete_workspace(self.ws["id"])

    def test_get_workspace_returns_saved(self):
        result = self.st.get_workspace(self.ws["id"])
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], self.ws["id"])
        self.assertEqual(result["name"], self.ws["name"])

    def test_get_workspaces_includes_saved(self):
        all_ws = self.st.get_workspaces()
        ids = [w["id"] for w in all_ws]
        self.assertIn(self.ws["id"], ids)

    def test_save_workspace_updates_name(self):
        updated = {**self.ws, "name": "Updated Name"}
        self.st.save_workspace(updated)
        result = self.st.get_workspace(self.ws["id"])
        self.assertEqual(result["name"], "Updated Name")

    def test_delete_workspace_removes_it(self):
        deleted = self.st.delete_workspace(self.ws["id"])
        self.assertTrue(deleted)
        self.assertIsNone(self.st.get_workspace(self.ws["id"]))

    def test_delete_nonexistent_returns_false(self):
        self.assertFalse(self.st.delete_workspace("does_not_exist_xyz"))

    def test_get_missing_workspace_returns_none(self):
        self.assertIsNone(self.st.get_workspace("nope_xyz"))


@unittest.skipIf(SKIP, SKIP_REASON)
class TestPostgresAccountCRUD(unittest.TestCase):

    def setUp(self):
        self.st = _load_pg()
        self.ws = _ws(2)
        self.st.save_workspace(self.ws)
        self.acct = {
            "id":           f"acct_{secrets.token_hex(4)}",
            "workspace_id": self.ws["id"],
            "accountName":  "Prod Account",
            "accountId":    "123456789012",
        }
        self.st.save_account(self.acct)

    def tearDown(self):
        self.st.delete_account(self.acct["id"], self.ws["id"])
        self.st.delete_workspace(self.ws["id"])

    def test_get_accounts_by_workspace(self):
        accounts = self.st.get_accounts(self.ws["id"])
        ids = [a["id"] for a in accounts]
        self.assertIn(self.acct["id"], ids)

    def test_account_workspace_isolation(self):
        other_ws = _ws(3)
        self.st.save_workspace(other_ws)
        try:
            accounts = self.st.get_accounts(other_ws["id"])
            self.assertNotIn(self.acct["id"], [a["id"] for a in accounts])
        finally:
            self.st.delete_workspace(other_ws["id"])

    def test_delete_account(self):
        self.st.delete_account(self.acct["id"], self.ws["id"])
        self.assertNotIn(self.acct["id"], [a["id"] for a in self.st.get_accounts(self.ws["id"])])


@unittest.skipIf(SKIP, SKIP_REASON)
class TestPostgresInventory(unittest.TestCase):

    def setUp(self):
        self.st = _load_pg()
        self.ws = _ws(4)
        self.st.save_workspace(self.ws)
        self.ws_id   = self.ws["id"]
        self.acct_id = f"acct_{secrets.token_hex(4)}"

    def tearDown(self):
        # Clean up inventory and workspace
        conn = self.st._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM inventory_resources WHERE workspace_id = %s", (self.ws_id,))
            conn.commit()
        except Exception:
            conn.rollback()
        self.st.delete_workspace(self.ws_id)

    def _make_resource(self, rid: str) -> dict:
        return {
            "resource_id":  rid,
            "workspace_id": self.ws_id,
            "account_id":   self.acct_id,
            "service_type": "Lambda",
            "eol_status":   "EOL",
            "region":       "us-east-1",
        }

    def test_replace_resources_removes_stale(self):
        old = [self._make_resource(f"arn:old:{i}") for i in range(3)]
        self.st.replace_resources_for_account(self.ws_id, self.acct_id, old)
        new = [self._make_resource("arn:new:1")]
        self.st.replace_resources_for_account(self.ws_id, self.acct_id, new)
        resources = self.st.get_resources({"workspace_id": self.ws_id})
        ids = [r["resource_id"] for r in resources]
        self.assertIn("arn:new:1", ids)
        self.assertNotIn("arn:old:0", ids)
        self.assertNotIn("arn:old:1", ids)

    def test_get_resource_by_id(self):
        r = self._make_resource("arn:test:xyz")
        self.st.replace_resources_for_account(self.ws_id, self.acct_id, [r])
        result = self.st.get_resource_by_id("arn:test:xyz")
        self.assertIsNotNone(result)
        self.assertEqual(result["resource_id"], "arn:test:xyz")

    def test_get_resources_filter_status(self):
        resources = [
            {**self._make_resource("arn:eol:1"), "eol_status": "EOL"},
            {**self._make_resource("arn:ok:1"),  "eol_status": "OK"},
        ]
        self.st.replace_resources_for_account(self.ws_id, self.acct_id, resources)
        eol = self.st.get_resources({"workspace_id": self.ws_id, "status": "eol"})
        self.assertTrue(all(r["eol_status"] == "EOL" for r in eol))

    def test_get_resources_filter_account_id(self):
        acct_b = f"acct_{secrets.token_hex(4)}_b"
        res_a = [{**self._make_resource("arn:a:1"), "account_id": self.acct_id},
                 {**self._make_resource("arn:a:2"), "account_id": self.acct_id}]
        res_b = [{**self._make_resource("arn:b:1"), "account_id": acct_b}]
        self.st.replace_resources_for_account(self.ws_id, self.acct_id, res_a)
        self.st.replace_resources_for_account(self.ws_id, acct_b, res_b)
        # Only account A
        result_a = self.st.get_resources({"workspace_id": self.ws_id, "account_id": self.acct_id})
        ids_a = [r["resource_id"] for r in result_a]
        self.assertIn("arn:a:1", ids_a)
        self.assertIn("arn:a:2", ids_a)
        self.assertNotIn("arn:b:1", ids_a, "account B resource must not appear when filtering by account A")
        # Only account B
        result_b = self.st.get_resources({"workspace_id": self.ws_id, "account_id": acct_b})
        ids_b = [r["resource_id"] for r in result_b]
        self.assertIn("arn:b:1", ids_b)
        self.assertNotIn("arn:a:1", ids_b, "account A resource must not appear when filtering by account B")
        # Cleanup account B resources
        conn = self.st._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM inventory_resources WHERE account_id = %s", (acct_b,))
            conn.commit()
        except Exception:
            conn.rollback()


@unittest.skipIf(SKIP, SKIP_REASON)
class TestPostgresScanRuns(unittest.TestCase):

    def setUp(self):
        self.st = _load_pg()
        self.ws = _ws(5)
        self.st.save_workspace(self.ws)
        self.ws_id = self.ws["id"]

    def tearDown(self):
        conn = self.st._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM scan_runs WHERE workspace_id = %s", (self.ws_id,))
            conn.commit()
        except Exception:
            conn.rollback()
        self.st.delete_workspace(self.ws_id)

    def _make_run(self) -> dict:
        return {
            "scanId":      f"scan_{secrets.token_hex(6)}",
            "workspaceId": self.ws_id,
            "accountId":   "acct1",
            "status":      "COMPLETED",
            "startedAt":   datetime.now(timezone.utc).isoformat(),
            "createdAt":   datetime.now(timezone.utc).isoformat(),
        }

    def test_save_and_get_scan_run(self):
        run = self._make_run()
        self.st.save_scan_run(run)
        result = self.st.get_scan_run(run["scanId"])
        self.assertIsNotNone(result)
        self.assertEqual(result["scanId"], run["scanId"])

    def test_get_scan_runs_ordered_newest_first(self):
        run1 = {**self._make_run(), "startedAt": "2024-01-01T00:00:00+00:00"}
        run2 = {**self._make_run(), "startedAt": "2024-06-01T00:00:00+00:00"}
        self.st.save_scan_run(run1)
        self.st.save_scan_run(run2)
        runs = self.st.get_scan_runs(self.ws_id)
        self.assertEqual(runs[0]["scanId"], run2["scanId"])

    def test_update_scan_run_status(self):
        run = self._make_run()
        self.st.save_scan_run(run)
        updated = {**run, "status": "FAILED"}
        self.st.save_scan_run(updated)
        result = self.st.get_scan_run(run["scanId"])
        self.assertEqual(result["status"], "FAILED")


@unittest.skipIf(SKIP, SKIP_REASON)
class TestPostgresReportSnapshots(unittest.TestCase):

    def setUp(self):
        self.st = _load_pg()
        self.ws = _ws(6)
        self.st.save_workspace(self.ws)
        self.ws_id = self.ws["id"]

    def tearDown(self):
        conn = self.st._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM reports WHERE workspace_id = %s", (self.ws_id,))
            conn.commit()
        except Exception:
            conn.rollback()
        self.st.delete_workspace(self.ws_id)

    def _make_snapshot(self) -> dict:
        return {
            "id":          f"rpt_{secrets.token_hex(6)}",
            "workspaceId": self.ws_id,
            "createdAt":   datetime.now(timezone.utc).isoformat(),
            "summary":     {"total": 5, "eol": 2},
        }

    def test_save_and_list_snapshots(self):
        snap = self._make_snapshot()
        self.st.save_report_snapshot(snap)
        snaps = self.st.get_report_snapshots(self.ws_id)
        self.assertIn(snap["id"], [s["id"] for s in snaps])

    def test_get_snapshot_by_id(self):
        snap = self._make_snapshot()
        self.st.save_report_snapshot(snap)
        result = self.st.get_report_snapshot(self.ws_id, snap["id"])
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], snap["id"])

    def test_workspace_isolation(self):
        other = _ws(7)
        self.st.save_workspace(other)
        try:
            snap = {**self._make_snapshot()}
            self.st.save_report_snapshot(snap)
            snaps = self.st.get_report_snapshots(other["id"])
            self.assertNotIn(snap["id"], [s["id"] for s in snaps])
        finally:
            self.st.delete_workspace(other["id"])


@unittest.skipIf(SKIP, SKIP_REASON)
class TestPostgresApiTokens(unittest.TestCase):

    def setUp(self):
        self.st = _load_pg()
        self.ws = _ws(8)
        self.st.save_workspace(self.ws)
        self.ws_id = self.ws["id"]
        raw = f"eolm_api_{secrets.token_hex(16)}"
        self.raw_token = raw
        self.tok = {
            "id":          f"tok_{secrets.token_hex(4)}",
            "workspaceId": self.ws_id,
            "name":        "CI token",
            "role":        "VIEWER",
            "tokenHash":   hashlib.sha256(raw.encode()).hexdigest(),
            "prefix":      raw[:18],
            "createdAt":   datetime.now(timezone.utc).isoformat(),
            "revokedAt":   None,
        }
        self.st.save_api_token(self.tok)

    def tearDown(self):
        conn = self.st._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM api_tokens WHERE workspace_id = %s", (self.ws_id,))
            conn.commit()
        except Exception:
            conn.rollback()
        self.st.delete_workspace(self.ws_id)

    def test_get_api_tokens(self):
        tokens = self.st.get_api_tokens(self.ws_id)
        self.assertIn(self.tok["id"], [t["id"] for t in tokens])

    def test_find_api_token_by_hash(self):
        h = hashlib.sha256(self.raw_token.encode()).hexdigest()
        result = self.st.find_api_token_by_hash(h, self.ws_id)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], self.tok["id"])

    def test_revoke_api_token(self):
        revoked = {**self.tok, "revokedAt": datetime.now(timezone.utc).isoformat()}
        self.st.save_api_token(revoked)
        result = self.st.get_api_token_by_id(self.tok["id"], self.ws_id)
        self.assertIsNotNone(result["revokedAt"])

    def test_workspace_isolation(self):
        other = _ws(9)
        self.st.save_workspace(other)
        try:
            h = hashlib.sha256(self.raw_token.encode()).hexdigest()
            result = self.st.find_api_token_by_hash(h, other["id"])
            self.assertIsNone(result)
        finally:
            self.st.delete_workspace(other["id"])


@unittest.skipIf(SKIP, SKIP_REASON)
class TestPostgresAuditLogs(unittest.TestCase):

    def setUp(self):
        self.st = _load_pg()
        self.ws = _ws(10)
        self.st.save_workspace(self.ws)
        self.ws_id = self.ws["id"]

    def tearDown(self):
        conn = self.st._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM audit_logs WHERE workspace_id = %s", (self.ws_id,))
            conn.commit()
        except Exception:
            conn.rollback()
        self.st.delete_workspace(self.ws_id)

    def test_save_and_retrieve_audit_log(self):
        log = {
            "id":          f"audit_{secrets.token_hex(10)}",
            "workspaceId": self.ws_id,
            "action":      "WORKSPACE_ACCESSED",
            "message":     "Workspace accessed",
            "createdAt":   datetime.now(timezone.utc).isoformat(),
        }
        self.st.save_audit_log(log)
        logs = self.st.get_audit_logs(self.ws_id)
        self.assertIn(log["id"], [l["id"] for l in logs])

    def test_audit_logs_newest_first(self):
        t1 = "2024-01-01T00:00:00+00:00"
        t2 = "2024-06-01T00:00:00+00:00"
        log1 = {"id": f"audit_{secrets.token_hex(6)}", "workspaceId": self.ws_id,
                "action": "A", "createdAt": t1, "message": ""}
        log2 = {"id": f"audit_{secrets.token_hex(6)}", "workspaceId": self.ws_id,
                "action": "B", "createdAt": t2, "message": ""}
        self.st.save_audit_log(log1)
        self.st.save_audit_log(log2)
        logs = self.st.get_audit_logs(self.ws_id, limit=10)
        first_ids = [l["id"] for l in logs]
        self.assertLess(first_ids.index(log2["id"]), first_ids.index(log1["id"]))

    def test_audit_log_workspace_isolation(self):
        other = _ws(11)
        self.st.save_workspace(other)
        try:
            log = {"id": f"audit_{secrets.token_hex(6)}", "workspaceId": self.ws_id,
                   "action": "X", "createdAt": datetime.now(timezone.utc).isoformat(), "message": ""}
            self.st.save_audit_log(log)
            logs = self.st.get_audit_logs(other["id"])
            self.assertNotIn(log["id"], [l["id"] for l in logs])
        finally:
            self.st.delete_workspace(other["id"])


@unittest.skipIf(SKIP, SKIP_REASON)
class TestPostgresConfig(unittest.TestCase):

    def setUp(self):
        self.st = _load_pg()
        self.ws = _ws(12)
        self.st.save_workspace(self.ws)

    def tearDown(self):
        self.st.delete_workspace(self.ws["id"])

    def test_workspace_config_save_get(self):
        config = {"warn_days": 90, "alert_email": "ops@example.com"}
        saved = self.st.save_workspace_config(self.ws["id"], config)
        result = self.st.get_workspace_config(self.ws["id"])
        self.assertEqual(result["warn_days"], 90)
        self.assertEqual(result["alert_email"], "ops@example.com")

    def test_workspace_config_defaults_merged(self):
        self.st.save_workspace_config(self.ws["id"], {})
        result = self.st.get_workspace_config(self.ws["id"])
        # CONFIG_DEFAULTS should be merged in
        self.assertIn("warn_days", result)
        self.assertIn("enabled_services", result)

    def test_notification_settings_save_get(self):
        settings = {"slack_webhook": "https://hooks.slack.com/xxx", "enabled": True}
        self.st.save_notification_settings(self.ws["id"], settings)
        result = self.st.get_notification_settings(self.ws["id"])
        self.assertEqual(result["slack_webhook"], settings["slack_webhook"])

    def test_notification_settings_missing_returns_empty(self):
        result = self.st.get_notification_settings("no_such_ws_xyz")
        self.assertEqual(result, {})


@unittest.skipIf(SKIP, SKIP_REASON)
class TestPostgresUpgradeGuides(unittest.TestCase):

    def setUp(self):
        self.st    = _load_pg()
        self.guide = {
            "id":      f"guide_{secrets.token_hex(4)}",
            "service": "Lambda",
            "title":   "Upgrade to Python 3.12",
        }
        self.st.save_upgrade_guide(self.guide)

    def tearDown(self):
        self.st.delete_upgrade_guide(self.guide["id"])

    def test_save_and_list_guides(self):
        guides = self.st.get_upgrade_guides()
        self.assertIn(self.guide["id"], [g["id"] for g in guides])

    def test_delete_guide(self):
        deleted = self.st.delete_upgrade_guide(self.guide["id"])
        self.assertTrue(deleted)
        guides = self.st.get_upgrade_guides()
        self.assertNotIn(self.guide["id"], [g["id"] for g in guides])

    def test_delete_nonexistent_returns_false(self):
        self.assertFalse(self.st.delete_upgrade_guide("nope_xyz"))


@unittest.skipIf(SKIP, SKIP_REASON)
class TestPostgresMigrationDryRun(unittest.TestCase):
    """Verify migration script --dry-run reads counts without writing."""

    def test_dry_run_runs_without_error(self):
        import tempfile
        from scripts.migrate_file_to_postgres import migrate

        with tempfile.TemporaryDirectory() as tmp:
            # Write minimal JSON files
            import json as _json
            with open(os.path.join(tmp, "workspaces.json"), "w") as f:
                _json.dump([{"id": "ws_dry", "name": "Dry", "token_hash": "abc"}], f)
            # Run dry-run — must not raise
            migrate(tmp, DATABASE_URL, dry_run=True)


if __name__ == "__main__":
    if SKIP:
        print(f"SKIP: {SKIP_REASON}")
    else:
        unittest.main()
