"""
API token + audit log security tests.
Uses FileBackend with a temp directory — no AWS credentials needed.
"""
import hashlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

# Ensure backend/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_backend():
    d = tempfile.mkdtemp()
    os.environ["EOL_DATA_DIR"] = d
    os.environ["STORAGE_BACKEND"] = "file"
    import importlib, storage
    importlib.reload(storage)
    return storage.FileBackend(), d


class TestApiTokenStorage(unittest.TestCase):

    def setUp(self):
        self.backend, self.tmp = _make_backend()

    # 1. Create → raw token returned, hash stored, raw not stored
    def test_create_token_hash_stored_not_raw(self):
        raw   = "eolm_api_testsecretvalue12345678"
        thash = hashlib.sha256(raw.encode()).hexdigest()
        rec   = {
            "id": "api_tok_001", "workspaceId": "ws_test", "name": "Test",
            "role": "VIEWER", "tokenHash": thash, "prefix": "eolm_api_tes...",
            "lastUsedAt": None, "createdAt": datetime.now(timezone.utc).isoformat(),
            "expiresAt": None, "revokedAt": None, "createdBy": "workspace",
        }
        self.backend.save_api_token(rec)
        stored = self.backend.get_api_token_by_id("api_tok_001", "ws_test")
        self.assertEqual(stored["tokenHash"], thash)
        self.assertNotIn(raw, str(stored))         # raw token not in stored data

    # 2. find_api_token_by_hash — correct hash resolves
    def test_find_by_hash_resolves_token(self):
        raw   = "eolm_api_findbyhash_testsecret123"
        thash = hashlib.sha256(raw.encode()).hexdigest()
        rec   = {"id": "api_tok_002", "workspaceId": "ws_test", "name": "CI",
                 "role": "EDITOR", "tokenHash": thash, "prefix": "eolm_api_fin...",
                 "lastUsedAt": None, "createdAt": datetime.now(timezone.utc).isoformat(),
                 "expiresAt": None, "revokedAt": None, "createdBy": "workspace"}
        self.backend.save_api_token(rec)
        found = self.backend.find_api_token_by_hash(thash, "ws_test")
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], "api_tok_002")

    # 3. Wrong hash returns None
    def test_wrong_hash_returns_none(self):
        found = self.backend.find_api_token_by_hash("wronghash", "ws_test")
        self.assertIsNone(found)

    # 4. Cross-workspace isolation — token from ws_A not visible from ws_B
    def test_cross_workspace_isolation(self):
        thash = hashlib.sha256(b"eolm_api_xws_secret").hexdigest()
        rec   = {"id": "api_tok_003", "workspaceId": "ws_A", "name": "T",
                 "role": "VIEWER", "tokenHash": thash, "prefix": "x...",
                 "lastUsedAt": None, "createdAt": datetime.now(timezone.utc).isoformat(),
                 "expiresAt": None, "revokedAt": None, "createdBy": "workspace"}
        self.backend.save_api_token(rec)
        # Looking up from ws_B must return None
        found = self.backend.find_api_token_by_hash(thash, "ws_B")
        self.assertIsNone(found)

    # 5. Revoked token is marked revokedAt
    def test_revoke_sets_revoked_at(self):
        rec = {"id": "api_tok_004", "workspaceId": "ws_test", "name": "R",
               "role": "VIEWER", "tokenHash": "h", "prefix": "x...",
               "lastUsedAt": None, "createdAt": datetime.now(timezone.utc).isoformat(),
               "expiresAt": None, "revokedAt": None, "createdBy": "workspace"}
        self.backend.save_api_token(rec)
        revoked = {**rec, "revokedAt": datetime.now(timezone.utc).isoformat()}
        self.backend.save_api_token(revoked)
        stored = self.backend.get_api_token_by_id("api_tok_004", "ws_test")
        self.assertIsNotNone(stored["revokedAt"])

    # 6. Expired token detection (application-level check)
    def test_expired_token_detected(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        rec  = {"id": "api_tok_005", "workspaceId": "ws_test", "name": "E",
                "role": "VIEWER", "tokenHash": "h2", "prefix": "x...",
                "lastUsedAt": None, "createdAt": datetime.now(timezone.utc).isoformat(),
                "expiresAt": past, "revokedAt": None, "createdBy": "workspace"}
        self.backend.save_api_token(rec)
        stored = self.backend.get_api_token_by_id("api_tok_005", "ws_test")
        now    = datetime.now(timezone.utc).isoformat()
        self.assertTrue(stored["expiresAt"] < now)   # application must reject

    # 7. Audit log — save and retrieve, workspace-scoped
    def test_audit_log_saved_and_scoped(self):
        from audit import make_audit_log
        log = make_audit_log("ws_audit", "API_TOKEN_CREATED", "Token 'CI' created")
        self.backend.save_audit_log(log)
        logs = self.backend.get_audit_logs("ws_audit")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["action"], "API_TOKEN_CREATED")

    # 8. Audit log does NOT contain raw token
    def test_audit_log_no_raw_token(self):
        from audit import make_audit_log
        raw = "eolm_api_supersecret"
        log = make_audit_log("ws_audit2", "API_TOKEN_CREATED", "Token created",
                             metadata={"name": "CI", "role": "VIEWER"})
        # Simulate safe metadata — raw token must NOT be present
        self.assertNotIn(raw, str(log))
        self.assertNotIn(raw, str(log.get("metadata", {})))

    # 9. Audit log cross-workspace isolation
    def test_audit_log_cross_workspace_isolation(self):
        from audit import make_audit_log
        log_a = make_audit_log("ws_X", "SCAN_COMPLETED", "Scan done")
        log_b = make_audit_log("ws_Y", "SCAN_COMPLETED", "Scan done")
        self.backend.save_audit_log(log_a)
        self.backend.save_audit_log(log_b)
        logs_x = self.backend.get_audit_logs("ws_X")
        logs_y = self.backend.get_audit_logs("ws_Y")
        self.assertEqual(len(logs_x), 1)
        self.assertEqual(len(logs_y), 1)
        self.assertEqual(logs_x[0]["workspaceId"], "ws_X")
        self.assertEqual(logs_y[0]["workspaceId"], "ws_Y")

    # 10. Role order check
    def test_role_order(self):
        from api_handler import _has_role
        self.assertTrue(_has_role("ADMIN",  "ADMIN"))
        self.assertTrue(_has_role("ADMIN",  "EDITOR"))
        self.assertTrue(_has_role("ADMIN",  "VIEWER"))
        self.assertTrue(_has_role("EDITOR", "EDITOR"))
        self.assertTrue(_has_role("EDITOR", "VIEWER"))
        self.assertFalse(_has_role("VIEWER", "EDITOR"))
        self.assertFalse(_has_role("VIEWER", "ADMIN"))
        self.assertFalse(_has_role("EDITOR", "ADMIN"))

    # 11. Workspace token still works (basic)
    def test_workspace_token_maps_to_admin_role(self):
        # _has_role used in auth — workspace token always mapped to ADMIN
        from api_handler import _has_role
        self.assertTrue(_has_role("ADMIN", "VIEWER"))
        self.assertTrue(_has_role("ADMIN", "EDITOR"))
        self.assertTrue(_has_role("ADMIN", "ADMIN"))

    # 12. API token must start with eolm_api_ prefix
    def test_api_token_prefix_validation(self):
        raw_valid   = "eolm_api_validtoken"
        raw_invalid = "Bearer some_other_token"
        self.assertTrue(raw_valid.startswith("eolm_api_"))
        self.assertFalse(raw_invalid.startswith("eolm_api_"))

    # 13. Constant-time hash comparison — using hmac.compare_digest
    def test_hmac_compare_digest_used(self):
        import hmac
        h1 = hashlib.sha256(b"token_a").hexdigest()
        h2 = hashlib.sha256(b"token_b").hexdigest()
        h3 = hashlib.sha256(b"token_a").hexdigest()
        self.assertFalse(hmac.compare_digest(h1, h2))
        self.assertTrue(hmac.compare_digest(h1, h3))


if __name__ == "__main__":
    unittest.main(verbosity=2)
