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


def _ws_headers(token: str) -> dict:
    return {"x-workspace-token": token}


def _api_headers(raw_token: str) -> dict:
    return {"x-api-token": raw_token}


def _body(result: dict) -> dict:
    return json.loads(result["body"])


def _seed_workspace(st, ws_id: str, ws_token: str, name: str = "Acme") -> None:
    st.save_workspace({
        "id":         ws_id,
        "name":       name,
        "token_hash": hashlib.sha256(ws_token.encode()).hexdigest(),
    })


def _make_api_token(st, ws_id: str, role: str = "VIEWER", token_id: str | None = None) -> str:
    raw = f"eolm_api_{role.lower()}_{ws_id}_{secrets.token_hex(8)}"
    tid = token_id or f"tok_{role.lower()}_{ws_id}"
    rec = {
        "id":          tid,
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
    }
    st.save_api_token(rec)
    return raw


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestMembersBackend(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.st, self.api = _load_backend(self.tmp)
        self.tok_a = "wstoken_alpha_test"
        self.tok_b = "wstoken_beta_test"
        _seed_workspace(self.st, "ws-a", self.tok_a, "Alpha Corp")
        _seed_workspace(self.st, "ws-b", self.tok_b, "Beta LLC")

    # ── Invite ─────────────────────────────────────────────────────────────────

    def test_invite_creates_invited_record(self):
        result = self.api.handle_ws_member_invite(
            "ws-a",
            {"email": "alice@example.com", "role": "VIEWER"},
            _ws_headers(self.tok_a),
        )
        self.assertEqual(result["statusCode"], 201)
        body = _body(result)
        self.assertIn("member", body)
        self.assertIn("inviteToken", body)
        member = body["member"]
        self.assertEqual(member["email"], "alice@example.com")
        self.assertEqual(member["role"], "VIEWER")
        self.assertEqual(member["status"], "INVITED")
        self.assertNotIn("inviteTokenHash", member)

    def test_invite_token_starts_with_inv(self):
        result = self.api.handle_ws_member_invite(
            "ws-a",
            {"email": "bob@example.com", "role": "EDITOR"},
            _ws_headers(self.tok_a),
        )
        self.assertEqual(result["statusCode"], 201)
        token = _body(result)["inviteToken"]
        self.assertTrue(token.startswith("inv_"), f"token={token}")

    def test_invite_with_name(self):
        result = self.api.handle_ws_member_invite(
            "ws-a",
            {"email": "carol@example.com", "role": "ADMIN", "name": "Carol Smith"},
            _ws_headers(self.tok_a),
        )
        self.assertEqual(result["statusCode"], 201)
        self.assertEqual(_body(result)["member"]["name"], "Carol Smith")

    def test_duplicate_email_rejected(self):
        self.api.handle_ws_member_invite(
            "ws-a",
            {"email": "dup@example.com", "role": "VIEWER"},
            _ws_headers(self.tok_a),
        )
        result = self.api.handle_ws_member_invite(
            "ws-a",
            {"email": "dup@example.com", "role": "EDITOR"},
            _ws_headers(self.tok_a),
        )
        self.assertEqual(result["statusCode"], 409)
        self.assertEqual(_body(result)["error"]["code"], "MEMBER_ALREADY_EXISTS")

    def test_invite_writes_audit_log(self):
        self.api.handle_ws_member_invite(
            "ws-a",
            {"email": "audited@example.com", "role": "VIEWER"},
            _ws_headers(self.tok_a),
        )
        logs = self.st.get_audit_logs("ws-a", limit=5)
        invite_logs = [l for l in logs if l["action"] == "MEMBER_INVITED"]
        self.assertEqual(len(invite_logs), 1)
        meta = invite_logs[0]["metadata"]
        self.assertEqual(meta["email"], "audited@example.com")
        self.assertEqual(meta["role"], "VIEWER")

    def test_raw_token_not_in_storage(self):
        result = self.api.handle_ws_member_invite(
            "ws-a",
            {"email": "secret@example.com", "role": "VIEWER"},
            _ws_headers(self.tok_a),
        )
        raw_token = _body(result)["inviteToken"]
        members   = self.st.get_members("ws-a")
        stored    = members[0]
        for key, val in stored.items():
            self.assertNotEqual(str(val), raw_token, f"raw token found in field {key}")
        self.assertIn("inviteTokenHash", stored)

    def test_raw_token_not_in_audit_log(self):
        result = self.api.handle_ws_member_invite(
            "ws-a",
            {"email": "noleak@example.com", "role": "VIEWER"},
            _ws_headers(self.tok_a),
        )
        raw_token = _body(result)["inviteToken"]
        logs      = self.st.get_audit_logs("ws-a", limit=5)
        logs_str  = json.dumps(logs)
        self.assertNotIn(raw_token, logs_str, "Raw invite token found in audit logs")

    def test_invalid_email_rejected(self):
        result = self.api.handle_ws_member_invite(
            "ws-a",
            {"email": "not-an-email", "role": "VIEWER"},
            _ws_headers(self.tok_a),
        )
        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(_body(result)["error"]["code"], "INVALID_EMAIL")

    # ── Accept invite ──────────────────────────────────────────────────────────

    def test_accept_invite_activates_member(self):
        inv_res = self.api.handle_ws_member_invite(
            "ws-a",
            {"email": "joiner@example.com", "role": "EDITOR"},
            _ws_headers(self.tok_a),
        )
        token = _body(inv_res)["inviteToken"]

        result = self.api.handle_ws_member_accept_invite(
            "ws-a", {"token": token, "name": "Jo Joiner"}
        )
        self.assertEqual(result["statusCode"], 200)
        member = _body(result)["member"]
        self.assertEqual(member["status"], "ACTIVE")
        self.assertEqual(member["name"], "Jo Joiner")
        self.assertIsNotNone(member.get("acceptedAt"))
        self.assertNotIn("inviteTokenHash", member)

    def test_expired_invite_rejected(self):
        inv_res   = self.api.handle_ws_member_invite(
            "ws-a",
            {"email": "stale@example.com", "role": "VIEWER"},
            _ws_headers(self.tok_a),
        )
        token     = _body(inv_res)["inviteToken"]
        member_id = _body(inv_res)["member"]["id"]

        members = self.st.get_members("ws-a")
        for m in members:
            if m["id"] == member_id:
                m["inviteExpiresAt"] = (
                    datetime.now(timezone.utc) - timedelta(days=1)
                ).isoformat()
                self.st.save_member(m)
                break

        result = self.api.handle_ws_member_accept_invite("ws-a", {"token": token})
        self.assertEqual(result["statusCode"], 410)
        self.assertEqual(_body(result)["error"]["code"], "INVITE_EXPIRED")

    def test_invalid_token_prefix_rejected(self):
        result = self.api.handle_ws_member_accept_invite(
            "ws-a", {"token": "eolm_api_nope_123"}
        )
        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(_body(result)["error"]["code"], "INVALID_INVITE_TOKEN")

    # ── Update member ──────────────────────────────────────────────────────────

    def _invite_and_activate(self, email: str, role: str = "VIEWER") -> str:
        """Invite and accept to get an ACTIVE member. Returns member_id."""
        inv_res = self.api.handle_ws_member_invite(
            "ws-a", {"email": email, "role": role}, _ws_headers(self.tok_a)
        )
        token   = _body(inv_res)["inviteToken"]
        acc_res = self.api.handle_ws_member_accept_invite("ws-a", {"token": token})
        return _body(acc_res)["member"]["id"]

    def test_update_role_changes_role(self):
        mbr_id = self._invite_and_activate("rolechange@example.com", "VIEWER")
        result = self.api.handle_ws_member_update(
            "ws-a", mbr_id, {"role": "EDITOR"}, _ws_headers(self.tok_a)
        )
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(_body(result)["member"]["role"], "EDITOR")

    def test_update_role_writes_audit(self):
        mbr_id = self._invite_and_activate("roleaudit@example.com", "VIEWER")
        self.api.handle_ws_member_update(
            "ws-a", mbr_id, {"role": "ADMIN"}, _ws_headers(self.tok_a)
        )
        logs      = self.st.get_audit_logs("ws-a", limit=10)
        role_logs = [l for l in logs if l["action"] == "MEMBER_ROLE_CHANGED"]
        self.assertEqual(len(role_logs), 1)
        meta = role_logs[0]["metadata"]
        self.assertEqual(meta["old_role"], "VIEWER")
        self.assertEqual(meta["new_role"], "ADMIN")

    def test_disable_member_writes_audit(self):
        mbr_id = self._invite_and_activate("disable@example.com")
        result = self.api.handle_ws_member_update(
            "ws-a", mbr_id, {"status": "DISABLED"}, _ws_headers(self.tok_a)
        )
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(_body(result)["member"]["status"], "DISABLED")

        logs     = self.st.get_audit_logs("ws-a", limit=10)
        dis_logs = [l for l in logs if l["action"] == "MEMBER_DISABLED"]
        self.assertEqual(len(dis_logs), 1)

    def test_enable_member_writes_audit(self):
        mbr_id = self._invite_and_activate("reenable@example.com")
        self.api.handle_ws_member_update(
            "ws-a", mbr_id, {"status": "DISABLED"}, _ws_headers(self.tok_a)
        )
        result = self.api.handle_ws_member_update(
            "ws-a", mbr_id, {"status": "ACTIVE"}, _ws_headers(self.tok_a)
        )
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(_body(result)["member"]["status"], "ACTIVE")

        logs    = self.st.get_audit_logs("ws-a", limit=10)
        en_logs = [l for l in logs if l["action"] == "MEMBER_ENABLED"]
        self.assertEqual(len(en_logs), 1)

    def test_update_nonexistent_member_returns_404(self):
        result = self.api.handle_ws_member_update(
            "ws-a", "mbr_doesnotexist", {"role": "EDITOR"}, _ws_headers(self.tok_a)
        )
        self.assertEqual(result["statusCode"], 404)
        self.assertEqual(_body(result)["error"]["code"], "MEMBER_NOT_FOUND")

    # ── Remove member ──────────────────────────────────────────────────────────

    def test_remove_deletes_record(self):
        inv_res = self.api.handle_ws_member_invite(
            "ws-a", {"email": "gone@example.com", "role": "VIEWER"}, _ws_headers(self.tok_a)
        )
        mbr_id = _body(inv_res)["member"]["id"]

        result = self.api.handle_ws_member_remove("ws-a", mbr_id, _ws_headers(self.tok_a))
        self.assertEqual(result["statusCode"], 200)
        self.assertTrue(_body(result)["removed"])
        self.assertIsNone(self.st.get_member_by_id(mbr_id, "ws-a"))

    def test_remove_writes_audit(self):
        inv_res = self.api.handle_ws_member_invite(
            "ws-a", {"email": "removeaudit@example.com", "role": "EDITOR"}, _ws_headers(self.tok_a)
        )
        mbr_id = _body(inv_res)["member"]["id"]
        self.api.handle_ws_member_remove("ws-a", mbr_id, _ws_headers(self.tok_a))

        logs     = self.st.get_audit_logs("ws-a", limit=10)
        rem_logs = [l for l in logs if l["action"] == "MEMBER_REMOVED"]
        self.assertEqual(len(rem_logs), 1)
        self.assertEqual(rem_logs[0]["metadata"]["email"], "removeaudit@example.com")

    def test_remove_nonexistent_returns_404(self):
        result = self.api.handle_ws_member_remove("ws-a", "mbr_ghost", _ws_headers(self.tok_a))
        self.assertEqual(result["statusCode"], 404)

    # ── List members ───────────────────────────────────────────────────────────

    def test_list_members_returns_all(self):
        self.api.handle_ws_member_invite(
            "ws-a", {"email": "one@example.com", "role": "VIEWER"}, _ws_headers(self.tok_a)
        )
        self.api.handle_ws_member_invite(
            "ws-a", {"email": "two@example.com", "role": "EDITOR"}, _ws_headers(self.tok_a)
        )
        result = self.api.handle_ws_members_list("ws-a", _ws_headers(self.tok_a))
        self.assertEqual(result["statusCode"], 200)
        body   = _body(result)
        self.assertEqual(body["count"], 2)
        emails = {m["email"] for m in body["members"]}
        self.assertEqual(emails, {"one@example.com", "two@example.com"})

    def test_list_hides_token_hash(self):
        self.api.handle_ws_member_invite(
            "ws-a", {"email": "hashcheck@example.com", "role": "VIEWER"}, _ws_headers(self.tok_a)
        )
        result = self.api.handle_ws_members_list("ws-a", _ws_headers(self.tok_a))
        for m in _body(result)["members"]:
            self.assertNotIn("inviteTokenHash", m)

    # ── Cross-workspace isolation ──────────────────────────────────────────────

    def test_ws_b_cannot_list_ws_a_members(self):
        self.api.handle_ws_member_invite(
            "ws-a", {"email": "isolated@example.com", "role": "VIEWER"}, _ws_headers(self.tok_a)
        )
        result = self.api.handle_ws_members_list("ws-a", _ws_headers(self.tok_b))
        self.assertNotEqual(result["statusCode"], 200)

    def test_ws_b_cannot_invite_to_ws_a(self):
        result = self.api.handle_ws_member_invite(
            "ws-a",
            {"email": "cross@example.com", "role": "VIEWER"},
            _ws_headers(self.tok_b),
        )
        self.assertNotEqual(result["statusCode"], 201)

    def test_accept_invite_wrong_workspace_fails(self):
        inv_res = self.api.handle_ws_member_invite(
            "ws-a", {"email": "wstest@example.com", "role": "VIEWER"}, _ws_headers(self.tok_a)
        )
        token  = _body(inv_res)["inviteToken"]
        result = self.api.handle_ws_member_accept_invite("ws-b", {"token": token})
        self.assertNotEqual(result["statusCode"], 200)

    # ── API token role enforcement ─────────────────────────────────────────────

    def test_viewer_api_token_cannot_list_members(self):
        raw    = _make_api_token(self.st, "ws-a", role="VIEWER")
        result = self.api.handle_ws_members_list("ws-a", _api_headers(raw))
        self.assertNotEqual(result["statusCode"], 200)

    def test_editor_api_token_cannot_list_members(self):
        raw    = _make_api_token(self.st, "ws-a", role="EDITOR")
        result = self.api.handle_ws_members_list("ws-a", _api_headers(raw))
        self.assertNotEqual(result["statusCode"], 200)

    def test_viewer_api_token_cannot_invite(self):
        raw    = _make_api_token(self.st, "ws-a", role="VIEWER")
        result = self.api.handle_ws_member_invite(
            "ws-a", {"email": "v@example.com", "role": "VIEWER"}, _api_headers(raw)
        )
        self.assertNotEqual(result["statusCode"], 201)

    def test_editor_api_token_cannot_invite(self):
        raw    = _make_api_token(self.st, "ws-a", role="EDITOR")
        result = self.api.handle_ws_member_invite(
            "ws-a", {"email": "e@example.com", "role": "VIEWER"}, _api_headers(raw)
        )
        self.assertNotEqual(result["statusCode"], 201)

    def test_admin_api_token_can_invite(self):
        raw    = _make_api_token(self.st, "ws-a", role="ADMIN")
        result = self.api.handle_ws_member_invite(
            "ws-a", {"email": "apiadmin@example.com", "role": "VIEWER"}, _api_headers(raw)
        )
        self.assertEqual(result["statusCode"], 201)

    def test_admin_api_token_can_list(self):
        raw    = _make_api_token(self.st, "ws-a", role="ADMIN")
        result = self.api.handle_ws_members_list("ws-a", _api_headers(raw))
        self.assertEqual(result["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
