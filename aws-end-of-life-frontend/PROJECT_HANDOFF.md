# AWS EOL Monitor — Developer Handoff + Full Product Mapping

You are taking over the AWS EOL Monitor project.

This is an AWS/cloud end-of-life lifecycle monitoring product. The goal is to help teams detect AWS resources running EOL, expiring soon, supported, extended support, or unknown lifecycle versions.

The product has:
- Public Overview
- Public General EOL Library
- Workspace-based private scanning
- Account Scan
- Connected Accounts
- Dashboard
- Services drilldown
- Alerts
- Resource Detail
- Settings
- Internal Admin Console
- Global CK Upgrade Guide Library

Do not drift into unrelated product ideas.
Keep all work focused on AWS/cloud EOL lifecycle monitoring.

==================================================
1. Product goal
==================================================

AWS EOL Monitor should answer:

1. Which AWS resources are running EOL or expiring versions?
2. Which AWS accounts/regions/services are affected?
3. What should the customer upgrade to?
4. What is the official AWS upgrade guide?
5. Is there a CK lab-tested upgrade guide?
6. What alerts/actions should the customer take?

Main flow:

Overview
→ General EOL Library
→ Create/Access Workspace
→ Connect AWS Account
→ Validate IAM Role
→ Run Scan
→ Dashboard
→ Services / Alerts / Resource Detail
→ AWS Guide + CK Guide

==================================================
2. Public vs Private pages
==================================================

Public pages:
- /overview
- /general-eol

These must not require workspace token.

Private workspace-scoped pages:
- /account-scan
- /connected-accounts
- /dashboard
- /services
- /alerts
- /settings
- /account-results/:accountId
- resource detail drawer/page

These must require workspace access.

Internal admin:
- /admin

Admin uses X-Admin-Token.
Workspace token must never authorize admin endpoints.

==================================================
3. Workspace model
==================================================

There is no signup/login currently.

Workspace access uses:
- Workspace ID
- Workspace token

Workspace token is a one-time/secret style token.
It is stored in browser session/local storage for the current workspace session.

Workspace data includes:
- connected accounts
- inventory
- scan results
- alerts
- settings

Workspace data must be isolated.
No workspace should ever see another workspace's:
- accounts
- inventory
- alerts
- scan runs
- resource detail
- settings

Important:
All private React Query keys must include workspaceId.

Examples:
["workspaceSummary", workspaceId]
["accounts", workspaceId]
["inventory", workspaceId, filters]
["alerts", workspaceId, filters]
["services", workspaceId]
["resource", workspaceId, resourceId]
["settings", workspaceId]

On workspace create/access/clear/exit demo/token rotate:
- clear private query cache
- clear old private state
- do not flash old workspace data

==================================================
4. Workspace creation one-time token UX
==================================================

After workspace creation:
- Show Workspace ID
- Show Access Token
- Token is shown once only
- Add Copy Workspace ID
- Add Copy Access Token
- Add Download CSV

Continue to Dashboard must be disabled until:
- Access token is copied, OR
- CSV is downloaded

CSV should include:
- Workspace Name
- Workspace ID
- Access Token
- Created At
- Note: "Save this token now. It will not be shown again."

Show warning:
"Save this access token now. It will not be shown again."
"Anyone with this token can access this workspace. Store it securely."

==================================================
5. Admin token rotation one-time token UX
==================================================

Admin can rotate a customer workspace token.

After rotate:
- New token is shown once only
- Show Workspace ID
- Show Access Token
- Add Copy Token
- Add Download CSV
- Done must be disabled until token is copied or CSV is downloaded
- Prevent/confirm close before saving

CSV should include:
- Workspace Name if available
- Workspace ID
- Access Token
- Rotated At
- Note: "Save this token now. It will not be shown again."

==================================================
6. AWS account connection flow
==================================================

Account Scan lets customer connect AWS account using:
- IAM role ARN
- ExternalId
- CloudFormation template
- selected regions

Security copy:
- Read-only IAM role
- ExternalId protected
- No AWS access keys stored
- Revoke anytime by deleting IAM role

Connected Accounts page shows:
- account name
- AWS account id
- role ARN
- externalId
- regions
- status
- last scan
- scan summary
- scan actions

Actions:
- View Results
- Run Scan Again
- Edit Regions
- Delete Account
- Add Another Account

==================================================
7. Scan model
==================================================

Scan runs are stored and tracked.

Scan run fields:
- scanId
- workspaceId
- accountId
- status: QUEUED / RUNNING / SUCCESS / FAILED / PARTIAL_SUCCESS
- startedAt
- completedAt
- regions
- error
- summary:
  - total
  - eol
  - expiringSoon
  - extendedSupport
  - supported
  - unknown

APIs:
POST /workspaces/:workspaceId/accounts/:accountId/scans
GET /workspaces/:workspaceId/scans/:scanId
GET /workspaces/:workspaceId/accounts/:accountId/latest-scan

Scan errors should use clear codes:
- ASSUME_ROLE_FAILED
- SERVICE_ACCESS_DENIED
- SCAN_FAILED
- ACCESS_DENIED

Do not clear workspace session for AWS/IAM scan errors.
Only clear workspace session for workspace token errors.

Clear workspace only for:
- WORKSPACE_TOKEN_MISSING
- WORKSPACE_TOKEN_INVALID
- WORKSPACE_TOKEN_EXPIRED
- WORKSPACE_NOT_FOUND

Do not clear for:
- ASSUME_ROLE_FAILED
- SERVICE_ACCESS_DENIED
- SCAN_FAILED
- ACCESS_DENIED

==================================================
8. Inventory model
==================================================

Inventory/resource records must include:
- workspaceId
- accountId
- scanId
- resourceId
- resourceName
- service
- region
- version/runtime/engine/OS
- status
- eolDate
- daysToEol
- classificationReason
- recommendation
- detectionSource
- confidence
- lastScannedAt

Statuses:
- EOL
- EXPIRING_SOON
- EXTENDED_SUPPORT
- SUPPORTED
- UNKNOWN
- LEGACY if used for public library

Inventory must always be workspace-scoped.
Resource detail lookup must be workspace-scoped:
GET /workspaces/:workspaceId/resource/:resourceId

Workspace B must not open Workspace A resource URL.
Expected: 404 Resource not found.

==================================================
9. Dashboard
==================================================

Dashboard is the main risk center.

Shows:
- EOL count
- Expiring Soon count
- Extended Support count
- Supported count
- Unknown count
- filters
- affected resources table
- detail drawer
- export CSV

Empty states:
- No workspace → workspace access gate
- Workspace but no account → "No AWS account connected"
- Account connected but no scan → "No scan run yet"
- Scan completed but no resources → "No resources found"
- Scan failed → clear error with scanId

Refresh behavior:
- Do not show wrong table skeleton before workspace/account state loads
- New workspace refresh:
  Loading workspace → No AWS account connected
- Workspace with scan data:
  Loading workspace → dashboard skeleton → data

==================================================
10. Connected Accounts
==================================================

Connected Accounts page is the operational page for AWS accounts.

Shows connected account cards with:
- Account name
- AWS account ID
- Role ARN
- ExternalId
- Regions
- Connected status
- Last scan
- Scan summary badges
- Actions

If no accounts:
"No accounts connected yet"
CTA: Connect AWS Account

Important:
Connected account cache must be workspace-keyed.
Old workspace account list must not appear in a new workspace.

==================================================
11. Account Results
==================================================

Account Results page displays scan results for one connected account.

Route:
/account-results/:accountId

Important:
The route param accountId is the connected account id, e.g. conn-xxxx.
Resource table must filter by connected account id, not account name.

If summary total > 0:
- All tab should show all resources
- EOL tab shows EOL
- Expiring tab shows EXPIRING_SOON
- Supported tab shows SUPPORTED
- Unknown tab shows UNKNOWN

If total > 0 but selected filter has no rows:
Show:
"No resources match this filter."

If total = 0:
Show:
"No resources found for this account."

==================================================
12. Services page
==================================================

Services page shows service-level drilldown.

It should not show broken service names like:
0lambda9420
0EC25010
0RDS_postgres1000

Each row shape:
{
  service: "Lambda",
  serviceKey: "lambda",
  total: number,
  eol: number,
  expiringSoon: number,
  extendedSupport: number,
  supported: number,
  unknown: number,
  lastScanAt: string | null
}

Readable service names:
- Lambda
- EC2
- RDS / PostgreSQL
- RDS / MySQL
- EKS
- ElastiCache
- MSK
- OpenSearch
- DocumentDB
- Neptune
- Glue

Counts should show 0, not dash.

Click behavior:
- Row click or View All → /dashboard?service=<serviceKey>
- Count cell click → /dashboard?service=<serviceKey>&status=<STATUS>

Table and Grid views must use same normalized data.

==================================================
13. Alerts
==================================================

Alerts are generated from inventory.

Alert statuses:
- ACTIVE
- ACKNOWLEDGED
- SNOOZED
- RESOLVED

Alert severity:
- EOL → HIGH
- EXPIRING_SOON → MEDIUM
- UNKNOWN optional low/info only if useful
- SUPPORTED → no active alert

Alerts page tabs:
- Active
- Acknowledged
- Snoozed
- Resolved

Actions:
- View Resource
- Acknowledge
- Snooze
- Resolve

Alerts are in-app even if notification delivery channels are not configured.

No workspace should see another workspace's alerts.

==================================================
14. Resource Detail
==================================================

Resource detail appears as a right drawer/sidebar.

Shows:
- service
- resource name
- region
- version/runtime/engine/OS
- account
- resource id
- last scanned
- lifecycle status
- EOL date
- days remaining/past EOL
- recommendation
- AWS Upgrade Guide
- CK Upgrade Guide
- Full Detail View

AWS Guide:
Official AWS/source guide.

CK Guide:
Global admin-managed guide from CK Upgrade Guide Library.

Resource detail endpoint should return:
{
  item: { resource data },
  ckGuide: { matched published guide } | null
}

==================================================
15. Global CK Upgrade Guide Library
==================================================

This is a global product-level library.
It is NOT workspace-specific.

Admin adds guide once.
Any workspace scanning matching resource sees the guide.

Guide schema:
{
  id,
  title,
  service,
  versionPattern,
  targetVersion,
  guideUrl,
  guideType: "CK_GUIDE",
  testedInLab: boolean,
  status: "DRAFT" | "PUBLISHED",
  summary,
  createdAt,
  updatedAt
}

Important:
- No workspaceId in guide record
- Draft guides visible only in admin
- Only Published guides visible to workspace users
- Workspace token cannot create/update/delete guides

Matching priority:
1. Exact service + exact versionPattern
2. Service + wildcard/prefix versionPattern
3. Service-level fallback with "*" or empty pattern
4. No guide → null

Examples:
Lambda + nodejs18.x → Lambda nodejs18.x guide
Lambda + python3.9 → Lambda python3.9 guide
EC2 + Ubuntu 20.04 → EC2 Ubuntu 20.04 guide
EKS + 1.31 → EKS 1.31 guide
RDS + postgres13 → RDS PostgreSQL 13 guide
No guide → CK Guide coming soon

==================================================
16. CK Guide UI behavior
==================================================

If ckGuide exists in Resource Detail:

Show:
CK Upgrade Guide
Badge: Tested in lab if testedInLab=true

Show:
- ckGuide.title
- ckGuide.summary
- Target version: ckGuide.targetVersion
- Button: Open CK Guide

Button:
- uses ckGuide.guideUrl
- opens in new tab
- target="_blank"
- rel="noreferrer"

If no ckGuide:
Show:
CK Upgrade Guide
Coming soon
A lab-tested CK upgrade guide is not available yet for this service/version.

Do not use hardcoded CK guide URLs.

==================================================
17. Admin Console
==================================================

Admin route:
/admin

Admin Console tabs:
- Workspaces
- Scan Runs
- System
- Upgrade Guides

Admin auth:
- X-Admin-Token
- sessionStorage only
- admin token separate from workspace token
- workspace token must never work on admin endpoints

Admin HTTP behavior:
For production:
- admin over HTTP should be blocked
- HTTPS required

For temporary development:
- REACT_APP_ALLOW_INSECURE_ADMIN=true can allow admin over HTTP IP
- default must be false

Admin shortcut:
- hidden in production unless REACT_APP_SHOW_ADMIN_SHORTCUT=true

==================================================
18. Admin Upgrade Guides tab
==================================================

Admin Console → Upgrade Guides

Table columns:
- Title
- Service
- Version Pattern
- Target
- Lab
- Status
- Updated
- Actions

Actions:
- Add Guide
- Edit
- Publish/Unpublish
- Preview
- Delete

Add/Edit form:
- Guide Title
- Service
- Version Pattern
- Target Version
- Guide URL
- Summary
- Tested in lab checkbox
- Status Draft/Published

Validation:
- title required
- service required
- guideUrl required for published guide
- guideUrl must start http:// or https://
- status DRAFT or PUBLISHED

==================================================
19. Admin APIs
==================================================

Admin endpoints:
GET /admin/summary
GET /admin/workspaces
GET /admin/scans
GET /admin/system
POST /admin/general-eol/refresh

Upgrade Guide endpoints:
GET /admin/upgrade-guides
POST /admin/upgrade-guides
GET /admin/upgrade-guides/:id
PATCH /admin/upgrade-guides/:id
DELETE /admin/upgrade-guides/:id

All admin endpoints require X-Admin-Token.
Do not log admin token.

==================================================
20. Backend storage
==================================================

Current storage supports:
- File backend
- S3 backend
- DynamoDB backend

File backend uses EOL_DATA_DIR.

Important files:
- workspaces.json
- accounts.json
- inventory.json
- scan_runs.json
- alerts.json if present
- upgrade_guides.json
- general_eol_cache.json

File backend writes should be atomic:
write temp file → os.replace()

Backup is required for file backend.

Backup cron example:
0 2 * * * tar -czf /home/ubuntu/eol-backups/eol-data-$(date +\%F-\%H\%M).tar.gz /home/ubuntu/eol-data

==================================================
21. General EOL
==================================================

General EOL is public.

Endpoints:
GET /eol/general
GET /eol/general/summary
POST /eol/general/refresh if admin protected

Source:
endoflife.date

General EOL page should show source freshness:
- last refreshed
- source/cache metadata if available

Public page must not require workspace.

==================================================
22. Demo workspace
==================================================

Demo workspace is sample data.

Rules:
- clearly labeled Demo
- banner on protected pages
- destructive actions disabled
- demo data read-only
- real workspace data must not mix with demo
- demo data must not appear in real workspace

Demo is for exploration, not real customer scan.

==================================================
23. Loading and refresh UX
==================================================

No white screen on route switch.

Fix requirements:
- Suspense fallback must not be null
- PrivatePageGate/WorkspaceBootGate must not return null
- show page-level loader:
  Loading workspace...
  Loading dashboard...
  Loading services...
  Loading alerts...
  Loading settings...

Clicking sidebar routes should never show blank white main content.

New workspace refresh:
Loading workspace → No AWS account connected

Workspace with data:
Loading workspace → page skeleton → data

Invalid token:
Loading workspace → clear session/access gate

==================================================
24. Production build/deployment
==================================================

Frontend production build:
REACT_APP_API_URL=/api
REACT_APP_SHOW_ADMIN_SHORTCUT=false
REACT_APP_ALLOW_INSECURE_ADMIN=false
npm run build

Production build should use hashed assets:
build/static/js/main.xxxxx.js
No huge dev bundle.js.

Nginx:
- / serves frontend build
- /api proxies backend 127.0.0.1:3001
- SPA fallback try_files $uri /index.html
- gzip enabled
- /static cache immutable
- index.html no-cache

Backend env:
STORAGE_BACKEND=file
EOL_DATA_DIR=/home/ubuntu/eol-data
ALLOWED_ORIGIN=https://your-domain.com
ADMIN_PORTAL_TOKEN=<strong token>
GENERAL_EOL_CACHE_TTL_HOURS=24

HTTPS/domain required for real production.

Current HTTP/IP can be used only for development/internal testing.

==================================================
25. Known launch blockers to verify
==================================================

Before launch, verify:

1. Services page does not show broken service names.
2. Account Results table matches account summary.
3. CK Guide card shows real guide title/summary/target/url.
4. New workspace never shows old workspace data.
5. Workspace B cannot open Workspace A resource detail URL.
6. Admin shortcut hidden in production.
7. No white screen on route switch.
8. Frontend uses production hashed build.
9. /api proxy works.
10. HTTPS enabled.
11. Backup cron configured.

==================================================
26. Smoke test checklist
==================================================

Public:
- Open /overview
- Open /general-eol
- General EOL loads
- Source freshness visible

Workspace:
- Create workspace
- Copy/download token required before continue
- Access workspace with token
- Sidebar chip shows workspace

Account:
- Connect AWS account
- Validate role
- Run scan
- Connected account summary updates

Dashboard:
- Shows counts
- Filters work
- Details drawer opens
- Export CSV works

Services:
- Shows readable service rows
- Counts match dashboard
- Row click filters dashboard

Alerts:
- Alerts generated for EOL/Expiring resources
- Acknowledge/Snooze/Resolve works

Resource Detail:
- AWS Guide visible
- CK Guide visible if published match exists
- Coming soon if no match
- CK Guide opens admin-managed URL

Admin:
- /admin login works with admin token
- Workspaces visible
- Scan Runs visible
- System visible
- Upgrade Guides CRUD works
- Draft guide hidden from user
- Published guide visible in Resource Detail

Isolation:
- Workspace A data not shown in Workspace B
- Resource URL from A returns 404 in B
- Demo data not mixed with real workspace

==================================================
27. Current project status
==================================================

Achieved:
- Public EOL Library
- Workspace access
- AWS Account Scan
- Connected Accounts
- Scan Run model
- Dashboard
- Services drilldown
- Alerts
- Resource Detail
- Admin Console
- Global CK Upgrade Guide Library
- Workspace data isolation fixes
- Resource detail scoping
- Production hashed build support
- General EOL source freshness

Remaining before real production launch:
- HTTPS/domain
- Nginx /api proxy
- backup cron
- final smoke test
- route-switch white screen fix if still visible
- verify Services/Account Results/CK Guide UI after rebuild

==================================================
28. Important instruction for future work
==================================================

Do not add signup/login yet.
Do not make CK Guides workspace-specific.
Do not add unrelated product ideas.
Do not break workspace isolation.
Do not allow workspace token to access admin APIs.
Do not show draft guides to workspace users.
Do not show old workspace data during route changes.
Do not use hardcoded CK Guide URLs.
Do not show fake scan success in real workspace.

Focus only on AWS/cloud EOL lifecycle monitoring.
