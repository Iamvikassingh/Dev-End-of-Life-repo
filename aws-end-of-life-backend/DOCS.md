# Backend — AWS EOL Monitor

Python 3.10+ · boto3 · requests · Flask (local dev server only)

---

## How to run

### Install dependencies

```bash
cd backend
pip3 install -r requirements.txt flask flask-cors --break-system-packages
```

### Option A — Local dev server (no AWS needed)

Uses file storage (`/tmp/eol-data/`). Fetches live lifecycle data from endoflife.date.

```bash
# From project root
STORAGE_BACKEND=file python3 scripts/run-local-backend.py
# → http://localhost:3001
```

Or via Makefile:

```bash
make backend
```

**First request to `GET /eol/general`** fetches 13 AWS service catalogues from endoflife.date (~15s). All subsequent requests are served from cache (24h TTL).

### Option B — Against real AWS

```bash
export AWS_PROFILE=your-profile
export DYNAMODB_TABLE=aws-eol-inventory
export WARN_DAYS=180
export STORAGE_BACKEND=dynamodb

python3 eol_collector.py
```

### Run tests

```bash
python3 -m pytest tests/ -v
# 47 tests, all pass

python3 -m pytest tests/ -v --cov=. --cov-report=term-missing
```

---

## Environment variables

Set in shell, `.env` file (loaded manually), or as Lambda environment variables.

| Variable | Default | Description |
|---|---|---|
| `STORAGE_BACKEND` | `dynamodb` | `file` (local dev), `dynamodb` (production), `s3` |
| `EOL_DATA_DIR` | `/tmp/eol-data` | Data directory when `STORAGE_BACKEND=file` |
| `DYNAMODB_TABLE` | `aws-eol-inventory` | DynamoDB inventory table name |
| `CONFIG_TABLE` | `aws-eol-config` | DynamoDB config + general EOL cache table |
| `DEDUP_TABLE` | `aws-eol-alert-dedup` | Alert deduplication table |
| `EOL_BUCKET` | — | S3 bucket name when `STORAGE_BACKEND=s3` |
| `GENERAL_EOL_CACHE_TTL_HOURS` | `24` | Hours before general EOL cache expires |
| `EOL_API_BASE` | `https://endoflife.date/api` | endoflife.date stable JSON API base |
| `WARN_DAYS` | `180` | Days before EOL to classify as `EXPIRING_SOON` |
| `SNS_TOPIC_ARN` | — | SNS topic ARN for alerts (empty = disabled) |
| `DEDUP_HOURS` | `24` | Minimum hours between duplicate alerts for the same resource |
| `COLLECTOR_FUNCTION` | `aws-eol-collector` | Collector Lambda name for manual scan trigger |
| `AWS_DEFAULT_REGION` | `us-east-1` | AWS region for local runs |
| `PORT` | `3001` | Port for local dev server (`run-local-backend.py`) |

Copy `.env.example` as a reference.

---

## Modules

### `api_handler.py` — REST API router

Lambda entry point. Converts API Gateway proxy events to Python dicts, routes by method + path, and returns responses.

**Routes:**

| Method | Path | Handler | Description |
|---|---|---|---|
| `GET` | `/eol/general` | `handle_general_eol` | Public lifecycle library |
| `GET` | `/eol/general/summary` | `handle_general_eol_summary` | Status counts for library |
| `POST` | `/eol/general/refresh` | `handle_general_eol_refresh` | Force-refresh lifecycle cache |
| `GET` | `/eol/inventory` | `handle_inventory` | Account scanned resources |
| `GET` | `/eol/summary` | `handle_summary` | Inventory totals by service + status |
| `GET` | `/eol/resource/:id` | `handle_resource` | Single resource detail |
| `GET` | `/eol/alerts` | `handle_alerts` | EOL + expiring resources, sorted by recency |
| `GET` | `/eol/config` | `handle_config_get` | Load current settings |
| `PUT` | `/eol/config` | `handle_config_put` | Save settings |
| `POST` | `/eol/scan` | `handle_scan_trigger` | Invoke collector Lambda asynchronously |

**Query parameters for `/eol/general`:**

| Param | Type | Default | Description |
|---|---|---|---|
| `service` | string | — | Substring match on service name, case-insensitive |
| `status` | string | — | Exact match: `EOL`, `EXPIRING_SOON`, `EXTENDED_SUPPORT`, `SUPPORTED` |
| `search` | string | — | Searches service + version + family fields |
| `includeLegacy` | `"true"/"false"` | `"false"` | Include EOL records older than 3 years |

**Response envelope:**

```json
// Success
{
  "ok": true,
  "data": { ... },
  "meta": { "total": 14, "source": "endoflife.date", "refreshed_at": "..." }
}

// Error
{
  "ok": false,
  "error": { "code": "DATA_SOURCE_ERROR", "message": "...", "details": "..." }
}
```

**Key helper:**

```python
def resp(status: int, body: dict) -> dict:
    # Returns API Gateway proxy response with CORS headers
```

---

### `general_eol.py` — Public lifecycle library

Fetches and caches AWS service lifecycle data from endoflife.date. No AWS credentials required.

**Configured products (13):**

| Slug | Display name |
|---|---|
| `aws-lambda` | Lambda |
| `amazon-eks` | EKS |
| `amazon-rds-mysql` | RDS MySQL |
| `amazon-rds-postgresql` | RDS PostgreSQL |
| `amazon-rds-mariadb` | RDS MariaDB |
| `amazon-aurora-postgresql` | Aurora PostgreSQL |
| `amazon-elasticache-redis` | ElastiCache Redis |
| `amazon-linux` | Amazon Linux |
| `amazon-msk` | MSK Kafka |
| `amazon-opensearch` | OpenSearch |
| `amazon-documentdb` | DocumentDB |
| `amazon-neptune` | Neptune |
| `amazon-glue` | AWS Glue |

**Public functions:**

```python
fetch_all() -> list[dict]
# Fetches all 13 products from endoflife.date, normalizes records.
# Uses stable JSON API: https://endoflife.date/api/{slug}.json

get_or_refresh(storage) -> tuple[list[dict], str]
# Returns (records, refreshed_at).
# Serves from cache if TTL not expired.
# Thread-safe: module-level threading.Lock() prevents concurrent stampede.
# Empty results are NOT cached — retried on next request.

filter_records(records, service="", status="", search="", include_legacy=False) -> list[dict]
# Server-side filter. include_legacy=False hides EOL records older than 3 years.

compute_summary(records) -> dict
# Returns { "EOL": n, "EXPIRING_SOON": n, "EXTENDED_SUPPORT": n, "SUPPORTED": n, "UNKNOWN": n }
```

**Private functions:**

```python
_fetch_product_versions(slug) -> list[dict]
# GET https://endoflife.date/api/{slug}.json
# Returns list of cycle dicts or [] on error/non-200

_normalize(slug, raw) -> Optional[dict]
# Converts raw endoflife.date cycle record to frontend shape:
# { id, service, version, eolDate, daysToEol, status, family, recommendedUpgrade, source, product_slug }

_classify(eol_from, is_eoes) -> tuple[str, Optional[int]]
# Returns (status, days_to_eol)
# EOL if past, EXPIRING_SOON if within WARN_DAYS, EXTENDED_SUPPORT if is_eoes, else SUPPORTED

_is_legacy(record) -> bool
# True if status=EOL and eolDate is older than LEGACY_CUTOFF_YEARS (3 years)
```

**Cache behavior:**

```
Request 1 (no cache) → acquires lock → fetches 13 products → writes cache → returns
Request 2 (concurrent) → waits for lock → reads fresh cache → returns instantly
Request 3 (24h later) → cache expired → acquires lock → refetches → writes cache
```

**Normalized record shape:**

```json
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
```

---

### `eol_collector.py` — Account / org scanner

Scans AWS services using read-only API calls, cross-references version against endoflife.date per-version API, and writes to storage.

**Supported AWS services:**

| Service | What is collected |
|---|---|
| Lambda | Function runtime (python3.x, nodejs22.x, java21, etc.) |
| EKS | Cluster Kubernetes version |
| RDS MySQL / PostgreSQL / MariaDB | DB instance engine version |
| Aurora PostgreSQL / MySQL | DB cluster engine version |
| ElastiCache | Redis cluster engine version |
| EC2 | Amazon Linux AMI version (1, 2, 2023) |
| MSK | Kafka broker version |
| OpenSearch | Domain engine version |
| DocumentDB | Cluster engine version |
| Neptune | Cluster engine version |
| Glue | Job Glue version |

**Key functions:**

```python
fetch_eol(product, version) -> Optional[dict]
# GET https://endoflife.date/api/v1/products/{product}/{version}/
# In-memory module-level cache (EOL_CACHE dict) for the Lambda invocation lifetime

classify_status(eol_data) -> tuple[str, Optional[str], Optional[int]]
# Returns (status, eol_date_str, days_to_eol)

get_enabled_regions() -> list[str]
# Calls EC2 describe_regions for opt-in + default regions

run_all_collectors(session, account_id) -> list[dict]
# Runs all 10 collectors across all regions

collect_lambda(session, region, account_id) -> list[dict]
collect_eks(session, region, account_id) -> list[dict]
collect_rds(session, region, account_id) -> list[dict]
collect_elasticache(session, region, account_id) -> list[dict]
collect_ec2_amis(session, region, account_id) -> list[dict]
collect_msk(session, region, account_id) -> list[dict]
collect_opensearch(session, region, account_id) -> list[dict]
collect_documentdb(session, region, account_id) -> list[dict]
collect_neptune(session, region, account_id) -> list[dict]
collect_glue(session, region, account_id) -> list[dict]

send_alert(resource) -> None
# Publishes EOL/EXPIRING_SOON resource to SNS if SNS_TOPIC_ARN is set

lambda_handler(event, context) -> dict
# Entry point. Reads scan_org flag from config.
# For org scans: calls STS AssumeRole for each member account, collects in parallel.
```

**Resource record shape written to storage:**

```json
{
  "resource_id":   "arn:aws:lambda:us-east-1:123456789012:function:my-fn",
  "resource_name": "my-fn",
  "service_type":  "Lambda",
  "region":        "us-east-1",
  "account_id":    "123456789012",
  "version":       "python3.9",
  "eol_status":    "EXPIRING_SOON",
  "eol_date":      "2026-07-14",
  "days_to_eol":   45,
  "scanned_at":    "2026-05-30T09:00:00",
  "ttl":           1751234567
}
```

**Security model:**
- Uses `STS AssumeRole` — no credentials stored
- `ExternalId` required for cross-account trust
- Read-only IAM policy (`iam/eol-collector-policy.json`)
- No write, delete, or secrets access

---

### `storage.py` — Storage abstraction

Unified interface over three storage backends. Controlled by `STORAGE_BACKEND` env var.

```python
from storage import get_storage
storage = get_storage()  # returns FileBackend / DynamoDBBackend / S3Backend
```

**Backends:**

| Class | Env value | Storage | Best for |
|---|---|---|---|
| `FileBackend` | `file` | JSON files in `EOL_DATA_DIR` | Local development, no AWS needed |
| `DynamoDBBackend` | `dynamodb` | AWS DynamoDB | Production Lambda |
| `S3Backend` | `s3` | Single JSON file per data type in S3 | Alternative production storage |

**Interface (same for all backends):**

```python
storage.save_resources(resources: list) -> int
# Upsert scan results. Adds scanned_at timestamp.
# FileBackend: deduplicates by resource_id#service_type key.
# DynamoDB: put_item with TTL (90 days).
# Returns number of records written.

storage.get_resources(filters: Optional[dict] = None) -> list
# filters: { "status": "EOL", "service": "Lambda", "region": "us-east-1" }
# All filters are optional. Returns all records if no filters.

storage.get_resource_by_id(resource_id: str) -> Optional[dict]
# Returns single resource or None.

storage.get_config() -> dict
# Returns settings merged with CONFIG_DEFAULTS.
# CONFIG_DEFAULTS: warn_days=180, enabled_services=[...], etc.

storage.save_config(config: dict) -> None
# Persists settings with updated_at timestamp.

storage.get_general_eol_cache() -> Optional[dict]
# Returns { "records": [...], "refreshed_at": "...", "expires_at": "..." } or None.

storage.save_general_eol_cache(records, refreshed_at, expires_at) -> None
# Persists lifecycle cache.
# DynamoDB: stored in CONFIG_TABLE under config_key="general_eol_cache" as JSON blob.
# FileBackend: written to {EOL_DATA_DIR}/general_eol_cache.json.
```

**DynamoDB tables used:**

| Table | PK | SK | Purpose |
|---|---|---|---|
| `aws-eol-inventory` | `resource_id` | `service_type` | Scanned resource records with TTL |
| `aws-eol-config` | `config_key` | — | Settings + general EOL cache blob |
| `aws-eol-alert-dedup` | `alert_key` | — | Alert deduplication keys with TTL |

---

### `alert_notifier.py` — SNS alert sender

Sends deduplicated SNS notifications for EOL and expiring-soon resources.

**How deduplication works:**

Each alert creates a key `{resource_id}#{eol_status}` in the dedup table with TTL = `now + DEDUP_HOURS`. If the key already exists, the alert is skipped. Default: 24h between duplicate alerts for the same resource.

**Triggered by:**
- DynamoDB Streams on `aws-eol-inventory` (auto-trigger when new records are written)
- Direct call from `eol_collector.py` via `send_alert(resource)`

**Alert message format:**

```
Resource: arn:aws:lambda:us-east-1:123:function:legacy-fn
Service:  Lambda
Region:   us-east-1
Version:  python3.8
Status:   EOL
EOL Date: 2024-10-14
Days:     -228
```

SNS subject: `[AWS EOL] EOL: arn:...function/legacy-fn (Lambda)`

---

## Tests

```bash
python3 -m pytest tests/ -v
```

### `tests/test_classify.py` — 8 tests

Tests for `eol_collector.classify_status()`:

| Test | Scenario |
|---|---|
| `test_eol_when_past` | Date in the past → `EOL`, days negative |
| `test_expiring_soon_within_warn` | Date within 180 days → `EXPIRING_SOON` |
| `test_supported_beyond_warn` | Date beyond 180 days → `SUPPORTED` |
| `test_extended_support` | `isEoes=True` → `EXTENDED_SUPPORT` |
| `test_unknown_on_none` | No EOL data → `UNKNOWN` |
| `test_no_eol_date_returns_supported` | `isMaintained=True`, no date → `SUPPORTED` |
| `test_eol_date_preserved` | EOL date string passes through unchanged |
| `test_days_boundary_zero` | EOL today → `EXPIRING_SOON`, days=0 |

---

### `tests/test_collector.py` — 7 tests

| Test | Scenario |
|---|---|
| `test_fetch_eol_success` | endoflife.date API mock → returns data |
| `test_fetch_eol_uses_cache` | Second call with same slug/version → only 1 HTTP request |
| `test_fetch_eol_404_returns_none` | Non-200 response → returns None |
| `test_collect_lambda` | Mocked Lambda list → 2 function records, status EXPIRING_SOON |
| `test_collect_eks` | Mocked EKS cluster → 1 record, version 1.33 |
| `test_collect_lambda_unknown_runtime` | `provided.al2` runtime → skipped |
| `test_storage_save_adds_ttl_and_scanned_at` | FileBackend round-trip → scanned_at present |

---

### `tests/test_general_eol.py` — 32 tests

**`_classify()` tests (6):**
EOL (past date), expiring soon, supported, extended support, no date (supported), invalid date (unknown)

**`_normalize()` tests (5):**
EKS basic record, `eolFrom: false` → null eolDate, known upgrade lookup, missing cycle field → None, slugified ID has no dots

**`compute_summary()` tests (2):**
Correct counts across statuses, empty list → all zeros

**`filter_records()` tests (10):**
By service, by status (include_legacy=True), by search, combined service+status, no match, empty returns non-legacy by default, include_legacy=True returns all, `_is_legacy` old EOL, `_is_legacy` recent EOL, expiring_soon never legacy

**`get_or_refresh()` tests (3):**
Fresh cache hit (no fetch), expired cache triggers fetch, no cache triggers fetch

**`fetch_all()` tests (2):**
Network mock → normalizes all products, network exception → returns empty list gracefully

**File backend cache round-trip (1):**
`save_general_eol_cache` → `get_general_eol_cache` → records match

**Legacy classification tests (3):**
`_is_legacy` with 4-year-old EOL date, 1-year-old, and EXPIRING_SOON status

---

## API contract

### `GET /eol/general`

```
Query: service=Lambda&status=EOL&search=python&includeLegacy=false

Response 200:
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
    "refreshed_at":   "2026-05-30T09:00:00.000000",
    "source":         "endoflife.date",
    "include_legacy": false
  }
}

Response 502 (endoflife.date unreachable):
{
  "ok": false,
  "error": {
    "code": "DATA_SOURCE_ERROR",
    "message": "Unable to refresh lifecycle data",
    "details": "Connection refused"
  }
}
```

### `GET /eol/general/summary`

```
Query: includeLegacy=false

Response 200:
{
  "ok": true,
  "data": {
    "EOL":              10,
    "EXPIRING_SOON":    14,
    "EXTENDED_SUPPORT": 0,
    "SUPPORTED":        89,
    "UNKNOWN":          2
  },
  "meta": {
    "total":          115,
    "refreshed_at":   "2026-05-30T09:00:00",
    "include_legacy": false
  }
}
```

### `POST /eol/general/refresh`

```
Response 200:
{
  "ok": true,
  "meta": { "total": 197, "refreshed_at": "2026-05-30T09:00:00" }
}
```

### `GET /eol/inventory`

```
Query: service=Lambda&status=EOL&region=us-east-1

Response 200:
{
  "items": [
    {
      "resource_id":   "arn:aws:lambda:us-east-1:123456789012:function:my-fn",
      "resource_name": "my-fn",
      "service_type":  "Lambda",
      "region":        "us-east-1",
      "account_id":    "123456789012",
      "version":       "python3.8",
      "eol_status":    "EOL",
      "eol_date":      "2024-10-14",
      "days_to_eol":   -228,
      "scanned_at":    "2026-05-30T09:00:00"
    }
  ],
  "count": 1
}
```

---

## File storage layout

When `STORAGE_BACKEND=file`, data is stored as JSON in `EOL_DATA_DIR` (default `/tmp/eol-data/`):

```
/tmp/eol-data/
├── inventory.json          # Scanned resource records
├── config.json             # Settings
└── general_eol_cache.json  # Lifecycle cache from endoflife.date
```

---

## Dependency reference

| Package | Version | Purpose |
|---|---|---|
| `boto3` | ≥1.34 | AWS SDK — DynamoDB, S3, Lambda, SNS, STS, EC2 |
| `botocore` | ≥1.34 | Core AWS SDK transport |
| `requests` | ≥2.31 | HTTP client for endoflife.date API calls |
| `flask` | dev only | HTTP wrapper for `run-local-backend.py` |
| `flask-cors` | dev only | CORS headers for local frontend |
| `pytest` | dev only | Test runner |
| `pytest-cov` | dev only | Coverage reporting |
