# AWS EOL Monitor — Backend

Python 3.10+ · boto3 · requests

REST API + data collection Lambdas for tracking AWS service end-of-life status. Supports three storage backends (file, DynamoDB, S3) so it can run locally with zero AWS credentials.

---

## Quick start

### Install

```bash
pip3 install -r requirements.txt flask flask-cors --break-system-packages
```

### Run locally (no AWS needed)

```bash
# From project root
STORAGE_BACKEND=file python3 scripts/run-local-backend.py
# → http://localhost:3001
```

Or via Makefile:

```bash
make backend
```

> **First `GET /eol/general` request** fetches 13 AWS service lifecycle catalogues from endoflife.date (~15s). All subsequent requests are served from cache (24h TTL stored at `/tmp/eol-data/`).

### Force refresh lifecycle cache

```bash
curl -X POST http://localhost:3001/eol/general/refresh
```

### Run against real AWS

```bash
export AWS_PROFILE=your-profile
export STORAGE_BACKEND=dynamodb
export DYNAMODB_TABLE=aws-eol-inventory
export WARN_DAYS=180

python3 eol_collector.py
```

### Run tests

```bash
python3 -m pytest tests/ -v
# 89 tests, all pass

python3 -m pytest tests/ -v --cov=. --cov-report=term-missing
```

---

## Environment variables

Copy `.env.example` as a reference.

| Variable | Default | Description |
|---|---|---|
| `STORAGE_BACKEND` | `file` | `file` (local), `dynamodb` (production), `s3` |
| `EOL_DATA_DIR` | `/tmp/eol-data` | Data directory when `STORAGE_BACKEND=file` |
| `DYNAMODB_TABLE` | `aws-eol-inventory` | DynamoDB inventory table |
| `CONFIG_TABLE` | `aws-eol-config` | DynamoDB config + general EOL cache table |
| `DEDUP_TABLE` | `aws-eol-alert-dedup` | Alert deduplication table |
| `EOL_BUCKET` | — | S3 bucket when `STORAGE_BACKEND=s3` |
| `GENERAL_EOL_CACHE_TTL_HOURS` | `24` | Hours before general EOL cache expires |
| `EOL_API_BASE` | `https://endoflife.date/api` | endoflife.date stable JSON API base |
| `WARN_DAYS` | `180` | Days before EOL to flag as `EXPIRING_SOON` |
| `SNS_TOPIC_ARN` | — | SNS topic for alerts (empty = disabled) |
| `DEDUP_HOURS` | `24` | Min hours between duplicate alerts for same resource |
| `COLLECTOR_FUNCTION` | `aws-eol-collector` | Collector Lambda name (for manual scan trigger) |
| `AWS_DEFAULT_REGION` | `us-east-1` | AWS region for local runs |
| `PORT` | `3001` | Port for `scripts/run-local-backend.py` |
| `ENABLE_ORG_SCAN` | `false` | Enable Organization Scan feature (`true` to activate) |
| `ORG_MEMBER_ROLE_NAME` | `EOLMonitorReadOnly` | IAM role name assumed in each member account during org scan |
| `ORG_SCAN_ASYNC_MODE` | `thread` | Org scan dispatch mode: `sync` (inline, tests only), `thread` (daemon worker, EC2/ECS/PM2), `lambda_event` (async Lambda invoke, API Gateway deployments) |
| `ORG_SCAN_WORKER_FUNCTION` | — | Lambda function name or ARN for `ORG_SCAN_ASYNC_MODE=lambda_event`. Falls back to `AWS_LAMBDA_FUNCTION_NAME` if unset |
| `ORG_SCAN_ACCOUNT_TIMEOUT_SECONDS` | `300` | Per-member-account timeout in seconds during org scan worker execution |
| `NOTIFICATIONS_EMAIL_PROVIDER` | `ses` | Email delivery backend: `ses` (AWS SES) or `smtp` (generic SMTP) |
| `NOTIFICATIONS_FROM_EMAIL` | — | Sender address for SES email notifications |
| `SMTP_HOST` | — | SMTP server hostname when `NOTIFICATIONS_EMAIL_PROVIDER=smtp` |
| `SMTP_PORT` | `587` | SMTP server port |
| `SMTP_USERNAME` | — | SMTP login username |
| `SMTP_PASSWORD` | — | SMTP login password. Never logged. |
| `SMTP_FROM_EMAIL` | — | From address for SMTP delivery. Falls back to `NOTIFICATIONS_FROM_EMAIL` if unset |
| `APP_URL` | — | Public frontend URL included as a link in email and Slack notifications (e.g. `https://eol.example.com`) |

> **Lambda/API Gateway deployment note:** Use `ORG_SCAN_ASYNC_MODE=lambda_event` for serverless deployments. Do not rely on `thread` mode in Lambda — background threads can be killed if the runtime container is recycled before the scan completes. Stale `RUNNING` scans older than 30 minutes are automatically marked `FAILED` on the next scan request.

---

## Modules

### `api_handler.py` — REST API router

Lambda entry point for all HTTP requests from the frontend. Routes by HTTP method + path and returns API Gateway proxy responses with CORS headers.

**Routes:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/eol/general` | Public lifecycle library. Params: `service`, `status`, `search`, `includeLegacy` |
| `GET` | `/eol/general/summary` | Status counts. Param: `includeLegacy` |
| `POST` | `/eol/general/refresh` | Force-refresh lifecycle cache from endoflife.date |
| `GET` | `/eol/inventory` | Account scanned resources. Params: `service`, `status`, `region` |
| `GET` | `/eol/summary` | Inventory totals grouped by service + status |
| `GET` | `/eol/resource/:id` | Single resource detail |
| `GET` | `/eol/alerts` | EOL + expiring resources sorted by recency. Param: `limit` |
| `GET` | `/eol/config` | Current settings |
| `PUT` | `/eol/config` | Save settings |
| `POST` | `/eol/scan` | Invoke collector Lambda asynchronously |

**Response envelope:**

```json
// Success
{ "ok": true, "data": { ... }, "meta": { "total": 14, "source": "endoflife.date" } }

// Error
{ "ok": false, "error": { "code": "DATA_SOURCE_ERROR", "message": "...", "details": "..." } }
```

---

### `general_eol.py` — Public lifecycle library

Fetches AWS service lifecycle data from [endoflife.date](https://endoflife.date), normalizes it to the frontend shape, and caches results. No AWS credentials required.

**Configured products (13):**

| endoflife.date slug | Display name |
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

**Key functions:**

| Function | Description |
|---|---|
| `fetch_all()` | Fetches all 13 products using stable JSON API: `https://endoflife.date/api/{slug}.json` |
| `get_or_refresh(storage)` | Returns cached data if fresh; otherwise fetches + caches. Thread-safe via `threading.Lock()` — prevents concurrent stampede when React Query fires parallel requests |
| `filter_records(records, service, status, search, include_legacy)` | `include_legacy=False` hides EOL records older than 3 years |
| `compute_summary(records)` | Returns `{ EOL: n, EXPIRING_SOON: n, EXTENDED_SUPPORT: n, SUPPORTED: n, UNKNOWN: n }` |
| `_normalize(slug, raw)` | Converts raw endoflife.date cycle → `{ id, service, version, eolDate, daysToEol, status, family, recommendedUpgrade, source, product_slug }` |
| `_classify(eol_from, is_eoes)` | Returns `(status, days_to_eol)` |
| `_is_legacy(record)` | `True` if `status=EOL` and `eolDate` is older than 3 years |

**Cache behavior:**
- First request: ~15s (13 sequential API calls)
- Subsequent: instant (served from file/DynamoDB cache)
- **Empty results are NOT cached** — retried on next request
- `POST /eol/general/refresh` bypasses TTL and force-fetches

---

### `eol_collector.py` — Account / org scanner

Scans AWS services using read-only API calls, cross-references discovered versions against endoflife.date, and writes results to storage.

**Supported services (21 collectors):**

| AWS Service | What is scanned | Lifecycle source |
|---|---|---|
| Lambda | Function runtime (python3.x, nodejs22.x, java21, ruby3.x, etc.) | endoflife.date |
| EKS | Cluster Kubernetes version | endoflife.date |
| RDS MySQL / PostgreSQL / MariaDB | Instance engine versions | endoflife.date |
| Aurora MySQL / PostgreSQL | Cluster engine versions | endoflife.date |
| ElastiCache Redis / Valkey | Cache cluster engine version | endoflife.date |
| EC2 | AMI OS + instance generation advisory (AL2, AL2023, Ubuntu, Windows, etc.) | inline + SSM |
| MSK | Kafka broker version | endoflife.date |
| OpenSearch | Domain engine version (OpenSearch + legacy Elasticsearch mode) | endoflife.date |
| DocumentDB | Cluster engine version | endoflife.date |
| Neptune | Cluster engine version | endoflife.date |
| Glue | Job Glue version + Python version | endoflife.date |
| Amazon MQ | ActiveMQ / RabbitMQ engine version (major.minor) | endoflife.date |
| AWS DMS | Replication instance engine version (major.minor) | endoflife.date |
| Amazon MWAA | Apache Airflow environment version (major.minor) | endoflife.date |
| ECS Fargate | Service platform version (1.0–1.4; LATEST → not tracked) | inline table |
| SageMaker Notebook | Notebook instance platform identifier (AL1/AL2/AL2023) | inline table |
| Elastic Beanstalk | Platform branch lifecycle state via AWS API; OS fallback | AWS API + inline |
| AWS Batch | Compute environment AMI type (ECS/EKS AL2 vs AL2023) | inline table |
| CloudFront Functions | Function runtime | not tracked |
| ECR | Container image inventory | inventory only |
| CodeBuild | Build project image | not tracked |
| EMR | Cluster release label | not tracked |

**Key functions:**

| Function | Description |
|---|---|
| `fetch_eol(product, version)` | Calls `endoflife.date/api/v1/products/{product}/{version}/` with in-process memory cache |
| `classify_status(eol_data)` | Returns `(status, eol_date, days_to_eol)` |
| `get_enabled_regions()` | Lists all opt-in + default AWS regions via EC2 |
| `run_all_collectors(session, account_id)` | Runs all service collectors across all regions |
| `send_alert(resource)` | Publishes EOL/EXPIRING_SOON alert to SNS if `SNS_TOPIC_ARN` is set |
| `lambda_handler(event, context)` | Entry point. Reads `scan_org` flag from config. Assumes cross-account roles for org scans via STS. |

**Resource record shape:**

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
- `STS AssumeRole` — no credentials stored or passed through
- `ExternalId` required for all cross-account trust
- Read-only IAM policy (`iam/eol-collector-policy.json`)
- No write, delete, or secrets access

---

### `storage.py` — Storage abstraction

Unified interface over three storage backends. Swap backends by changing `STORAGE_BACKEND` env var — no code changes needed.

```python
from storage import get_storage
storage = get_storage()   # returns FileBackend / DynamoDBBackend / S3Backend
```

**Backends:**

| Backend | Env value | Best for |
|---|---|---|
| `FileBackend` | `file` | Local development — zero AWS required, data in `/tmp/eol-data/` |
| `DynamoDBBackend` | `dynamodb` | Production Lambda |
| `S3Backend` | `s3` | Alternative — single JSON blob per data type in S3 |

**Interface (identical across all backends):**

```python
save_resources(resources: list) -> int
get_resources(filters: dict = None) -> list       # filters: service, status, region
get_resource_by_id(resource_id: str) -> Optional[dict]
get_config() -> dict                              # merged with CONFIG_DEFAULTS
save_config(config: dict) -> None
get_general_eol_cache() -> Optional[dict]         # { records, refreshed_at, expires_at }
save_general_eol_cache(records, refreshed_at, expires_at) -> None
```

**DynamoDB tables:**

| Table | PK | SK | Purpose |
|---|---|---|---|
| `aws-eol-inventory` | `resource_id` | `service_type` | Scanned resources with 90-day TTL |
| `aws-eol-config` | `config_key` | — | Settings + general EOL cache blob |
| `aws-eol-alert-dedup` | `alert_key` | — | Alert deduplication keys with TTL |

**File storage layout (`/tmp/eol-data/`):**

```
/tmp/eol-data/
├── inventory.json              Scanned resource records
├── config.json                 Settings
└── general_eol_cache.json      Lifecycle cache from endoflife.date
```

---

### `alert_notifier.py` — SNS alert sender

Sends deduplicated SNS notifications for EOL and expiring-soon resources.

**Deduplication:** Creates key `{resource_id}#{eol_status}` in the dedup table with TTL = `now + DEDUP_HOURS`. If the key exists, the alert is skipped. Default: max one alert per resource per 24h.

**Triggered by:**
- DynamoDB Streams on `aws-eol-inventory` (automatic when new records written)
- Direct call from `eol_collector.py` via `send_alert(resource)`

**SNS message format:**
```
Subject: [AWS EOL] EOL: arn:...function/legacy-fn (Lambda)
Body:
  Resource: arn:aws:lambda:...
  Service:  Lambda
  Region:   us-east-1
  Version:  python3.8
  Status:   EOL
  EOL Date: 2024-10-14
  Days:     -228
```

---

## API contract

### `GET /eol/general`

```
Query params:
  service=Lambda            substring match, case-insensitive
  status=EOL                exact: EOL | EXPIRING_SOON | EXTENDED_SUPPORT | SUPPORTED
  search=python             searches service + version + family
  includeLegacy=false       true shows EOL records older than 3 years (default false)

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
    "refreshed_at":   "2026-05-30T09:00:00",
    "source":         "endoflife.date",
    "include_legacy": false
  }
}

Response 502 (endoflife.date unreachable):
{
  "ok": false,
  "error": { "code": "DATA_SOURCE_ERROR", "message": "Unable to refresh lifecycle data" }
}
```

### `GET /eol/general/summary?includeLegacy=false`

```json
{
  "ok": true,
  "data": { "EOL": 10, "EXPIRING_SOON": 14, "EXTENDED_SUPPORT": 0, "SUPPORTED": 89, "UNKNOWN": 2 },
  "meta": { "total": 115, "refreshed_at": "...", "include_legacy": false }
}
```

### `POST /eol/general/refresh`

```json
{ "ok": true, "meta": { "total": 197, "refreshed_at": "..." } }
```

### `GET /eol/inventory`

```json
{
  "items": [
    {
      "resource_id": "arn:aws:lambda:us-east-1:123456789012:function:my-fn",
      "resource_name": "my-fn",
      "service_type": "Lambda",
      "region": "us-east-1",
      "version": "python3.8",
      "eol_status": "EOL",
      "eol_date": "2024-10-14",
      "days_to_eol": -228,
      "scanned_at": "2026-05-30T09:00:00"
    }
  ],
  "count": 1
}
```

---

## Tests

```bash
python3 -m pytest tests/ -v        # 47 tests
python3 -m pytest tests/ -q        # quiet output
python3 -m pytest tests/test_general_eol.py -v   # single file
```

### `tests/test_classify.py` — 8 tests
`classify_status()` edge cases: EOL, expiring, supported, extended support, unknown, no date, boundary zero, date preserved.

### `tests/test_collector.py` — 82 tests
Full collector integration suite covering all 21 service collectors with mocked AWS clients. Includes lifecycle scoring, ACCESS_DENIED warning paths, ARN fallbacks, version extraction, and multi-resource scenarios. Collector coverage: Lambda, EKS, RDS, ElastiCache (Redis+Valkey), OpenSearch (legacy Elasticsearch mode), EC2, MSK, Glue, Amazon MQ (ActiveMQ+RabbitMQ), AWS DMS, Amazon MWAA, ECS Fargate, SageMaker Notebook, Elastic Beanstalk (API + OS fallback), AWS Batch AMI types.

### `tests/test_general_eol.py` — 32 tests
`_classify()` (6), `_normalize()` (5), `compute_summary()` (2), `filter_records()` (10 — including legacy on/off), `get_or_refresh()` cache hit/miss/expiry (3), `fetch_all()` network mock + graceful failure (2), file backend cache round-trip (1), `_is_legacy()` edge cases (3).

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| `boto3` | ≥1.34 | DynamoDB, S3, Lambda, SNS, STS, EC2 |
| `botocore` | ≥1.34 | Core AWS SDK transport |
| `requests` | ≥2.31 | HTTP calls to endoflife.date |
| `flask` | dev only | HTTP wrapper for local dev server |
| `flask-cors` | dev only | CORS headers for local frontend |
| `pytest` | dev only | Test runner |
| `pytest-cov` | dev only | Coverage reporting |
