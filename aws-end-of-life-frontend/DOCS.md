# Frontend — AWS EOL Monitor

React 18 + Tailwind CSS + TanStack React Query

---

## How to run

### Install dependencies

```bash
cd frontend
npm install
```

### Option A — Real backend (recommended)

Start the backend first (see `backend/DOCS.md`), then:

```bash
npm start
# Opens http://localhost:3000
```

Or start both together from the frontend folder:

```bash
npm run dev
# Starts backend on :3001 + React on :3000 via concurrently
```

### Option B — Demo mode (no backend needed)

Create `frontend/.env.local`:

```env
REACT_APP_API_URL=
REACT_APP_ENABLE_DEMO_DATA=true
```

```bash
npm start
```

All pages load sample mock data. No network calls made.

### Production build

```bash
npm run build
# Output: frontend/build/
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `REACT_APP_API_URL` | _(empty)_ | Backend base URL. Empty = CRA proxy to `:3001` in dev. Set to API Gateway URL in production. |
| `REACT_APP_ENABLE_DEMO_DATA` | `false` | `true` enables mock data fallback (local demo only, never in production) |
| `REACT_APP_COGNITO_USER_POOL_ID` | — | Cognito User Pool ID (optional auth) |
| `REACT_APP_COGNITO_CLIENT_ID` | — | Cognito App Client ID |
| `REACT_APP_COGNITO_REGION` | `us-east-1` | Cognito region |

**Env behavior matrix:**

| `REACT_APP_API_URL` | `REACT_APP_ENABLE_DEMO_DATA` | Behavior |
|---|---|---|
| empty | false | Dev — CRA proxy forwards `/eol/*` to `:3001` |
| empty | true | Demo — mock data only, no API calls |
| set | false | Production — real API, proper error states |
| set | true | Dev with API + demo fallback on failure |

Copy `.env.local.example` for local setup.

---

## Project structure

```
src/
├── App.jsx                     Sidebar navigation + React Router routes
├── pages/                      One file per route
├── components/                 Shared UI components
├── hooks/                      React Query data hooks
├── mocks/                      Sample data (demo mode only)
└── utils/                      Config helpers, label mappers, auth
```

---

## Pages

### `OverviewPage.jsx` — `/overview`

Product landing page. Fully static — no backend required.

- Hero section with headline and subtext
- Trust stats row (13 services, 50+ lifecycles, all regions)
- Security strip (6 points: no access keys, read-only, ExternalId, STS, no secrets, revoke anytime)
- Three scan mode cards with CTAs → `/general-eol`, `/account-scan`, `/org-scan`
- "How it works" 4-step section
- "Why teams use this" 4-point grid

---

### `GeneralEolPage.jsx` — `/general-eol`

Public lifecycle library. Fetches real data from the backend which sources it from endoflife.date.

**Data:** `useGeneralEol` + `useGeneralEolSummary`

**Features:**
- 4 summary cards (EOL / Expiring Soon / Ext. Support / Supported) — click to filter
- Search input, Service dropdown, Status dropdown — all reset to page 1 on change
- **Include legacy toggle** — default OFF hides EOL records older than 3 years; ON shows full history
- Clear filters button (does NOT reset the legacy toggle)
- Sortable table columns
- Pagination (15 rows/page)
- `Source: endoflife.date` attribution
- Planning tip below table
- Demo banner (only when `IS_DEMO_ENABLED=true` and using mock data)
- API error state with Retry button

**Service list** is derived from real API response (populated via `useEffect` + `useRef` when no service filter is active).

---

### `AccountScanPage.jsx` — `/account-scan`

5-step onboarding wizard for connecting a single AWS account.

| Step | What happens |
|---|---|
| 1 — ExternalId | Generate unique ExternalId for this account |
| 2 — Deploy Role | CloudFormation template (Copy / Download / CLI command) |
| 3 — Role ARN | Account name, Account ID (12 digits), Role ARN, Region scope. Cross-validates ARN account ID vs Account ID field |
| 4 — Validate | Confirms role is accessible (placeholder until Account Validation API is built) |
| 5 — Done | Success state |

**Production mode:** Wizard completion navigates to `/dashboard`.
**Demo mode** (`IS_DEMO_ENABLED=true`): Wizard completion loads mock `AccountDashboard` component inline.

---

### `OrgScanPage.jsx` — `/org-scan`

6-step onboarding wizard for connecting AWS Organizations.

| Step | What happens |
|---|---|
| 1 — Admin Account | Choose management account |
| 2 — ExternalId | Generate unique org ExternalId |
| 3 — Org Role | CloudFormation for management account role |
| 4 — StackSet | CloudFormation for member account roles via StackSet |
| 5 — Details | Org ID (`o-[a-z0-9]{10,32}`), Management Account ID, Org Role ARN, OU filters. Cross-validates ARN vs account ID |
| 6 — Review | Monospace summary; Validate & Discover |

Same production/demo behavior as AccountScanPage.

---

### `DashboardPage.jsx` — `/dashboard`

Account inventory table with EOL metrics.

**Data:** `useInventory` + `useSummary`

**Features:**
- Eyebrow: `ACCOUNT INVENTORY`
- 4 metric cards — click to toggle status filter
- `FilterBar` component: search + service + status + region
- Filtered result count (`Showing X filtered resources`)
- Export CSV (filtered rows)
- Run Scan Now button (hidden if no API configured)
- Paginated sortable table
- Days to EOL format: `"730d past EOL · EOL: 2024-05-30"`
- Demo banner (only when `IS_DEMO_ENABLED=true`)
- Not-configured banner (when no API and no demo)
- API error banner (when API returns error)

---

### `ServicesPage.jsx` — `/services`

Service-level risk overview.

**Data:** `useSummary`

**Features:**
- Global distribution bar across all services
- One card per service type showing EOL/Expiring/etc counts
- Distribution bar per card
- Click card → `/dashboard?service=<name>`
- Click status chip → `/dashboard?service=<name>&status=<status>`
- Empty state when no API and no demo mode

---

### `AlertsPage.jsx` — `/alerts`

Alert history for EOL and expiring-soon resources.

**Data:** `useAlerts`

**Features:**
- Header with eyebrow `ALERT HISTORY`
- 5 tabs: All / EOL / Expiring Soon / Acknowledged / Snoozed
- Paginated table (15 rows/page) with sticky header
- Resource ARN truncated with `title` tooltip
- Last seen formatted relative time
- Refresh button
- Demo / not-configured / error banners

---

### `SettingsPage.jsx` — `/settings`

Section-based settings form.

**Data:** `useConfig` + `useSaveConfig` + `useTriggerScan`

**Sections (left nav):**

| Section | Fields |
|---|---|
| General | Warning window (days), notification email |
| Notifications | Slack webhook, SNS topic ARN |
| Scan Schedule | Cron expression |
| Scan Scope | Current account only / All organization accounts |
| Monitored Services | Toggle per-service enable/disable |

**Behavior:**
- Form state persists when switching sections
- Save button: "Save Settings"
- Save confirmation: green ✓ in production, amber in demo mode
- Reset Changes restores to last saved state
- Run Scan Now triggers `POST /eol/scan`

---

### `ResourceDetailPage.jsx` — `/resource/:id`

Full detail view for a single scanned resource.

**Data:** `useResource(id)`

Shows all fields: ARN, service type, region, version, EOL date, days to EOL, recommended upgrade, last scanned. Uses `EOLTimeline` component for visual status bar.

---

## Components

### `StatusBadge.jsx`

Colored pill label for EOL status.

```jsx
<StatusBadge status="EOL" />           // red
<StatusBadge status="EXPIRING_SOON" /> // amber
<StatusBadge status="EXTENDED_SUPPORT" /> // blue
<StatusBadge status="SUPPORTED" />    // green
```

---

### `MetricCard.jsx`

Summary count card used in DashboardPage.

Props: `label`, `value`, `status`, `loading`, `onClick`, `active`

Shows loading skeleton when `loading=true`. Highlights when `active=true` (user filtered by this status).

---

### `ResourceTable.jsx`

Paginated sortable table for account inventory.

Props: `items`, `onSelect`, `filterKey` (resets page when filter changes)

Features: sticky `<thead>`, hover row highlight, resource name truncated with `title` tooltip.

---

### `FilterBar.jsx`

Shared filter row used by DashboardPage.

Props: `filters` (`{ service, status, region, search }`), `onChange`, `totalFiltered`

Shows "Showing X filtered resources" when any filter is active. All selects use polished `appearance-none` + ChevronDown icon.

---

### `EOLTimeline.jsx`

Visual days-to-EOL progress bar.

Props: `daysToEol`, `eolDate`, `status`

Red for past EOL, amber for expiring soon, green for supported.

---

### `DetailPanel.jsx`

Slide-in detail drawer for a selected resource row.

Props: `resource`, `onClose`

---

## Hooks

All hooks use TanStack React Query. Production vs demo behavior is controlled by `utils/config.js`.

### `useGeneralEol(filters)`

```js
const { data, loading, isError, isMock, refetch } = useGeneralEol({
  service: "Lambda",
  status: "EOL",
  search: "python",
  includeLegacy: false,   // default false — hides records older than 3 years
});
```

Calls `GET /eol/general` with the filter params. Returns sorted, filtered records array.

---

### `useGeneralEolSummary(includeLegacy)`

```js
const { summary, isMock } = useGeneralEolSummary(false);
// summary = { EOL: 10, EXPIRING_SOON: 14, EXTENDED_SUPPORT: 0, SUPPORTED: 89 }
```

Calls `GET /eol/general/summary?includeLegacy=false`. Counts stay in sync with the table.

---

### `useInventory(filters)` / `useSummary()` / `useResource(id)`

```js
const { data, isLoading, isError } = useInventory({ service, status, region });
// data = { items: [...], isMock: false }

const { data: summary } = useSummary();
// summary = { totals: { EOL, EXPIRING_SOON, ... }, by_service: {...} }
```

Calls `/eol/inventory` and `/eol/summary`. Both refetch every 60s.

---

### `useAlerts(limit)`

```js
const { data, isLoading, refetch } = useAlerts(500);
// data = { items: [...], isMock: false }
```

Calls `GET /eol/alerts?limit=500`.

---

### `useConfig()` / `useSaveConfig()` / `useTriggerScan()`

```js
const { data: config } = useConfig();
const save = useSaveConfig();
const scan = useTriggerScan();

save.mutate({ warn_days: 90, alert_email: "ops@example.com" });
scan.mutate();
```

---

## Utils

### `utils/config.js`

Single source of truth for runtime configuration.

```js
import { API_BASE_URL, IS_DEMO_ENABLED, HAS_API, IS_PRODUCTION_LIKE } from "../utils/config";
```

| Export | Value | Description |
|---|---|---|
| `API_BASE_URL` | `REACT_APP_API_URL` env | Backend base URL (empty = relative, CRA proxy in dev) |
| `IS_DEMO_ENABLED` | `REACT_APP_ENABLE_DEMO_DATA === "true"` | Whether mock data fallback is allowed |
| `HAS_API` | `!IS_DEMO_ENABLED` | Treat API as present unless demo-only mode |
| `IS_PRODUCTION_LIKE` | `HAS_API && !IS_DEMO_ENABLED` | True in realistic prod-like session |

---

### `utils/classify.js`

```js
import { serviceLabel, getStatusConfig } from "../utils/classify";

serviceLabel("RDS_postgres")      // → "RDS PostgreSQL"
serviceLabel("Aurora_PostgreSQL") // → "Aurora PostgreSQL"
serviceLabel("Lambda")            // → "Lambda"

const cfg = getStatusConfig("EOL");
// { label: "EOL", hex: "#E53E3E", bghex: "#FFF5F5", ... }
```

---

### `utils/auth.js`

```js
import { getJwt } from "../utils/auth";
const jwt = await getJwt();
// Returns Cognito JWT string if auth is configured, null otherwise
```

Used by hooks to attach `Authorization: Bearer <jwt>` headers.

---

## Mocks

Used only when `REACT_APP_ENABLE_DEMO_DATA=true` or in unit tests. Never shown in production without explicit env flag.

| File | Contents |
|---|---|
| `mocks/mockGeneralEolData.js` | `GENERAL_EOL_DATA` (49 records), `GENERAL_SERVICES` list, `computeGeneralSummary()` |
| `mocks/mockAccountScanData.js` | `MOCK_ACCOUNT`, `MOCK_ACCOUNT_SUMMARY`, `MOCK_ACCOUNT_INVENTORY` |
| `mocks/mockOrgScanData.js` | `MOCK_ORG`, `MOCK_ACCOUNTS`, `ORG_TOTALS`, `MOCK_ORG_INVENTORY` |
| `mocks/eolMockData.js` | `MOCK_INVENTORY`, `MOCK_SUMMARY` for dashboard/alerts/services |

---

## Key dependencies

| Package | Version | Purpose |
|---|---|---|
| `react` | 18 | UI framework |
| `react-router-dom` | 6 | Client-side routing |
| `@tanstack/react-query` | 5 | Data fetching, caching, background refetch |
| `axios` | 1.7 | HTTP client for API calls |
| `lucide-react` | 1.17 | Icon library (all icons, size 16, strokeWidth 1.5/2) |
| `tailwindcss` | 3 | Utility-first CSS |
| `recharts` | 2 | Charts (distribution bars in ServicesPage) |
| `date-fns` | 3 | Relative time formatting in AlertsPage |
| `concurrently` | 9 | Run backend + frontend with `npm run dev` |
| `aws-amplify` | 6 | Cognito auth (optional) |













