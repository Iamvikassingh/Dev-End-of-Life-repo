# Next Phase Roadmap

Features and improvements excluded from Phase 1, ordered by priority and complexity.

---

## Priority Legend

| Priority | Meaning |
|---|---|
| P1 | Critical for production launch |
| P2 | High value, next sprint |
| P3 | Medium value |
| P4 | Nice to have |

---

## P1 — Required for Production Launch

### 1. Scheduled Scans

**What:** Automated scan on a cron schedule (daily, weekly) per connected account.  
**Why excluded:** Requires job scheduler infrastructure; out of scope for demo.  
**Complexity:** Medium  
**Notes:** Backend scan logic is complete. Need: cron scheduler, PM2 or external scheduler integration, last-scan-time tracking in account record.

---

### 2. Email / Slack Alerts

**What:** Send notification when a resource enters EOL or EXPIRING_SOON.  
**Why excluded:** Notification preferences UI is a placeholder; delivery not wired.  
**Complexity:** Medium  
**Notes:** Alert records are already created on scan completion. Need: webhook delivery, email via SES, per-user / per-workspace notification prefs. Dedup logic to avoid re-notifying on the same resource.

---

### 3. Rate Limiting

**What:** Limit API requests per workspace/IP to prevent abuse.  
**Why excluded:** Demo/internal use only; rate limiting would add complexity with no demo benefit.  
**Complexity:** Low  
**Notes:** Add token-bucket or sliding-window middleware before all API endpoints. Consider: per-workspace (prevents one customer from flooding others), per-IP (prevents scraping).

---

### 4. HTTPS / TLS

**What:** HTTPS with a valid certificate on the public endpoint.  
**Why excluded:** Demo uses EC2 public IP only (HTTP acceptable for demo).  
**Complexity:** Low (Let's Encrypt / ACM + nginx)  
**Notes:** Required before any real customer data is sent over the wire.

---

### 5. DynamoDB or PostgreSQL Storage

**What:** Replace file-based storage with a real database.  
**Why excluded:** File-based storage is simpler to set up for demo and avoids provisioning costs.  
**Complexity:** High  
**Notes:** File-based storage is not atomic — concurrent writes risk partial data. Critical for multi-instance deployment. Storage layer is abstracted (`storage.*` calls) — swapping backends should not require changing business logic. DynamoDB recommended for serverless scale; PostgreSQL for relational queries.

---

## P2 — High Value, Next Sprint

### 6. ECR Image Inspection (SBOM)

**What:** Instead of NEEDS_INSPECTION, actually scan container images for OS/package lifecycle.  
**Why excluded:** Requires Trivy or Grype integration; significantly heavier than other collectors.  
**Complexity:** High  
**Notes:** Current behavior: discovers all ECR repos and images, returns NEEDS_INSPECTION. Phase 2: pull image metadata, use Trivy in-process or as a sidecar, classify base OS and installed packages against EOL data.

---

### 7. CSV / PDF Export

**What:** Export inventory or scan results as CSV or PDF.  
**Why excluded:** UI not built; backend data is available.  
**Complexity:** Low (CSV) / Medium (PDF)  
**Notes:** Backend can stream CSV. PDF generation (e.g. WeasyPrint or Puppeteer) is heavier but provides a clean deliverable for compliance reports.

---

### 8. Audit Logs UI

**What:** Show history of actions (who ran a scan, when, what changed).  
**Why excluded:** Backend logs exist; no UI to display them.  
**Complexity:** Medium  
**Notes:** Events to log: scan run, account added/removed, member invited/removed, token rotated. Store as structured events in audit_log table.

---

### 9. Per-Account RBAC

**What:** Assign roles at the connected account level (e.g. member X can only view account Y).  
**Why excluded:** Workspace-level RBAC is sufficient for Phase 1 and most small teams.  
**Complexity:** High  
**Notes:** Current model: one role per workspace. Phase 2: role can be scoped to specific account IDs. Requires changes to `_verify_workspace_access` and storage permission model.

---

### 10. AWS Organizations Multi-Account Discovery

**What:** Auto-discover all accounts in an AWS Org and onboard them in bulk.  
**Why excluded:** Needs extra IAM permissions (organizations:ListAccounts), OU-level trust policy, and validation flow.  
**Complexity:** High  
**Notes:** Feature flag exists in backend but disabled. Requires: organizations:ListAccounts + DescribeAccount, delegation role in management account, mapping from OU to workspace. High value for enterprise customers managing 10+ accounts.

---

## P3 — Medium Value

### 11. Custom EOL Data Sources

**What:** Allow workspace admins to upload custom EOL data for internal software not on endoflife.date.  
**Why excluded:** No customer demand identified yet.  
**Complexity:** Medium  
**Notes:** Custom source overrides endoflife.date lookup for matching service+version keys. Useful for: internal Java frameworks, custom OS images, private package repositories.

---

### 12. Upgrade Recommendation Engine

**What:** Show "upgrade to version X" guidance per resource type.  
**Why excluded:** Placeholder UI exists; guidance data not populated.  
**Complexity:** Medium  
**Notes:** Data source: endoflife.date latest cycle. For each EOL/EXPIRING resource, suggest the newest supported cycle. Include estimated upgrade effort classification (Easy/Medium/Hard) based on version distance.

---

### 13. Trend / Risk Over Time Charts

**What:** Charts showing EOL count change over time, MTTR for EOL remediation.  
**Why excluded:** Needs historical scan data (multiple scans over weeks).  
**Complexity:** Low-Medium  
**Notes:** Scan history records are already stored. Need: time-series chart library (recharts already in frontend), aggregation endpoint for historical summary data.

---

### 14. Billing / Subscription Management

**What:** Workspace plans (free/paid) with resource scan limits.  
**Why excluded:** Out of scope for Phase 1.  
**Complexity:** High  
**Notes:** Requires: Stripe integration, plan enforcement middleware, usage metering (resource count, scan count per month), upgrade flow.

---

### 15. Member Self-Service Registration

**What:** Members sign up with their own email/password instead of invite-only flow.  
**Why excluded:** Invite-only is simpler and more controlled.  
**Complexity:** Medium  
**Notes:** Phase 1 invites are workspace-scoped (no central identity). Phase 2 options: (a) central identity service, (b) Cognito, (c) OAuth SSO (Google/GitHub).

---

## P4 — Nice to Have

### 16. Slack / GitHub Integration

**What:** Post EOL summaries to a Slack channel or comment on PRs with runtime version findings.  
**Complexity:** Medium  

### 17. Terraform Provider

**What:** Manage connected accounts as Terraform resources.  
**Complexity:** High  

### 18. CLI Tool

**What:** `eolmonitor scan --role-arn ... --account-id ...` from a developer's machine.  
**Complexity:** Medium  

### 19. Bulk Resource Acknowledge

**What:** Select multiple resources and bulk-acknowledge or bulk-snooze alerts.  
**Complexity:** Low  

### 20. Dark Mode

**What:** UI dark mode toggle.  
**Complexity:** Low  

---

## Phase 1 → Phase 2 Transition Criteria

Phase 2 should begin when:
- [ ] At least 2 real customers are actively using Phase 1
- [ ] Scheduled scans (P1) are required by a customer
- [ ] Any P0 security finding is discovered
- [ ] File storage causes data loss in production (triggers DynamoDB migration)

Phase 2 must not begin until Phase 1 is stable and the freeze checklist is complete (`docs/PHASE_1_FREEZE.md`).
