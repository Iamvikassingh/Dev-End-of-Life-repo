# User Flow Guide — AWS EOL Monitor

---

## Flow 1: New User — Create Workspace

```
Landing page
  └─ "Get Started" / "Create Workspace"
       └─ Enter workspace name
            └─ POST /workspaces → {workspaceId, workspaceToken}
                 └─ Token shown ONCE — copy and store securely
                      └─ Redirect to Dashboard
```

**Key point:** The workspace token is shown only once at creation. There is no recovery flow; if lost, rotate it from Settings.

---

## Flow 2: Returning User — Access Workspace

```
Landing page
  └─ "Enter Workspace"
       └─ Enter workspaceId + workspaceToken
            └─ GET /workspaces/:wsId (with token header)
                 ├─ Valid → Redirect to Dashboard
                 └─ Invalid → "Invalid token" error
```

Session is stored in browser localStorage. Clearing localStorage or opening a new browser requires re-entering credentials.

---

## Flow 3: Connect an AWS Account

```
Dashboard → "Add Account"
  └─ Step 1: Enter AWS Account ID + display name
       └─ ExternalId is auto-generated and shown
            └─ Step 2: Copy CloudFormation template
                 └─ Deploy CF stack in your AWS account
                      ├─ CLI: aws cloudformation deploy ...
                      └─ Console: upload template, add ExternalId parameter
                           └─ Step 3: Enter Role ARN from CF Outputs
                                └─ POST /workspaces/:wsId/accounts/validate-role
                                     ├─ Valid → Account saved
                                     └─ Invalid → Error with reason
```

See `docs/IAM_SETUP.md` for CloudFormation template and troubleshooting.

---

## Flow 4: Run a Scan

```
Connected Accounts page
  └─ Select account → "Run Scan" / "Scan Again"
       └─ [Optional] Select regions or "All regions"
            └─ POST /workspaces/:wsId/accounts/:acctId/scans
                 └─ Scan starts (async background job)
                      └─ Poll GET /workspaces/:wsId/accounts/:acctId/scans/:scanId
                           ├─ status: "running" → show progress spinner
                           └─ status: "completed" | "failed"
                                └─ Results loaded in Account Results page
```

Typical scan duration: 30–120 seconds depending on region count and resource volume.

---

## Flow 5: View Account Results

```
Account Results page (/accounts/:acctId)
  └─ Summary cards (7 statuses)
       └─ Main row: EOL / Expiring Soon / Extended Support / Supported / Unknown
       └─ Secondary row (if any): Needs Inspection / Lifecycle Not Tracked
            └─ Resource table with filters
                 ├─ Filter tabs: All / EOL / Expiring Soon / Extended Support / Supported /
                 │               Unknown / Needs Inspection / Lifecycle Not Tracked
                 ├─ Sort by: Service / Status / Version / EOL Date
                 └─ Click resource → Resource Detail page
```

**EOL Date column behavior:**
- `NEEDS_INSPECTION` / `LIFECYCLE_NOT_TRACKED` → shows `—`
- Date announced → shows `YYYY-MM-DD`
- No date available → shows `—`

---

## Flow 6: View Resource Detail

```
Resource table → click row
  └─ Resource Detail page
       └─ Service info, version, status, region
            └─ EOL Timeline bar (visual days-to-EOL)
            └─ Lifecycle history
            └─ Upgrade recommendations (if available)
```

---

## Flow 7: Dashboard Overview

```
Dashboard
  └─ Summary cards: total resources by status across all accounts
       └─ Risk trend chart (EOL count over scan history)
       └─ Top EOL risks list
       └─ Recent scan runs
            └─ Quick "View Results" links per account
```

---

## Flow 8: Services Overview Page

```
Services page (/services)
  └─ All scanned service types with EOL count
       └─ Clicking a service filters inventory to that service type
```

---

## Flow 9: Alerts

```
Alerts page (/alerts)
  └─ Active alerts (EOL/Expiring resources requiring attention)
       └─ Acknowledge → removes from active, moves to acknowledged
       └─ Snooze → hide for N days
       └─ Resolve → mark as resolved (handled)
```

Alert generation is triggered on scan completion for:
- New EOL resources (not seen before)
- Resources transitioning to EXPIRING_SOON within 90 days

---

## Flow 10: Settings

```
Settings page (/settings)
  └─ Workspace name
       └─ Notification preferences
            └─ Email notifications (placeholder — Phase 1)
            └─ Slack webhook (placeholder — Phase 1)
       └─ Scan defaults (default region selection)
       └─ Danger zone: Delete workspace
```

---

## Flow 11: Manage Members (Admin only)

```
Settings → Members
  └─ View current members and roles
       └─ "Invite Member"
            └─ Enter email + assign role (ADMIN / EDITOR / VIEWER)
                 └─ POST /workspaces/:wsId/invites
                      └─ Invite link generated
                           └─ Share link with team member
                                └─ Member opens link → enters their display name
                                     └─ Member session token issued
                                          └─ Member accesses workspace with their role
```

**Roles:**
- `ADMIN` — full access, can manage accounts, members, tokens
- `EDITOR` — can run scans, view results
- `VIEWER` — read-only, can view inventory and alerts

---

## Flow 12: API Token Management (Admin only)

```
Settings → API Tokens
  └─ "Create Token" → name + role
       └─ Token shown once: eolm_api_xxxx
            └─ Use in scripts / CI:
                 curl -H "X-API-Token: eolm_api_xxxx" \
                      https://your-api/workspaces/:wsId/inventory
```

---

## Flow 13: Rotate Workspace Token (Admin only)

```
Settings → Security → "Rotate Token"
  └─ Confirm action
       └─ New token generated and shown once
            └─ All existing sessions using old token become invalid
                 └─ Update all integrations / team members with new token
```

---

## Flow 14: Admin Portal (System Admin only)

```
GET /admin/workspaces (X-Admin-Token header)
  └─ List all workspaces
       └─ View usage stats
            └─ Delete workspace (destructive)
```

The admin token is separate from workspace tokens. It is set via `ADMIN_TOKEN` environment variable. Never expose admin endpoints publicly.

---

## Error States

| Scenario | UI behavior |
|---|---|
| Invalid workspace token | Redirect to login with "Invalid token" |
| Account scan fails | Shows scan status "failed" with error reason |
| AssumeRole fails during scan | Error shown in scan results, account marked as connection error |
| endoflife.date API unreachable | Resources show UNKNOWN with reason "EOL API unavailable" |
| No resources found in account | Empty state with "No resources found in selected regions" |
| All regions scan, some regions fail | Partial results with warning banner listing failed regions |
