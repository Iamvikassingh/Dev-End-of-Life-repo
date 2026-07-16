# AWS EOL Monitor — Frontend

React 18 · Tailwind CSS · TanStack React Query · lucide-react

A SaaS-style dashboard for tracking AWS service end-of-life dates. Supports three scan modes — public lifecycle library, single account scan, and organization-wide scan — all using real backend data with a demo mode for local development.

---

## Quick start

### 1. Install

```bash
npm install
```

### 2. Configure environment

```bash
cp .env.local.example .env.local
```

`.env.local` options:

```env
# Option A — Real backend (recommended)
REACT_APP_API_URL=http://localhost:3001
REACT_APP_ENABLE_DEMO_DATA=false

# Option B — Demo mode (no backend needed)
REACT_APP_API_URL=
REACT_APP_ENABLE_DEMO_DATA=true
```

### 3. Run

```bash
# Frontend only (backend must be running separately on :3001)
npm start

# Frontend + backend together (one command)
npm run dev

# Production build
npm run build
```

> **CRA proxy:** When `REACT_APP_API_URL` is empty, all `/eol/*` requests are automatically forwarded to `http://localhost:3001` via the `"proxy"` field in `package.json`. No extra config needed for local dev.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `REACT_APP_API_URL` | empty | Backend base URL. Empty = CRA proxy to `:3001` in dev. Set to API Gateway URL in production. |
| `REACT_APP_ENABLE_DEMO_DATA` | `false` | `true` enables mock data fallback (local demo only, never in production) |
| `REACT_APP_COGNITO_USER_POOL_ID` | — | Cognito User Pool ID (optional auth) |
| `REACT_APP_COGNITO_CLIENT_ID` | — | Cognito App Client ID |
| `REACT_APP_COGNITO_REGION` | `us-east-1` | Cognito region |

---

## Project structure

```
src/
├── App.jsx                      Sidebar + React Router routes
│
├── pages/
│   ├── OverviewPage.jsx         /overview       Product landing (static)
│   ├── GeneralEolPage.jsx       /general-eol    Public lifecycle library (real API)
│   ├── AccountScanPage.jsx      /account-scan   5-step account onboarding wizard
│   ├── OrgScanPage.jsx          /org-scan       6-step org onboarding wizard
│   ├── DashboardPage.jsx        /dashboard      Account inventory + metric cards
│   ├── ServicesPage.jsx         /services       Service-level risk overview
│   ├── AlertsPage.jsx           /alerts         Alert history with tabs
│   ├── SettingsPage.jsx         /settings       Section-based settings form
│   └── ResourceDetailPage.jsx   /resource/:id   Single resource detail
│
├── components/
│   ├── StatusBadge.jsx          EOL status pill (EOL / Expiring Soon / Ext. Support / Supported)
│   ├── MetricCard.jsx           Summary count card with click-to-filter
│   ├── ResourceTable.jsx        Paginated sortable inventory table
│   ├── FilterBar.jsx            Search + Service + Status + Region filter row
│   ├── EOLTimeline.jsx          Visual days-to-EOL bar
│   └── DetailPanel.jsx          Slide-in resource detail drawer
│
├── hooks/
│   ├── useGeneralEol.js         GET /eol/general  +  /eol/general/summary
│   ├── useInventory.js          GET /eol/inventory  +  /eol/summary  +  /eol/resource/:id
│   ├── useAlerts.js             GET /eol/alerts
│   └── useConfig.js             GET/PUT /eol/config  +  POST /eol/scan
│
├── mocks/                       Sample data (used only when REACT_APP_ENABLE_DEMO_DATA=true)
│   ├── mockGeneralEolData.js    49 sample lifecycle records
│   ├── mockAccountScanData.js   Sample account inventory + summary
│   ├── mockOrgScanData.js       Sample org with multiple accounts
│   └── eolMockData.js           Dashboard/alerts/services sample data
│
└── utils/
    ├── config.js                API_BASE_URL, IS_DEMO_ENABLED, HAS_API constants
    ├── classify.js              serviceLabel() and getStatusConfig() helpers
    └── auth.js                  Cognito JWT helper (returns null if auth not configured)
```

---

## Pages

### `/overview` — Overview
Static product landing. No API calls. Shows scan mode cards (→ `/general-eol`, `/account-scan`, `/org-scan`), security strip, how-it-works steps, and why-teams-use-this grid.

### `/general-eol` — General EOL Library
Public lifecycle data from endoflife.date via the real backend API. No AWS credentials required.

- Summary cards (EOL / Expiring Soon / Ext. Support / Supported) — click to filter
- Search, Service dropdown, Status dropdown — all reset page on change
- **Legacy toggle** — default OFF hides EOL records older than 3 years; ON shows full history
- Clear filters does not reset the legacy toggle
- Sortable table, 15 rows/page, pagination
- Demo banner only when `IS_DEMO_ENABLED=true`

### `/account-scan` — Account Scan Wizard
5-step onboarding for a single AWS account:
`ExternalId → CloudFormation role → Role ARN → Validate → Done`

Validates: Account ID = 12 digits, Role ARN format, ARN account ID matches Account ID field.
In production: wizard completion navigates to `/dashboard`.
In demo mode: shows mock `AccountDashboard`.

### `/org-scan` — Organization Scan Wizard
6-step onboarding for AWS Organizations:
`Admin account → ExternalId → Org role (CF) → StackSet (CF) → Details → Review`

Validates: Org ID format `o-[a-z0-9]{10,32}`, Management Account ID = 12 digits, Org Role ARN cross-validated.

### `/dashboard` — EOL Dashboard
Account inventory from real backend. Eyebrow: `ACCOUNT INVENTORY`.

- 4 metric cards (click to toggle status filter)
- FilterBar: search + service + status + region
- Export CSV (filtered rows)
- Run Scan Now → `POST /eol/scan` (hidden if no API configured)
- Paginated sortable table

### `/services` — Services Overview
Service-level risk from `GET /eol/summary`. Distribution bars per service type. Click card → `/dashboard?service=<name>`.

### `/alerts` — Alert History
Alert records from `GET /eol/alerts`.
Tabs: All / EOL / Expiring Soon / Acknowledged / Snoozed. Paginated, 15 rows/page.

### `/settings` — Settings
5-section left-nav form. Sections: General, Notifications, Scan Schedule, Scan Scope, Monitored Services.
Save → `PUT /eol/config`. Scan trigger → `POST /eol/scan`.

---

## Hooks

All hooks use [TanStack React Query](https://tanstack.com/query) for caching and background refetch.

### `useGeneralEol({ service, status, search, includeLegacy })`
Calls `GET /eol/general` with filter params. Returns `{ data, loading, isError, isMock, refetch }`.

### `useGeneralEolSummary(includeLegacy)`
Calls `GET /eol/general/summary`. Returns `{ summary: { EOL, EXPIRING_SOON, ... }, isMock }`.

### `useInventory(filters)` / `useSummary()` / `useResource(id)`
Inventory and summary data for the dashboard. Refetch every 60s.

### `useAlerts(limit)`
Returns `{ data: { items, isMock }, isLoading, refetch }`.

### `useConfig()` / `useSaveConfig()` / `useTriggerScan()`
Settings CRUD and manual scan trigger.

**Production vs demo (all hooks):**
1. `REACT_APP_API_URL` set → real API, throws on failure
2. `REACT_APP_ENABLE_DEMO_DATA=true`, no API → mock data silently
3. Neither → empty state, no fallback

---

## Components

| Component | Purpose | Key props |
|---|---|---|
| `StatusBadge` | Colored EOL status pill | `status` |
| `MetricCard` | Count card with loading skeleton | `label`, `value`, `status`, `loading`, `onClick`, `active` |
| `ResourceTable` | Sortable paginated inventory table | `items`, `onSelect`, `filterKey` |
| `FilterBar` | Search + dropdowns filter row | `filters`, `onChange`, `totalFiltered` |
| `EOLTimeline` | Days-to-EOL progress bar | `daysToEol`, `eolDate`, `status` |
| `DetailPanel` | Slide-in resource detail drawer | `resource`, `onClose` |

---

## Utils

### `utils/config.js`
```js
import { API_BASE_URL, IS_DEMO_ENABLED, HAS_API } from "../utils/config";
```
Single source of truth for runtime config. Import here instead of reading `process.env` directly in components.

### `utils/classify.js`
```js
import { serviceLabel, getStatusConfig } from "../utils/classify";

serviceLabel("RDS_postgres")   // → "RDS PostgreSQL"
getStatusConfig("EOL")         // → { label, hex, bghex, ... }
```

### `utils/auth.js`
```js
import { getJwt } from "../utils/auth";
const jwt = await getJwt();    // Cognito JWT or null
```
Used by hooks to add `Authorization: Bearer <jwt>` headers when Cognito is configured.

---

## Key dependencies

| Package | Purpose |
|---|---|
| `react` + `react-dom` | UI framework |
| `react-router-dom` v6 | Client-side routing |
| `@tanstack/react-query` v5 | Data fetching and caching |
| `axios` | HTTP client |
| `lucide-react` | Icon library (all icons, 16px, strokeWidth 1.5/2) |
| `tailwindcss` | Utility-first CSS |
| `recharts` | Distribution bar charts in ServicesPage |
| `date-fns` | Relative time in AlertsPage |
| `concurrently` | `npm run dev` — runs backend + frontend together |
| `aws-amplify` | Cognito auth (optional, disabled by default) |

---

## Scripts

```bash
npm start          # Start dev server on :3000
npm run dev        # Start backend :3001 + frontend :3000
npm run build      # Production build → frontend/build/
npm test           # React tests
```
