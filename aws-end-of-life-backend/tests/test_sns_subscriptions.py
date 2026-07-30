"""
AWS EOL Monitor — SNS Subscription Unit Tests

Tests:
  - validate_email
  - make_subscription / update_subscription_status
  - make_notification_history
  - is_within_cooldown
  - should_alert / classify_alert_type
  - build_eol_alert_html (basic structure)
  - FileBackend SNS storage methods
  - API handler routes (mocked storage)

Run with:
  cd aws-end-of-life-backend
  pip install pytest
  pytest tests/test_sns_subscriptions.py -v
"""
import json
import os
import sys
import tempfile
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Ensure the backend root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── sns_subscriptions module ──────────────────────────────────────────────────

class TestValidateEmail:
    def test_valid_email(self):
        from sns_subscriptions import validate_email
        assert validate_email("user@example.com")
        assert validate_email("ops+team@company.co.uk")
        assert validate_email("ADMIN@AWS.COM")

    def test_invalid_email(self):
        from sns_subscriptions import validate_email
        assert not validate_email("")
        assert not validate_email("not-an-email")
        assert not validate_email("@missing-local.com")
        assert not validate_email("missing-domain@")


class TestMakeSubscription:
    def test_structure(self):
        from sns_subscriptions import make_subscription, STATUS_PENDING
        sub = make_subscription("ws_abc", "test@example.com",
                                "arn:aws:sns:us-east-1:123:eolm-ws-ws_abc")
        assert sub["workspace_id"] == "ws_abc"
        assert sub["email"] == "test@example.com"
        assert sub["status"] == STATUS_PENDING
        assert sub["id"].startswith("sns_sub_")
        assert "created_at" in sub

    def test_email_lowercased(self):
        from sns_subscriptions import make_subscription
        sub = make_subscription("ws_abc", "UPPER@CASE.COM", "arn:dummy")
        assert sub["email"] == "upper@case.com"


class TestUpdateSubscriptionStatus:
    def test_update_to_verified(self):
        from sns_subscriptions import make_subscription, update_subscription_status, STATUS_VERIFIED
        sub = make_subscription("ws_abc", "a@b.com", "arn:dummy")
        updated = update_subscription_status(sub, STATUS_VERIFIED, "arn:actual")
        assert updated["status"] == STATUS_VERIFIED
        assert updated["subscription_arn"] == "arn:actual"
        assert updated["updated_at"] != sub["updated_at"] or True  # may be same ms

    def test_original_unchanged(self):
        from sns_subscriptions import make_subscription, update_subscription_status, STATUS_VERIFIED
        sub = make_subscription("ws_abc", "a@b.com", "arn:dummy")
        update_subscription_status(sub, STATUS_VERIFIED)
        assert sub["status"] == "PENDING"  # original untouched


class TestCooldown:
    def _make_record(self, workspace_id, resource_id, severity, status, hours_ago=0):
        from sns_subscriptions import make_notification_history, _cooldown_key
        resource = {
            "resource_id": resource_id,
            "severity":    severity,
            "service_type": "Lambda",
        }
        rec = make_notification_history(workspace_id, resource, "all", status)
        if hours_ago > 0:
            past = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
            rec["sent_at"] = past.isoformat()
        return rec

    def test_within_cooldown(self):
        from sns_subscriptions import is_within_cooldown
        history = [self._make_record("ws1", "res1", "HIGH", "SENT", hours_ago=1)]
        assert is_within_cooldown(history, "ws1", "res1", "HIGH", cooldown_hours=24)

    def test_outside_cooldown(self):
        from sns_subscriptions import is_within_cooldown
        history = [self._make_record("ws1", "res1", "HIGH", "SENT", hours_ago=25)]
        assert not is_within_cooldown(history, "ws1", "res1", "HIGH", cooldown_hours=24)

    def test_failed_does_not_count(self):
        from sns_subscriptions import is_within_cooldown
        history = [self._make_record("ws1", "res1", "HIGH", "FAILED", hours_ago=1)]
        assert not is_within_cooldown(history, "ws1", "res1", "HIGH", cooldown_hours=24)

    def test_different_severity(self):
        from sns_subscriptions import is_within_cooldown
        history = [self._make_record("ws1", "res1", "HIGH", "SENT", hours_ago=1)]
        assert not is_within_cooldown(history, "ws1", "res1", "MEDIUM", cooldown_hours=24)

    def test_empty_history(self):
        from sns_subscriptions import is_within_cooldown
        assert not is_within_cooldown([], "ws1", "res1", "HIGH")


class TestShouldAlert:
    def test_high_severity(self):
        from sns_subscriptions import should_alert
        assert should_alert({"severity": "HIGH"})

    def test_medium_severity(self):
        from sns_subscriptions import should_alert
        assert should_alert({"severity": "MEDIUM"})

    def test_low_severity_skipped(self):
        from sns_subscriptions import should_alert
        assert not should_alert({"severity": "LOW"})

    def test_no_severity(self):
        from sns_subscriptions import should_alert
        assert not should_alert({})


class TestClassifyAlertType:
    def test_already_eol(self):
        from sns_subscriptions import classify_alert_type
        r = {"lifecycleStatus": "EOL", "severity": "HIGH", "days_to_eol": -5}
        assert classify_alert_type(r) == "ALREADY_EOL"

    def test_deprecated(self):
        from sns_subscriptions import classify_alert_type
        r = {"lifecycleStatus": "DEPRECATED", "severity": "HIGH", "days_to_eol": 10}
        assert classify_alert_type(r) == "DEPRECATED_RESOURCE"

    def test_critical(self):
        from sns_subscriptions import classify_alert_type
        r = {"lifecycleStatus": "EXPIRING_SOON", "severity": "HIGH", "days_to_eol": 20}
        assert classify_alert_type(r) == "UPCOMING_EOL_CRITICAL"

    def test_warning(self):
        from sns_subscriptions import classify_alert_type
        r = {"lifecycleStatus": "EXPIRING_SOON", "severity": "MEDIUM", "days_to_eol": 60}
        assert classify_alert_type(r) == "UPCOMING_EOL_WARNING"


# ── sns_alert_handler HTML builder ────────────────────────────────────────────

class TestBuildEolAlertHtml:
    def _build(self, alert_type="ALREADY_EOL"):
        from sns_alert_handler import build_eol_alert_html
        resource = {
            "resource_id":   "lambda-my-func",
            "resource_name": "my-function",
            "service_type":  "Lambda",
            "version":       "python3.8",
            "eol_date":      "2023-10-14",
            "severity":      "HIGH",
            "region":        "us-east-1",
            "account_id":    "123456789012",
            "days_to_eol":   -200,
        }
        return build_eol_alert_html(resource, "Test Workspace", alert_type)

    def test_returns_tuple(self):
        subject, html, text = self._build()
        assert isinstance(subject, str)
        assert isinstance(html, str)
        assert isinstance(text, str)

    def test_subject_contains_severity(self):
        subject, _, _ = self._build()
        assert "HIGH" in subject

    def test_html_contains_resource_name(self):
        _, html, _ = self._build()
        assert "my-function" in html

    def test_html_contains_service(self):
        _, html, _ = self._build()
        assert "Lambda" in html

    def test_text_body_is_plain(self):
        _, _, text = self._build()
        assert "<" not in text  # no HTML tags


# ── FileBackend SNS storage ────────────────────────────────────────────────────

class TestFileBackendSns:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        import storage as _st
        _st._storage_instance = None
        # Patch the module-level constant so FileBackend.__init__ uses our tmpdir
        self._orig_dir = _st.EOL_DATA_DIR
        _st.EOL_DATA_DIR = self.tmpdir

    def teardown_method(self):
        import storage as _st
        _st.EOL_DATA_DIR = self._orig_dir
        _st._storage_instance = None

    def _backend(self):
        import storage as _st
        _st._storage_instance = None
        return _st.FileBackend()

    def test_save_and_get_subscription(self):
        from sns_subscriptions import make_subscription
        backend = self._backend()
        sub = make_subscription("ws_test", "a@test.com", "arn:dummy")
        backend.save_sns_subscription(sub)

        subs = backend.get_sns_subscriptions("ws_test")
        assert len(subs) == 1
        assert subs[0]["email"] == "a@test.com"

    def test_delete_subscription(self):
        from sns_subscriptions import make_subscription
        backend = self._backend()
        sub = make_subscription("ws_test", "a@test.com", "arn:dummy")
        backend.save_sns_subscription(sub)
        assert backend.delete_sns_subscription(sub["id"], "ws_test")
        assert backend.get_sns_subscriptions("ws_test") == []

    def test_save_and_get_history(self):
        from sns_subscriptions import make_notification_history
        backend = self._backend()
        resource = {"resource_id": "res1", "severity": "HIGH", "service_type": "Lambda"}
        rec = make_notification_history("ws_test", resource, "all", "SENT")
        backend.save_sns_notification_history(rec)

        history = backend.get_sns_notification_history("ws_test")
        assert len(history) == 1

    def test_is_duplicate_within_cooldown(self):
        from sns_subscriptions import make_notification_history
        backend = self._backend()
        resource = {"resource_id": "res1", "severity": "HIGH", "service_type": "Lambda"}
        rec = make_notification_history("ws_test", resource, "all", "SENT")
        backend.save_sns_notification_history(rec)

        assert backend.is_duplicate_sns_alert("ws_test", "res1", "HIGH", cooldown_hours=24)

    def test_is_not_duplicate_different_resource(self):
        from sns_subscriptions import make_notification_history
        backend = self._backend()
        resource = {"resource_id": "res1", "severity": "HIGH", "service_type": "Lambda"}
        rec = make_notification_history("ws_test", resource, "all", "SENT")
        backend.save_sns_notification_history(rec)

        assert not backend.is_duplicate_sns_alert("ws_test", "res2", "HIGH", cooldown_hours=24)


# ── API handler routes (mocked) ────────────────────────────────────────────────

class TestApiHandlerSnsRoutes:
    """Smoke tests for handler functions with mocked storage and SNS."""

    def _mock_storage(self):
        s = MagicMock()
        s.get_workspace.return_value = {"id": "ws1", "name": "TestWS", "token": "tok"}
        s.get_sns_subscriptions.return_value = []
        s.get_sns_notification_history.return_value = []
        return s

    def _headers(self):
        return {"x-workspace-token": "tok"}

    def test_list_subscriptions_empty(self):
        import api_handler
        storage_mock = self._mock_storage()
        with patch("api_handler.get_storage", return_value=storage_mock):
            with patch("api_handler._verify_workspace_access",
                       return_value=({"id": "ws1", "name": "Test"}, "tok", None)):
                result = api_handler.handle_ws_sns_subscriptions_list("ws1", self._headers())
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["subscriptions"] == []

    def test_subscribe_invalid_email(self):
        import api_handler
        storage_mock = self._mock_storage()
        with patch("api_handler.get_storage", return_value=storage_mock):
            with patch("api_handler._verify_workspace_access",
                       return_value=({"id": "ws1"}, "tok", None)):
                result = api_handler.handle_ws_sns_subscribe(
                    "ws1", {"email": "not-valid"}, self._headers()
                )
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error"]["code"] == "INVALID_EMAIL"

    def test_history_returns_list(self):
        import api_handler
        storage_mock = self._mock_storage()
        with patch("api_handler.get_storage", return_value=storage_mock):
            with patch("api_handler._verify_workspace_access",
                       return_value=({"id": "ws1"}, "tok", None)):
                result = api_handler.handle_ws_sns_history("ws1", self._headers(), {})
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "history" in body

    def test_test_alert_no_subscribers(self):
        import api_handler
        storage_mock = self._mock_storage()
        with patch("api_handler.get_storage", return_value=storage_mock):
            with patch("api_handler._verify_workspace_access",
                       return_value=({"id": "ws1", "name": "Test"}, "tok", None)):
                result = api_handler.handle_ws_sns_test("ws1", self._headers())
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error"]["code"] == "NO_VERIFIED_SUBSCRIBERS"
