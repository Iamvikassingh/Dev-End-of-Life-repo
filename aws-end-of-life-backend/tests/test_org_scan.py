import hashlib
import importlib
import json
import os
import secrets
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_backend(tmp_path, enabled=False, async_mode="sync"):
    for key in ("STORAGE_BACKEND", "EOL_DATA_DIR", "ENABLE_ORG_SCAN", "ORG_SCAN_ASYNC_MODE"):
        os.environ.pop(key, None)
    os.environ["STORAGE_BACKEND"] = "file"
    os.environ["EOL_DATA_DIR"] = str(tmp_path)
    os.environ["ENABLE_ORG_SCAN"] = "true" if enabled else "false"
    os.environ["ORG_SCAN_ASYNC_MODE"] = async_mode
    import storage, api_handler
    importlib.reload(storage)
    importlib.reload(api_handler)
    return storage.FileBackend(), api_handler


def _body(result):
    return json.loads(result["body"])


def _ws_headers(token):
    return {"x-workspace-token": token}


def _api_headers(raw_token):
    return {"x-api-token": raw_token}


def _seed_workspace(st, ws_id, raw_token, name="Acme"):
    st.save_workspace({
        "id": ws_id,
        "name": name,
        "token_hash": hashlib.sha256(raw_token.encode()).hexdigest(),
    })


def _make_api_token(st, ws_id, role):
    raw = f"eolm_api_{role.lower()}_{secrets.token_hex(12)}"
    st.save_api_token({
        "id": f"tok_{role.lower()}_{secrets.token_hex(4)}",
        "workspaceId": ws_id,
        "name": f"{role} token",
        "role": role,
        "tokenHash": hashlib.sha256(raw.encode()).hexdigest(),
        "prefix": raw[:18] + "...",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "lastUsedAt": None,
        "expiresAt": None,
        "revokedAt": None,
        "createdBy": "test",
    })
    return raw


def _org_body(account="123456789012"):
    return {
        "name": "Production Organization",
        "managementAccountId": account,
        "roleArn": f"arn:aws:iam::{account}:role/EOLMonitorOrgReadOnly",
        "externalId": "eolm-org-test",
        "regions": ["us-east-1"],
    }


class TestOrgScanBackend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws_token = "workspace_token_org"

    def _setup(self, enabled=True, async_mode="sync"):
        st, api = _load_backend(self.tmp, enabled=enabled, async_mode=async_mode)
        _seed_workspace(st, "ws-a", self.ws_token, "Alpha")
        _seed_workspace(st, "ws-b", "workspace_token_beta", "Beta")
        return st, api

    def test_org_routes_return_feature_disabled_when_flag_false(self):
        st, api = self._setup(enabled=False)
        result = api.handle_ws_org_status("ws-a", _ws_headers(self.ws_token))
        self.assertEqual(result["statusCode"], 403)
        self.assertEqual(_body(result)["error"]["code"], "FEATURE_DISABLED")

    def test_enabled_status_route_works(self):
        st, api = self._setup(enabled=True)
        result = api.handle_ws_org_status("ws-a", _ws_headers(self.ws_token))
        self.assertEqual(result["statusCode"], 200)
        self.assertTrue(_body(result)["enabled"])

    def test_viewer_can_read_org_summary(self):
        st, api = self._setup(enabled=True)
        viewer = _make_api_token(st, "ws-a", "VIEWER")
        result = api.handle_ws_org_summary("ws-a", _api_headers(viewer))
        self.assertEqual(result["statusCode"], 200)
        self.assertIn("summary", _body(result))

    def test_viewer_cannot_configure_org_connection(self):
        st, api = self._setup(enabled=True)
        viewer = _make_api_token(st, "ws-a", "VIEWER")
        result = api.handle_ws_org_connection_create("ws-a", _org_body(), _api_headers(viewer))
        # INSUFFICIENT_ROLE returns 403 (auth succeeded, role denied) — correct HTTP semantics
        self.assertEqual(result["statusCode"], 403)
        self.assertEqual(_body(result)["error"]["code"], "INSUFFICIENT_ROLE")

    def test_validate_role_rejects_account_mismatch(self):
        st, api = self._setup(enabled=True)
        body = _org_body("123456789012")
        body["roleArn"] = "arn:aws:iam::210987654321:role/EOLMonitorOrgReadOnly"
        result = api.handle_ws_org_validate_role("ws-a", body, _ws_headers(self.ws_token))
        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(_body(result)["error"]["code"], "ROLE_ACCOUNT_MISMATCH")

    def test_admin_can_configure_and_delete_org_connection(self):
        st, api = self._setup(enabled=True)
        with patch.object(api, "_sts_validate_role", return_value=(True, "", "")):
            created = api.handle_ws_org_connection_create("ws-a", _org_body(), _ws_headers(self.ws_token))
        self.assertEqual(created["statusCode"], 201)
        conn_id = _body(created)["connection"]["id"]
        listed = api.handle_ws_org_connections_list("ws-a", _ws_headers(self.ws_token))
        self.assertEqual(_body(listed)["count"], 1)
        deleted = api.handle_ws_org_connection_delete("ws-a", conn_id, _ws_headers(self.ws_token))
        self.assertEqual(deleted["statusCode"], 200)

    def test_discover_handles_access_denied_safely(self):
        st, api = self._setup(enabled=True)
        conn = {**_org_body(), "id": "org_conn_a", "workspaceId": "ws-a", "status": "CONNECTED"}
        st.save_org_connection(conn)
        with patch.object(api, "_assume_role_client", side_effect=Exception("AccessDeniedException: denied")):
            result = api.handle_ws_org_discover("ws-a", "org_conn_a", _ws_headers(self.ws_token))
        self.assertEqual(result["statusCode"], 403)
        body = _body(result)
        self.assertEqual(body["error"]["code"], "ORG_DISCOVERY_ACCESS_DENIED")
        self.assertNotIn("AccessDeniedException", body["error"]["message"])

    def test_editor_can_run_org_scan_with_partial_member_assume_failure(self):
        st, api = self._setup(enabled=True)
        editor = _make_api_token(st, "ws-a", "EDITOR")
        conn = {**_org_body(), "id": "org_conn_a", "workspaceId": "ws-a", "status": "CONNECTED"}
        st.save_org_connection(conn)
        st.save_org_account({
            "id": "org_acct_ok",
            "workspaceId": "ws-a",
            "orgConnectionId": "org_conn_a",
            "awsAccountId": "111111111111",
            "name": "ok",
            "status": "ACTIVE",
        })
        st.save_org_account({
            "id": "org_acct_bad",
            "workspaceId": "ws-a",
            "orgConnectionId": "org_conn_a",
            "awsAccountId": "222222222222",
            "name": "bad",
            "status": "ACTIVE",
        })
        def fake_assume(role_arn, external_id, account_id):
            if account_id == "111111111111":
                return MagicMock()
            raise Exception("AccessDeniedException: unable to assume member scan role")
        with patch.object(api, "_assume_role_session", side_effect=fake_assume), \
             patch("eol_collector.run_all_collectors", return_value=[]):
            result = api.handle_ws_org_scan_create("ws-a", "org_conn_a", _api_headers(editor))
        self.assertEqual(result["statusCode"], 202)
        body = _body(result)
        self.assertEqual(body["status"], "RUNNING")
        final_run = st.get_org_scan_run("ws-a", body["orgScanId"])
        self.assertEqual(final_run["status"], "PARTIAL_SUCCESS")
        self.assertEqual(final_run["accountsScanned"], 1)
        self.assertEqual(final_run["accountsFailed"], 1)

    def test_org_scan_create_returns_202_running_when_dispatch_is_mocked(self):
        st, api = self._setup(enabled=True, async_mode="thread")
        editor = _make_api_token(st, "ws-a", "EDITOR")
        st.save_org_connection({**_org_body(), "id": "org_conn_a", "workspaceId": "ws-a", "status": "CONNECTED"})
        st.save_org_account({
            "id": "org_acct_1", "workspaceId": "ws-a", "orgConnectionId": "org_conn_a",
            "awsAccountId": "111111111111", "name": "one", "status": "ACTIVE",
        })
        with patch.object(api, "dispatch_org_scan_worker") as dispatch:
            result = api.handle_ws_org_scan_create("ws-a", "org_conn_a", _api_headers(editor))
        self.assertEqual(result["statusCode"], 202)
        body = _body(result)
        self.assertEqual(body["status"], "RUNNING")
        self.assertEqual(body["run"]["status"], "RUNNING")
        self.assertEqual(body["run"]["accountsScanned"], 0)
        dispatch.assert_called_once_with("ws-a", "org_conn_a", body["orgScanId"])
        accounts = st.get_org_accounts("ws-a", "org_conn_a")
        self.assertEqual(accounts[0]["lastScanStatus"], "RUNNING")
        self.assertEqual(accounts[0]["lastScanId"], body["orgScanId"])

    def test_duplicate_org_scan_while_running_returns_409(self):
        st, api = self._setup(enabled=True, async_mode="thread")
        editor = _make_api_token(st, "ws-a", "EDITOR")
        st.save_org_connection({**_org_body(), "id": "org_conn_a", "workspaceId": "ws-a", "status": "CONNECTED"})
        st.save_org_scan_run({
            "id": "org_scan_running", "workspaceId": "ws-a", "orgConnectionId": "org_conn_a",
            "status": "RUNNING", "startedAt": datetime.now(timezone.utc).isoformat(),
        })
        result = api.handle_ws_org_scan_create("ws-a", "org_conn_a", _api_headers(editor))
        self.assertEqual(result["statusCode"], 409)
        self.assertEqual(_body(result)["error"]["code"], "ORG_SCAN_IN_PROGRESS")

    def test_org_scan_get_shows_running_account_statuses_before_completion(self):
        st, api = self._setup(enabled=True, async_mode="thread")
        editor = _make_api_token(st, "ws-a", "EDITOR")
        st.save_org_connection({**_org_body(), "id": "org_conn_a", "workspaceId": "ws-a", "status": "CONNECTED"})
        st.save_org_account({
            "id": "org_acct_1", "workspaceId": "ws-a", "orgConnectionId": "org_conn_a",
            "awsAccountId": "111111111111", "name": "one", "status": "ACTIVE",
        })
        with patch.object(api, "dispatch_org_scan_worker"):
            created = api.handle_ws_org_scan_create("ws-a", "org_conn_a", _api_headers(editor))
        scan_id = _body(created)["orgScanId"]
        result = api.handle_ws_org_scan_get("ws-a", scan_id, _ws_headers(self.ws_token))
        body = _body(result)
        self.assertEqual(body["run"]["status"], "RUNNING")
        self.assertEqual(body["accounts"][0]["lastScanStatus"], "RUNNING")

    def test_sync_mode_worker_success_updates_run_accounts_and_resources(self):
        st, api = self._setup(enabled=True, async_mode="sync")
        editor = _make_api_token(st, "ws-a", "EDITOR")
        st.save_org_connection({**_org_body(), "id": "org_conn_a", "workspaceId": "ws-a", "status": "CONNECTED"})
        st.save_org_account({
            "id": "org_acct_1", "workspaceId": "ws-a", "orgConnectionId": "org_conn_a",
            "awsAccountId": "111111111111", "name": "one", "status": "ACTIVE",
        })
        resources = [{
            "resource_id": "arn:aws:lambda:us-east-1:111111111111:function:f",
            "service_type": "Lambda",
            "eol_status": "SUPPORTED",
            "region": "us-east-1",
        }]
        with patch.object(api, "_assume_role_session", return_value=MagicMock()), \
             patch("eol_collector.run_all_collectors", return_value=resources):
            result = api.handle_ws_org_scan_create("ws-a", "org_conn_a", _api_headers(editor))
        self.assertEqual(result["statusCode"], 202)
        scan_id = _body(result)["orgScanId"]
        run = st.get_org_scan_run("ws-a", scan_id)
        self.assertEqual(run["status"], "SUCCESS")
        self.assertEqual(run["accountsScanned"], 1)
        account = st.get_org_accounts("ws-a", "org_conn_a")[0]
        self.assertEqual(account["lastScanStatus"], "SUCCESS")
        saved = st.get_resources({"workspace_id": "ws-a"})
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["orgScanId"], scan_id)

    def test_cleanup_stale_org_scans_marks_running_failed(self):
        st, api = self._setup(enabled=True)
        old_started = "2000-01-01T00:00:00+00:00"
        st.save_org_scan_run({
            "id": "org_scan_stale", "workspaceId": "ws-a", "orgConnectionId": "org_conn_a",
            "status": "RUNNING", "startedAt": old_started,
        })
        changed = st.cleanup_stale_org_scans("ws-a", timeout_minutes=30)
        self.assertEqual(changed, 1)
        run = st.get_org_scan_run("ws-a", "org_scan_stale")
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["errorCode"], "STALE_ORG_SCAN_TIMEOUT")

    def test_internal_lambda_worker_event_routes_to_worker(self):
        st, api = self._setup(enabled=True)
        with patch.object(api, "run_org_scan_worker", return_value={"status": "SUCCESS"}) as worker:
            result = api.lambda_handler({
                "type": "ORG_SCAN_WORKER",
                "workspaceId": "ws-a",
                "orgConnectionId": "org_conn_a",
                "orgScanId": "org_scan_123",
            }, None)
        self.assertEqual(result["statusCode"], 200)
        worker.assert_called_once_with("ws-a", "org_conn_a", "org_scan_123")

    def test_workspace_b_cannot_access_workspace_a_connection(self):
        st, api = self._setup(enabled=True)
        st.save_org_connection({**_org_body(), "id": "org_conn_a", "workspaceId": "ws-a", "status": "CONNECTED"})
        result = api.handle_ws_org_connection_get("ws-b", "org_conn_a", _ws_headers("workspace_token_beta"))
        self.assertEqual(result["statusCode"], 404)

    # ── handle_ws_org_summary ─────────────────────────────────────────────────

    def test_org_summary_empty_workspace_returns_safe_defaults(self):
        st, api = self._setup(enabled=True)
        result = api.handle_ws_org_summary("ws-a", _ws_headers(self.ws_token))
        self.assertEqual(result["statusCode"], 200)
        body = _body(result)
        self.assertEqual(body["accountsTotal"], 0)
        self.assertEqual(body["summary"]["eol"], 0)
        self.assertIsNone(body["latestRun"])
        self.assertEqual(body["riskByOu"], [])

    def test_org_summary_returns_connections(self):
        st, api = self._setup(enabled=True)
        with patch.object(api, "_sts_validate_role", return_value=(True, "", "")):
            api.handle_ws_org_connection_create("ws-a", _org_body(), _ws_headers(self.ws_token))
        result = api.handle_ws_org_summary("ws-a", _ws_headers(self.ws_token))
        self.assertEqual(len(_body(result)["connections"]), 1)

    def test_org_summary_top_risky_accounts_populated(self):
        st, api = self._setup(enabled=True)
        st.save_org_connection({**_org_body(), "id": "conn_1", "workspaceId": "ws-a", "status": "CONNECTED"})
        st.save_org_account({
            "id": "acct_risky", "workspaceId": "ws-a", "orgConnectionId": "conn_1",
            "awsAccountId": "111111111111", "name": "Risky", "status": "ACTIVE",
            "lastScanSummary": {"EOL": 3, "EXPIRING_SOON": 1, "total": 4},
        })
        result = api.handle_ws_org_summary("ws-a", _ws_headers(self.ws_token))
        body = _body(result)
        self.assertEqual(len(body["topRiskyAccounts"]), 1)
        self.assertEqual(body["topRiskyAccounts"][0]["summary"]["EOL"], 3)

    def test_org_summary_risk_by_ou_aggregates_eol_and_expiring(self):
        st, api = self._setup(enabled=True)
        st.save_org_connection({**_org_body(), "id": "conn_1", "workspaceId": "ws-a", "status": "CONNECTED"})
        for i, (eol, exp) in enumerate([(2, 1), (3, 0)]):
            st.save_org_account({
                "id": f"acct_{i}", "workspaceId": "ws-a", "orgConnectionId": "conn_1",
                "awsAccountId": f"1111111111{i:02d}", "name": f"acct{i}",
                "status": "ACTIVE", "ouPath": "/Root/Prod",
                "lastScanSummary": {"EOL": eol, "EXPIRING_SOON": exp, "total": eol + exp},
            })
        result = api.handle_ws_org_summary("ws-a", _ws_headers(self.ws_token))
        body = _body(result)
        by_ou = {r["ouPath"]: r for r in body["riskByOu"]}
        self.assertIn("/Root/Prod", by_ou)
        self.assertEqual(by_ou["/Root/Prod"]["accounts"], 2)
        self.assertEqual(by_ou["/Root/Prod"]["eol"], 5)
        self.assertEqual(by_ou["/Root/Prod"]["expiringSoon"], 1)

    def test_org_summary_returns_latest_run(self):
        st, api = self._setup(enabled=True)
        st.save_org_connection({**_org_body(), "id": "conn_1", "workspaceId": "ws-a", "status": "CONNECTED"})
        for i in range(3):
            st.save_org_account({
                "id": f"acct_s_{i}", "workspaceId": "ws-a", "orgConnectionId": "conn_1",
                "awsAccountId": f"00000000000{i}", "name": f"acct{i}",
                "status": "ACTIVE", "lastScanStatus": "SUCCESS",
            })
        run = {
            "id": "org_scan_abc", "workspaceId": "ws-a", "orgConnectionId": "conn_1",
            "status": "SUCCESS", "accountsScanned": 3, "accountsFailed": 0,
            "summary": {"eol": 1, "expiringSoon": 0, "totalResources": 10},
        }
        st.save_org_scan_run(run)
        result = api.handle_ws_org_summary("ws-a", _ws_headers(self.ws_token))
        body = _body(result)
        self.assertIsNotNone(body["latestRun"])
        self.assertEqual(body["latestRun"]["id"], "org_scan_abc")
        self.assertEqual(body["accountsScanned"], 3)

    # ── handle_ws_org_scan_get ────────────────────────────────────────────────

    def test_org_scan_get_happy_path(self):
        st, api = self._setup(enabled=True)
        st.save_org_scan_run({
            "id": "org_scan_xyz", "workspaceId": "ws-a", "orgConnectionId": "conn_1",
            "status": "SUCCESS", "accountsScanned": 2, "accountsFailed": 0,
        })
        result = api.handle_ws_org_scan_get("ws-a", "org_scan_xyz", _ws_headers(self.ws_token))
        self.assertEqual(result["statusCode"], 200)
        body = _body(result)
        self.assertEqual(body["run"]["id"], "org_scan_xyz")
        self.assertIn("accounts", body)

    def test_org_scan_get_missing_returns_404(self):
        st, api = self._setup(enabled=True)
        result = api.handle_ws_org_scan_get("ws-a", "nonexistent", _ws_headers(self.ws_token))
        self.assertEqual(result["statusCode"], 404)
        self.assertEqual(_body(result)["error"]["code"], "ORG_SCAN_NOT_FOUND")

    def test_org_scan_get_workspace_isolation(self):
        st, api = self._setup(enabled=True)
        st.save_org_scan_run({
            "id": "org_scan_ws_a", "workspaceId": "ws-a", "orgConnectionId": "conn_1",
            "status": "SUCCESS",
        })
        result = api.handle_ws_org_scan_get("ws-b", "org_scan_ws_a", _ws_headers("workspace_token_beta"))
        self.assertEqual(result["statusCode"], 404)

    # ── handle_ws_org_connection_scans ────────────────────────────────────────

    def test_org_connection_scans_viewer_can_list_runs(self):
        st, api = self._setup(enabled=True)
        viewer = _make_api_token(st, "ws-a", "VIEWER")
        st.save_org_connection({**_org_body(), "id": "conn_1", "workspaceId": "ws-a", "status": "CONNECTED"})
        st.save_org_scan_run({"id": "run_1", "workspaceId": "ws-a", "orgConnectionId": "conn_1", "status": "SUCCESS"})
        result = api.handle_ws_org_connection_scans("ws-a", "conn_1", _api_headers(viewer))
        self.assertEqual(result["statusCode"], 200)
        body = _body(result)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["runs"][0]["id"], "run_1")

    def test_org_connection_scans_filters_by_connection(self):
        st, api = self._setup(enabled=True)
        st.save_org_connection({**_org_body(), "id": "conn_1", "workspaceId": "ws-a", "status": "CONNECTED"})
        st.save_org_scan_run({"id": "run_a", "workspaceId": "ws-a", "orgConnectionId": "conn_1", "status": "SUCCESS"})
        st.save_org_scan_run({"id": "run_b", "workspaceId": "ws-a", "orgConnectionId": "conn_2", "status": "SUCCESS"})
        result = api.handle_ws_org_connection_scans("ws-a", "conn_1", _ws_headers(self.ws_token))
        body = _body(result)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["runs"][0]["id"], "run_a")

    def test_org_connection_scans_missing_connection_returns_404(self):
        st, api = self._setup(enabled=True)
        result = api.handle_ws_org_connection_scans("ws-a", "conn_nope", _ws_headers(self.ws_token))
        self.assertEqual(result["statusCode"], 404)
        self.assertEqual(_body(result)["error"]["code"], "ORG_CONNECTION_NOT_FOUND")

    def test_org_connection_scans_feature_disabled_returns_403(self):
        st, api = self._setup(enabled=False)
        result = api.handle_ws_org_connection_scans("ws-a", "conn_1", _ws_headers(self.ws_token))
        self.assertEqual(result["statusCode"], 403)
        self.assertEqual(_body(result)["error"]["code"], "FEATURE_DISABLED")


if __name__ == "__main__":
    unittest.main()
