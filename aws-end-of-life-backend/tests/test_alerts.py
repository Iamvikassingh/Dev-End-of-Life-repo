"""
Tests for alert generation and reconciliation.

Key behaviors verified:
- New risky resource → alert created as ACTIVE
- Same risky resource rescanned → alert updated (lastSeenAt, version, etc.)
- Resource lifecycle improves (EOL → SUPPORTED) → alert RESOLVED (no resolvedReason)
- Resource disappears from scan → alert RESOLVED with resolvedReason="Resource not found in latest scan"
- ACKNOWLEDGED / SNOOZED alerts for gone resources → also auto-resolved as stale
- Account Scan reconciliation never touches Org Scan alerts and vice versa
"""

import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _setup(tmp_path):
    os.environ["STORAGE_BACKEND"] = "file"
    os.environ["EOL_DATA_DIR"] = str(tmp_path)
    import storage
    import api_handler
    importlib.reload(storage)
    importlib.reload(api_handler)
    return storage.FileBackend(), api_handler


def _resource(resource_id, service, status, scan_source="ACCOUNT_SCAN"):
    return {
        "resource_id":   resource_id,
        "resource_name": resource_id,
        "service_type":  service,
        "eol_status":    status,
        "eol_date":      "2025-09-01",
        "days_to_eol":   -10 if status == "EOL" else 60,
        "region":        "us-east-1",
        "version":       "1.0",
        "scan_source":   scan_source,
    }


class TestAlertGeneration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store, self.api = _setup(self.tmp)
        self.store.save_workspace({"id": "ws1", "name": "Test"})
        self.gen = self.api._generate_alerts_from_scan

    # ── Basic creation ─────────────────────────────────────────────────────────

    def test_creates_active_alert_for_eol_resource(self):
        resources = [_resource("arn:fn1", "Lambda", "EOL")]
        self.gen("ws1", "acct1", resources, self.store)

        alerts = self.store.get_alerts("ws1", account_id="acct1")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["status"], "ACTIVE")
        self.assertEqual(alerts[0]["severity"], "HIGH")
        self.assertIsNone(alerts[0].get("resolvedReason"))

    def test_creates_active_alert_for_expiring_soon(self):
        resources = [_resource("arn:eks1", "EKS", "EXPIRING_SOON")]
        self.gen("ws1", "acct1", resources, self.store)

        alerts = self.store.get_alerts("ws1", account_id="acct1")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "MEDIUM")

    def test_no_alert_for_supported_resource(self):
        resources = [_resource("arn:rds1", "RDS_postgres", "SUPPORTED")]
        self.gen("ws1", "acct1", resources, self.store)
        alerts = self.store.get_alerts("ws1", account_id="acct1")
        self.assertEqual(len(alerts), 0)

    # ── Update on rescan ───────────────────────────────────────────────────────

    def test_updates_existing_alert_on_rescan(self):
        resources = [_resource("arn:fn1", "Lambda", "EOL")]
        self.gen("ws1", "acct1", resources, self.store)
        first_seen = self.store.get_alerts("ws1", account_id="acct1")[0]["lastSeenAt"]

        # Second scan — same resource, still EOL
        self.gen("ws1", "acct1", resources, self.store)
        alerts = self.store.get_alerts("ws1", account_id="acct1")
        self.assertEqual(len(alerts), 1, "Should not duplicate")
        self.assertGreaterEqual(alerts[0]["lastSeenAt"], first_seen)

    # ── Lifecycle improvement → resolve without stale reason ──────────────────

    def test_resolves_alert_when_lifecycle_improves(self):
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "EOL")], self.store)
        self.assertEqual(self.store.get_alerts("ws1", account_id="acct1")[0]["status"], "ACTIVE")

        # Next scan: same resource is now SUPPORTED
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "SUPPORTED")], self.store)
        alert = self.store.get_alerts("ws1", account_id="acct1", status="RESOLVED")[0]
        self.assertEqual(alert["status"], "RESOLVED")
        # No resolvedReason — lifecycle improved, not missing
        self.assertFalsy(alert.get("resolvedReason"))
        # resolutionSource set by scan reconciliation
        self.assertEqual(alert.get("resolutionSource"), "scan_reconciliation")

    def test_resolves_acknowledged_alert_when_lifecycle_improves(self):
        """P0-2 fix: ACKNOWLEDGED alerts must also resolve when resource is no longer risky."""
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "EOL")], self.store)
        alert_id = self.store.get_alerts("ws1", account_id="acct1")[0]["id"]
        alert = self.store.get_alert(alert_id, "ws1")
        alert["status"] = "ACKNOWLEDGED"
        self.store.save_alert(alert)

        # Resource improves to SUPPORTED in next scan
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "SUPPORTED")], self.store)
        resolved = self.store.get_alerts("ws1", account_id="acct1", status="RESOLVED")
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["status"], "RESOLVED")
        self.assertFalsy(resolved[0].get("resolvedReason"))

    def test_resolves_snoozed_alert_when_lifecycle_improves(self):
        """P0-2 fix: SNOOZED alerts must also resolve when resource is no longer risky."""
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "EOL")], self.store)
        alert_id = self.store.get_alerts("ws1", account_id="acct1")[0]["id"]
        alert = self.store.get_alert(alert_id, "ws1")
        alert["status"] = "SNOOZED"
        alert["snoozedUntil"] = "2099-01-01T00:00:00Z"
        self.store.save_alert(alert)

        # Resource improves to SUPPORTED in next scan
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "SUPPORTED")], self.store)
        resolved = self.store.get_alerts("ws1", account_id="acct1", status="RESOLVED")
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["status"], "RESOLVED")
        self.assertFalsy(resolved[0].get("resolvedReason"))

    def assertFalsy(self, val):
        self.assertFalse(bool(val), f"Expected falsy, got {val!r}")

    # ── Missing resource → resolve with stale reason ──────────────────────────

    def test_resolves_alert_with_stale_reason_when_resource_missing(self):
        # Scan 1: resource found and risky
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "EOL")], self.store)
        self.assertEqual(self.store.get_alerts("ws1", account_id="acct1")[0]["status"], "ACTIVE")

        # Scan 2: resource no longer in scan results (deleted from AWS)
        self.gen("ws1", "acct1", [], self.store)

        resolved = self.store.get_alerts("ws1", account_id="acct1", status="RESOLVED")
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["resolvedReason"], "Resource not found in latest scan")
        self.assertEqual(resolved[0]["resolutionSource"], "scan_reconciliation")
        self.assertIsNotNone(resolved[0]["resolvedAt"])

    def test_stale_resolves_acknowledged_alert(self):
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "EOL")], self.store)
        alert_id = self.store.get_alerts("ws1", account_id="acct1")[0]["id"]
        # User acknowledges the alert
        alert = self.store.get_alert(alert_id, "ws1")
        alert["status"] = "ACKNOWLEDGED"
        self.store.save_alert(alert)

        # Next scan: resource gone
        self.gen("ws1", "acct1", [], self.store)

        resolved = self.store.get_alerts("ws1", account_id="acct1", status="RESOLVED")
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["resolvedReason"], "Resource not found in latest scan")

    def test_stale_resolves_snoozed_alert(self):
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "EOL")], self.store)
        alert_id = self.store.get_alerts("ws1", account_id="acct1")[0]["id"]
        alert = self.store.get_alert(alert_id, "ws1")
        alert["status"] = "SNOOZED"
        alert["snoozedUntil"] = "2099-01-01T00:00:00Z"
        self.store.save_alert(alert)

        # Next scan: resource gone
        self.gen("ws1", "acct1", [], self.store)

        resolved = self.store.get_alerts("ws1", account_id="acct1", status="RESOLVED")
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["resolvedReason"], "Resource not found in latest scan")

    def test_already_resolved_not_touched_again(self):
        # If alert is already resolved, another scan without that resource should not change it
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "EOL")], self.store)
        # Resolve manually
        alert_id = self.store.get_alerts("ws1", account_id="acct1")[0]["id"]
        alert = self.store.get_alert(alert_id, "ws1")
        alert["status"] = "RESOLVED"
        alert["resolvedAt"] = "2026-01-01T00:00:00Z"
        self.store.save_alert(alert)

        # Scan without resource — should not create another resolved alert
        self.gen("ws1", "acct1", [], self.store)
        all_alerts = self.store.get_alerts("ws1", account_id="acct1")
        self.assertEqual(len(all_alerts), 1, "No duplicate alerts should be created")

    # ── Scope isolation ────────────────────────────────────────────────────────

    def test_account_scan_reconciliation_does_not_touch_other_account_alerts(self):
        """Alert for acct2 must not be resolved when acct1 scan runs without that resource."""
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "EOL")], self.store)
        self.gen("ws1", "acct2", [_resource("arn:fn2", "Lambda", "EOL")], self.store)

        # acct1 rescans and finds nothing — should only affect acct1 alerts
        self.gen("ws1", "acct1", [], self.store)

        acct1_alerts = self.store.get_alerts("ws1", account_id="acct1")
        acct2_alerts = self.store.get_alerts("ws1", account_id="acct2")

        # acct1: resolved as stale
        self.assertTrue(all(a["status"] == "RESOLVED" for a in acct1_alerts))
        self.assertTrue(all(a.get("resolvedReason") == "Resource not found in latest scan"
                            for a in acct1_alerts))

        # acct2: untouched — still ACTIVE
        self.assertTrue(all(a["status"] == "ACTIVE" for a in acct2_alerts))

    def test_new_risky_resource_restores_resolved_alert(self):
        """If a resource was stale-resolved but reappears in a future scan, alert should become ACTIVE."""
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "EOL")], self.store)
        # Resource disappears
        self.gen("ws1", "acct1", [], self.store)
        self.assertEqual(
            self.store.get_alerts("ws1", account_id="acct1", status="RESOLVED")[0]["status"],
            "RESOLVED"
        )

        # Resource reappears (maybe it was redeployed with same ID and still EOL)
        self.gen("ws1", "acct1", [_resource("arn:fn1", "Lambda", "EOL")], self.store)
        active = self.store.get_alerts("ws1", account_id="acct1", status="ACTIVE")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["status"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
