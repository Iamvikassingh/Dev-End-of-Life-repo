#!/usr/bin/env python3
"""
Local mock API server for AWS EOL Monitor frontend development.
Serves realistic mock data — no AWS credentials or DynamoDB needed.

Usage:
    pip install flask flask-cors
    python scripts/local-api.py

Then set REACT_APP_API_URL=http://localhost:3001 in frontend/.env.local
"""
import hashlib
import json
import os
import secrets
from datetime import date, datetime, timezone, timedelta

try:
    from flask import Flask, jsonify, request
    from flask_cors import CORS
except ImportError:
    print("Missing dependencies. Run: pip install flask flask-cors --break-system-packages")
    raise

app = Flask(__name__)
CORS(app)

# ── Admin token resolution ────────────────────────────────────────────────────
# Same priority as api_handler.py so both servers share the same token file.

def _resolve_admin_token():
    env_token = os.environ.get("ADMIN_PORTAL_TOKEN", "")
    if env_token:
        return env_token, hashlib.sha256(env_token.encode()).hexdigest()

    data_dir   = os.environ.get("EOL_DATA_DIR", "/tmp/eol-data")
    token_file = os.path.join(data_dir, "secrets", "initial-admin-token")

    if os.path.isfile(token_file):
        try:
            token = open(token_file).read().strip()
            if token:
                return token, hashlib.sha256(token.encode()).hexdigest()
        except Exception:
            pass

    # Generate new token
    token = f"eolm_admin_{secrets.token_hex(24)}"
    try:
        os.makedirs(os.path.join(data_dir, "secrets"), exist_ok=True)
        with open(token_file, "w") as fh:
            fh.write(token)
        try:
            os.chmod(token_file, 0o600)
        except Exception:
            pass
    except Exception as exc:
        print(f"  Warning: could not write admin token file: {exc}")

    return token, hashlib.sha256(token.encode()).hexdigest()


_ADMIN_TOKEN, _ADMIN_TOKEN_HASH = _resolve_admin_token()

# ── In-memory workspace store (mock only — restarts clear data) ───────────────
_WORKSPACES: dict    = {}   # ws_id → { id, name, token_hash, created_at }
_WS_ACCOUNTS: dict   = {}   # ws_id → [account, ...]
_UPGRADE_GUIDES: list = []  # global upgrade guide library

def _ws_token_valid(ws_id: str) -> bool:
    token = request.headers.get("X-Workspace-Token", "")
    ws    = _WORKSPACES.get(ws_id)
    if not ws or not token:
        return False
    return hashlib.sha256(token.encode()).hexdigest() == ws["token_hash"]

def _admin_token_valid() -> bool:
    incoming = request.headers.get("X-Admin-Token", "")
    return bool(incoming) and bool(_ADMIN_TOKEN_HASH) and \
           hashlib.sha256(incoming.encode()).hexdigest() == _ADMIN_TOKEN_HASH

# ── Mock Data ─────────────────────────────────────────────────────────────────

def days_from_today(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()

MOCK_ITEMS = [
    # EOL resources
    {"resource_id": "arn:aws:lambda:us-east-1:123456789012:function:legacy-processor",  "resource_name": "legacy-processor",  "service_type": "Lambda",      "region": "us-east-1", "account_id": "123456789012", "version": "python3.8",   "eol_status": "EOL",           "eol_date": days_from_today(-120), "days_to_eol": -120, "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:lambda:us-east-1:123456789012:function:old-api-handler",    "resource_name": "old-api-handler",    "service_type": "Lambda",      "region": "us-east-1", "account_id": "123456789012", "version": "nodejs14.x",  "eol_status": "EOL",           "eol_date": days_from_today(-200), "days_to_eol": -200, "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:eks:us-east-1:123456789012:cluster/prod-cluster-v126",      "resource_name": "prod-cluster-v126",  "service_type": "EKS",         "region": "us-east-1", "account_id": "123456789012", "version": "1.26",        "eol_status": "EOL",           "eol_date": days_from_today(-60),  "days_to_eol": -60,  "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:rds:eu-west-1:123456789012:db:postgres-prod-old",           "resource_name": "postgres-prod-old",  "service_type": "RDS_postgres", "region": "eu-west-1", "account_id": "123456789012", "version": "11.19",       "eol_status": "EOL",           "eol_date": days_from_today(-30),  "days_to_eol": -30,  "scanned_at": "2026-05-29T08:00:00"},

    # Expiring Soon
    {"resource_id": "arn:aws:lambda:us-west-2:123456789012:function:data-pipeline",      "resource_name": "data-pipeline",      "service_type": "Lambda",      "region": "us-west-2", "account_id": "123456789012", "version": "python3.9",   "eol_status": "EXPIRING_SOON", "eol_date": days_from_today(45),   "days_to_eol": 45,   "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:eks:us-west-2:123456789012:cluster/staging-cluster",        "resource_name": "staging-cluster",    "service_type": "EKS",         "region": "us-west-2", "account_id": "123456789012", "version": "1.28",        "eol_status": "EXPIRING_SOON", "eol_date": days_from_today(90),   "days_to_eol": 90,   "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:rds:us-east-1:123456789012:db:mysql-app-db",               "resource_name": "mysql-app-db",       "service_type": "RDS_mysql",   "region": "us-east-1", "account_id": "123456789012", "version": "8.0.35",      "eol_status": "EXPIRING_SOON", "eol_date": days_from_today(120),  "days_to_eol": 120,  "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:elasticache:us-east-1:123456789012:cluster:redis-cache-01", "resource_name": "redis-cache-01",     "service_type": "ElastiCache", "region": "us-east-1", "account_id": "123456789012", "version": "6.2.14",      "eol_status": "EXPIRING_SOON", "eol_date": days_from_today(60),   "days_to_eol": 60,   "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "i-0abc123def456789a",                                                "resource_name": "i-0abc123def456789a","service_type": "EC2",         "region": "ap-southeast-1", "account_id": "123456789012", "version": "Amazon Linux 2", "eol_status": "EXPIRING_SOON", "eol_date": days_from_today(150), "days_to_eol": 150, "scanned_at": "2026-05-29T08:00:00"},

    # Extended Support
    {"resource_id": "arn:aws:eks:eu-central-1:123456789012:cluster/prod-eu-cluster",     "resource_name": "prod-eu-cluster",    "service_type": "EKS",         "region": "eu-central-1", "account_id": "123456789012", "version": "1.27", "eol_status": "EXTENDED_SUPPORT", "eol_date": days_from_today(200),  "days_to_eol": 200, "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:rds:us-east-1:123456789012:db:aurora-pg-prod",              "resource_name": "aurora-pg-prod",     "service_type": "Aurora_PostgreSQL", "region": "us-east-1", "account_id": "123456789012", "version": "13.12", "eol_status": "EXTENDED_SUPPORT", "eol_date": days_from_today(250), "days_to_eol": 250, "scanned_at": "2026-05-29T08:00:00"},

    # Supported
    {"resource_id": "arn:aws:lambda:us-east-1:123456789012:function:auth-service",       "resource_name": "auth-service",       "service_type": "Lambda",      "region": "us-east-1", "account_id": "123456789012", "version": "python3.12",  "eol_status": "SUPPORTED",     "eol_date": days_from_today(700),  "days_to_eol": 700,  "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:lambda:us-east-1:123456789012:function:image-resizer",      "resource_name": "image-resizer",      "service_type": "Lambda",      "region": "us-east-1", "account_id": "123456789012", "version": "nodejs20.x",  "eol_status": "SUPPORTED",     "eol_date": days_from_today(500),  "days_to_eol": 500,  "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:eks:us-east-1:123456789012:cluster/main-cluster",           "resource_name": "main-cluster",       "service_type": "EKS",         "region": "us-east-1", "account_id": "123456789012", "version": "1.32",        "eol_status": "SUPPORTED",     "eol_date": days_from_today(400),  "days_to_eol": 400,  "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:rds:us-east-1:123456789012:db:postgres-main",              "resource_name": "postgres-main",      "service_type": "RDS_postgres", "region": "us-east-1", "account_id": "123456789012", "version": "16.3",        "eol_status": "SUPPORTED",     "eol_date": days_from_today(900),  "days_to_eol": 900,  "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:kafka:us-east-1:123456789012:cluster/events-cluster/abc123","resource_name": "events-cluster",     "service_type": "MSK",         "region": "us-east-1", "account_id": "123456789012", "version": "3.7.0",       "eol_status": "SUPPORTED",     "eol_date": days_from_today(600),  "days_to_eol": 600,  "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:es:us-east-1:123456789012:domain/search-prod",             "resource_name": "search-prod",        "service_type": "OpenSearch",  "region": "us-east-1", "account_id": "123456789012", "version": "2.13",        "eol_status": "SUPPORTED",     "eol_date": days_from_today(550),  "days_to_eol": 550,  "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:rds:us-east-1:123456789012:cluster:docdb-prod",            "resource_name": "docdb-prod",         "service_type": "DocumentDB",  "region": "us-east-1", "account_id": "123456789012", "version": "5.0.0",       "eol_status": "SUPPORTED",     "eol_date": days_from_today(480),  "days_to_eol": 480,  "scanned_at": "2026-05-29T08:00:00"},
    {"resource_id": "arn:aws:glue:us-east-1:123456789012:job/etl-daily",               "resource_name": "etl-daily",           "service_type": "Glue",        "region": "us-east-1", "account_id": "123456789012", "version": "4.0",         "eol_status": "SUPPORTED",     "eol_date": days_from_today(800),  "days_to_eol": 800,  "scanned_at": "2026-05-29T08:00:00"},
]

MOCK_GENERAL_EOL = [
    {"id": "lambda-py38",    "service": "Lambda",            "version": "python3.8",   "status": "EOL",              "eolDate": days_from_today(-228),  "daysToEol": -228,  "recommendedUpgrade": "python3.12", "family": "Python",      "source": "endoflife.date"},
    {"id": "lambda-py39",    "service": "Lambda",            "version": "python3.9",   "status": "EXPIRING_SOON",    "eolDate": days_from_today(45),    "daysToEol": 45,    "recommendedUpgrade": "python3.12", "family": "Python",      "source": "endoflife.date"},
    {"id": "lambda-py311",   "service": "Lambda",            "version": "python3.11",  "status": "SUPPORTED",        "eolDate": days_from_today(400),   "daysToEol": 400,   "recommendedUpgrade": None,         "family": "Python",      "source": "endoflife.date"},
    {"id": "lambda-py312",   "service": "Lambda",            "version": "python3.12",  "status": "SUPPORTED",        "eolDate": days_from_today(700),   "daysToEol": 700,   "recommendedUpgrade": None,         "family": "Python",      "source": "endoflife.date"},
    {"id": "lambda-node14",  "service": "Lambda",            "version": "nodejs14.x",  "status": "EOL",              "eolDate": days_from_today(-201),  "daysToEol": -201,  "recommendedUpgrade": "nodejs22.x", "family": "Node.js",     "source": "endoflife.date"},
    {"id": "lambda-node18",  "service": "Lambda",            "version": "nodejs18.x",  "status": "EXPIRING_SOON",    "eolDate": days_from_today(30),    "daysToEol": 30,    "recommendedUpgrade": "nodejs22.x", "family": "Node.js",     "source": "endoflife.date"},
    {"id": "lambda-node20",  "service": "Lambda",            "version": "nodejs20.x",  "status": "SUPPORTED",        "eolDate": days_from_today(500),   "daysToEol": 500,   "recommendedUpgrade": None,         "family": "Node.js",     "source": "endoflife.date"},
    {"id": "lambda-node22",  "service": "Lambda",            "version": "nodejs22.x",  "status": "SUPPORTED",        "eolDate": days_from_today(900),   "daysToEol": 900,   "recommendedUpgrade": None,         "family": "Node.js",     "source": "endoflife.date"},
    {"id": "lambda-java11",  "service": "Lambda",            "version": "java11",       "status": "EXPIRING_SOON",    "eolDate": days_from_today(55),    "daysToEol": 55,    "recommendedUpgrade": "java21",     "family": "Java",        "source": "endoflife.date"},
    {"id": "lambda-java21",  "service": "Lambda",            "version": "java21",       "status": "SUPPORTED",        "eolDate": days_from_today(900),   "daysToEol": 900,   "recommendedUpgrade": None,         "family": "Java",        "source": "endoflife.date"},
    {"id": "eks-125",        "service": "EKS",               "version": "1.25",         "status": "EOL",              "eolDate": days_from_today(-300),  "daysToEol": -300,  "recommendedUpgrade": "1.33",       "family": "EKS",         "source": "endoflife.date"},
    {"id": "eks-128",        "service": "EKS",               "version": "1.28",         "status": "EXPIRING_SOON",    "eolDate": days_from_today(75),    "daysToEol": 75,    "recommendedUpgrade": "1.33",       "family": "EKS",         "source": "endoflife.date"},
    {"id": "eks-130",        "service": "EKS",               "version": "1.30",         "status": "SUPPORTED",        "eolDate": days_from_today(320),   "daysToEol": 320,   "recommendedUpgrade": None,         "family": "EKS",         "source": "endoflife.date"},
    {"id": "eks-133",        "service": "EKS",               "version": "1.33",         "status": "SUPPORTED",        "eolDate": days_from_today(600),   "daysToEol": 600,   "recommendedUpgrade": None,         "family": "EKS",         "source": "endoflife.date"},
    {"id": "rds-pg11",       "service": "RDS PostgreSQL",    "version": "11",           "status": "EOL",              "eolDate": days_from_today(-30),   "daysToEol": -30,   "recommendedUpgrade": "16",         "family": "PostgreSQL",  "source": "endoflife.date"},
    {"id": "rds-pg13",       "service": "RDS PostgreSQL",    "version": "13",           "status": "SUPPORTED",        "eolDate": days_from_today(280),   "daysToEol": 280,   "recommendedUpgrade": None,         "family": "PostgreSQL",  "source": "endoflife.date"},
    {"id": "rds-pg16",       "service": "RDS PostgreSQL",    "version": "16",           "status": "SUPPORTED",        "eolDate": days_from_today(900),   "daysToEol": 900,   "recommendedUpgrade": None,         "family": "PostgreSQL",  "source": "endoflife.date"},
    {"id": "rds-my57",       "service": "RDS MySQL",         "version": "5.7",          "status": "EOL",              "eolDate": days_from_today(-50),   "daysToEol": -50,   "recommendedUpgrade": "8.4",        "family": "MySQL",       "source": "endoflife.date"},
    {"id": "rds-my80",       "service": "RDS MySQL",         "version": "8.0",          "status": "EXTENDED_SUPPORT", "eolDate": days_from_today(120),   "daysToEol": 120,   "recommendedUpgrade": "8.4",        "family": "MySQL",       "source": "endoflife.date"},
    {"id": "rds-my84",       "service": "RDS MySQL",         "version": "8.4",          "status": "SUPPORTED",        "eolDate": days_from_today(1000),  "daysToEol": 1000,  "recommendedUpgrade": None,         "family": "MySQL",       "source": "endoflife.date"},
    {"id": "ec-redis5",      "service": "ElastiCache Redis", "version": "5.0",          "status": "EOL",              "eolDate": days_from_today(-15),   "daysToEol": -15,   "recommendedUpgrade": "7.x",        "family": "Redis",       "source": "endoflife.date"},
    {"id": "ec-redis62",     "service": "ElastiCache Redis", "version": "6.2",          "status": "EXPIRING_SOON",    "eolDate": days_from_today(60),    "daysToEol": 60,    "recommendedUpgrade": "7.x",        "family": "Redis",       "source": "endoflife.date"},
    {"id": "ec-redis71",     "service": "ElastiCache Redis", "version": "7.1",          "status": "SUPPORTED",        "eolDate": days_from_today(800),   "daysToEol": 800,   "recommendedUpgrade": None,         "family": "Redis",       "source": "endoflife.date"},
    {"id": "al-2",           "service": "Amazon Linux",      "version": "2",            "status": "EXPIRING_SOON",    "eolDate": days_from_today(150),   "daysToEol": 150,   "recommendedUpgrade": "2023",       "family": "Amazon Linux","source": "endoflife.date"},
    {"id": "al-2023",        "service": "Amazon Linux",      "version": "2023",         "status": "SUPPORTED",        "eolDate": days_from_today(2500),  "daysToEol": 2500,  "recommendedUpgrade": None,         "family": "Amazon Linux","source": "endoflife.date"},
    {"id": "msk-34",         "service": "MSK Kafka",         "version": "3.4",          "status": "EXPIRING_SOON",    "eolDate": days_from_today(40),    "daysToEol": 40,    "recommendedUpgrade": "3.7",        "family": "Kafka",       "source": "endoflife.date"},
    {"id": "msk-37",         "service": "MSK Kafka",         "version": "3.7",          "status": "SUPPORTED",        "eolDate": days_from_today(600),   "daysToEol": 600,   "recommendedUpgrade": None,         "family": "Kafka",       "source": "endoflife.date"},
    {"id": "os-13",          "service": "OpenSearch",        "version": "1.3",          "status": "EXPIRING_SOON",    "eolDate": days_from_today(10),    "daysToEol": 10,    "recommendedUpgrade": "2.x",        "family": "OpenSearch",  "source": "endoflife.date"},
    {"id": "os-213",         "service": "OpenSearch",        "version": "2.13",         "status": "SUPPORTED",        "eolDate": days_from_today(550),   "daysToEol": 550,   "recommendedUpgrade": None,         "family": "OpenSearch",  "source": "endoflife.date"},
    {"id": "glue-20",        "service": "AWS Glue",          "version": "2.0",          "status": "EOL",              "eolDate": days_from_today(-100),  "daysToEol": -100,  "recommendedUpgrade": "4.0",        "family": "Glue",        "source": "endoflife.date"},
    {"id": "glue-40",        "service": "AWS Glue",          "version": "4.0",          "status": "SUPPORTED",        "eolDate": days_from_today(800),   "daysToEol": 800,   "recommendedUpgrade": None,         "family": "Glue",        "source": "endoflife.date"},
]

_GENERAL_EOL_REFRESHED_AT = datetime.now(timezone.utc).isoformat()


def _filter_general_eol(rows, service="", status="", search="", include_legacy=False):
    if service:
        rows = [r for r in rows if service.lower() in r["service"].lower()]
    if status:
        rows = [r for r in rows if r["status"] == status.upper()]
    if search:
        q = search.lower()
        rows = [r for r in rows if q in r["service"].lower() or q in r["version"].lower()]
    return rows


def _general_summary(rows):
    counts = {"EOL": 0, "EXPIRING_SOON": 0, "EXTENDED_SUPPORT": 0, "SUPPORTED": 0}
    for r in rows:
        sts = r.get("status", "")
        if sts in counts:
            counts[sts] += 1
    return counts


MOCK_CONFIG = {
    "config_key":        "global",
    "warn_days":         180,
    "alert_email":       "devops@example.com",
    "slack_webhook":     "",
    "scan_schedule":     "cron(0 8 * * ? *)",
    "scan_org":          False,
    "sns_topic_arn":     "arn:aws:sns:us-east-1:123456789012:eol-alerts",
    "enabled_services":  ["Lambda", "EKS", "RDS", "ElastiCache", "EC2", "MSK", "OpenSearch", "DocumentDB", "Neptune", "Glue"],
}


def compute_summary():
    by_service: dict = {}
    totals: dict = {"EOL": 0, "EXPIRING_SOON": 0, "EXTENDED_SUPPORT": 0, "SUPPORTED": 0, "UNKNOWN": 0}
    regions: set = set()
    last_scanned = ""
    for item in MOCK_ITEMS:
        svc = item["service_type"]
        sts = item["eol_status"]
        by_service.setdefault(svc, {"EOL": 0, "EXPIRING_SOON": 0, "EXTENDED_SUPPORT": 0, "SUPPORTED": 0, "UNKNOWN": 0})
        by_service[svc][sts] = by_service[svc].get(sts, 0) + 1
        totals[sts] = totals.get(sts, 0) + 1
        if item.get("region"):
            regions.add(item["region"])
        if item.get("scanned_at", "") > last_scanned:
            last_scanned = item["scanned_at"]
    return {
        "by_service":      by_service,
        "totals":          totals,
        "resources_count": len(MOCK_ITEMS),
        "regions_count":   len(regions),
        "last_scanned":    last_scanned or None,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.after_request
def cors_headers(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type,X-Workspace-Token,X-Admin-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET,PUT,POST,DELETE,OPTIONS"
    return response


@app.route("/eol/inventory", methods=["GET", "OPTIONS"])
def inventory():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    items = MOCK_ITEMS[:]
    service = request.args.get("service", "")
    status  = request.args.get("status", "")
    region  = request.args.get("region", "")
    if service: items = [i for i in items if service.lower() in i["service_type"].lower()]
    if status:  items = [i for i in items if i["eol_status"] == status.upper()]
    if region:  items = [i for i in items if region in i["region"]]
    return jsonify({"items": items, "count": len(items)})


@app.route("/eol/summary", methods=["GET", "OPTIONS"])
def summary():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    return jsonify(compute_summary())


@app.route("/eol/resource/<path:resource_id>", methods=["GET", "OPTIONS"])
def resource_detail(resource_id):
    if request.method == "OPTIONS":
        return jsonify({}), 200
    match = next((i for i in MOCK_ITEMS if i["resource_id"] == resource_id), None)
    if not match:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"item": match})


@app.route("/eol/alerts", methods=["GET", "OPTIONS"])
def alerts():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    alert_items = [i for i in MOCK_ITEMS if i["eol_status"] in ("EOL", "EXPIRING_SOON")]
    return jsonify({"items": alert_items, "count": len(alert_items)})


@app.route("/eol/config", methods=["GET", "PUT", "OPTIONS"])
def config():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    if request.method == "PUT":
        MOCK_CONFIG.update(request.json or {})
        return jsonify({"message": "Config saved"})
    return jsonify(MOCK_CONFIG)


@app.route("/eol/scan", methods=["POST", "OPTIONS"])
def scan():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    return jsonify({"message": "Mock scan triggered (no-op in local dev)"}), 202


@app.route("/eol/general", methods=["GET", "OPTIONS"])
def general_eol():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    rows = _filter_general_eol(
        MOCK_GENERAL_EOL,
        service=request.args.get("service", ""),
        status=request.args.get("status", ""),
        search=request.args.get("search", ""),
        include_legacy=request.args.get("includeLegacy", "false").lower() == "true",
    )
    return jsonify({
        "ok":   True,
        "data": rows,
        "meta": {
            "total":               len(rows),
            "refreshed_at":        _GENERAL_EOL_REFRESHED_AT,
            "source":              "mock",
            "include_legacy":      False,
            "stale":               False,
            "refresh_recommended": False,
        },
    })


@app.route("/eol/general/summary", methods=["GET", "OPTIONS"])
def general_eol_summary():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    include_legacy = request.args.get("includeLegacy", "false").lower() == "true"
    rows   = MOCK_GENERAL_EOL
    counts = _general_summary(rows)
    return jsonify({
        "ok":   True,
        "data": counts,
        "meta": {
            "total":               sum(counts.values()),
            "refreshed_at":        _GENERAL_EOL_REFRESHED_AT,
            "include_legacy":      include_legacy,
            "stale":               False,
            "refresh_recommended": False,
        },
    })


@app.route("/eol/general/refresh", methods=["POST", "OPTIONS"])
def general_eol_refresh():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    return jsonify({
        "ok":   True,
        "meta": {"total": len(MOCK_GENERAL_EOL), "refreshed_at": _GENERAL_EOL_REFRESHED_AT},
    })


@app.route("/", methods=["GET"])
def root():
    return jsonify({"status": "ok"})


# ── Workspace routes (mock — in-memory) ───────────────────────────────────────

@app.route("/workspaces", methods=["POST", "OPTIONS"])
def create_workspace():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    name = (request.json or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    token = f"eolm_live_{secrets.token_hex(20)}"
    ws_id = f"ws_{secrets.token_hex(8)}"
    _WORKSPACES[ws_id] = {
        "id":         ws_id,
        "name":       name,
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return jsonify({
        "workspace_id": ws_id,
        "name":         name,
        "token":        token,
        "note":         "Save this token — it will not be shown again.",
    }), 201


@app.route("/workspaces/<ws_id>/validate", methods=["GET", "OPTIONS"])
def validate_workspace(ws_id):
    if request.method == "OPTIONS":
        return jsonify({}), 200
    if not _ws_token_valid(ws_id):
        return jsonify({"error": "Invalid workspace ID or token"}), 401
    ws = _WORKSPACES[ws_id]
    return jsonify({"valid": True, "workspace": {"id": ws["id"], "name": ws["name"]}})


@app.route("/workspaces/<ws_id>/accounts", methods=["GET", "POST", "OPTIONS"])
def workspace_accounts(ws_id):
    if request.method == "OPTIONS":
        return jsonify({}), 200
    if not _ws_token_valid(ws_id):
        return jsonify({"error": "Invalid workspace credentials"}), 401

    accounts = _WS_ACCOUNTS.setdefault(ws_id, [])

    if request.method == "GET":
        return jsonify({"accounts": accounts, "count": len(accounts)})

    body = dict(request.json or {})
    body["workspace_id"] = ws_id
    idx = next((i for i, a in enumerate(accounts) if a.get("id") == body.get("id")), None)
    if idx is not None:
        accounts[idx] = body
    else:
        accounts.append(body)
    return jsonify({"account": body})


@app.route("/workspaces/<ws_id>/accounts/<acct_id>", methods=["PUT", "DELETE", "OPTIONS"])
def workspace_account(ws_id, acct_id):
    if request.method == "OPTIONS":
        return jsonify({}), 200
    if not _ws_token_valid(ws_id):
        return jsonify({"error": "Invalid workspace credentials"}), 401

    accounts = _WS_ACCOUNTS.setdefault(ws_id, [])

    if request.method == "DELETE":
        _WS_ACCOUNTS[ws_id] = [a for a in accounts if a.get("id") != acct_id]
        return jsonify({"deleted": True, "id": acct_id})

    existing = next((a for a in accounts if a.get("id") == acct_id), None)
    if not existing:
        return jsonify({"error": "Account not found"}), 404
    merged = {**existing, **(request.json or {}), "id": acct_id, "workspace_id": ws_id}
    _WS_ACCOUNTS[ws_id] = [merged if a.get("id") == acct_id else a for a in accounts]
    return jsonify({"account": merged})


# ── Admin routes ──────────────────────────────────────────────────────────────

@app.route("/admin/validate", methods=["GET", "OPTIONS"])
def admin_validate():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    if not _admin_token_valid():
        err = "Admin portal not configured." if not _ADMIN_TOKEN_HASH else "Invalid admin token."
        return jsonify({"error": err}), 401
    return jsonify({"valid": True})


@app.route("/admin/workspaces", methods=["GET", "OPTIONS"])
def admin_workspaces_list():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    if not _admin_token_valid():
        return jsonify({"error": "Admin token required"}), 401
    result = [
        {
            "id":            ws["id"],
            "name":          ws["name"],
            "created_at":    ws.get("created_at", ""),
            "rotated_at":    ws.get("rotated_at"),
            "account_count": len(_WS_ACCOUNTS.get(ws["id"], [])),
        }
        for ws in _WORKSPACES.values()
    ]
    return jsonify({"workspaces": result, "count": len(result)})


@app.route("/admin/workspaces/<ws_id>/rotate-token", methods=["POST", "OPTIONS"])
def admin_rotate_token(ws_id):
    if request.method == "OPTIONS":
        return jsonify({}), 200
    if not _admin_token_valid():
        return jsonify({"error": "Admin token required"}), 401
    if ws_id not in _WORKSPACES:
        return jsonify({"error": "Workspace not found"}), 404
    new_token = f"eolm_live_{secrets.token_hex(20)}"
    _WORKSPACES[ws_id]["token_hash"] = hashlib.sha256(new_token.encode()).hexdigest()
    _WORKSPACES[ws_id]["rotated_at"] = datetime.now(timezone.utc).isoformat()
    return jsonify({"rotated": True, "token": new_token, "note": "Save this token — it will not be shown again."})


@app.route("/admin/workspaces/<ws_id>", methods=["DELETE", "OPTIONS"])
def admin_delete_workspace(ws_id):
    if request.method == "OPTIONS":
        return jsonify({}), 200
    if not _admin_token_valid():
        return jsonify({"error": "Admin token required"}), 401
    if ws_id not in _WORKSPACES:
        return jsonify({"error": "Workspace not found"}), 404
    del _WORKSPACES[ws_id]
    _WS_ACCOUNTS.pop(ws_id, None)
    return jsonify({"deleted": True, "id": ws_id})


@app.route("/admin/upgrade-guides", methods=["GET", "POST", "OPTIONS"])
def admin_upgrade_guides():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    if not _admin_token_valid():
        return jsonify({"error": "Admin token required"}), 401
    if request.method == "POST":
        body  = request.json or {}
        for field in ("title", "service", "guideUrl"):
            if not (body.get(field) or "").strip():
                return jsonify({"error": {"code": f"GUIDE_{field.upper()}_REQUIRED",
                                          "message": f"{field} is required."}}), 400
        url = (body.get("guideUrl") or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return jsonify({"error": {"code": "GUIDE_URL_INVALID",
                                      "message": "Guide URL must start with http:// or https://"}}), 400
        now  = datetime.now(timezone.utc).isoformat()
        guide = {
            "id":             f"guide_{secrets.token_hex(10)}",
            "title":          body.get("title", "").strip(),
            "service":        body.get("service", "").strip(),
            "versionPattern": body.get("versionPattern", "").strip(),
            "targetVersion":  body.get("targetVersion", "").strip(),
            "guideUrl":       url,
            "guideType":      body.get("guideType", "CK_GUIDE"),
            "testedInLab":    bool(body.get("testedInLab", False)),
            "status":         body.get("status", "DRAFT"),
            "summary":        body.get("summary", "").strip(),
            "createdAt":      now,
            "updatedAt":      now,
        }
        _UPGRADE_GUIDES.append(guide)
        return jsonify({"guide": guide}), 201
    # GET
    return jsonify({"guides": list(reversed(_UPGRADE_GUIDES)), "count": len(_UPGRADE_GUIDES)})


@app.route("/admin/upgrade-guides/<guide_id>", methods=["GET", "PATCH", "DELETE", "OPTIONS"])
def admin_upgrade_guide(guide_id):
    if request.method == "OPTIONS":
        return jsonify({}), 200
    if not _admin_token_valid():
        return jsonify({"error": "Admin token required"}), 401
    guide = next((g for g in _UPGRADE_GUIDES if g.get("id") == guide_id), None)
    if not guide:
        return jsonify({"error": {"code": "GUIDE_NOT_FOUND", "message": "Guide not found"}}), 404
    if request.method == "GET":
        return jsonify({"guide": guide})
    if request.method == "DELETE":
        _UPGRADE_GUIDES[:] = [g for g in _UPGRADE_GUIDES if g.get("id") != guide_id]
        return jsonify({"deleted": True, "id": guide_id})
    # PATCH
    body = request.json or {}
    for k in ("title", "service", "versionPattern", "targetVersion", "guideUrl", "summary"):
        if k in body:
            guide[k] = (body[k] or "").strip()
    if "testedInLab" in body: guide["testedInLab"] = bool(body["testedInLab"])
    if "status"      in body: guide["status"]      = body["status"] if body["status"] in ("DRAFT", "PUBLISHED") else "DRAFT"
    guide["updatedAt"] = datetime.now(timezone.utc).isoformat()
    return jsonify({"guide": guide})


@app.route("/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    return jsonify({
        "status":          "ok",
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "storage_backend": "mock",
    })


if __name__ == "__main__":
    data_dir   = os.environ.get("EOL_DATA_DIR", "/tmp/eol-data")
    token_file = os.path.join(data_dir, "secrets", "initial-admin-token")
    eol_count  = sum(1 for i in MOCK_ITEMS if i["eol_status"] == "EOL")
    warn_count = sum(1 for i in MOCK_ITEMS if i["eol_status"] == "EXPIRING_SOON")

    if not os.environ.get("ADMIN_PORTAL_TOKEN"):
        print()
        print("=" * 56)
        print("  AWS EOL Monitor — Initial Admin Token")
        print()
        print(f"  {_ADMIN_TOKEN}")
        print()
        print(f"  File: {token_file}")
        print("  Use Ctrl+Shift+A in the app to open Admin panel.")
        print("=" * 56)

    print()
    print(f"  AWS EOL Monitor — Mock API  http://localhost:3001")
    print(f"  {len(MOCK_ITEMS)} resources  |  {eol_count} EOL  |  {warn_count} Expiring Soon")
    print()
    app.run(port=3001, debug=True)
