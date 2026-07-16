"""
Tests for POST /workspaces/:wsId/accounts/validate-role

Covers:
- Invalid account ID format
- Invalid Role ARN format
- ARN/account ID mismatch
- STS AssumeRole failure -> ASSUME_ROLE_FAILED
- AccessDenied maps to ACCESS_DENIED
- ExternalId error maps to EXTERNAL_ID_MISMATCH
- Success returns validated=true
- Account save revalidates before persisting
- Account save blocked on validation failure
- Workspace isolation (ws-A cannot act in ws-B)
- Raw boto3 exception text not exposed to frontend
"""

import hashlib
import importlib
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _load(tmp_path):
    os.environ["STORAGE_BACKEND"] = "file"
    os.environ["EOL_DATA_DIR"] = str(tmp_path)
    import storage
    import api_handler
    importlib.reload(storage)
    importlib.reload(api_handler)
    return storage.FileBackend(), api_handler


def _ws_headers(raw_token: str) -> dict:
    return {"x-workspace-token": raw_token}


def _seed_workspace(st, ws_id: str, raw_token: str):
    st.save_workspace({
        "id": ws_id,
        "name": "Test WS",
        "token_hash": hashlib.sha256(raw_token.encode()).hexdigest(),
    })


VALID_ARN    = "arn:aws:iam::123456789012:role/EOLMonitorReadOnly"
VALID_ACCT   = "123456789012"
VALID_EXT_ID = "eolm-TEST-001"

BASE_BODY = {
    "roleArn":      VALID_ARN,
    "externalId":   VALID_EXT_ID,
    "awsAccountId": VALID_ACCT,
    "accountName":  "test-account",
}


def _call(api, ws_id, body, token="ws-token-abc"):
    return api.handle_ws_account_validate_role(ws_id, body, _ws_headers(token))


def _error_code(result):
    body = json.loads(result["body"])
    return body.get("error", {}).get("code")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_invalid_account_id_rejected(tmp_path):
    st, api = _load(tmp_path)
    _seed_workspace(st, "ws-1", "tok")
    body = {**BASE_BODY, "awsAccountId": "12345"}        # too short
    r = api.handle_ws_account_validate_role("ws-1", body, _ws_headers("tok"))
    assert r["statusCode"] == 400
    assert _error_code(r) == "INVALID_ACCOUNT_ID"


def test_invalid_role_arn_rejected(tmp_path):
    st, api = _load(tmp_path)
    _seed_workspace(st, "ws-1", "tok")
    body = {**BASE_BODY, "roleArn": "not-an-arn"}
    r = _call(api, "ws-1", body, "tok")
    assert r["statusCode"] == 400
    assert _error_code(r) == "INVALID_ROLE_ARN"


def test_arn_account_mismatch_rejected(tmp_path):
    st, api = _load(tmp_path)
    _seed_workspace(st, "ws-1", "tok")
    # ARN has different account than awsAccountId
    body = {**BASE_BODY, "roleArn": "arn:aws:iam::999999999999:role/EOLMonitorReadOnly"}
    r = _call(api, "ws-1", body, "tok")
    assert r["statusCode"] == 400
    assert _error_code(r) == "ROLE_ACCOUNT_MISMATCH"


def test_missing_external_id_rejected(tmp_path):
    st, api = _load(tmp_path)
    _seed_workspace(st, "ws-1", "tok")
    body = {**BASE_BODY, "externalId": ""}
    r = _call(api, "ws-1", body, "tok")
    assert r["statusCode"] == 400
    assert _error_code(r) == "VALIDATION_FAILED"


def test_assume_role_failure_returns_safe_code(tmp_path):
    st, api = _load(tmp_path)
    _seed_workspace(st, "ws-1", "tok")
    with patch("api_handler.boto3") as mock_boto:
        mock_sts = MagicMock()
        mock_boto.client.return_value = mock_sts
        mock_sts.assume_role.side_effect = Exception(
            "An error occurred (NoSuchEntity) when calling the AssumeRole operation"
        )
        r = _call(api, "ws-1", BASE_BODY, "tok")
    assert r["statusCode"] == 403
    assert _error_code(r) == "ASSUME_ROLE_FAILED"


def test_access_denied_maps_to_access_denied_code(tmp_path):
    st, api = _load(tmp_path)
    _seed_workspace(st, "ws-1", "tok")
    with patch("api_handler.boto3") as mock_boto:
        mock_sts = MagicMock()
        mock_boto.client.return_value = mock_sts
        mock_sts.assume_role.side_effect = Exception(
            "An error occurred (AccessDenied) when calling the AssumeRole operation"
        )
        r = _call(api, "ws-1", BASE_BODY, "tok")
    assert r["statusCode"] == 403
    assert _error_code(r) == "ACCESS_DENIED"


def test_external_id_error_maps_correctly(tmp_path):
    st, api = _load(tmp_path)
    _seed_workspace(st, "ws-1", "tok")
    with patch("api_handler.boto3") as mock_boto:
        mock_sts = MagicMock()
        mock_boto.client.return_value = mock_sts
        mock_sts.assume_role.side_effect = Exception(
            "ExternalId does not match the condition in the trust policy"
        )
        r = _call(api, "ws-1", BASE_BODY, "tok")
    assert r["statusCode"] == 403
    assert _error_code(r) == "EXTERNAL_ID_MISMATCH"


def test_success_returns_validated_true(tmp_path):
    st, api = _load(tmp_path)
    _seed_workspace(st, "ws-1", "tok")
    with patch("api_handler.boto3") as mock_boto:
        mock_sts = MagicMock()
        mock_boto.client.return_value = mock_sts
        mock_sts.assume_role.return_value = {"Credentials": {
            "AccessKeyId": "AK", "SecretAccessKey": "SK", "SessionToken": "ST"
        }}
        mock_sts.get_caller_identity.return_value = {"Account": VALID_ACCT}
        r = _call(api, "ws-1", BASE_BODY, "tok")
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["ok"] is True
    assert body["validated"] is True
    assert body["accountId"] == VALID_ACCT


def test_raw_boto3_error_not_exposed(tmp_path):
    st, api = _load(tmp_path)
    _seed_workspace(st, "ws-1", "tok")
    secret_internal_msg = "INTERNAL_SECRET_ARN_xyz_DO_NOT_LEAK"
    with patch("api_handler.boto3") as mock_boto:
        mock_sts = MagicMock()
        mock_boto.client.return_value = mock_sts
        mock_sts.assume_role.side_effect = Exception(secret_internal_msg)
        r = _call(api, "ws-1", BASE_BODY, "tok")
    body_str = r["body"]
    assert secret_internal_msg not in body_str


def test_workspace_isolation(tmp_path):
    """ws-A cannot call validate-role for ws-B."""
    st, api = _load(tmp_path)
    _seed_workspace(st, "ws-A", "tok-a")
    _seed_workspace(st, "ws-B", "tok-b")
    # Using ws-A token against ws-B workspace
    r = api.handle_ws_account_validate_role("ws-B", BASE_BODY, _ws_headers("tok-a"))
    assert r["statusCode"] == 401


def test_save_blocked_on_validation_failure(tmp_path):
    st, api = _load(tmp_path)
    _seed_workspace(st, "ws-1", "tok")
    save_body = {
        "id": "conn-1",
        "accountId": VALID_ACCT,
        "roleArn": VALID_ARN,
        "externalId": VALID_EXT_ID,
        "accountName": "test",
        "workspace_id": "ws-1",
    }
    with patch("api_handler.boto3") as mock_boto:
        mock_sts = MagicMock()
        mock_boto.client.return_value = mock_sts
        mock_sts.assume_role.side_effect = Exception(
            "An error occurred (AccessDenied) when calling the AssumeRole operation"
        )
        r = api.handle_ws_account_save("ws-1", save_body, _ws_headers("tok"))
    assert r["statusCode"] == 403
    # Account must NOT have been saved
    accounts = st.get_accounts("ws-1")
    assert not any(a.get("id") == "conn-1" for a in accounts)


def test_save_revalidates_and_saves_on_success(tmp_path):
    st, api = _load(tmp_path)
    _seed_workspace(st, "ws-1", "tok")
    save_body = {
        "id": "conn-1",
        "accountId": VALID_ACCT,
        "roleArn": VALID_ARN,
        "externalId": VALID_EXT_ID,
        "accountName": "test",
        "workspace_id": "ws-1",
    }
    with patch("api_handler.boto3") as mock_boto:
        mock_sts = MagicMock()
        mock_boto.client.return_value = mock_sts
        mock_sts.assume_role.return_value = {"Credentials": {
            "AccessKeyId": "AK", "SecretAccessKey": "SK", "SessionToken": "ST"
        }}
        mock_sts.get_caller_identity.return_value = {"Account": VALID_ACCT}
        r = api.handle_ws_account_save("ws-1", save_body, _ws_headers("tok"))
    assert r["statusCode"] == 200
    accounts = st.get_accounts("ws-1")
    assert any(a.get("id") == "conn-1" for a in accounts)
