import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _load_reporting_backend(tmp_path):
    os.environ["STORAGE_BACKEND"] = "file"
    os.environ["EOL_DATA_DIR"] = str(tmp_path)
    import storage
    import api_handler
    importlib.reload(storage)
    importlib.reload(api_handler)
    return storage.FileBackend(), api_handler


def _seed(storage):
    storage.save_workspace({"id": "ws-a", "name": "Acme"})
    storage.save_workspace({"id": "ws-b", "name": "Other"})
    storage.save_account({"id": "conn-a", "workspace_id": "ws-a", "accountName": "Prod", "accountId": "111"})
    storage.save_account({"id": "conn-b", "workspace_id": "ws-b", "accountName": "Dev", "accountId": "222"})
    storage.replace_resources_for_account("ws-a", "conn-a", [
        {"workspace_id": "ws-a", "account_id": "conn-a", "scan_id": "scan-2", "resource_id": "arn:1", "resource_name": "old-fn", "service_type": "Lambda", "region": "us-east-1", "version": "nodejs18.x", "eol_status": "EOL", "eol_date": "2025-09-01", "days_to_eol": -10, "recommendation": "Upgrade runtime", "detection_source": "LAMBDA_RUNTIME", "confidence": "HIGH"},
        {"workspace_id": "ws-a", "account_id": "conn-a", "scan_id": "scan-2", "resource_id": "arn:2", "resource_name": "soon", "service_type": "EKS", "region": "us-east-1", "version": "1.33", "eol_status": "EXPIRING_SOON", "eol_date": "2026-07-29", "days_to_eol": 30},
        {"workspace_id": "ws-a", "account_id": "conn-a", "scan_id": "scan-2", "resource_id": "arn:3", "resource_name": "ok", "service_type": "EC2", "region": "us-east-2", "version": "Amazon Linux 2023", "eol_status": "SUPPORTED", "eol_date": "2028-03-15", "days_to_eol": 600},
    ])
    storage.replace_resources_for_account("ws-b", "conn-b", [
        {"workspace_id": "ws-b", "account_id": "conn-b", "scan_id": "scan-x", "resource_id": "arn:x", "resource_name": "other", "service_type": "Lambda", "eol_status": "EOL"},
    ])


def _ws_headers(workspace_token: str) -> dict:
    return {"x-workspace-token": workspace_token}


def _api_headers(raw_token: str, via: str = "header") -> dict:
    if via == "bearer":
        return {"authorization": f"Bearer {raw_token}"}
    return {"x-api-token": raw_token}


def _make_token_record(
    workspace_id: str,
    role: str = "VIEWER",
    raw: str | None = None,
    revoked: bool = False,
    expired: bool = False,
    token_id: str | None = None,
) -> tuple[str, dict]:
    raw = raw or f"eolm_api_{role.lower()}_{workspace_id}_test_secret_123"
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires_at = None
    if expired:
        expires_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    # Use explicit token_id to avoid ID collisions when multiple VIEWER tokens exist
    tid = token_id or f"tok_{role.lower()}_{workspace_id}"
    rec = {
        "id": tid,
        "workspaceId": workspace_id,
        "name": f"{role} token",
        "role": role,
        "tokenHash": token_hash,
        "prefix": raw[:18] + "...",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "lastUsedAt": None,
        "expiresAt": expires_at,
        "revokedAt": datetime.now(timezone.utc).isoformat() if revoked else None,
        "createdBy": "workspace",
    }
    return raw, rec


def _seed_ws_token(st, workspace_id: str, workspace_raw_token: str) -> None:
    ws = st.get_workspace(workspace_id)
    if ws:
        ws["token_hash"] = hashlib.sha256(workspace_raw_token.encode()).hexdigest()
        st.save_workspace(ws)


# ── Original report logic tests ────────────────────────────────────────────────

def test_report_summary_risk_score_and_workspace_isolation(tmp_path):
    storage, api = _load_reporting_backend(tmp_path)
    _seed(storage)

    report = api._build_report_summary("ws-a")

    assert report["summary"]["total"] == 3
    assert report["summary"]["eol"] == 1
    assert report["summary"]["expiringSoon"] == 1
    assert report["summary"]["supported"] == 1
    assert report["summary"]["riskScore"] == 14
    assert report["summary"]["riskLevel"] == "LOW"
    assert len(report["byAccount"]) == 1
    assert report["byAccount"][0]["accountName"] == "Prod"
    assert all(r["accountId"] == "conn-a" for r in report["topRisks"])


def test_report_snapshot_creation_stores_workspace(tmp_path):
    storage, api = _load_reporting_backend(tmp_path)
    _seed(storage)

    summary = api._build_report_summary("ws-a")
    snapshot = api._snapshot_from_summary("ws-a", summary, "MANUAL")
    storage.save_report_snapshot(snapshot)

    saved = storage.get_report_snapshot("ws-a", snapshot["id"])
    assert saved["workspaceId"] == "ws-a"
    assert saved["summary"]["total"] == 3
    assert storage.get_report_snapshot("ws-b", snapshot["id"]) is None


def test_report_csv_rows_match_inventory_count(tmp_path):
    storage, api = _load_reporting_backend(tmp_path)
    _seed(storage)

    csv_body, filename = api._report_csv("ws-a")

    assert filename.startswith("aws-eol-risk-report-")
    assert len(csv_body.strip().splitlines()) == 4
    assert "Workspace Name,Account Name,AWS Account ID,Source Type" in csv_body.splitlines()[0]
    assert "Lifecycle Message" in csv_body.splitlines()[0]
    assert "Upgrade Guide URL" in csv_body.splitlines()[0]
    assert "Upgrade runtime" in csv_body


def test_monthly_admin_endpoint_rejects_missing_token(tmp_path):
    storage, api = _load_reporting_backend(tmp_path)
    _seed(storage)

    result = api.handle_admin_monthly_reports({})

    assert result["statusCode"] == 401
    body = json.loads(result["body"])
    assert body["error"]["code"] == "ADMIN_TOKEN_INVALID"


# ── Phase 7.1b — API token access for report endpoints ────────────────────────

class TestApiTokenReportAccess(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.storage, self.api = _load_reporting_backend(self.tmp)
        _seed(self.storage)

        # VIEWER token for ws-a
        self.viewer_raw, viewer_rec = _make_token_record("ws-a", "VIEWER")
        self.storage.save_api_token(viewer_rec)

        # EDITOR token for ws-a
        self.editor_raw, editor_rec = _make_token_record("ws-a", "EDITOR")
        self.storage.save_api_token(editor_rec)

        # VIEWER token for ws-b (cross-workspace test)
        self.wsb_viewer_raw, wsb_viewer_rec = _make_token_record("ws-b", "VIEWER")
        self.storage.save_api_token(wsb_viewer_rec)

        # Revoked token for ws-a (distinct token_id to avoid ID collision with viewer)
        self.revoked_raw, revoked_rec = _make_token_record(
            "ws-a", "VIEWER", raw="eolm_api_revoked_token_secret_xyz",
            revoked=True, token_id="tok_revoked_ws-a",
        )
        self.storage.save_api_token(revoked_rec)

        # Expired token for ws-a (distinct token_id to avoid ID collision with viewer)
        self.expired_raw, expired_rec = _make_token_record(
            "ws-a", "VIEWER", raw="eolm_api_expired_token_secret_xyz",
            expired=True, token_id="tok_expired_ws-a",
        )
        self.storage.save_api_token(expired_rec)

        # Workspace token for ws-a
        self.ws_token_raw = "eolm_live_workspace_token_raw_secret"
        _seed_ws_token(self.storage, "ws-a", self.ws_token_raw)

    # 1. VIEWER API token can GET report summary
    def test_viewer_api_token_can_get_summary(self):
        result = self.api.handle_ws_reports_summary("ws-a", _api_headers(self.viewer_raw))
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertIn("summary", body)

    # 2. VIEWER API token can GET summary via Authorization: Bearer
    def test_viewer_api_token_bearer_can_get_summary(self):
        result = self.api.handle_ws_reports_summary("ws-a", _api_headers(self.viewer_raw, via="bearer"))
        self.assertEqual(result["statusCode"], 200)

    # 3. VIEWER API token can GET export CSV
    def test_viewer_api_token_can_get_csv(self):
        result = self.api.handle_ws_report_csv("ws-a", _api_headers(self.viewer_raw))
        self.assertEqual(result["statusCode"], 200)
        self.assertIn("text/csv", result["headers"]["Content-Type"])

    # 4. VIEWER API token can GET snapshots list
    def test_viewer_api_token_can_get_snapshots_list(self):
        result = self.api.handle_ws_report_snapshots_list("ws-a", _api_headers(self.viewer_raw))
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertIn("snapshots", body)

    # 5. VIEWER API token can GET single snapshot
    def test_viewer_api_token_can_get_single_snapshot(self):
        # First create a snapshot via editor token
        self.api.handle_ws_report_snapshot_create("ws-a", _api_headers(self.editor_raw))
        snapshots_result = self.api.handle_ws_report_snapshots_list("ws-a", _api_headers(self.viewer_raw))
        snapshots = json.loads(snapshots_result["body"])["snapshots"]
        self.assertTrue(len(snapshots) > 0, "Expected at least one snapshot")
        snap_id = snapshots[0]["id"]

        result = self.api.handle_ws_report_snapshot_get("ws-a", snap_id, _api_headers(self.viewer_raw))
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertIn("snapshot", body)

    # 6. VIEWER API token can GET audit logs
    def test_viewer_api_token_can_get_audit_logs(self):
        result = self.api.handle_ws_audit_logs("ws-a", _api_headers(self.viewer_raw), {})
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertIn("logs", body)

    # 7. VIEWER API token CANNOT POST (create) snapshot
    def test_viewer_api_token_cannot_create_snapshot(self):
        result = self.api.handle_ws_report_snapshot_create("ws-a", _api_headers(self.viewer_raw))
        # INSUFFICIENT_ROLE returns 403 (auth succeeded, role denied) — correct HTTP semantics
        self.assertEqual(result["statusCode"], 403)
        body = json.loads(result["body"])
        self.assertEqual(body["error"]["code"], "INSUFFICIENT_ROLE")

    # 8. EDITOR API token CAN POST snapshot
    def test_editor_api_token_can_create_snapshot(self):
        result = self.api.handle_ws_report_snapshot_create("ws-a", _api_headers(self.editor_raw))
        self.assertEqual(result["statusCode"], 201)
        body = json.loads(result["body"])
        self.assertIn("snapshot", body)

    # 9. EDITOR snapshot creation writes audit log
    def test_editor_snapshot_creates_audit_log(self):
        self.api.handle_ws_report_snapshot_create("ws-a", _api_headers(self.editor_raw))
        logs = self.storage.get_audit_logs("ws-a")
        snapshot_logs = [l for l in logs if l["action"] == "REPORT_SNAPSHOT_CREATED"]
        self.assertEqual(len(snapshot_logs), 1)
        log = snapshot_logs[0]
        self.assertEqual(log["actor"]["type"], "API_TOKEN")
        self.assertNotIn(self.editor_raw, str(log))
        self.assertNotIn(self.editor_raw, str(log.get("metadata", {})))

    # 10. CSV download via API token writes audit log, raw token not in log
    def test_csv_download_audit_log_no_raw_token(self):
        self.api.handle_ws_report_csv("ws-a", _api_headers(self.viewer_raw))
        logs = self.storage.get_audit_logs("ws-a")
        csv_logs = [l for l in logs if l["action"] == "REPORT_CSV_DOWNLOADED"]
        self.assertEqual(len(csv_logs), 1)
        log = csv_logs[0]
        self.assertEqual(log["actor"]["type"], "API_TOKEN")
        self.assertNotIn(self.viewer_raw, str(log))

    # 11. API token for ws-b cannot access ws-a reports
    def test_wsb_token_cannot_access_wsa_reports(self):
        result = self.api.handle_ws_reports_summary("ws-a", _api_headers(self.wsb_viewer_raw))
        self.assertEqual(result["statusCode"], 401)

    # 12. Revoked token is rejected
    def test_revoked_api_token_rejected(self):
        result = self.api.handle_ws_reports_summary("ws-a", _api_headers(self.revoked_raw))
        self.assertEqual(result["statusCode"], 401)
        body = json.loads(result["body"])
        self.assertEqual(body["error"]["code"], "API_TOKEN_REVOKED")

    # 13. Expired token is rejected
    def test_expired_api_token_rejected(self):
        result = self.api.handle_ws_reports_summary("ws-a", _api_headers(self.expired_raw))
        self.assertEqual(result["statusCode"], 401)
        body = json.loads(result["body"])
        self.assertEqual(body["error"]["code"], "API_TOKEN_EXPIRED")

    # 14. API token cannot access admin monthly reports endpoint
    def test_api_token_cannot_access_admin_endpoint(self):
        result = self.api.handle_admin_monthly_reports(_api_headers(self.editor_raw))
        self.assertEqual(result["statusCode"], 401)
        body = json.loads(result["body"])
        self.assertEqual(body["error"]["code"], "ADMIN_TOKEN_INVALID")

    # 15. Workspace token still works for all report endpoints
    def test_workspace_token_still_works_for_summary(self):
        result = self.api.handle_ws_reports_summary("ws-a", _ws_headers(self.ws_token_raw))
        self.assertEqual(result["statusCode"], 200)

    def test_workspace_token_still_works_for_csv(self):
        result = self.api.handle_ws_report_csv("ws-a", _ws_headers(self.ws_token_raw))
        self.assertEqual(result["statusCode"], 200)

    def test_workspace_token_still_works_for_snapshots_list(self):
        result = self.api.handle_ws_report_snapshots_list("ws-a", _ws_headers(self.ws_token_raw))
        self.assertEqual(result["statusCode"], 200)

    def test_workspace_token_still_works_for_snapshot_create(self):
        result = self.api.handle_ws_report_snapshot_create("ws-a", _ws_headers(self.ws_token_raw))
        self.assertEqual(result["statusCode"], 201)

    def test_workspace_token_still_works_for_audit_logs(self):
        result = self.api.handle_ws_audit_logs("ws-a", _ws_headers(self.ws_token_raw), {})
        self.assertEqual(result["statusCode"], 200)

    # 16. Workspace token snapshot creation does NOT write API_TOKEN audit event
    def test_workspace_token_snapshot_no_api_audit_event(self):
        self.api.handle_ws_report_snapshot_create("ws-a", _ws_headers(self.ws_token_raw))
        logs = self.storage.get_audit_logs("ws-a")
        api_token_logs = [l for l in logs if l.get("actor", {}).get("type") == "API_TOKEN"]
        self.assertEqual(len(api_token_logs), 0)


def teardown_module(module):
    os.environ.pop("STORAGE_BACKEND", None)
    os.environ.pop("EOL_DATA_DIR", None)
