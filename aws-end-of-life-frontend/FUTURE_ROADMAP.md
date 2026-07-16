# AWS EOL Monitor — Future Roadmap

## 1. Current Product Status

AWS EOL Monitor is a workspace-scoped AWS/cloud end-of-life lifecycle monitoring product.

**Currently shipped and working:**

- Public Overview page
- Public General EOL Library
- Workspace create / access / token rotation
- Account Scan with STS AssumeRole + ExternalId validation
- Connected Accounts management
- Account Results with per-resource detail
- Dashboard (workspace-scoped)
- Services overview
- Alerts (EOL / Expiring Soon / Extended Support)
- Reports / Compliance (CSV, print/PDF, risk score, snapshots)
- Notifications (Email/Slack, delivery logs, test notifications)
- CK Upgrade Guide Library
- Settings (workspace config, notifications, scope)
- Admin Console
- API Tokens (scoped by role)
- Audit Logs
- Members + Invite flow
- Member Session + Magic Login (one-time link)
- Role-based access: VIEWER / EDITOR / ADMIN (frontend + backend enforced)
- PostgreSQL storage backend
- Broader AWS service coverage (Lambda, EKS, RDS, EC2, ElastiCache, OpenSearch, MSK, Glue, CodeBuild, Elastic Beanstalk, EMR, CloudFront Functions, ECR, DocumentDB, Neptune)
- Organization Scan end-to-end async rollout — controlled rollout behind feature flag

**Private beta status:** GO — after latest P0/P1 audit fixes are deployed and smoke-tested.
**Public production launch:** Requires production hardening (domain, HTTPS, DB backup, secrets rotation, rate limiting). See Section 3.

---

## 2. Completed Phases

| Phase | Name | Status | Notes |
|---|---|---|---|
| Phase 1 | Core AWS EOL Monitor | ✅ Done | Workspace, Account Scan, Connected Accounts, Dashboard, Services, Alerts, Settings, Resource Detail, CK Guides |
| Phase 2 | Notifications | ✅ Done | Email/Slack foundation, test notifications, scan-complete trigger, delivery logs, weekly/monthly/admin digest foundation |
| Phase 3 | Organization Scan Foundation | ✅ Done | Feature flags, schema/storage, org connection APIs, org discovery foundation, IAM templates |
| Phase 3.1 | Organization Scan Async Rollout | ✅ Done | Async backend execution, frontend polling, scan history, per-account progress, `riskByOu` aggregation fix. Controlled rollout behind flags |
| Phase 5 | Compliance & Reporting | ✅ Done | Reports page, CSV export, print/save PDF, risk score, trends, compliance mapping, snapshots |
| Phase 6 | Broader Service Coverage | ✅ Done | Lambda, EKS, RDS/Aurora, EC2 SSM OS detection, ElastiCache, OpenSearch/ES, MSK, Glue, CodeBuild, Elastic Beanstalk, EMR, CloudFront Functions, ECR metadata, DocumentDB, Neptune |
| Phase 7.1 | Team Access Foundation | ✅ Done | API tokens, roles, audit logs, Workspace Access UI |
| Phase 7.1b | API Token Access for Reports | ✅ Done | VIEWER tokens can read reports/CSV/snapshots; EDITOR tokens can create snapshots |
| Phase 7.2 | Members + Invite | ✅ Done | Invite link flow, member status, roles, member management UI |
| Phase 7.2b | Member Session + Magic Login | ✅ Done | Invite accept creates member session, magic login, session expiry, role-based frontend and backend enforcement |
| Security Audit Fixes | P0/P1 Hardening | ✅ Done | Legacy routes deprecated (410), ExternalId crypto-safe, dev magic-link response leak removed, CORS production guard, member session revocation on role/status/remove change, workspace-scoped resource lookup, IAM ExternalId condition, IAM permission set synced across all templates |

---

## 3. Production Hardening Backlog

> Highest priority before public launch. Private beta can proceed without all of these, but public traffic requires them.

| # | Item | Priority | Status | Notes |
|---|---|---|---|---|
| 1 | Domain + HTTPS | P0 before public launch | ⏳ Pending | Nginx + Certbot, redirect HTTP → HTTPS |
| 2 | Nginx `/api` proxy | P0 before public launch | ⏳ Pending/verify | Same-origin `/api` proxy to backend `localhost:3001` |
| 3 | Nginx rate limiting | P1 | ⏳ Pending | Protect member magic login, admin, scan, and invite endpoints |
| 4 | PostgreSQL backup cron | P1 | ⏳ Pending | Nightly `pg_dump`, retention policy, restore test documented |
| 5 | PostgreSQL network restriction | P1 | ⏳ Pending | Port 5432 reachable only from app EC2 / private IP; not exposed to internet |
| 6 | Secrets rotation | P1 | ⏳ Pending | Rotate admin token, DB password, and any workspace tokens used during testing |
| 7 | Production env hardening | P1 | ⏳ Pending | See env vars below |
| 8 | PostgreSQL connection pool | P1 before public scale | ⏳ Pending | Replace single persistent `psycopg2` connection with `ThreadedConnectionPool` or SQLAlchemy |
| 9 | CSP / security headers | P2 | ⏳ Pending | Add `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options` via Nginx |
| 10 | PM2 startup + log retention | P2 | ⏳ Pending | `pm2 save` + `pm2 startup`, configure `logrotate` |

**Required production env vars (item 7):**

```env
APP_ENV=production
MEMBER_LOGIN_DEV_LINKS=false
ALLOWED_ORIGIN=https://yourdomain.com
APP_PUBLIC_URL=https://yourdomain.com
REACT_APP_ALLOW_INSECURE_ADMIN=false
REACT_APP_SHOW_ADMIN_SHORTCUT=false
```

---

## 4. Phase 3.1 — Organization Scan Async Rollout

**Status:** Done for controlled rollout. Keep behind feature flags until the rollout owner enables it for selected workspaces/customers.

**Feature flags:**
```env
ENABLE_ORG_SCAN=true
REACT_APP_ENABLE_ORG_SCAN=true
```

**Completed:**
- [x] Feature flag verified
- [x] Org schema / storage tables
- [x] Org connection APIs (create, validate, list)
- [x] Management account role validation foundation
- [x] AWS Organizations account/OU discovery foundation
- [x] Member role validation per account foundation
- [x] Org scan run records and scan history route
- [x] Async backend execution with `202 RUNNING`
- [x] Duplicate running scan guard with `409 ORG_SCAN_IN_PROGRESS`
- [x] Frontend polling every 2.5s until `SUCCESS`, `PARTIAL_SUCCESS`, or `FAILED`
- [x] Per-account running/success/failure status display
- [x] Org summary dashboard and `riskByOu` aggregation
- [x] IAM templates (`iam/org-management-role.yaml`, `iam/org-member-scan-role.yaml`)
- [x] Backend test suite passing
- [x] Frontend build passing

**Future optimization:**

| Task | Priority | Notes |
|---|---|---|
| SQS/account fan-out for very large organizations | Later | Current async worker avoids API timeouts. Add queue fan-out only if very large org scale needs it. |
| Decide if global Dashboard includes org data | Later | Design choice: separate org dashboard or merged. |

> Organization Scan is now implemented end-to-end with async backend execution and frontend polling. It is ready for controlled rollout. Future large-scale optimization can use SQS/account fan-out if needed.

---

## 5. Phase 4 — Remediation Tracking

**Status:** Pending. Hidden behind feature flag.

**Feature flags:**
```env
ENABLE_REMEDIATION=false
REACT_APP_ENABLE_REMEDIATION=false
```

**Goal:** Move from detection to fix tracking. Let users assign ownership, set due dates, and track resolution status per EOL resource.

| Feature | Priority | Notes |
|---|---|---|
| Resource remediation status | High | Statuses: Open, In Progress, Deferred, Accepted Risk, Resolved |
| Owner assignment | High | Assign a member or email to each resource |
| Due date / SLA | High | Target date for resolution |
| Notes / history per resource | Medium | Timestamped comment thread |
| Bulk status update | Medium | Select multiple resources, set status/owner in one action |
| Risk acceptance expiry | Medium | Accepted Risk auto-expires after N days |
| Report unresolved risk by owner/team | Medium | Exportable view for security reviews |
| Jira / GitHub issue creation | Later | One-click issue from Resource Detail |
| Slack reminder for overdue remediation | Later | Notification hook when due date passes |

**Suggested UI placement:**
- Resource Detail page → Remediation panel
- Alerts page → remediation status filter
- Reports page → open risk by owner / due date
- Dashboard → overdue remediation card

---

## 6. Phase 7.3 — SSO / SAML

**Status:** Later. Hidden behind feature flag.

**Feature flags:**
```env
ENABLE_SSO=false
REACT_APP_ENABLE_SSO=false
```

> Current member magic login is sufficient for private beta and early paid customers.

| Feature | Priority | Notes |
|---|---|---|
| Google OAuth | Later | Social login for members |
| Microsoft OAuth | Later | Azure AD personal accounts |
| SAML SSO with Okta / Azure AD | Later | Enterprise requirement |
| SCIM provisioning | Later | Auto-provision/deprovision members from IdP |
| Workspace domain claim | Later | `@acme.com` → auto-route to workspace |
| Group-to-role mapping | Later | IdP group → VIEWER / EDITOR / ADMIN |
| SSO audit events | Later | Log SSO login/logout/provisioning in audit trail |

---

## 7. Phase 8 — SaaS / Growth / Billing

**Status:** Later. Hidden behind feature flag.

**Feature flags:**
```env
ENABLE_BILLING=false
REACT_APP_ENABLE_BILLING=false
```

| Feature | Priority | Notes |
|---|---|---|
| Signup / self-serve onboarding | Later | Public sign-up flow, workspace auto-create |
| Free tier | Later | 1 account, limited resources, no reports |
| Usage metering | Later | Track accounts, scans, members per workspace |
| Plan limits enforcement | Later | Block over-limit actions gracefully |
| Stripe billing | Later | Subscription creation, invoice, card management |
| Customer billing portal | Later | Stripe customer portal embed |
| Subscription lifecycle webhooks | Later | Handle plan changes, cancellations |
| Tenant provisioning automation | Later | Auto-provision new workspaces on signup |

**Suggested plan tiers:**

| Tier | Accounts | Features |
|---|---|---|
| Free | 1 | Basic scan, dashboard, alerts |
| Team | Multiple | Notifications, reports, snapshots, members |
| Enterprise | Org scan | SSO, audit exports, SLA support |

---

## 8. Extra — CI/CD Scan-on-push

**Status:** Later. Hidden behind feature flag.

**Feature flags:**
```env
ENABLE_CICD_SCAN=false
REACT_APP_ENABLE_CICD_SCAN=false
```

**Goal:** Detect EOL risk in infrastructure code before it ships to production.

| Feature | Priority | Notes |
|---|---|---|
| GitHub Action | Medium | `uses: eolmonitor/scan-action@v1` in workflow |
| CLI tool (`eolm scan`) | Medium | Local and CI scan from command line |
| PR comments with EOL findings | Medium | Inline annotation on changed resources |
| SARIF output | Later | Upload to GitHub Security tab |
| Terraform plan parser | Later | Detect EOL versions from `terraform plan` output |
| CloudFormation template parser | Later | Detect EOL runtime/engine versions in CF templates |
| API token auth | ✅ Foundation done | CI jobs use workspace API tokens (VIEWER role) |
| CI/CD documentation | Later | Setup guide, examples for GitHub/GitLab/Jenkins |

---

## 9. Hidden Feature Flag Policy

All incomplete or untested features **must** remain hidden in production behind both a backend and frontend flag.

**Backend flags** (`backend/.env`):
```env
ENABLE_ORG_SCAN=false
ENABLE_REMEDIATION=false
ENABLE_SSO=false
ENABLE_BILLING=false
ENABLE_CICD_SCAN=false
```

**Frontend flags** (`frontend/.env`):
```env
REACT_APP_ENABLE_ORG_SCAN=false
REACT_APP_ENABLE_REMEDIATION=false
REACT_APP_ENABLE_SSO=false
REACT_APP_ENABLE_BILLING=false
REACT_APP_ENABLE_CICD_SCAN=false
```

**Rules:**

- If frontend flag is `false`: hide nav item, sidebar entry, and all CTAs. Page should not be reachable via URL.
- If backend flag is `false`: route returns `{ error: { code: "FEATURE_DISABLED" } }` with 403.
- A direct URL to a hidden feature must show a clean "not available" state — not a broken UI or 404.
- Both flags must be `true` to enable any feature. Enabling only one side is not enough.
- Do not ship partially-built flows. A feature is either fully working behind a flag, or it does not exist in production.

---

## 10. Recommended Execution Order

### Immediate (before private beta)

1. Deploy latest codebase to EC2 (P0/P1 audit fixes are in)
2. Full smoke test: workspace create, account connect, scan, reports, members, magic login
3. Rotate all secrets: admin token, DB password, test workspace tokens
4. Set `APP_ENV=production` + all production env vars
5. PostgreSQL backup cron (nightly `pg_dump`)
6. Restrict DB security group (port 5432 internal only)
7. Invite 1–2 private beta testers

### Before public launch (after private beta)

8. Domain + HTTPS (Nginx + Certbot)
9. Nginx rate limiting on sensitive endpoints
10. PostgreSQL connection pool
11. CSP / security headers
12. PM2 startup + log retention

### Next product work (based on beta feedback)

**Option A — Remediation Tracking (Phase 4)**
> Reason: increases stickiness, makes EOL risk actionable, high user value immediately after detecting problems.

**Option B — Org Scan scale optimization**
> Reason: Organization Scan is end-to-end async complete for controlled rollout. Add SQS/account fan-out only if very large AWS Organizations need higher throughput.

**Recommendation:**
After private beta, let tester feedback decide:
- "Who owns this and how do I track the fix?" → **Phase 4 Remediation** first
- "Can I scan all my accounts at once?" → **Org Scan controlled rollout is ready**

### Later (in order)

- SSO / SAML (Phase 7.3) — unlock after first enterprise customer asks
- SaaS / Billing (Phase 8) — unlock when going multi-tenant / public
- CI/CD Scan-on-push (Extra) — unlock after API and CLI tooling matures

---

## 11. Private Beta Scope

### Included in private beta

- [ ] Workspace create / access
- [ ] Account scan (single account, STS AssumeRole)
- [ ] Connected accounts
- [ ] Dashboard
- [ ] Services
- [ ] Alerts
- [ ] Reports (CSV, PDF, snapshots, risk score)
- [ ] Notifications (Email / Slack)
- [ ] Members / invite / magic login
- [ ] Role-based access (VIEWER / EDITOR / ADMIN)
- [ ] API tokens
- [ ] Audit logs
- [ ] CK Upgrade Guides
- [ ] PostgreSQL backend
- [ ] Admin console

### Excluded / hidden in private beta

- Full organization scan (Phase 3.1)
- Remediation tracking (Phase 4)
- SSO / SAML (Phase 7.3)
- SaaS billing (Phase 8)
- CI/CD scan-on-push (Extra)

---

## 12. Final Roadmap Summary

| Phase | Name | Status | UI Visibility |
|---|---|---|---|
| Phase 0 | Production Hardening | ⏳ Pending | N/A |
| Phase 1 | Core AWS EOL Monitor | ✅ Done | Visible |
| Phase 2 | Notifications | ✅ Done | Visible |
| Phase 3 | Org Scan Foundation | ✅ Done | Flag-controlled |
| Phase 3.1 | Org Scan Async Rollout | ✅ Done | Controlled rollout |
| Phase 4 | Remediation Tracking | ⏳ Pending | Hidden (flag) |
| Phase 5 | Compliance Reports | ✅ Done | Visible |
| Phase 6 | Broader AWS Coverage | ✅ Done | Visible |
| Phase 7 | Team Access (API tokens, audit, roles) | ✅ Done | Visible |
| Phase 7.2 | Members + Invite + Magic Login | ✅ Done | Visible |
| Phase 7.3 | SSO / SAML | 🔵 Later | Hidden (flag) |
| Phase 8 | SaaS / Billing | 🔵 Later | Hidden (flag) |
| Extra | CI/CD Scan-on-push | 🔵 Later | Hidden (flag) |

---

*Last updated: 2026-06-07*
*Private beta verdict: GO after deploy + smoke test.*
*All future phases must remain behind feature flags until complete, tested, and explicitly enabled.*
