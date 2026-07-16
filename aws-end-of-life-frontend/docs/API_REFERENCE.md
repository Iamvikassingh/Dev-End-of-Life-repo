# API Reference — AWS EOL Monitor Backend

**Base URL:** `http://<server>:3001`  
**Auth header:** `X-Workspace-Token: eolm_live_xxxx` (or `eolm_member_xxxx` / `eolm_api_xxxx`)

---

## Authentication

All workspace endpoints require a token in the `X-Workspace-Token` header (or `Authorization: Bearer <token>` for API tokens).

| Token type | Header | Notes |
|---|---|---|
| Workspace owner | `X-Workspace-Token: eolm_live_xxxx` | Full ADMIN access |
| Member session | `X-Workspace-Token: eolm_member_xxxx` | Role inherited from invite |
| API token | `X-API-Token: eolm_api_xxxx` or `Authorization: Bearer eolm_api_xxxx` | Role set at token creation |
| Admin portal | `X-Admin-Token: <admin_token>` | System-level only |

---

## Error Response Shape

```json
{
  "error": {
    "code": "WORKSPACE_TOKEN_INVALID",
    "message": "Workspace authentication failed"
  }
}
```

Common error codes:

| Code | HTTP | Meaning |
|---|---|---|
| `WORKSPACE_TOKEN_INVALID` | 401 | Missing or wrong token |
| `INSUFFICIENT_ROLE` | 403 | Token valid but role not high enough |
| `ACCOUNT_NOT_FOUND` | 404 | Account not in this workspace |
| `SCAN_NOT_FOUND` | 404 | Scan run not in this workspace |
| `RESOURCE_NOT_FOUND` | 404 | Resource not in this workspace |
| `ROUTE_DEPRECATED` | 410 | Legacy route — no longer supported |
| `VALIDATION_ERROR` | 400 | Missing/invalid request field |

---

## Workspace Endpoints

### Create Workspace

```
POST /workspaces
Body: { "name": "My Team" }
```

Response `201`:
```json
{
  "workspace": {
    "id": "ws_abc123",
    "name": "My Team",
    "createdAt": "2026-06-01T00:00:00Z"
  },
  "token": "eolm_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

Token shown only once. Not returned again.

---

### Get Workspace

```
GET /workspaces/:wsId
Headers: X-Workspace-Token
```

Response `200`:
```json
{
  "workspace": {
    "id": "ws_abc123",
    "name": "My Team",
    "plan": "free",
    "createdAt": "2026-06-01T00:00:00Z"
  }
}
```

---

## Account Endpoints

### List Accounts

```
GET /workspaces/:wsId/accounts
Headers: X-Workspace-Token (VIEWER+)
```

Response `200`:
```json
{
  "accounts": [
    {
      "id": "conn_abc123",
      "displayName": "Production",
      "awsAccountId": "123456789012",
      "roleArn": "arn:aws:iam::123456789012:role/EOLMonitorScanRole",
      "lastScanAt": "2026-06-01T12:00:00Z",
      "lastScanStatus": "completed",
      "connectedAt": "2026-05-01T00:00:00Z"
    }
  ]
}
```

---

### Validate Role (before saving)

```
POST /workspaces/:wsId/accounts/validate-role
Headers: X-Workspace-Token (ADMIN)
Body: { "roleArn": "...", "externalId": "...", "awsAccountId": "..." }
```

Response `200`:
```json
{ "valid": true }
```

or:
```json
{ "valid": false, "error": "ASSUME_ROLE_FAILED" }
```

---

### Add Account

```
POST /workspaces/:wsId/accounts
Headers: X-Workspace-Token (ADMIN)
Body:
{
  "displayName": "Production",
  "awsAccountId": "123456789012",
  "roleArn": "arn:aws:iam::123456789012:role/EOLMonitorScanRole",
  "externalId": "eolm-ext-xxxx"
}
```

Response `201`:
```json
{
  "account": {
    "id": "conn_abc123",
    "displayName": "Production",
    "awsAccountId": "123456789012"
  }
}
```

---

### Delete Account

```
DELETE /workspaces/:wsId/accounts/:acctId
Headers: X-Workspace-Token (ADMIN)
```

Response `200`: `{ "deleted": true }`

---

## Scan Endpoints

### Start Scan

```
POST /workspaces/:wsId/accounts/:acctId/scans
Headers: X-Workspace-Token (EDITOR+)
Body (optional): { "regions": ["us-east-1", "eu-west-1"] }
```

Response `202`:
```json
{
  "scanId": "scan_abc123xxxxxxxxxxxx",
  "status": "running",
  "startedAt": "2026-06-01T12:00:00Z"
}
```

---

### Get Scan Status

```
GET /workspaces/:wsId/accounts/:acctId/scans/:scanId
Headers: X-Workspace-Token (VIEWER+)
```

Response `200`:
```json
{
  "scanId": "scan_abc123",
  "status": "completed",
  "startedAt": "2026-06-01T12:00:00Z",
  "completedAt": "2026-06-01T12:01:45Z",
  "summary": {
    "total": 42,
    "eol": 3,
    "expiringSoon": 5,
    "extendedSupport": 2,
    "supported": 29,
    "unknown": 2,
    "needsInspection": 1,
    "lifecycleNotTracked": 0
  },
  "warnings": []
}
```

Scan status values: `"running"` | `"completed"` | `"failed"`

---

### List Scan History

```
GET /workspaces/:wsId/accounts/:acctId/scans
Headers: X-Workspace-Token (VIEWER+)
```

Response `200`:
```json
{
  "scans": [
    {
      "scanId": "scan_abc123",
      "status": "completed",
      "startedAt": "2026-06-01T12:00:00Z",
      "summary": { ... }
    }
  ]
}
```

---

## Inventory Endpoints

### Get Workspace Inventory

```
GET /workspaces/:wsId/inventory
Headers: X-Workspace-Token (VIEWER+)
Query params: ?accountId=conn_abc123 (optional filter)
```

Response `200`:
```json
{
  "items": [
    {
      "id": "base64-encoded-resource-id",
      "resource_name": "my-lambda",
      "resource_arn": "arn:aws:lambda:us-east-1:123456789012:function:my-lambda",
      "service_type": "Lambda",
      "version": "python3.12",
      "region": "us-east-1",
      "eol_status": "SUPPORTED",
      "eol_date": "2026-12-01",
      "support_end_date": null,
      "days_to_eol": 175,
      "classification_reason": "within lifecycle",
      "account_id": "conn_abc123",
      "aws_account_id": "123456789012",
      "last_seen": "2026-06-01T12:00:00Z"
    }
  ],
  "total": 42
}
```

---

### Get Resource Detail

```
GET /workspaces/:wsId/resource/:encodedArn
Headers: X-Workspace-Token (VIEWER+)
```

`:encodedArn` is URL-encoded ARN or base64-encoded resource ID.

Response `200`: Single resource object (same shape as inventory item, with additional detail).

---

## Summary Endpoint

```
GET /workspaces/:wsId/summary
Headers: X-Workspace-Token (VIEWER+)
```

Response `200`:
```json
{
  "resources": {
    "total": 42,
    "eol": 3,
    "expiringSoon": 5,
    "extendedSupport": 2,
    "supported": 29,
    "unknown": 2,
    "needsInspection": 1,
    "lifecycleNotTracked": 0
  },
  "accounts": {
    "total": 2,
    "connected": 2,
    "lastScanAt": "2026-06-01T12:00:00Z"
  },
  "topRisks": [
    {
      "resource_name": "old-rds-db",
      "service_type": "RDS",
      "version": "mysql8.0",
      "eol_status": "EOL",
      "days_to_eol": -30
    }
  ]
}
```

---

## Alerts Endpoints

### List Alerts

```
GET /workspaces/:wsId/alerts
Headers: X-Workspace-Token (VIEWER+)
Query params: ?status=active (active|acknowledged|snoozed|resolved)
```

Response `200`:
```json
{
  "alerts": [
    {
      "id": "alert_abc123",
      "resourceId": "...",
      "resourceName": "old-lambda",
      "serviceType": "Lambda",
      "status": "active",
      "eolStatus": "EOL",
      "daysToEol": -5,
      "createdAt": "2026-06-01T00:00:00Z"
    }
  ]
}
```

---

### Update Alert

```
PATCH /workspaces/:wsId/alerts/:alertId
Headers: X-Workspace-Token (EDITOR+)
Body: { "status": "acknowledged" }
```

Valid status values: `"acknowledged"` | `"snoozed"` | `"resolved"` | `"active"`

Response `200`: Updated alert object.

---

## Members & Invites

### List Members

```
GET /workspaces/:wsId/members
Headers: X-Workspace-Token (ADMIN)
```

Response `200`:
```json
{
  "members": [
    {
      "id": "member_abc123",
      "email": "alice@example.com",
      "role": "EDITOR",
      "joinedAt": "2026-05-15T00:00:00Z"
    }
  ]
}
```

---

### Create Invite

```
POST /workspaces/:wsId/invites
Headers: X-Workspace-Token (ADMIN)
Body: { "email": "alice@example.com", "role": "EDITOR" }
```

Response `201`:
```json
{
  "inviteToken": "eolm_inv_xxxx",
  "inviteUrl": "/join?token=eolm_inv_xxxx",
  "email": "alice@example.com",
  "role": "EDITOR",
  "expiresAt": "2026-06-08T00:00:00Z"
}
```

---

### Accept Invite

```
POST /workspaces/:wsId/invites/:inviteToken/accept
Body: { "displayName": "Alice" }
```

Response `200`:
```json
{
  "sessionToken": "eolm_member_xxxx",
  "member": { "id": "member_abc123", "role": "EDITOR" }
}
```

---

## API Token Endpoints

### Create API Token

```
POST /workspaces/:wsId/api-tokens
Headers: X-Workspace-Token (ADMIN)
Body: { "name": "CI Pipeline", "role": "VIEWER" }
```

Response `201`:
```json
{
  "tokenId": "tok_abc123",
  "name": "CI Pipeline",
  "token": "eolm_api_xxxx",
  "role": "VIEWER",
  "createdAt": "2026-06-01T00:00:00Z"
}
```

Token shown once.

---

### List API Tokens

```
GET /workspaces/:wsId/api-tokens
Headers: X-Workspace-Token (ADMIN)
```

Response `200`: List of token metadata (no plaintext token values).

---

### Delete API Token

```
DELETE /workspaces/:wsId/api-tokens/:tokenId
Headers: X-Workspace-Token (ADMIN)
```

Response `200`: `{ "deleted": true }`

---

## General EOL Lookup (Public)

```
GET /eol/lookup?service=<slug>&version=<version>
```

No auth required. Uses cached data from `endoflife.date`.

Response `200`:
```json
{
  "service": "amazon-opensearch",
  "version": "3.5",
  "status": "SUPPORTED",
  "eol_date": "2025-09-15",
  "days_to_eol": 177,
  "source": "endoflife.date"
}
```

---

## Health Check

```
GET /health
```

No auth required.

Response `200`: `{ "status": "ok", "version": "1.0.0" }`

---

## Admin Endpoints (System Admin only)

```
GET  /admin/workspaces          — list all workspaces
GET  /admin/workspaces/:wsId    — get workspace detail
DELETE /admin/workspaces/:wsId  — delete workspace and all data
```

All require `X-Admin-Token: <admin_token>` header. Admin token set via `ADMIN_TOKEN` env var.

---

## Deprecated Routes (return 410)

```
GET  /eol/inventory       → 410 ROUTE_DEPRECATED
GET  /eol/summary         → 410 ROUTE_DEPRECATED
GET  /eol/resource/*      → 410 ROUTE_DEPRECATED
GET  /eol/alerts          → 410 ROUTE_DEPRECATED
POST /workspaces/:wsId/accounts/:acctId/scan  → 410 ROUTE_DEPRECATED
```

Use `/workspaces/:wsId/inventory` and `/workspaces/:wsId/accounts/:acctId/scans` instead.
