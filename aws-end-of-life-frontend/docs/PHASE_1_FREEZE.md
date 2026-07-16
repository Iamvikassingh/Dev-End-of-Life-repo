# Phase 1 — Demo-Ready Freeze

**Status:** FROZEN  
**Tag:** `v0.1-demo-freeze`  
**Date:** June 2026

---

## What Phase 1 Is

Phase 1 is the first complete, demo-ready build of AWS EOL Monitor. It can connect to real AWS accounts, scan supported services, classify lifecycle status, and display results in a web dashboard. It is not production-SaaS-ready but is stable enough for customer demos and internal use.

---

## Completed Modules

| Module | Status |
|---|---|
| Public Overview page | Done |
| General EOL library (endoflife.date) | Done |
| Workspace access (ID + Token) | Done |
| Account Scan flow (CloudFormation + AssumeRole) | Done |
| Connected Accounts management | Done |
| Account Results page | Done |
| Dashboard | Done |
| Services page | Done |
| Alerts page | Done |
| Settings page | Done |
| Members / Invite flow (workspace-level roles) | Done |
| Resource detail page | Done |
| All enabled regions scan | Done |
| Single / multiple region scan | Done |
| Run Scan Again | Done |
| Workspace data isolation | Done |
| Read-only IAM policy | Done |
| CORS production guard | Done |

---

## Feature List

### Account Connectivity
- Customer deploys a CloudFormation stack in their AWS account — creates a read-only IAM role.
- Backend validates the role with STS AssumeRole + ExternalId before storing.
- Per-account ExternalId prevents confused-deputy attacks.
- Backend scanner principal is hardcoded: `arn:aws:iam::495234635788:role/EOLMonitorBackendEC2Role`.
- No customer-supplied MonitorAccountId required.

### Scan Engine
- Scans: Lambda, EKS, RDS (MySQL/PostgreSQL/MariaDB), Aurora (PostgreSQL/MySQL), ElastiCache Redis, EC2 AMI/OS, CodeBuild, Elastic Beanstalk, EMR, MSK, OpenSearch, DocumentDB, Neptune, Glue, CloudFront Functions, ECR.
- Supports all enabled regions, single region, or a user-selected region list.
- EC2 OS detection chain: SSM Inventory → AMI Metadata → Unknown OS.

### Lifecycle Classification
- Statuses: `EOL`, `EXPIRING_SOON`, `EXTENDED_SUPPORT`, `SUPPORTED`, `UNKNOWN`, `NEEDS_INSPECTION`, `LIFECYCLE_NOT_TRACKED`.
- `NEEDS_INSPECTION`: Resource discovered but lifecycle not calculable from metadata alone (ECR images).
- `LIFECYCLE_NOT_TRACKED`: Resource discovered but no public EOL lifecycle tracked (CloudFront Functions).
- Neither inflates main EOL risk counts.

### Security
- Workspace token stored as SHA-256 hash (never plaintext).
- All workspace API endpoints require valid `X-Workspace-Token`.
- Missing/wrong token returns 401.
- Token from Workspace A cannot access Workspace B.
- Account/resource/scan ownership verified by workspace.
- Viewer cannot run scan or delete accounts.
- Legacy unscoped routes return 410 DEPRECATED.
- CORS wildcard blocked when `APP_ENV=production`.

### UI
- Dashboard summary with 7 status cards.
- Account Results with per-account breakdown.
- Status badges with tooltips for NEEDS_INSPECTION and LIFECYCLE_NOT_TRACKED.
- EOL Timeline bar per resource.
- Filter chips for all statuses.
- `whitespace-nowrap` on all status badges.

---

## Intentionally Included in Phase 1

- Workspace-level access only (one token = full workspace access).
- File-based storage (production can upgrade to DynamoDB or PostgreSQL).
- Basic member roles: `ADMIN`, `EDITOR`, `VIEWER` — workspace-scoped, backend-enforced.
- Basic alerts: active/acknowledged/snoozed/resolved.
- Basic settings: notification preferences, workspace config.
- Upgrade guides: read-only placeholder, admin-managed.

---

## Intentionally Excluded from Phase 1

| Feature | Why Excluded |
|---|---|
| Per-account RBAC | Workspace-level roles are sufficient for Phase 1 |
| AWS Organizations multi-account scan | Needs hardening; available behind feature flag |
| ECR SBOM / image inspection | Requires Trivy or external scanner integration |
| Email/Slack alerts | Notifications wired but not user-configurable |
| Scheduled scans | Not yet exposed in UI |
| Reports / PDF / CSV export | Backend exists; UI not fully built |
| Billing / subscriptions | Out of scope for Phase 1 |
| Rate limiting | Acceptable for demo/small deployments |
| Audit logs UI | Backend exists; UI not built |
| Custom EOL data sources | Not needed for Phase 1 |

---

## Current Deployment Assumptions

- Backend: EC2 instance running Python with PM2.
- Frontend: Served as a static build.
- Storage: File-based at `/home/ubuntu/eol-data/` (or `EOL_DATA_DIR`).
- No public domain — accessed via EC2 public IP for demo.
- `APP_ENV=production` and `ALLOWED_ORIGIN=<your-domain>` must be set before exposing publicly.

---

## Security Model Summary

| Layer | Mechanism |
|---|---|
| Workspace auth | SHA-256 token hash comparison |
| Cross-workspace isolation | `workspace_id` param in all storage calls |
| Resource ownership | `get_resource_by_id(id, workspace_id)` |
| Scan ownership | `run.get("workspaceId") != workspace_id` |
| Role enforcement | Backend `_verify_workspace_access(required_role)` |
| IAM AssumeRole | ExternalId condition mandatory |
| CORS | `*` blocked in `APP_ENV=production` |

---

## EOL Classification Model

- Source: `endoflife.date` API (primary), inline OS tables (EC2), internal rules (ECR/CloudFront).
- Version normalization is service-specific (see `docs/EOL_CLASSIFICATION.md`).
- `eolDate` stored as `null` when no EOL announced — never stores `"unknown"` string.
- Days calculated from primary risk date (support end precedes final EOL for Lambda/EKS).

---

## Known Limitations

1. **File storage is not atomic** — concurrent scans writing the same workspace could cause partial writes. Acceptable for Phase 1 (single-backend EC2); upgrade to DynamoDB for production.
2. **Neptune full-version matching** — `endoflife.date` uses full patch versions (`1.4.7.0`). If AWS ships a patch not yet tracked, Neptune shows UNKNOWN.
3. **EC2 OS detection requires SSM** — instances without SSM Agent fall back to AMI metadata. Results may be less accurate.
4. **ECR only flags NEEDS_INSPECTION** — actual container OS/runtime lifecycle requires external SBOM scanning.
5. **General EOL cache is in-memory** — restarts clear cache; will re-fetch from `endoflife.date` on next request.
6. **No rate limiting** — suitable for internal demo only; add rate limiting before public exposure.

---

## Freeze Checklist

- [x] P0 security audit passed
- [x] Workspace isolation verified
- [x] Token bypass impossible
- [x] Account ownership enforced
- [x] IAM policy is read-only
- [x] ExternalId condition mandatory
- [x] CF template principal hardcoded
- [x] OpenSearch version mapping fixed
- [x] DocumentDB version mapping fixed
- [x] Neptune version mapping fixed
- [x] `"unknown"` string removed from date fields
- [x] `NEEDS_INSPECTION` / `LIFECYCLE_NOT_TRACKED` separate from EOL counts
- [x] Status badge wrapping fixed
- [x] Account Results summary cards complete
- [x] Filter chips include all 7 statuses
- [x] EOLTimeline handles null dates correctly
- [x] CORS production guard verified

---

## Demo Readiness Checklist

- [ ] Backend running with PM2 on EC2
- [ ] Frontend built and served
- [ ] At least one connected AWS account with successful scan
- [ ] `APP_ENV=production` set
- [ ] `ALLOWED_ORIGIN` set to demo domain or EC2 IP
- [ ] Admin token secured (not default generated)
- [ ] Fresh scan run after latest deploy

---

## Final Lock Decision

Phase 1 is **LOCKED**. No new features will be added without a new phase designation.

Allowed after freeze:
- P0/P1 security fixes
- EOL classification correctness fixes
- Broken UI fixes
- Deployment fixes

Not allowed after freeze:
- New large features
- Per-account RBAC
- Billing
- Org scan expansion
- SBOM scanning

See `docs/LOCK_DECISION.md` for full lock policy.
