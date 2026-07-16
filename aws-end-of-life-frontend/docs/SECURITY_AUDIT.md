# Security Audit — Phase 1

**Audit date:** June 2026  
**Result:** PASS (no P0 vulnerabilities found)

---

## Workspace Isolation Model

Every resource in the system is scoped to a workspace. A workspace is identified by a `workspaceId` and protected by a `workspaceToken`. The token is stored only as a SHA-256 hash in the database.

```
Client request
  └─ X-Workspace-Token: eolm_live_xxxx
       └─ SHA-256(token) == workspace.token_hash?
            ├─ Yes → authorized, set actor.role = ADMIN
            └─ No  → 401 WORKSPACE_TOKEN_INVALID
```

API tokens (`eolm_api_xxx`) and member session tokens (`eolm_member_xxx`) follow the same hash-comparison model and are additionally scoped to a `workspace_id` in storage — a token found in Workspace A cannot satisfy auth for Workspace B even if presented.

---

## Token Model

| Token type | Format | Stored as | Scope |
|---|---|---|---|
| Workspace token | `eolm_live_xxxx` | SHA-256 hash | Full workspace ADMIN |
| API token | `eolm_api_xxxx` | SHA-256 hash | Workspace + explicit role |
| Member session | `eolm_member_xxxx` | SHA-256 hash | Workspace + member's role |
| Admin portal token | env var or file | SHA-256 hash in memory | System-level only |

Plaintext tokens are:
- Shown once at creation
- Never logged
- Never stored in the database
- Never returned by any API endpoint after initial creation

---

## API Authorization Checks

Every `handle_ws_*` function begins with:

```python
ws, actor, err_code = _verify_workspace_access(workspace_id, headers, required_role)
if not ws:
    return _error_resp(401, err_code, "Workspace authentication failed")
```

`_verify_workspace_access` resolves the caller in order:
1. API token (`X-API-Token` or `Authorization: Bearer eolm_api_xxx`)
2. Member session token (`X-Workspace-Token: eolm_member_xxx`)
3. Workspace owner token (`X-Workspace-Token: eolm_live_xxx`)

All paths include workspace ownership check — token lookup is keyed by `(token_hash, workspace_id)`.

---

## Role-Based Permissions

| Action | Required role |
|---|---|
| View inventory / summary / alerts | VIEWER |
| View resource detail | VIEWER |
| Run scan | EDITOR |
| Add / edit connected account | ADMIN |
| Delete connected account | ADMIN |
| Manage members / invites | ADMIN |
| Rotate workspace token | ADMIN |
| Manage API tokens | ADMIN |
| Change notification settings | ADMIN |

Backend enforces these. Frontend hides buttons, but the backend will reject unauthorized API calls regardless.

---

## Direct URL / API Bypass Protections

### Account ownership
```python
accounts = storage.get_accounts(workspace_id)        # filtered to workspace
account  = next((a for a in accounts if a.get("id") == account_id), None)
if not account:
    return _error_resp(404, "ACCOUNT_NOT_FOUND", ...)
```
An `account_id` from a different workspace returns 404 because `get_accounts(workspace_id)` only returns accounts belonging to that workspace.

### Resource ownership
```python
item = storage.get_resource_by_id(decoded_id, workspace_id)
if not item:
    return resp(404, {"error": "Resource not found"})
```
Storage layer enforces the workspace filter — a resource ARN from another workspace returns 404.

### Scan ownership
```python
run = storage.get_scan_run(scan_id)
if not run or run.get("workspaceId") != workspace_id:
    return _error_resp(404, "SCAN_NOT_FOUND", ...)
```
Scan IDs are not guessable (`scan_xxx` with 24 random hex chars) and are workspace-tagged.

---

## IAM Trust Policy

The CloudFormation template deployed in customer accounts enforces:

```yaml
Principal:
  AWS: "arn:aws:iam::495234635788:role/EOLMonitorBackendEC2Role"
Condition:
  StringEquals:
    sts:ExternalId: !Ref ExternalId
```

- Principal is hardcoded to the backend EC2 role — customers cannot supply a different account.
- ExternalId is generated per-connection and stored in the account record.
- Without the correct ExternalId, AssumeRole fails with `AccessDenied`.

---

## Read-Only Policy

The IAM policy attached to the customer role grants only `Describe*`, `List*`, `Get*` actions. It explicitly excludes:

- `ec2:RunInstances`, `ec2:TerminateInstances`
- `rds:DeleteDBInstance`, `rds:CreateDBSnapshot` (etc.)
- `lambda:InvokeFunction`, `lambda:DeleteFunction`
- Any write/delete action on any service

Full policy: `aws-end-of-life-frontend/iam/eol-collector-policy.json`

---

## CORS Production Guard

In `api_handler.py`:

```python
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

if ALLOWED_ORIGIN == "*":
    if _IS_PRODUCTION:   # APP_ENV=production
        raise RuntimeError("FATAL: CORS wildcard not allowed in production...")
    logger.warning("SECURITY: CORS wildcard active. Set ALLOWED_ORIGIN in production.")
```

- Development/staging: wildcard allowed with a warning logged.
- Production (`APP_ENV=production`): server refuses to start if `ALLOWED_ORIGIN=*`.
- Set `ALLOWED_ORIGIN=https://yourdomain.com` before any public exposure.

---

## Legacy Route Deprecation

All pre-workspace routes now return `410 GONE`:

```
GET  /eol/inventory  → 410 ROUTE_DEPRECATED
GET  /eol/summary    → 410 ROUTE_DEPRECATED
GET  /eol/resource/* → 410 ROUTE_DEPRECATED
GET  /eol/alerts     → 410 ROUTE_DEPRECATED
POST /workspaces/:wsId/accounts/:acctId/scan → 410 ROUTE_DEPRECATED (use /scans)
```

None of these routes reach unprotected handler functions.

---

## Logging / Security Notes

- Workspace tokens are **never** logged.
- Admin tokens are **never** logged.
- RoleArn and ExternalId may appear in logs (acceptable — not secret).
- AWS credentials obtained via AssumeRole are never stored or logged.
- Backend stack traces are not exposed in API error responses (sanitized to `error.code` + `error.message`).

---

## P0/P1 Findings and Status

| Finding | Severity | Status |
|---|---|---|
| Workspace isolation (token hash comparison) | P0 | PASS |
| Cross-workspace token bypass | P0 | PASS — lookup keyed by (hash, workspace_id) |
| Account ownership bypass | P0 | PASS — get_accounts(workspace_id) filtered |
| Resource ownership bypass | P0 | PASS — get_resource_by_id includes workspace |
| Scan ownership bypass | P0 | PASS — workspaceId field verified |
| Role bypass (viewer run scan) | P0 | PASS — backend enforces EDITOR |
| Role bypass (viewer delete) | P0 | PASS — backend enforces ADMIN |
| Legacy routes expose data | P0 | PASS — all return 410 |
| CORS wildcard in production | P1 | PASS — RuntimeError guard |
| IAM ExternalId optional | P1 | PASS — required in CF + validate-role |
| CF template wrong principal | P1 | PASS — hardcoded to backend EC2 role |
| Workspace token in logs | P1 | PASS — never logged |
| Admin token in frontend | P1 | PASS — never exposed to client |

---

## Manual Security Test Commands

Replace `<WS_ID>` and `<TOKEN>` with your values.

```bash
API="http://127.0.0.1:3001"
WS_ID="ws_xxxxxxxxxxxxxxxx"
TOKEN="eolm_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# 1. Missing token → must return 401
curl -i "$API/workspaces/$WS_ID/inventory"

# 2. Wrong token → must return 401
curl -i "$API/workspaces/$WS_ID/inventory" \
  -H "X-Workspace-Token: wrong_token"

# 3. Correct token → must return 200
curl -i "$API/workspaces/$WS_ID/inventory" \
  -H "X-Workspace-Token: $TOKEN"

# 4. Token from workspace A against workspace B → must return 401
WS_B="ws_another_workspace_id"
curl -i "$API/workspaces/$WS_B/inventory" \
  -H "X-Workspace-Token: $TOKEN"

# 5. Account from another workspace → must return 404
OTHER_ACCT="conn_account_from_another_ws"
curl -i -X POST "$API/workspaces/$WS_ID/accounts/$OTHER_ACCT/scans" \
  -H "X-Workspace-Token: $TOKEN"

# 6. Resource from another workspace → must return 404
OTHER_RESOURCE="arn:aws:lambda:us-east-1:999999999999:function:some-function"
curl -i "$API/workspaces/$WS_ID/resource/$(python3 -c "import urllib.parse; print(urllib.parse.quote('$OTHER_RESOURCE', safe=''))")" \
  -H "X-Workspace-Token: $TOKEN"
```

Expected results:

| Test | Expected HTTP |
|---|---|
| No token | 401 |
| Wrong token | 401 |
| Correct token | 200 |
| Token A → Workspace B | 401 |
| Account from other workspace | 404 |
| Resource from other workspace | 404 |
