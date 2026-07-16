"""
Tests for notification delivery helpers and threshold filter correctness.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import notifications


# ── SMTP timeout ──────────────────────────────────────────────────────────────

class TestSmtpTimeout(unittest.TestCase):
    """SMTP connection must use timeout=15 to avoid hanging on network partitions."""

    def test_smtp_called_with_timeout(self):
        with patch.object(notifications, "SMTP_HOST", "smtp.example.com"), \
             patch.object(notifications, "SMTP_PORT", 587), \
             patch.object(notifications, "SMTP_USERNAME", "user@example.com"), \
             patch.object(notifications, "SMTP_PASSWORD", "secret"), \
             patch.object(notifications, "SMTP_FROM", "from@example.com"), \
             patch("smtplib.SMTP") as mock_smtp:

            mock_server = MagicMock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

            notifications._send_smtp(
                ["to@example.com"], "Subject", "<p>html</p>", "text"
            )

            mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=15)

    def test_smtp_not_called_when_unconfigured(self):
        with patch.object(notifications, "SMTP_HOST", ""), \
             patch.object(notifications, "SMTP_USERNAME", ""), \
             patch.object(notifications, "SMTP_PASSWORD", ""), \
             patch("smtplib.SMTP") as mock_smtp:

            result = notifications._send_smtp(
                ["to@example.com"], "Subject", "<p>html</p>", "text"
            )

            mock_smtp.assert_not_called()
            self.assertFalse(result["success"])


# ── EXTENDED_SUPPORT threshold filter ─────────────────────────────────────────

def _make_alert(severity, status="ACTIVE"):
    return {"id": f"alert-{severity}", "severity": severity, "status": status}


def _run_email_trigger(alerts, stored_thresholds):
    """
    Call _trigger_scan_notifications with given active alerts and stored threshold settings.
    Returns the 'filtered' alerts list that was passed to build_email_scan_summary,
    or None if email was not sent (no filtered alerts).
    """
    import api_handler as api

    captured = {}

    def fake_build(ws_name, scan_id, acct_name, summary, filtered):
        captured["filtered"] = filtered
        return "subj", "<p>h</p>", "txt"

    storage = MagicMock()
    storage.get_notification_settings.return_value = {
        "email":      {"enabled": True, "sendImmediate": True, "recipients": ["r@t.com"]},
        "slack":      {"enabled": False},
        "thresholds": stored_thresholds,
    }
    storage.get_alerts.return_value = alerts

    with patch.object(api, "get_storage", return_value=storage), \
         patch("notifications.is_email_configured", return_value=True), \
         patch("notifications.send_email", return_value={"success": True}), \
         patch("notifications.build_email_scan_summary", side_effect=fake_build), \
         patch("notifications.make_delivery_log", return_value={"id": "log-1"}):

        api._trigger_scan_notifications(
            "ws-1", {"name": "WS"}, {"name": "Acct", "id": "a"},
            "scan-1", {"eol": 0, "expiringSoon": 0, "total": 0}, []
        )

    return captured.get("filtered")


class TestExtendedSupportThreshold(unittest.TestCase):

    def test_extended_support_included_when_flag_true(self):
        """LOW-severity alert is included in notification when sendExtendedSupport=True."""
        alerts = [
            _make_alert("HIGH"),
            _make_alert("LOW"),
        ]
        filtered = _run_email_trigger(alerts, {"sendExtendedSupport": True})
        self.assertIsNotNone(filtered, "Email should have been triggered")
        severities = {a["severity"] for a in filtered}
        self.assertIn("HIGH", severities)
        self.assertIn("LOW", severities)

    def test_extended_support_excluded_when_flag_false(self):
        """LOW-severity alert is not included when sendExtendedSupport=False (default)."""
        alerts = [
            _make_alert("HIGH"),
            _make_alert("LOW"),
        ]
        filtered = _run_email_trigger(alerts, {"sendExtendedSupport": False})
        self.assertIsNotNone(filtered, "Email should still be triggered by HIGH alert")
        severities = {a["severity"] for a in filtered}
        self.assertIn("HIGH", severities)
        self.assertNotIn("LOW", severities)

    def test_extended_support_excluded_by_default(self):
        """sendExtendedSupport defaults to False — LOW alerts silently dropped without opt-in."""
        alerts = [
            _make_alert("HIGH"),
            _make_alert("LOW"),
        ]
        # Pass empty stored thresholds; merged default must provide sendExtendedSupport=False
        filtered = _run_email_trigger(alerts, {})
        self.assertIsNotNone(filtered)
        severities = {a["severity"] for a in filtered}
        self.assertNotIn("LOW", severities)

    def test_only_low_alerts_does_not_trigger_email_when_flag_false(self):
        """If the only active alerts are LOW and sendExtendedSupport=False, no email is sent."""
        alerts = [_make_alert("LOW")]
        filtered = _run_email_trigger(alerts, {"sendExtendedSupport": False})
        # build_email_scan_summary should NOT have been called → filtered is None
        self.assertIsNone(filtered, "Email should not be sent when only LOW alerts and flag=False")

    def test_only_low_alerts_triggers_email_when_flag_true(self):
        """If the only active alerts are LOW and sendExtendedSupport=True, email is sent."""
        alerts = [_make_alert("LOW")]
        filtered = _run_email_trigger(alerts, {"sendExtendedSupport": True})
        self.assertIsNotNone(filtered, "Email should be sent when LOW alerts and flag=True")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["severity"], "LOW")

    def test_eol_and_expiring_soon_still_pass_by_default(self):
        """HIGH and MEDIUM alerts are sent by default regardless of extended support flag."""
        alerts = [_make_alert("HIGH"), _make_alert("MEDIUM")]
        filtered = _run_email_trigger(alerts, {})
        self.assertIsNotNone(filtered)
        severities = {a["severity"] for a in filtered}
        self.assertIn("HIGH", severities)
        self.assertIn("MEDIUM", severities)

    def test_inactive_alerts_excluded_regardless_of_threshold(self):
        """Only ACTIVE alerts are eligible — RESOLVED/SUPPRESSED are always excluded."""
        alerts = [
            _make_alert("HIGH", status="RESOLVED"),
            _make_alert("LOW",  status="ACTIVE"),
        ]
        # Even with sendExtendedSupport=True, RESOLVED HIGH should not appear
        filtered = _run_email_trigger(alerts, {"sendExtendedSupport": True})
        self.assertIsNotNone(filtered)
        severities = {a["severity"] for a in filtered}
        self.assertNotIn("HIGH", severities)
        self.assertIn("LOW", severities)


if __name__ == "__main__":
    unittest.main()
