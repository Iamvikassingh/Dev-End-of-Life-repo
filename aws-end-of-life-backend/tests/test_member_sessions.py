"""
Phase 7.2b — Member session access tests.

Covers:
- Accept invite returns member session token (raw shown once)
- Raw session token not stored anywhere
- Member session can access VIEWER-level endpoints
- Member session role enforcement (VIEWER/EDITOR/ADMIN)
- Disabled member cannot use session
- Expired session rejected
- Revoked session rejected
- Cross-workspace isolation
- Existing workspace token flow still works
- API token flow still works
- Audit logs written on accept + session create
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

def _load_backend(tmp_path):
    os.environ["STORAGE_BACKEND"] = "file"
    os.environ["EOL_DATA_DIR"]    = str(tmp_path)
    import storage, api_handler
    importlib.reload(storage)
    importlib.reload(api_handler)
    return storage.FileBackend(), api_handler


def _body(result: dict) -> dict:
    return json.loads(result["body"])


def _ws_headers(token: str) -> dict:
    return {"x-workspace-token": token}


def _api_headers(raw_token: str) -> dict:
    return {"x-api-token": raw_token}


def _member_headers(raw_token: str) -> dict:
    return {"x-member-session-token": raw_token}


def _member_bearer(raw_token: str) -> dict:
    return {"authorization": f"Bearer {raw_token}"}


def _seed_workspace(st, ws_id: str, ws_token: str, name: str = "Acme") -> None:
    st.save_workspace({
        "id":         ws_id,
        "name":       name,
        "token_hash": hashlib.sha256(ws_token.encode()).hexdigest(),
    })


def _make_api_token(st, ws_id: str, role: str = "VIEWER") -> str:
    raw = f"eolm_api_{role.lower()}_{ws_id}_{secrets.token_hex(8)}"
    st.save_api_token({
        "id":          f"tok_{role.lower()}_{ws_id}",
        "workspaceId": ws_id,
        "name":        f"{role} token",
        "role":        role,
        "tokenHash":   hashlib.sha256(raw.encode()).hexdigest(),
        "prefix":      raw[:18] + "...",
        "createdAt":   datetime.now(timezone.utc).isoformat(),
        "lastUsedAt":  None,
        "expiresAt":   None,
        "revokedAt":   None,
        "createdBy":   "workspace",
    })
    return raw


def _invite_and_accept(api, st, ws_id: str, ws_token: str,
                       email: str, role: str = "VIEWER", name: str = "") -> tuple[str, str]:
    """Invite + accept. Returns (member_id, raw_session_token)."""
    inv = api.handle_ws_member_invite(
        ws_id, {"email": email, "role": role, "name": name}, _ws_headers(ws_token)
    )
    invite_token = _body(inv)["inviteToken"]
    acc = api.handle_ws_member_accept_invite(
        ws_id, {"token": invite_token, "name": name or None}
    )
    b = _body(acc)
    return b["memberId"], b["memberSessionToken"]


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestMemberSessionBackend(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.st, self.api = _load_backend(self.tmp)
        self.tok_a = "wstoken_a_test"
        self.tok_b = "wstoken_b_test"
        _seed_workspace(self.st, "ws-a", self.tok_a, "Alpha Corp")
        _seed_workspace(self.st, "ws-b", self.tok_b, "Beta LLC")
        # Seed some resources so report summary endpoint works
        self.st.save_account({"id": "conn-a", "workspace_id": "ws-a", "accountName": "Prod", "accountId": "111"})

    # ── Accept-invite response ─────────────────────────────────────────────────

    def test_accept_returns_session_token(self):
        inv = self.api.handle_ws_member_invite(
            "ws-a", {"email": "t@example.com", "role": "VIEWER"}, _ws_headers(self.tok_a)
        )
        token = _body(inv)["inviteToken"]
        result = self.api.handle_ws_member_accept_invite("ws-a", {"token": token})
        self.assertEqual(result["statusCode"], 200)
        b = _body(result)
        self.assertIn("memberSessionToken", b)
        self.assertTrue(b["memberSessionToken"].startswith("eolm_member_"))
        self.assertIn("role", b)
        self.assertIn("expiresAt", b)
        self.assertIn("workspaceId", b)

    def test_raw_session_token_not_in_storage(self):
        _, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "s@example.com")
        # Check member_sessions.json (via internal storage read)
        import json as _json
        sess_file = os.path.join(self.tmp, "member_sessions.json")
        if os.path.exists(sess_file):
            contents = _json.loads(open(sess_file).read())
            raw_str  = _json.dumps(contents)
            self.assertNotIn(raw_sess, raw_str, "Raw session token found in member_sessions.json")
        else:
            self.fail("member_sessions.json not created")

    def test_accept_writes_audit_logs(self):
        _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "audit@example.com")
        logs    = self.st.get_audit_logs("ws-a", limit=10)
        actions = {l["action"] for l in logs}
        self.assertIn("MEMBER_INVITE_ACCEPTED", actions)
        self.assertIn("MEMBER_SESSION_CREATED", actions)

    def test_raw_session_token_not_in_audit_logs(self):
        _, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "noleak@example.com")
        logs     = self.st.get_audit_logs("ws-a", limit=10)
        logs_str = json.dumps(logs)
        self.assertNotIn(raw_sess, logs_str, "Raw session token found in audit logs")

    # ── Access with member session ─────────────────────────────────────────────

    def test_viewer_session_can_access_report_summary(self):
        _, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "v@example.com", "VIEWER")
        result = self.api.handle_ws_reports_summary("ws-a", _member_headers(raw_sess))
        self.assertEqual(result["statusCode"], 200)

    def test_viewer_session_bearer_form_works(self):
        _, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "vb@example.com", "VIEWER")
        result = self.api.handle_ws_reports_summary("ws-a", _member_bearer(raw_sess))
        self.assertEqual(result["statusCode"], 200)

    def test_viewer_session_cannot_manage_members(self):
        _, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "vlim@example.com", "VIEWER")
        result = self.api.handle_ws_members_list("ws-a", _member_headers(raw_sess))
        self.assertNotEqual(result["statusCode"], 200)
        self.assertEqual(_body(result)["error"]["code"], "INSUFFICIENT_ROLE")

    def test_viewer_session_cannot_create_api_token(self):
        _, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "vapitok@example.com", "VIEWER")
        result = self.api.handle_ws_api_token_create(
            "ws-a", {"name": "test", "role": "VIEWER"}, _member_headers(raw_sess)
        )
        self.assertNotEqual(result["statusCode"], 201)

    def test_editor_session_can_create_report_snapshot(self):
        _, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "ed@example.com", "EDITOR")
        result = self.api.handle_ws_report_snapshot_create("ws-a", _member_headers(raw_sess))
        self.assertEqual(result["statusCode"], 201)

    def test_editor_session_cannot_manage_members(self):
        _, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "edlim@example.com", "EDITOR")
        result = self.api.handle_ws_members_list("ws-a", _member_headers(raw_sess))
        self.assertNotEqual(result["statusCode"], 200)

    def test_admin_session_can_manage_members(self):
        _, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "adm@example.com", "ADMIN")
        result = self.api.handle_ws_members_list("ws-a", _member_headers(raw_sess))
        self.assertEqual(result["statusCode"], 200)

    def test_admin_session_can_invite_new_member(self):
        _, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "admhost@example.com", "ADMIN")
        result = self.api.handle_ws_member_invite(
            "ws-a", {"email": "newbie@example.com", "role": "VIEWER"}, _member_headers(raw_sess)
        )
        self.assertEqual(result["statusCode"], 201)

    # ── Session security ───────────────────────────────────────────────────────

    def test_expired_session_rejected(self):
        mbr_id, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "exp@example.com")
        # Back-date the session
        all_sess = self.st._read(self.st._member_sessions_path, {})
        for s in all_sess.get("ws-a", []):
            if s["memberId"] == mbr_id:
                s["expiresAt"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
                self.st.save_member_session(s)
                break

        result = self.api.handle_ws_reports_summary("ws-a", _member_headers(raw_sess))
        self.assertNotEqual(result["statusCode"], 200)
        self.assertEqual(_body(result)["error"]["code"], "MEMBER_SESSION_EXPIRED")

    def test_revoked_session_rejected(self):
        mbr_id, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "rev@example.com")
        # Revoke the session
        all_sess = self.st._read(self.st._member_sessions_path, {})
        for s in all_sess.get("ws-a", []):
            if s["memberId"] == mbr_id:
                s["revokedAt"] = datetime.now(timezone.utc).isoformat()
                self.st.save_member_session(s)
                break

        result = self.api.handle_ws_reports_summary("ws-a", _member_headers(raw_sess))
        self.assertNotEqual(result["statusCode"], 200)
        self.assertEqual(_body(result)["error"]["code"], "MEMBER_SESSION_REVOKED")

    def test_disabled_member_session_rejected(self):
        mbr_id, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "dis@example.com")
        # Disable the member
        member = self.st.get_member_by_id(mbr_id, "ws-a")
        self.st.save_member({**member, "status": "DISABLED"})

        result = self.api.handle_ws_reports_summary("ws-a", _member_headers(raw_sess))
        self.assertNotEqual(result["statusCode"], 200)
        self.assertEqual(_body(result)["error"]["code"], "MEMBER_DISABLED")

    def test_invalid_token_prefix_rejected(self):
        result = self.api.handle_ws_reports_summary("ws-a", _member_headers("eolm_api_wrong_prefix"))
        self.assertNotEqual(result["statusCode"], 200)
        self.assertEqual(_body(result)["error"]["code"], "MEMBER_SESSION_INVALID")

    def test_unknown_token_rejected(self):
        fake = f"eolm_member_{secrets.token_hex(32)}"
        result = self.api.handle_ws_reports_summary("ws-a", _member_headers(fake))
        self.assertNotEqual(result["statusCode"], 200)
        self.assertEqual(_body(result)["error"]["code"], "MEMBER_SESSION_INVALID")

    # ── Cross-workspace isolation ──────────────────────────────────────────────

    def test_ws_a_session_cannot_access_ws_b(self):
        _, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "cross@example.com")
        result = self.api.handle_ws_reports_summary("ws-b", _member_headers(raw_sess))
        self.assertNotEqual(result["statusCode"], 200)

    # ── Existing auth flows still work ─────────────────────────────────────────

    def test_workspace_token_still_works(self):
        result = self.api.handle_ws_reports_summary("ws-a", _ws_headers(self.tok_a))
        self.assertEqual(result["statusCode"], 200)

    def test_api_token_viewer_still_works(self):
        raw = _make_api_token(self.st, "ws-a", "VIEWER")
        result = self.api.handle_ws_reports_summary("ws-a", _api_headers(raw))
        self.assertEqual(result["statusCode"], 200)

    def test_api_token_editor_can_create_snapshot(self):
        raw = _make_api_token(self.st, "ws-a", "EDITOR")
        result = self.api.handle_ws_report_snapshot_create("ws-a", _api_headers(raw))
        self.assertEqual(result["statusCode"], 201)

    # ── Actor type in audit ────────────────────────────────────────────────────

    def test_member_actor_type_in_audit(self):
        _, raw_sess = _invite_and_accept(self.api, self.st, "ws-a", self.tok_a, "actor@example.com", "EDITOR")
        # Trigger an action that writes an audit log via member session
        self.api.handle_ws_report_snapshot_create("ws-a", _member_headers(raw_sess))
        logs = self.st.get_audit_logs("ws-a", limit=20)
        snap_logs = [l for l in logs if l["action"] == "REPORT_SNAPSHOT_CREATED"]
        # Snapshot created by member session — actor type should be MEMBER
        self.assertTrue(
            any(l["actor"]["type"] == "MEMBER" for l in snap_logs),
            "Expected MEMBER actor type in REPORT_SNAPSHOT_CREATED audit log"
        )


if __name__ == "__main__":
    unittest.main()
