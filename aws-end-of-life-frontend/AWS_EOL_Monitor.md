# AWS EOL Monitor

Track AWS service end-of-life dates before they become security or compliance risks.
Browse the public lifecycle library, scan a single AWS account, or monitor your entire organization — all without AWS access keys.

---

## Table of Contents

- [How it works](#how-it-works)
- [Project structure](#project-structure)
- [Quick start — local dev](#quick-start--local-dev)
- [Environment variables](#environment-variables)
- [Backend modules](#backend-modules)
- [Frontend modules](#frontend-modules)
- [API contract](#api-contract)
- [Running tests](#running-tests)
- [Makefile reference](#makefile-reference)
- [AWS deployment](#aws-deployment)
- [PostgreSQL operations](database/POSTGRES_OPS.md) ← setup, migration, host change, backup
- [Troubleshooting](#troubleshooting)

---

## How it works

```
endoflife.date API
      │
      ▼
general_eol.py ──► GET /eol/general          ← General EOL Library (no AWS needed)
      │
      ▼
    cache (file / DynamoDB / S3)

AWS Account (read-only IAM role)
      │
      ▼
eol_collector.py ──► Lambda + EventBridge    ← Account & Org scans
      │
      ▼
   DynamoDB inventory table
      │
      ▼
api_handler.py ──► API Gateway ──► React frontend
      │
      ▼
alert_notifier.py ──► SNS (email / Slack)
```

Three scan modes:

| Mode | AWS access | Use case |
|---|---|---|
| **General EOL Library** | None | Browse public lifecycle dates for all AWS service versions |
| **Account Scan** | Read-only IAM role + ExternalId | Surface EOL risk in a single AWS account |
| **Organization Scan** | Org role + member roles via StackSet | EOL governance across all accounts in AWS Organizations |

---

## Project structure

```
aws-eol-monitor/
│
├── backend/                        Python — Lambda functions + business logic
│   ├── api_handler.py              REST API router (Lambda entry point)
│   ├── general_eol.py              Public lifecycle library (endoflife.date)
│   ├── eol_collector.py            Account/org scanner (AWS API calls)
│   ├── storage.py                  Storage abstraction (DynamoDB / S3 / file)
│   ├── alert_notifier.py           SNS alert sender with deduplication
│   ├── requirements.txt
│   ├── .env.example                Backend env reference
│   └── tests/
│       ├── test_classify.py        EOL status classification tests
│       ├── test_collector.py       Collector + storage integration tests
│       └── test_general_eol.py     General EOL fetch, normalize, filter, cache tests
│
├── frontend/                       React — SaaS-style dashboard
│   ├── src/
│   │   ├── App.jsx                 Root app: sidebar navigation + routes
│   │   ├── pages/
│   │   │   ├── OverviewPage.jsx    Landing: scan mode cards + product overview
│   │   │   ├── GeneralEolPage.jsx  Public lifecycle library (real backend data)
│   │   │   ├── AccountScanPage.jsx Account onboarding wizard (5 steps)
│   │   │   ├── OrgScanPage.jsx     Organization onboarding wizard (6 steps)
│   │   │   ├── DashboardPage.jsx   Account inventory: EOL table + metric cards
│   │   │   ├── ServicesPage.jsx    Service-level risk overview
│   │   │   ├── AlertsPage.jsx      Alert history with status tabs
│   │   │   ├── SettingsPage.jsx    Section-based settings form
│   │   │   └── ResourceDetailPage.jsx  Single resource detail panel
│   │   ├── components/
│   │   │   ├── StatusBadge.jsx     EOL / Expiring Soon / Ext. Support / Supported pill
│   │   │   ├── MetricCard.jsx      Summary count card with click-to-filter
│   │   │   ├── ResourceTable.jsx   Paginated sortable inventory table
│   │   │   ├── FilterBar.jsx       Search + Service + Status + Region filter row
│   │   │   ├── EOLTimeline.jsx     Visual days-to-EOL bar
│   │   │   └── DetailPanel.jsx     Slide-in resource detail drawer
│   │   ├── hooks/
│   │   │   ├── useGeneralEol.js    Fetch /eol/general + /eol/general/summary
│   │   │   ├── useInventory.js     Fetch /eol/inventory + /eol/summary + /eol/resource/:id
│   │   │   ├── useAlerts.js        Fetch /eol/alerts
│   │   │   └── useConfig.js        Fetch/save /eol/config + trigger /eol/scan
│   │   ├── mocks/
│   │   │   ├── mockGeneralEolData.js   Sample lifecycle records (used when demo mode is on)
│   │   │   ├── mockAccountScanData.js  Sample account inventory
│   │   │   ├── mockOrgScanData.js      Sample org inventory
│   │   │   └── eolMockData.js          Sample dashboard data
│   │   └── utils/
│   │       ├── config.js           Runtime config: API_BASE_URL, IS_DEMO_ENABLED, HAS_API
│   │       ├── classify.js         serviceLabel() + getStatusConfig() helpers
│   │       └── auth.js             Cognito JWT helper (optional)
│   ├── .env                        Default env (safe to commit, no secrets)
│   ├── .env.example                Full env reference with Cognito fields
│   ├── .env.local.example          Local dev setup guide (copy → .env.local)
│   └── package.json
│
├── scripts/
│   ├── run-local-backend.py        Real backend wrapped in Flask — no AWS needed
│   ├── local-api.py                Legacy mock API (demo data only)
│   └── deploy.sh                   One-shot AWS deployment script
│
├── iam/
│   ├── eol-collector-policy.json   Least-privilege IAM policy for the Lambda role
│   ├── trust-lambda.json           Lambda execution role trust policy
│   └── member-account-role.json    Trust policy for member account read-only roles
│
└── Makefile                        Dev and deployment convenience commands
```

---

## Quick start — local dev

### Prerequisites

| Tool | Version |
|---|---|
| Python | 3.10+ |
| Node.js | 18+ (recommend via nvm) |
| pip | latest |

### Option A — Real backend (recommended)

Runs the actual `api_handler.py` logic with file storage. Fetches live lifecycle data from endoflife.date. No AWS credentials needed.

**Terminal 1 — backend:**

```bash
# Install Python deps
pip3 install -r backend/requirements.txt flask flask-cors --break-system-packages

# Start backend on :3001
STORAGE_BACKEND=file python3 scripts/run-local-backend.py
```

**Terminal 2 — frontend:**

```bash
cd frontend
npm install

# Create local env (points to :3001)
cp .env.local.example .env.local

npm start     # opens http://localhost:3000
```

**Or both in one command:**

```bash
cd frontend
npm run dev   # starts backend :3001 + frontend :3000 via concurrently
```

> **First request to `/general-eol`** fetches all 13 AWS service lifecycle catalogues from endoflife.date (~15s). Subsequent requests are served from cache (24h TTL, stored at `/tmp/eol-data/`).

---

### Option B — Demo mode (no backend, no network)

```bash
cd frontend
npm install
```

Create `frontend/.env.local`:

```env
REACT_APP_API_URL=
REACT_APP_ENABLE_DEMO_DATA=true
```

```bash
npm start
```

All pages load sample mock data. No API calls made.

---

### Force refresh General EOL cache

If the cached lifecycle data is stale or empty:

```bash
curl -X POST http://localhost:3001/eol/general/refresh
```

---

## Environment variables

### Backend (`backend/.env.example`)

| Variable | Default | Description |
|---|---|---|
| `STORAGE_BACKEND` | `file` | `file` (local), `dynamodb`, or `s3` |
| `EOL_DATA_DIR` | `/tmp/eol-data` | Data directory when `STORAGE_BACKEND=file` |
| `DYNAMODB_TABLE` | `aws-eol-inventory` | DynamoDB inventory table |
| `CONFIG_TABLE` | `aws-eol-config` | DynamoDB config/settings table |
| `DEDUP_TABLE` | `aws-eol-alert-dedup` | Alert deduplication table |
| `EOL_BUCKET` | — | S3 bucket when `STORAGE_BACKEND=s3` |
| `GENERAL_EOL_CACHE_TTL_HOURS` | `24` | Hours before lifecycle cache expires |
| `EOL_API_BASE` | `https://endoflife.date/api` | endoflife.date API base URL |
| `WARN_DAYS` | `180` | Days before EOL to classify as `EXPIRING_SOON` |
| `SNS_TOPIC_ARN` | — | SNS topic for alerts (empty = disabled) |
| `DEDUP_HOURS` | `24` | Minimum hours between duplicate alerts |
| `COLLECTOR_FUNCTION` | `aws-eol-collector` | Collector Lambda name (for manual scan trigger) |
| `AWS_DEFAULT_REGION` | `us-east-1` | AWS region for local runs |
| `PORT` | `3001` | Port for `run-local-backend.py` |

### Frontend (`frontend/.env.local`)

| Variable | Default | Description |
|---|---|---|
| `REACT_APP_API_URL` | _(empty)_ | Backend base URL. Empty = CRA proxy to `:3001` in dev. Set to API Gateway URL in prod. |
| `REACT_APP_ENABLE_DEMO_DATA` | `false` | `true` = use mock data when API unavailable (local demo only) |
| `REACT_APP_COGNITO_USER_POOL_ID` | — | Cognito User Pool ID (optional auth) |
| `REACT_APP_COGNITO_CLIENT_ID` | — | Cognito App Client ID |
| `REACT_APP_COGNITO_REGION` | `us-east-1` | Cognito region |

**Environment matrix:**

| `REACT_APP_API_URL` | `REACT_APP_ENABLE_DEMO_DATA` | Behavior |
|---|---|---|
| empty | false | Dev — CRA proxy forwards to `:3001` |
| empty | true | Demo — mock data, no API calls |
| set | false | Production — real API only |
| set | true | Dev with API + demo fallback |

---

## Backend modules

### `api_handler.py` — REST API router

Lambda entry point for all frontend API requests. Routes HTTP method + path to the correct handler function.

**Routes:**

| Method | Path | Handler | Description |
|---|---|---|---|
| `GET` | `/eol/general` | `handle_general_eol` | Public lifecycle library. Params: `service`, `status`, `search`, `includeLegacy` |
| `GET` | `/eol/general/summary` | `handle_general_eol_summary` | Status counts for the library. Param: `includeLegacy` |
| `POST` | `/eol/general/refresh` | `handle_general_eol_refresh` | Force-refresh lifecycle cache from endoflife.date |
| `GET` | `/eol/inventory` | `handle_inventory` | Account inventory. Params: `service`, `status`, `region` |
| `GET` | `/eol/summary` | `handle_summary` | Inventory totals by service and status |
| `GET` | `/eol/resource/:id` | `handle_resource` | Single resource detail |
| `GET` | `/eol/alerts` | `handle_alerts` | EOL + expiring resources sorted by recency |
| `GET` | `/eol/config` | `handle_config_get` | Current settings |
| `PUT` | `/eol/config` | `handle_config_put` | Save settings |
| `POST` | `/eol/scan` | `handle_scan_trigger` | Invoke collector Lambda asynchronously |

**Response envelope:**

```json
// Success
{ "ok": true, "data": { ... }, "meta": { ... } }

// Error
{ "ok": false, "error": { "code": "...", "message": "...", "details": "..." } }
```

---

### `general_eol.py` — Public lifecycle library

Fetches all AWS service lifecycle data from [endoflife.date](https://endoflife.date), normalizes it to the frontend shape, and caches results.

**Key functions:**

| Function | Description |
|---|---|
| `fetch_all()` | Fetches all 13 configured products from endoflife.date stable JSON API |
| `get_or_refresh(storage)` | Returns cached records if fresh; otherwise fetches and caches. Thread-safe — uses a module-level lock to prevent concurrent stampede |
| `filter_records(records, service, status, search, include_legacy)` | Server-side filtering. `include_legacy=False` (default) hides EOL records older than 3 years |
| `compute_summary(records)` | Returns `{ EOL: n, EXPIRING_SOON: n, ... }` counts |
| `_normalize(slug, raw)` | Converts a raw endoflife.date cycle record to frontend shape |
| `_classify(eol_from, is_eoes)` | Returns `(status, days_to_eol)` from an EOL date string |
| `_is_legacy(record)` | True if record is EOL and its EOL date is older than 3 years |

**Configured products (13):**

Lambda, EKS, RDS MySQL, RDS PostgreSQL, RDS MariaDB, Aurora PostgreSQL, ElastiCache Redis, Amazon Linux, MSK Kafka, OpenSearch, DocumentDB, Neptune, AWS Glue

**Cache behavior:**
- First request: ~15s (fetches 13 products from endoflife.date)
- Subsequent: instant (file/DynamoDB cache, 24h TTL by default)
- Empty results are NOT cached — retried on next request
- `POST /eol/general/refresh` force-bypasses cache

---

### `eol_collector.py` — Account/org scanner

Scans AWS services across all enabled regions for an account. Cross-references discovered versions against endoflife.date per-version API. Writes results to storage and fires SNS alerts.

**Supported services:**

Lambda (runtime), EKS (cluster version), RDS (MySQL, PostgreSQL, MariaDB instances + Aurora clusters), ElastiCache (Redis), EC2 (Amazon Linux AMIs), MSK (Kafka version), OpenSearch, DocumentDB, Neptune, Glue (job version)

**Key functions:**

| Function | Description |
|---|---|
| `fetch_eol(product, version)` | Calls `endoflife.date/api/v1/products/{product}/{version}/` with in-memory cache |
| `classify_status(eol_data)` | Returns `(status, eol_date, days_to_eol)` |
| `run_all_collectors(session, account_id)` | Runs all service collectors across all regions |
| `collect_lambda / collect_eks / collect_rds / ...` | Per-service AWS API collectors |
| `send_alert(resource)` | Publishes EOL/expiring alert to SNS |
| `lambda_handler(event, context)` | Entry point. Reads config for org-scan flag; assumes cross-account roles if enabled |

**Security model:**
- Uses `STS AssumeRole` — never stores credentials
- Read-only IAM policy (`iam/eol-collector-policy.json`)
- `ExternalId` required for cross-account access

---

### `storage.py` — Storage abstraction

Unified interface over three storage backends. Controlled by `STORAGE_BACKEND` env var.

**Backends:**

| Backend | Env value | When to use |
|---|---|---|
| `FileBackend` | `file` | Local development — zero AWS required |
| `DynamoDBBackend` | `dynamodb` | Production Lambda (default) |
| `S3Backend` | `s3` | Alternative production storage |

**Interface (all backends implement):**

| Method | Description |
|---|---|
| `save_resources(items)` | Upsert scan results with TTL and `scanned_at` timestamp |
| `get_resources(filters)` | Query by `status`, `service`, `region` |
| `get_resource_by_id(id)` | Single resource lookup |
| `get_config()` | Load settings, merged with defaults |
| `save_config(config)` | Persist settings |
| `get_general_eol_cache()` | Load lifecycle cache `{ records, refreshed_at, expires_at }` |
| `save_general_eol_cache(records, refreshed_at, expires_at)` | Persist lifecycle cache |

**DynamoDB tables used:**
- `aws-eol-inventory` — scanned resource records
- `aws-eol-config` — settings + general EOL cache (stored as JSON blob)
- `aws-eol-alert-dedup` — alert deduplication keys with TTL

---

### `alert_notifier.py` — SNS alert sender

Sends deduplicated SNS notifications for EOL and expiring-soon resources.

**Deduplication:** Each `(resource_id, eol_status)` pair is stored in the dedup table with a configurable TTL (`DEDUP_HOURS`, default 24h). The same resource won't trigger more than one alert per day.

**Triggered by:** DynamoDB Streams on the inventory table, or called directly from `eol_collector.py`.

---

## Frontend modules

### Pages

| Page | Route | Backend data | Description |
|---|---|---|---|
| `OverviewPage` | `/overview` | None (static) | Product landing: scan mode cards, security strip, how-it-works |
| `GeneralEolPage` | `/general-eol` | `GET /eol/general` | Public lifecycle library with real endoflife.date data, filters, legacy toggle |
| `AccountScanPage` | `/account-scan` | None yet (wizard only) | 5-step onboarding: ExternalId → CloudFormation → Role ARN → Validate → Done |
| `OrgScanPage` | `/org-scan` | None yet (wizard only) | 6-step onboarding: Admin account → ExternalId → Org role → StackSet → Details → Review |
| `DashboardPage` | `/dashboard` | `GET /eol/inventory` | Account inventory table with metric cards, filters, export CSV |
| `ServicesPage` | `/services` | `GET /eol/summary` | Service risk overview: distribution bars, click-to-filter |
| `AlertsPage` | `/alerts` | `GET /eol/alerts` | Alert history: All / EOL / Expiring Soon / Acknowledged / Snoozed tabs |
| `SettingsPage` | `/settings` | `GET /eol/config` | 5-section left-nav settings form |
| `ResourceDetailPage` | `/resource/:id` | `GET /eol/resource/:id` | Full resource detail with EOL timeline |

---

### Components

| Component | Description |
|---|---|
| `StatusBadge` | Colored pill for EOL / Expiring Soon / Ext. Support / Supported |
| `MetricCard` | Count card with label, click-to-filter, loading skeleton |
| `ResourceTable` | Sortable paginated table for the account inventory |
| `FilterBar` | Search + Service + Status + Region filter row with Clear filters |
| `EOLTimeline` | Visual bar showing days remaining or past EOL |
| `DetailPanel` | Slide-in drawer for a selected resource row |

---

### Hooks

All hooks use [TanStack React Query](https://tanstack.com/query) for caching and background refetch.

| Hook | Endpoint | Returns |
|---|---|---|
| `useGeneralEol(filters)` | `GET /eol/general` | `{ data, loading, isError, isMock, refetch }` |
| `useGeneralEolSummary(includeLegacy)` | `GET /eol/general/summary` | `{ summary, isMock }` |
| `useInventory(filters)` | `GET /eol/inventory` | `{ data: { items, isMock }, isLoading, isError }` |
| `useSummary()` | `GET /eol/summary` | `{ data: { totals, by_service, ... }, isMock }` |
| `useResource(id)` | `GET /eol/resource/:id` | normalized resource object |
| `useAlerts(limit)` | `GET /eol/alerts` | `{ data: { items, isMock } }` |
| `useConfig()` | `GET /eol/config` | config object |
| `useSaveConfig()` | `PUT /eol/config` | mutation |
| `useTriggerScan()` | `POST /eol/scan` | mutation |

**Production vs demo behavior:**

All hooks follow the same pattern:
1. If `REACT_APP_API_URL` is set → call real API, throw on failure
2. If `REACT_APP_ENABLE_DEMO_DATA=true` and no API → return mock data silently
3. If neither → return empty/error state, no mock data

---

### Utils

| File | Description |
|---|---|
| `utils/config.js` | `API_BASE_URL`, `IS_DEMO_ENABLED`, `HAS_API`, `IS_PRODUCTION_LIKE` — single source of truth for runtime config |
| `utils/classify.js` | `serviceLabel(rawName)` maps raw service types (e.g. `RDS_postgres`) to display names (`RDS PostgreSQL`). `getStatusConfig(status)` returns label, color hex, bg color per status. |
| `utils/auth.js` | `getJwt()` — returns Cognito JWT if auth is configured, else null. Used by hooks to add `Authorization` headers. |

---

### Mocks

Used only when `REACT_APP_ENABLE_DEMO_DATA=true` or during tests.

| File | Contents |
|---|---|
| `mocks/mockGeneralEolData.js` | 49 sample lifecycle records across all service families |
| `mocks/mockAccountScanData.js` | Sample account inventory + summary |
| `mocks/mockOrgScanData.js` | Sample org with multiple accounts |
| `mocks/eolMockData.js` | Dashboard inventory + summary used by useInventory/useSummary |

---

## API contract

### General EOL

```
GET /eol/general
Query params:
  service=Lambda          (substring match, case-insensitive)
  status=EOL              (exact: EOL | EXPIRING_SOON | EXTENDED_SUPPORT | SUPPORTED)
  search=python           (searches service + version + family)
  includeLegacy=true      (default false — hides EOL records older than 3 years)

Response:
{
  "ok": true,
  "data": [
    {
      "id":                 "aws-lambda-python3_9",
      "service":            "Lambda",
      "version":            "python3.9",
      "eolDate":            "2026-07-14",
      "daysToEol":          45,
      "status":             "EXPIRING_SOON",
      "family":             null,
      "recommendedUpgrade": "python3.12",
      "source":             "endoflife.date",
      "product_slug":       "aws-lambda"
    }
  ],
  "meta": {
    "total":          14,
    "refreshed_at":   "2026-05-30T09:00:00",
    "source":         "endoflife.date",
    "include_legacy": false
  }
}

GET /eol/general/summary?includeLegacy=false
Response:
{
  "ok": true,
  "data": { "EOL": 10, "EXPIRING_SOON": 14, "EXTENDED_SUPPORT": 0, "SUPPORTED": 89, "UNKNOWN": 2 },
  "meta": { "total": 115, "refreshed_at": "...", "include_legacy": false }
}

POST /eol/general/refresh
Response:
{ "ok": true, "meta": { "total": 197, "refreshed_at": "..." } }
```

### Account Inventory

```
GET /eol/inventory?service=Lambda&status=EOL&region=us-east-1
GET /eol/summary
GET /eol/resource/:resource_id
GET /eol/alerts?limit=100
GET /eol/config
PUT /eol/config   body: { warn_days, alert_email, scan_schedule, ... }
POST /eol/scan
```

---

## Running tests

```bash
cd backend

# Install
pip3 install pytest pytest-cov requests boto3 --break-system-packages

# Run all (47 tests)
python3 -m pytest tests/ -v

# With coverage
python3 -m pytest tests/ -v --cov=. --cov-report=term-missing
```

**Test files:**

| File | Tests | What is covered |
|---|---|---|
| `test_classify.py` | 8 | `classify_status()` — EOL, expiring, extended support, unknown, boundary conditions |
| `test_collector.py` | 7 | `fetch_eol()` caching, `collect_lambda()`, `collect_eks()`, file storage round-trip |
| `test_general_eol.py` | 32 | `_classify()`, `_normalize()`, `compute_summary()`, `filter_records()`, `_is_legacy()`, `get_or_refresh()` cache hit/miss/expiry, `fetch_all()` network mock, file backend cache round-trip |

---

## Makefile reference

```bash
make help               # Show all targets

make install            # Install Python + Node deps
make install-backend    # pip install requirements.txt + dev tools
make install-frontend   # npm install

make dev                # Start real backend :3001 + React :3000
make backend            # Real backend only (file storage, no AWS)
make dev-api            # Legacy mock API only (demo data)
make dev-frontend       # React dev server only

make test               # Run all Python tests (quiet)
make test-verbose       # Run with coverage report

make scan               # Run collector against real AWS → DynamoDB
make scan-file          # Run collector → /tmp/eol-data (no AWS storage)
make scan-org           # Trigger org-wide Lambda scan

make build              # Build React production bundle
make package            # Package Lambda zip (backend/ + deps)
make deploy             # Full AWS deployment via scripts/deploy.sh
make infra              # Create DynamoDB tables + enable TTL only

make logs               # Tail collector Lambda logs
make logs-api           # Tail API Lambda logs
make count              # Count DynamoDB inventory records

make clean              # Remove build artifacts and __pycache__
```

---

## AWS deployment

### One-shot deploy

```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

The script creates: IAM role, DynamoDB tables, SNS topic, 3 Lambda functions, EventBridge daily schedule, API Gateway.

### Manual package + deploy

```bash
# Package Lambda zip
make package

# Update existing Lambda
aws lambda update-function-code \
  --function-name aws-eol-collector \
  --zip-file fileb://eol_monitor.zip

aws lambda update-function-code \
  --function-name aws-eol-api \
  --zip-file fileb://eol_monitor.zip
```

### Production frontend

```bash
# Build
cd frontend && npm run build

# Upload to S3
aws s3 sync build/ s3://your-bucket/ --delete

# Invalidate CloudFront
aws cloudfront create-invalidation \
  --distribution-id EXXXXXXXXXX \
  --paths "/*"
```

Set `REACT_APP_API_URL=https://<api-id>.execute-api.<region>.amazonaws.com/<stage>` at build time.

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| `/general-eol` shows 0 entries | Stale empty cache from before fix | `curl -X POST http://localhost:3001/eol/general/refresh` |
| Backend starts but `/eol/general` returns `data: []` | endoflife.date unreachable | Check internet connection; run `curl https://endoflife.date/api/aws-lambda.json` |
| Frontend shows "Backend API is not configured" | `REACT_APP_API_URL` empty and `IS_DEMO_ENABLED=false` | Set one of them; see env matrix above |
| `Module not found: flask` | Flask not installed | `pip3 install flask flask-cors --break-system-packages` |
| `node: command not found` | Wrong Node version | Run `nvm use 20` or install Node 18+ |
| Account scan wizard shows mock dashboard in prod | `IS_DEMO_ENABLED=true` | Set `REACT_APP_ENABLE_DEMO_DATA=false` |
| DynamoDB `ResourceNotFoundException` | Table not created | `make infra` |
| Lambda `AccessDeniedException` | Missing IAM permissions | Check `iam/eol-collector-policy.json` against Lambda role |
| CORS error in browser | API Gateway CORS not configured | Redeploy API Gateway stage after adding OPTIONS method |

---

*Backend: Python 3.10+ · boto3 · requests · Flask (local dev only)*
*Frontend: React 18 · Tailwind CSS · TanStack React Query · lucide-react · Recharts · Axios*
*Data source: [endoflife.date](https://endoflife.date)*
