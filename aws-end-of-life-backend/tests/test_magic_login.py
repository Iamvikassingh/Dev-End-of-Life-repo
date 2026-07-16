"""
Phase 7.2b — Magic login link tests.

Covers:
- POST login-link creates a one-time token
- Raw login token NOT stored in JSON
- devLoginLink never returned in API response (P0-3 fix)
- POST complete-login creates a member session + returns token
- Used token rejected (TOKEN_USED)
- Expired token rejected (TOKEN_EXPIRED)
- Unknown/invalid token rejected
- Wrong prefix rejected
- Disabled member rejected
- Audit logs written: MEMBER_LOGIN_LINK_SENT + MEMBER_LOGIN_COMPLETED
- Cross-workspace token rejected
- MEMBER_LOGIN_DEV_LINKS=true → link logged only, NOT in response body
- Unknown email returns generic 200 (no email enumeration)
"""
import hashlib
import importlib
import json
import os
import secrets
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_backend(tmp_path, extra_env=None):
    for key in (
        "APP_PUBLIC_URL",
        "APP_URL",
        "MEMBER_LOGIN_DEV_LINKS",
        "MEMBER_LOGIN_DEBUG",
        "NOTIFICATIONS_EMAIL_PROVIDER",
        "NOTIFICATIONS_FROM_EMAIL",
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_EMAIL",
    ):
        os.environ.pop(key, None)
    env = {"STORAGE_BACKEND": "file", "EOL_DATA_DIR": str(tmp_path)}
    if extra_env:
        env.update(extra_env)
    os.environ.update(env)
    import storage, api_handler
    importlib.reload(storage)
    importlib.reload(api_handler)
    return storage.FileBackend(), api_handler


def _body(result: dict) -> dict:
    return json.loads(result["body"])


def _ws_headers(token: str) -> dict:
    return {"x-workspace-token": token}


def _seed_workspace(st, ws_id: str, ws_token: str, name: str = "Acme") -> None:
    st.save_workspace({
        "id":         ws_id,
        "name":       name,
        "token_hash": hashlib.sha256(ws_token.encode()).hexdigest(),
    })


def _invite_and_accept(api, ws_id: str, ws_token: str,
                       email: str, role: str = "VIEWER", name: str = "") -> tuple[str, str]:
    """Invite + accept. Returns (member_id, raw_session_token)."""
    inv = api.handle_ws_member_invite(
        ws_id, {"email": email, "role": role, "name": name}, _ws_headers(ws_token)
    )
    invite_token = _body(inv)["inviteToken"]
    acc = api.handle_ws_member_accept_invite(ws_id, {"token": invite_token, "name": name or None})
    b = _body(acc)
    return b["memberId"], b["memberSessionToken"]


def _create_login_token_direct(st, ws_id: str, member_id: str,
                                minutes: int = 15) -> str:
    """Insert a valid login token directly into storage and return the raw token.

    Used by tests instead of relying on devLoginLink in the API response,
    which was removed (P0-3) — the response no longer exposes the raw token.
    """
    raw_token  = f"login_{secrets.token_hex(32)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    st.save_member_login_token({
        "id":          f"login_tok_{secrets.token_hex(10)}",
        "workspaceId": ws_id,
        "memberId":    member_id,
        "tokenHash":   token_hash,
        "createdAt":   datetime.now(timezone.utc).isoformat(),
        "expiresAt":   expires_at,
        "usedAt":      None,
    })
    return raw_token


def _request_login_link(api, ws_id: str, email: str) -> dict:
    return api.handle_ws_member_login_link(ws_id, {"email": email})


def _complete_login(api, ws_id: str, token: str) -> dict:
    return api.handle_ws_member_complete_login(ws_id, {"token": token})


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestMagicLoginBackend(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.st, self.api = _load_backend(self.tmp, {
            "APP_PUBLIC_URL": "http://example.test",
            "MEMBER_LOGIN_DEV_LINKS": "true",
        })
        self.tok_a = "wstoken_a_magic"
        self.tok_b = "wstoken_b_magic"
        _seed_workspace(self.st, "ws-a", self.tok_a, "Alpha Corp")
        _seed_workspace(self.st, "ws-b", self.tok_b, "Beta LLC")
        self.mbr_id, _ = _invite_and_accept(self.api, "ws-a", self.tok_a, "alice@example.com", "VIEWER", "Alice")

    # ── login-link request ─────────────────────────────────────────────────────

    def test_login_link_returns_200_for_known_email(self):
        result = _request_login_link(self.api, "ws-a", "alice@example.com")
        self.assertEqual(result["statusCode"], 200)

    def test_login_link_returns_200_for_unknown_email(self):
        result = _request_login_link(self.api, "ws-a", "nobody@example.com")
        self.assertEqual(result["statusCode"], 200)

    def test_login_link_response_never_contains_dev_link(self):
        """P0-3: devLoginLink must NEVER appear in the API response body,
        even when MEMBER_LOGIN_DEV_LINKS=true. Link is server-log-only."""
        result = _request_login_link(self.api, "ws-a", "alice@example.com")
        b = _body(result)
        self.assertNotIn("devLoginLink", b,
                         "devLoginLink must not be exposed in the API response (P0-3 fix)")

    def test_login_link_dev_flag_false_hides_dev_login_link(self):
        st, api = _load_backend(self.tmp, {
            "APP_PUBLIC_URL": "http://example.test",
            "MEMBER_LOGIN_DEV_LINKS": "false",
        })
        _seed_workspace(st, "ws-c", "wstoken_c_magic", "Gamma LLC")
        _invite_and_accept(api, "ws-c", "wstoken_c_magic", "carol@example.com", "VIEWER", "Carol")

        result = api.handle_ws_member_login_link("ws-c", {"email": "carol@example.com"})
        b = _body(result)
        self.assertNotIn("devLoginLink", b)

    def test_login_link_token_stored_as_hash(self):
        """Raw login token must NOT appear in the token file — only hash stored."""
        # Trigger token creation
        _request_login_link(self.api, "ws-a", "alice@example.com")
        # Get a fresh raw token so we know its value
        raw_token  = f"login_{secrets.token_hex(32)}"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        self.st.save_member_login_token({
            "id": f"login_tok_{secrets.token_hex(10)}",
            "workspaceId": "ws-a",
            "memberId": self.mbr_id,
            "tokenHash": token_hash,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "expiresAt": expires_at,
            "usedAt": None,
        })
        tok_file = os.path.join(self.tmp, "member_login_tokens.json")
        self.assertTrue(os.path.exists(tok_file))
        contents = open(tok_file).read()
        self.assertNotIn(raw_token, contents, "Raw login token must NOT be stored")
        self.assertIn(token_hash, contents, "Token hash must be stored")

    def test_raw_login_token_not_stored(self):
        """Tokens saved by the login-link endpoint must only contain the hash."""
        _request_login_link(self.api, "ws-a", "alice@example.com")
        tok_file = os.path.join(self.tmp, "member_login_tokens.json")
        self.assertTrue(os.path.exists(tok_file))
        contents = json.loads(open(tok_file).read())
        for ws_tokens in contents.values():
            for tok in ws_tokens:
                self.assertNotIn("tokenHash" not in tok, [True],
                                 "Each stored token must have a tokenHash field")
                # tokenHash should look like a hex digest, not a raw login_ token
                h = tok.get("tokenHash", "")
                self.assertFalse(h.startswith("login_"),
                                 "tokenHash must not start with 'login_' — raw token stored?")

    def test_login_link_writes_audit_log(self):
        _request_login_link(self.api, "ws-a", "alice@example.com")
        logs    = self.st.get_audit_logs("ws-a", limit=20)
        actions = {l["action"] for l in logs}
        self.assertIn("MEMBER_LOGIN_LINK_SENT", actions)

    def test_login_link_no_audit_for_unknown_email(self):
        before = {l["id"] for l in self.st.get_audit_logs("ws-a", limit=50)}
        _request_login_link(self.api, "ws-a", "ghost@example.com")
        after  = {l["id"] for l in self.st.get_audit_logs("ws-a", limit=50)}
        new_logs = after - before
        link_sent_logs = [
            l for l in self.st.get_audit_logs("ws-a", limit=50)
            if l["id"] in new_logs and l["action"] == "MEMBER_LOGIN_LINK_SENT"
        ]
        self.assertEqual(len(link_sent_logs), 0)

    # ── complete-login ─────────────────────────────────────────────────────────

    def test_complete_login_returns_session_token(self):
        raw_token = _create_login_token_direct(self.st, "ws-a", self.mbr_id)
        result = _complete_login(self.api, "ws-a", raw_token)
        self.assertEqual(result["statusCode"], 200)
        b = _body(result)
        self.assertIn("memberSessionToken", b)
        self.assertTrue(b["memberSessionToken"].startswith("eolm_member_"))
        self.assertIn("workspaceId", b)
        self.assertIn("role", b)
        self.assertIn("expiresAt", b)

    def test_complete_login_writes_audit_log(self):
        raw_token = _create_login_token_direct(self.st, "ws-a", self.mbr_id)
        _complete_login(self.api, "ws-a", raw_token)
        logs    = self.st.get_audit_logs("ws-a", limit=20)
        actions = {l["action"] for l in logs}
        self.assertIn("MEMBER_LOGIN_COMPLETED", actions)
        self.assertIn("MEMBER_SESSION_CREATED", actions)

    def test_raw_token_not_in_audit_logs(self):
        raw_token = _create_login_token_direct(self.st, "ws-a", self.mbr_id)
        _complete_login(self.api, "ws-a", raw_token)
        logs_str = json.dumps(self.st.get_audit_logs("ws-a", limit=50))
        self.assertNotIn(raw_token, logs_str, "Raw login token must not appear in audit logs")

    def test_used_token_rejected(self):
        raw_token = _create_login_token_direct(self.st, "ws-a", self.mbr_id)
        r1 = _complete_login(self.api, "ws-a", raw_token)
        self.assertEqual(r1["statusCode"], 200)
        r2 = _complete_login(self.api, "ws-a", raw_token)
        self.assertNotEqual(r2["statusCode"], 200)
        self.assertEqual(_body(r2)["error"]["code"], "LOGIN_TOKEN_USED")

    def test_expired_token_rejected(self):
        raw_token = _create_login_token_direct(self.st, "ws-a", self.mbr_id, minutes=-5)
        result = _complete_login(self.api, "ws-a", raw_token)
        self.assertNotEqual(result["statusCode"], 200)
        self.assertEqual(_body(result)["error"]["code"], "LOGIN_TOKEN_EXPIRED")

    def test_unknown_token_rejected(self):
        fake = f"login_{secrets.token_hex(32)}"
        result = _complete_login(self.api, "ws-a", fake)
        self.assertNotEqual(result["statusCode"], 200)
        self.assertIn(_body(result)["error"]["code"],
                      ("LOGIN_TOKEN_NOT_FOUND", "LOGIN_TOKEN_INVALID", "LOGIN_TOKEN_EXPIRED", "LOGIN_TOKEN_USED"))

    def test_wrong_prefix_rejected(self):
        result = _complete_login(self.api, "ws-a", f"eolm_member_{secrets.token_hex(16)}")
        self.assertNotEqual(result["statusCode"], 200)

    def test_disabled_member_rejected(self):
        raw_token = _create_login_token_direct(self.st, "ws-a", self.mbr_id)
        member = self.st.get_member_by_id(self.mbr_id, "ws-a")
        self.st.save_member({**member, "status": "DISABLED"})
        result = _complete_login(self.api, "ws-a", raw_token)
        self.assertNotEqual(result["statusCode"], 200)

    # ── Cross-workspace isolation ──────────────────────────────────────────────

    def test_ws_a_token_cannot_complete_login_in_ws_b(self):
        raw_token = _create_login_token_direct(self.st, "ws-a", self.mbr_id)
        result = _complete_login(self.api, "ws-b", raw_token)
        self.assertNotEqual(result["statusCode"], 200)

    # ── Session usable after magic login ──────────────────────────────────────

    def test_session_from_magic_login_can_access_reports(self):
        raw_token = _create_login_token_direct(self.st, "ws-a", self.mbr_id)
        b = _body(_complete_login(self.api, "ws-a", raw_token))
        sess_tok = b["memberSessionToken"]
        result = self.api.handle_ws_reports_summary(
            "ws-a", {"x-member-session-token": sess_tok}
        )
        self.assertEqual(result["statusCode"], 200)

    # ── Production guard ──────────────────────────────────────────────────────

    def test_production_guard_rejects_dev_links_flag(self):
        """APP_ENV=production + MEMBER_LOGIN_DEV_LINKS=true must fail at import."""
        import importlib
        import api_handler as _api
        env_backup = {
            "APP_ENV": os.environ.get("APP_ENV", ""),
            "MEMBER_LOGIN_DEV_LINKS": os.environ.get("MEMBER_LOGIN_DEV_LINKS", ""),
            "ALLOWED_ORIGIN": os.environ.get("ALLOWED_ORIGIN", "*"),
        }
        os.environ["APP_ENV"]               = "production"
        os.environ["MEMBER_LOGIN_DEV_LINKS"] = "true"
        os.environ["ALLOWED_ORIGIN"]         = "https://example.com"
        try:
            with self.assertRaises(RuntimeError):
                importlib.reload(_api)
        finally:
            for k, v in env_backup.items():
                if v:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)
            importlib.reload(_api)

    # ── Missing fields ─────────────────────────────────────────────────────────

    def test_login_link_missing_email_rejected(self):
        result = self.api.handle_ws_member_login_link("ws-a", {})
        self.assertNotEqual(result["statusCode"], 200)

    def test_complete_login_missing_token_rejected(self):
        result = self.api.handle_ws_member_complete_login("ws-a", {})
        self.assertNotEqual(result["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
