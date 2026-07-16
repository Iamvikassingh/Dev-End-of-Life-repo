"""
Storage abstraction for AWS EOL Monitor.

Set STORAGE_BACKEND env var to choose where data is persisted:
  dynamodb  (default) — AWS DynamoDB tables
  s3                  — Single JSON file in an S3 bucket (set EOL_BUCKET)
  file                — Local JSON files on disk (set EOL_DATA_DIR, default /tmp/eol-data)

All three backends expose the same interface so the rest of the code is storage-agnostic.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)

STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "dynamodb").lower()
DYNAMODB_TABLE  = os.environ.get("DYNAMODB_TABLE", "aws-eol-inventory")
CONFIG_TABLE    = os.environ.get("CONFIG_TABLE", "aws-eol-config")
EOL_BUCKET      = os.environ.get("EOL_BUCKET", "")
EOL_DATA_DIR    = os.environ.get("EOL_DATA_DIR", "/var/lib/eol-data")

CONFIG_DEFAULTS = {
    "warn_days":        180,
    "alert_email":      "",
    "slack_webhook":    "",
    "scan_schedule":    "cron(0 8 * * ? *)",
    "scan_org":         False,
    "sns_topic_arn":    os.environ.get("SNS_TOPIC_ARN", ""),
    "enabled_services": ["Lambda", "EKS", "RDS", "ElastiCache", "EC2", "CodeBuild",
                         "ElasticBeanstalk", "EMR", "MSK", "OpenSearch", "DocumentDB",
                         "Neptune", "Glue", "CloudFrontFunctions", "ECR"],
}


def _merge_config(stored: dict) -> dict:
    merged = dict(CONFIG_DEFAULTS)
    merged.update(stored)
    return merged


def _serial(obj: Any):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError(f"Not serialisable: {type(obj)}")


def _workspace_id(item: dict) -> str:
    return item.get("workspace_id") or item.get("workspaceId") or ""


def _account_id(item: dict) -> str:
    return item.get("account_id") or item.get("accountId") or ""


def _workspace_id_camel(item: dict) -> str:
    return item.get("workspaceId") or item.get("workspace_id") or ""


def _org_connection_id(item: dict) -> str:
    return item.get("orgConnectionId") or item.get("org_connection_id") or ""


def _stamp_resources(resources: list, scan_started_at: Optional[str] = None) -> list:
    scanned_at = datetime.now(timezone.utc).isoformat()
    ts = scan_started_at or scanned_at
    return [{**dict(r), "scanned_at": scanned_at, "scan_started_at": ts} for r in resources]


def _auth_not_supported(*_args, **_kwargs):
    raise NotImplementedError(
        "Auth features (AUTH_EMAIL_SIGNUP_ENABLED, AUTH_GOOGLE_SIGNUP_ENABLED, etc.) "
        "require STORAGE_BACKEND=postgres.  Current backend does not support auth tables."
    )


# ── DynamoDB Backend ──────────────────────────────────────────────────────────

class DynamoDBBackend:
    def __init__(self):
        import boto3
        dynamo = boto3.resource("dynamodb")
        self._table  = dynamo.Table(DYNAMODB_TABLE)
        self._config = dynamo.Table(CONFIG_TABLE)

    # ── Workspaces ────────────────────────────────────────────────────────────

    def _get_all_workspaces(self) -> list:
        try:
            item = self._config.get_item(Key={"config_key": "workspaces"}).get("Item")
        except Exception:
            return []
        return json.loads((item or {}).get("records_json", "[]"))

    def _save_all_workspaces(self, workspaces: list) -> None:
        self._config.put_item(Item={
            "config_key":   "workspaces",
            "records_json": json.dumps(workspaces, default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })

    def get_workspaces(self) -> list:
        return self._get_all_workspaces()

    def get_workspace(self, workspace_id: str) -> Optional[dict]:
        return next((w for w in self._get_all_workspaces() if w.get("id") == workspace_id), None)

    def save_workspace(self, workspace: dict) -> dict:
        workspaces = self._get_all_workspaces()
        idx = next((i for i, w in enumerate(workspaces) if w.get("id") == workspace.get("id")), None)
        if idx is not None:
            workspaces[idx] = workspace
        else:
            workspaces.append(workspace)
        self._save_all_workspaces(workspaces)
        return workspace

    def delete_workspace(self, workspace_id: str) -> bool:
        workspaces = self._get_all_workspaces()
        new_list   = [w for w in workspaces if w.get("id") != workspace_id]
        if len(new_list) == len(workspaces):
            return False
        self._save_all_workspaces(new_list)
        return True

    # ── Connected accounts (workspace-scoped) ─────────────────────────────────

    def _get_all_accounts(self) -> list:
        try:
            item = self._config.get_item(Key={"config_key": "connected_accounts"}).get("Item")
        except Exception:
            return []
        return json.loads((item or {}).get("records_json", "[]"))

    def _save_all_accounts(self, accounts: list) -> None:
        self._config.put_item(Item={
            "config_key":   "connected_accounts",
            "records_json": json.dumps(accounts, default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })

    def get_accounts(self, workspace_id: Optional[str] = None) -> list:
        accounts = self._get_all_accounts()
        if workspace_id:
            return [a for a in accounts if a.get("workspace_id") == workspace_id]
        return accounts

    def save_account(self, account: dict) -> dict:
        accounts = self._get_all_accounts()
        idx = next((i for i, a in enumerate(accounts) if a.get("id") == account.get("id")), None)
        if idx is not None:
            accounts[idx] = account
        else:
            accounts.append(account)
        self._save_all_accounts(accounts)
        return account

    def delete_account(self, account_id: str, workspace_id: Optional[str] = None) -> bool:
        accounts = self._get_all_accounts()
        new_list = [
            a for a in accounts
            if not (a.get("id") == account_id and
                    (workspace_id is None or a.get("workspace_id") == workspace_id))
        ]
        if len(new_list) == len(accounts):
            return False
        self._save_all_accounts(new_list)
        return True

    # ── Organization scan records (DynamoDB/config table) ────────────────────

    def _get_org_records(self, key: str) -> list:
        try:
            item = self._config.get_item(Key={"config_key": key}).get("Item")
        except Exception:
            return []
        return json.loads((item or {}).get("records_json", "[]"))

    def _save_org_records(self, key: str, records: list) -> None:
        self._config.put_item(Item={
            "config_key":   key,
            "records_json": json.dumps(records, default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })

    def get_org_connections(self, workspace_id: str) -> list:
        return [r for r in self._get_org_records("org_connections") if _workspace_id_camel(r) == workspace_id]

    def get_org_connection(self, workspace_id: str, conn_id: str) -> Optional[dict]:
        return next((r for r in self.get_org_connections(workspace_id) if r.get("id") == conn_id), None)

    def save_org_connection(self, conn: dict) -> dict:
        records = self._get_org_records("org_connections")
        idx = next((i for i, r in enumerate(records) if r.get("id") == conn.get("id")), None)
        if idx is not None:
            records[idx] = conn
        else:
            records.append(conn)
        self._save_org_records("org_connections", records)
        return conn

    def delete_org_connection(self, workspace_id: str, conn_id: str) -> bool:
        records = self._get_org_records("org_connections")
        new_records = [r for r in records if not (r.get("id") == conn_id and _workspace_id_camel(r) == workspace_id)]
        if len(new_records) == len(records):
            return False
        self._save_org_records("org_connections", new_records)
        return True

    def get_org_accounts(self, workspace_id: str, conn_id: Optional[str] = None) -> list:
        records = [r for r in self._get_org_records("org_accounts") if _workspace_id_camel(r) == workspace_id]
        if conn_id:
            records = [r for r in records if _org_connection_id(r) == conn_id]
        return records

    def save_org_account(self, account: dict) -> dict:
        records = self._get_org_records("org_accounts")
        idx = next((i for i, r in enumerate(records) if r.get("id") == account.get("id")), None)
        if idx is not None:
            records[idx] = account
        else:
            records.append(account)
        self._save_org_records("org_accounts", records)
        return account

    def save_org_scan_run(self, run: dict) -> dict:
        records = self._get_org_records("org_scan_runs")
        idx = next((i for i, r in enumerate(records) if r.get("id") == run.get("id")), None)
        if idx is not None:
            records[idx] = run
        else:
            records.insert(0, run)
        self._save_org_records("org_scan_runs", records[:500])
        return run

    def get_org_scan_run(self, workspace_id: str, scan_id: str) -> Optional[dict]:
        return next((r for r in self._get_org_records("org_scan_runs")
                     if r.get("id") == scan_id and _workspace_id_camel(r) == workspace_id), None)

    def get_org_scan_runs(self, workspace_id: str, conn_id: Optional[str] = None, limit: int = 20) -> list:
        records = [r for r in self._get_org_records("org_scan_runs") if _workspace_id_camel(r) == workspace_id]
        if conn_id:
            records = [r for r in records if _org_connection_id(r) == conn_id]
        return records[:limit]

    def get_running_org_scan(self, workspace_id: str, conn_id: str) -> Optional[dict]:
        return next(
            (r for r in self._get_org_records("org_scan_runs")
             if _workspace_id_camel(r) == workspace_id
             and _org_connection_id(r) == conn_id
             and r.get("status") == "RUNNING"),
            None)

    def cleanup_stale_org_scans(self, workspace_id: str, timeout_minutes: int = 30) -> int:
        records = self._get_org_records("org_scan_runs")
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
        changed = 0
        for r in records:
            if (_workspace_id_camel(r) == workspace_id
                    and r.get("status") == "RUNNING"
                    and (r.get("startedAt") or "") < cutoff):
                r["status"] = "FAILED"
                r["completedAt"] = datetime.now(timezone.utc).isoformat()
                r["errorCode"] = "STALE_ORG_SCAN_TIMEOUT"
                r["error"] = "STALE_ORG_SCAN_TIMEOUT"
                changed += 1
        if changed:
            self._save_org_records("org_scan_runs", records[:500])
        return changed

    # ── Scan runs (DynamoDB) ──────────────────────────────────────────────────

    def _get_all_scan_runs(self) -> list:
        try:
            item = self._config.get_item(Key={"config_key": "scan_runs"}).get("Item")
        except Exception:
            return []
        return json.loads((item or {}).get("records_json", "[]"))

    def _save_all_scan_runs(self, runs: list) -> None:
        self._config.put_item(Item={
            "config_key":   "scan_runs",
            "records_json": json.dumps(runs[:200], default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })

    def save_scan_run(self, run: dict) -> dict:
        runs = self._get_all_scan_runs()
        idx  = next((i for i, r in enumerate(runs) if r.get("scanId") == run.get("scanId")), None)
        if idx is not None:
            runs[idx] = run
        else:
            runs.insert(0, run)
        self._save_all_scan_runs(runs)
        return run

    def get_scan_run(self, scan_id: str) -> Optional[dict]:
        return next((r for r in self._get_all_scan_runs() if r.get("scanId") == scan_id), None)

    def get_scan_runs(self, workspace_id: str, account_id: Optional[str] = None, limit: int = 20) -> list:
        runs = [r for r in self._get_all_scan_runs() if r.get("workspaceId") == workspace_id]
        if account_id:
            runs = [r for r in runs if r.get("accountId") == account_id]
        return runs[:limit]

    def get_all_scan_runs_admin(self, workspace_id: Optional[str] = None,
                                status: Optional[str] = None, search: Optional[str] = None,
                                limit: int = 100, offset: int = 0) -> dict:
        runs = self._get_all_scan_runs()
        if workspace_id:
            runs = [r for r in runs if r.get("workspaceId") == workspace_id]
        if status:
            runs = [r for r in runs if r.get("status") == status]
        if search:
            q = search.lower()
            runs = [r for r in runs if
                    q in (r.get("workspaceId") or "").lower() or
                    q in (r.get("accountId") or "").lower()]
        runs.sort(key=lambda r: r.get("startedAt") or "", reverse=True)
        total = len(runs)
        return {"runs": runs[offset:offset + limit], "total": total}

    def get_running_scan(self, workspace_id: str, account_id: str) -> Optional[dict]:
        return next(
            (r for r in self._get_all_scan_runs()
             if r.get("workspaceId") == workspace_id
             and r.get("accountId") == account_id
             and r.get("status") == "RUNNING"),
            None)

    def cleanup_stale_scans(self, workspace_id: str, timeout_minutes: int = 30) -> int:
        runs   = self._get_all_scan_runs()
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
        changed = 0
        for r in runs:
            if (r.get("workspaceId") == workspace_id
                    and r.get("status") == "RUNNING"
                    and (r.get("startedAt") or "") < cutoff):
                r["status"]      = "FAILED"
                r["completedAt"] = datetime.now(timezone.utc).isoformat()
                r["error"]       = "STALE_SCAN_TIMEOUT"
                changed += 1
        if changed:
            self._save_all_scan_runs(runs)
        return changed

    def find_alert_by_resource(self, workspace_id: str, account_id: str,
                                resource_id: str, service: str) -> Optional[dict]:
        return next(
            (a for a in self._get_all_alerts()
             if a.get("workspaceId") == workspace_id
             and a.get("accountId") == account_id
             and a.get("resourceId") == resource_id
             and a.get("service") == service
             and a.get("status") != "RESOLVED"),
            None)

    # ── Alerts (DynamoDB) ─────────────────────────────────────────────────────

    def _get_all_alerts(self) -> list:
        try:
            item = self._config.get_item(Key={"config_key": "alerts"}).get("Item")
        except Exception:
            return []
        return json.loads((item or {}).get("records_json", "[]"))

    def _save_all_alerts(self, alerts: list) -> None:
        self._config.put_item(Item={
            "config_key":   "alerts",
            "records_json": json.dumps(alerts[:2000], default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })

    def save_alert(self, alert: dict) -> dict:
        alerts = self._get_all_alerts()
        idx    = next((i for i, a in enumerate(alerts) if a.get("id") == alert.get("id")), None)
        if idx is not None:
            alerts[idx] = alert
        else:
            alerts.insert(0, alert)
        self._save_all_alerts(alerts)
        return alert

    def get_alerts(self, workspace_id: str, account_id: Optional[str] = None,
                   status: Optional[str] = None, limit: int = 200) -> list:
        alerts = [a for a in self._get_all_alerts() if a.get("workspaceId") == workspace_id]
        if account_id:
            alerts = [a for a in alerts if a.get("accountId") == account_id]
        if status:
            alerts = [a for a in alerts if a.get("status") == status]
        return alerts[:limit]

    def get_alert(self, alert_id: str, workspace_id: str) -> Optional[dict]:
        return next((a for a in self._get_all_alerts()
                     if a.get("id") == alert_id and a.get("workspaceId") == workspace_id), None)

    # ── Notification settings (DynamoDB) ──────────────────────────────────────

    def get_notification_settings(self, workspace_id: str) -> dict:
        try:
            item = self._config.get_item(
                Key={"config_key": f"notif_settings_{workspace_id}"}
            ).get("Item")
        except Exception:
            return {}
        return json.loads((item or {}).get("records_json", "{}"))

    def save_notification_settings(self, workspace_id: str, settings: dict) -> dict:
        self._config.put_item(Item={
            "config_key":   f"notif_settings_{workspace_id}",
            "records_json": json.dumps(settings, default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })
        return settings

    def get_notification_logs(self, workspace_id: str, limit: int = 50) -> list:
        try:
            item = self._config.get_item(
                Key={"config_key": f"notif_logs_{workspace_id}"}
            ).get("Item")
        except Exception:
            return []
        logs = json.loads((item or {}).get("records_json", "[]"))
        return logs[:limit]

    def save_notification_log(self, log: dict) -> dict:
        ws_id = log.get("workspaceId", "")
        logs  = self.get_notification_logs(ws_id, limit=200)
        logs.insert(0, log)
        self._config.put_item(Item={
            "config_key":   f"notif_logs_{ws_id}",
            "records_json": json.dumps(logs[:100], default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })
        return log

    # ── API tokens (DynamoDB) ────────────────────────────────────────────────

    def _api_tokens_key(self, workspace_id: str) -> str:
        return f"api_tokens_{workspace_id}"

    def get_api_tokens(self, workspace_id: str) -> list:
        try:
            item = self._config.get_item(
                Key={"config_key": self._api_tokens_key(workspace_id)}
            ).get("Item")
        except Exception:
            return []
        return json.loads((item or {}).get("records_json", "[]"))

    def save_api_token(self, token: dict) -> dict:
        ws_id  = token["workspaceId"]
        tokens = self.get_api_tokens(ws_id)
        idx    = next((i for i, t in enumerate(tokens) if t.get("id") == token.get("id")), None)
        if idx is not None:
            tokens[idx] = token
        else:
            tokens.append(token)
        self._config.put_item(Item={
            "config_key":   self._api_tokens_key(ws_id),
            "records_json": json.dumps(tokens, default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })
        return token

    def get_api_token_by_id(self, token_id: str, workspace_id: str) -> Optional[dict]:
        return next((t for t in self.get_api_tokens(workspace_id)
                     if t.get("id") == token_id), None)

    def find_api_token_by_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        return next((t for t in self.get_api_tokens(workspace_id)
                     if t.get("tokenHash") == token_hash), None)

    # ── Audit logs (DynamoDB) ─────────────────────────────────────────────────

    def _audit_key(self, workspace_id: str) -> str:
        return f"audit_logs_{workspace_id}"

    def save_audit_log(self, log: dict) -> dict:
        ws_id = log.get("workspaceId", "")
        logs  = self.get_audit_logs(ws_id, limit=2000)
        logs.insert(0, log)
        self._config.put_item(Item={
            "config_key":   self._audit_key(ws_id),
            "records_json": json.dumps(logs[:1000], default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })
        return log

    def get_audit_logs(self, workspace_id: str, limit: int = 50) -> list:
        try:
            item = self._config.get_item(
                Key={"config_key": self._audit_key(workspace_id)}
            ).get("Item")
        except Exception:
            return []
        logs = json.loads((item or {}).get("records_json", "[]"))
        return logs[:limit]

    # ── Report snapshots (DynamoDB config table) ─────────────────────────────

    def _get_all_report_snapshots(self) -> list:
        try:
            item = self._config.get_item(Key={"config_key": "report_snapshots"}).get("Item")
        except Exception:
            return []
        return json.loads((item or {}).get("records_json", "[]"))

    def _save_all_report_snapshots(self, snapshots: list) -> None:
        self._config.put_item(Item={
            "config_key":   "report_snapshots",
            "records_json": json.dumps(snapshots[:2000], default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })

    def save_report_snapshot(self, snapshot: dict) -> dict:
        snapshots = self._get_all_report_snapshots()
        snapshots = [s for s in snapshots if s.get("id") != snapshot.get("id")]
        snapshots.insert(0, snapshot)
        ws_id = snapshot.get("workspaceId", "")
        scoped = [s for s in snapshots if s.get("workspaceId") == ws_id][:500]
        other = [s for s in snapshots if s.get("workspaceId") != ws_id]
        self._save_all_report_snapshots(scoped + other)
        return snapshot

    def get_report_snapshots(self, workspace_id: str, limit: int = 50) -> list:
        return [s for s in self._get_all_report_snapshots() if s.get("workspaceId") == workspace_id][:limit]

    def get_report_snapshot(self, workspace_id: str, report_id: str) -> Optional[dict]:
        return next((s for s in self._get_all_report_snapshots()
                     if s.get("workspaceId") == workspace_id and s.get("id") == report_id), None)

    def save_resources(self, resources: list) -> int:
        written = 0
        ttl = int((datetime.now(timezone.utc) + timedelta(days=90)).timestamp())
        scanned_at = datetime.now(timezone.utc).isoformat()
        for item in resources:
            item = dict(item)
            item["ttl"] = ttl
            item["scanned_at"] = scanned_at
            # DynamoDB requires Decimal for numbers
            for k, v in list(item.items()):
                if isinstance(v, float):
                    item[k] = Decimal(str(v))
                elif isinstance(v, int) and k not in ("ttl",):
                    item[k] = Decimal(str(v))
            self._table.put_item(Item=item)
            written += 1
        return written

    def replace_resources_for_account(self, workspace_id: str, account_id: str,
                                       resources: list, scan_started_at: Optional[str] = None) -> int:
        from boto3.dynamodb.conditions import Attr
        scan_kwargs = {
            "FilterExpression": (
                (Attr("workspace_id").eq(workspace_id) | Attr("workspaceId").eq(workspace_id)) &
                (Attr("account_id").eq(account_id) | Attr("accountId").eq(account_id))
            )
        }
        old_items: list = []
        resp = self._table.scan(**scan_kwargs)
        old_items.extend(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            resp = self._table.scan(**scan_kwargs)
            old_items.extend(resp.get("Items", []))

        # Stale-write guard: if existing inventory is from a newer scan, do not overwrite
        if scan_started_at and old_items:
            newest = max((str(i.get("scan_started_at") or "") for i in old_items), default="")
            if newest and newest > scan_started_at:
                logger.warning("Stale write skipped account=%s existing=%s current=%s",
                               account_id, newest, scan_started_at)
                return 0

        for old in old_items:
            if old.get("resource_id"):
                self._table.delete_item(Key={"resource_id": old["resource_id"]})

        return self.save_resources(_stamp_resources(resources, scan_started_at=scan_started_at))

    def get_resources(self, filters: Optional[dict] = None) -> list:
        from boto3.dynamodb.conditions import Attr
        filter_expr = None
        if filters:
            if filters.get("workspace_id"):
                filter_expr = Attr("workspace_id").eq(filters["workspace_id"])
            if filters.get("status"):
                cond = Attr("eol_status").eq(filters["status"].upper())
                filter_expr = filter_expr & cond if filter_expr else cond
            if filters.get("service"):
                cond = Attr("service_type").begins_with(filters["service"])
                filter_expr = filter_expr & cond if filter_expr else cond
            if filters.get("region"):
                cond = Attr("region").eq(filters["region"])
                filter_expr = filter_expr & cond if filter_expr else cond
            if filters.get("account_id"):
                v = filters["account_id"]
                cond = Attr("account_id").eq(v) | Attr("accountId").eq(v)
                filter_expr = filter_expr & cond if filter_expr else cond

        kwargs: dict = {}
        if filter_expr:
            kwargs["FilterExpression"] = filter_expr

        items: list = []
        resp = self._table.scan(**kwargs)
        items.extend(resp["Items"])
        while "LastEvaluatedKey" in resp:
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            resp = self._table.scan(**kwargs)
            items.extend(resp["Items"])
        return items

    def get_resource_by_id(self, resource_id: str, workspace_id: Optional[str] = None) -> Optional[dict]:
        from boto3.dynamodb.conditions import Key
        resp = self._table.query(KeyConditionExpression=Key("resource_id").eq(resource_id))
        items = resp.get("Items", [])
        if workspace_id:
            items = [i for i in items if i.get("workspace_id") == workspace_id]
        return items[0] if items else None

    def get_config(self) -> dict:
        try:
            item = self._config.get_item(Key={"config_key": "global"}).get("Item", {})
        except Exception:
            item = {}
        return _merge_config(item)

    def save_config(self, config: dict) -> None:
        config = dict(config)
        config["config_key"] = "global"
        config["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._config.put_item(Item=config)

    def get_workspace_config(self, workspace_id: str) -> dict:
        try:
            item = self._config.get_item(Key={"config_key": f"workspace_config:{workspace_id}"}).get("Item", {})
        except Exception:
            item = {}
        item = dict(item or {})
        item.pop("config_key", None)
        return _merge_config(item)

    def save_workspace_config(self, workspace_id: str, config: dict) -> dict:
        merged = _merge_config(config)
        merged["config_key"] = f"workspace_config:{workspace_id}"
        merged["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._config.put_item(Item=merged)
        merged.pop("config_key", None)
        return merged

    # ── General EOL cache ────────────────────────────────────────────────────
    # Stored as a single oversized JSON blob in the config table under key
    # "general_eol_cache". Records are small (~200 B each) so a full library
    # of 200 records stays well under DynamoDB's 400 KB item limit.

    def get_general_eol_cache(self) -> Optional[dict]:
        try:
            item = self._config.get_item(Key={"config_key": "general_eol_cache"}).get("Item")
        except Exception:
            return None
        if not item:
            return None
        return {
            "records":      json.loads(item.get("records_json", "[]")),
            "refreshed_at": str(item.get("refreshed_at", "")),
            "expires_at":   str(item.get("expires_at", "")),
        }

    def save_general_eol_cache(self, records: list, refreshed_at: str, expires_at: str) -> None:
        self._config.put_item(Item={
            "config_key":   "general_eol_cache",
            "records_json": json.dumps(records, default=_serial),
            "refreshed_at": refreshed_at,
            "expires_at":   expires_at,
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })

    # ── EOL overrides (DynamoDB) ──────────────────────────────────────────────

    def _eol_overrides_key(self) -> str:
        return "eol_overrides"

    def _get_all_eol_overrides_raw(self) -> list:
        try:
            item = self._config.get_item(Key={"config_key": self._eol_overrides_key()}).get("Item")
        except Exception:
            return []
        return json.loads((item or {}).get("records_json", "[]"))

    def _save_all_eol_overrides_raw(self, overrides: list) -> None:
        self._config.put_item(Item={
            "config_key":   self._eol_overrides_key(),
            "records_json": json.dumps(overrides, default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })

    def list_eol_overrides(self) -> list:
        return self._get_all_eol_overrides_raw()

    def get_eol_override(self, product: str, version: str) -> Optional[dict]:
        overrides = self._get_all_eol_overrides_raw()
        return next((o for o in overrides if o.get("product") == product and o.get("version") == version), None)

    def save_eol_override(self, product: str, version: str, record: dict) -> dict:
        overrides = self._get_all_eol_overrides_raw()
        idx = next((i for i, o in enumerate(overrides)
                    if o.get("product") == product and o.get("version") == version), None)
        record = {**record, "product": product, "version": version,
                  "updatedAt": datetime.now(timezone.utc).isoformat()}
        if idx is not None:
            overrides[idx] = record
        else:
            overrides.append(record)
        self._save_all_eol_overrides_raw(overrides)
        return record

    def delete_eol_override(self, product: str, version: str) -> bool:
        overrides = self._get_all_eol_overrides_raw()
        new_list = [o for o in overrides if not (o.get("product") == product and o.get("version") == version)]
        if len(new_list) == len(overrides):
            return False
        self._save_all_eol_overrides_raw(new_list)
        return True

    # ── Verified lifecycle (DynamoDB) ─────────────────────────────────────────

    def _get_all_verified_lifecycle_raw(self) -> list:
        try:
            item = self._config.get_item(Key={"config_key": "verified_lifecycle"}).get("Item")
        except Exception:
            return []
        return json.loads((item or {}).get("records_json", "[]"))

    def _save_all_verified_lifecycle_raw(self, records: list) -> None:
        self._config.put_item(Item={
            "config_key":   "verified_lifecycle",
            "records_json": json.dumps(records, default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })

    def list_verified_lifecycle(self) -> list:
        return self._get_all_verified_lifecycle_raw()

    def get_verified_lifecycle(self, product: str, version: str) -> Optional[dict]:
        return next((r for r in self._get_all_verified_lifecycle_raw()
                     if r.get("product") == product and r.get("version") == version), None)

    def save_verified_lifecycle(self, product: str, version: str, record: dict) -> dict:
        records = self._get_all_verified_lifecycle_raw()
        idx = next((i for i, r in enumerate(records)
                    if r.get("product") == product and r.get("version") == version), None)
        now = datetime.now(timezone.utc).isoformat()
        record = {**record, "product": product, "version": version,
                  "updatedAt": now, "createdAt": record.get("createdAt", now)}
        if idx is not None:
            records[idx] = record
        else:
            records.append(record)
        self._save_all_verified_lifecycle_raw(records)
        return record

    def delete_verified_lifecycle(self, product: str, version: str) -> bool:
        records = self._get_all_verified_lifecycle_raw()
        new_list = [r for r in records if not (r.get("product") == product and r.get("version") == version)]
        if len(new_list) == len(records):
            return False
        self._save_all_verified_lifecycle_raw(new_list)
        return True

    # ── Upgrade guides (DynamoDB) ─────────────────────────────────────────────

    def _get_all_guides(self) -> list:
        try:
            item = self._config.get_item(Key={"config_key": "upgrade_guides"}).get("Item")
        except Exception:
            return []
        return json.loads((item or {}).get("records_json", "[]"))

    def _save_all_guides(self, guides: list) -> None:
        self._config.put_item(Item={
            "config_key":   "upgrade_guides",
            "records_json": json.dumps(guides, default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })

    def get_upgrade_guides(self) -> list:
        return self._get_all_guides()

    def save_upgrade_guide(self, guide: dict) -> dict:
        guides = self._get_all_guides()
        idx = next((i for i, g in enumerate(guides) if g.get("id") == guide.get("id")), None)
        if idx is not None:
            guides[idx] = guide
        else:
            guides.append(guide)
        self._save_all_guides(guides)
        return guide

    def delete_upgrade_guide(self, guide_id: str) -> bool:
        guides = self._get_all_guides()
        new_list = [g for g in guides if g.get("id") != guide_id]
        if len(new_list) == len(guides):
            return False
        self._save_all_guides(new_list)
        return True

    # ── Members (DynamoDB) ────────────────────────────────────────────────────

    def _members_key(self, workspace_id: str) -> str:
        return f"members_{workspace_id}"

    def get_members(self, workspace_id: str) -> list:
        try:
            item = self._config.get_item(Key={"config_key": self._members_key(workspace_id)}).get("Item")
        except Exception:
            return []
        return json.loads((item or {}).get("records_json", "[]"))

    def get_member_by_id(self, member_id: str, workspace_id: str) -> Optional[dict]:
        return next((m for m in self.get_members(workspace_id) if m.get("id") == member_id), None)

    def find_member_by_invite_token_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        return next((m for m in self.get_members(workspace_id) if m.get("inviteTokenHash") == token_hash), None)

    def save_member(self, member: dict) -> dict:
        ws_id   = member["workspaceId"]
        members = self.get_members(ws_id)
        idx     = next((i for i, m in enumerate(members) if m.get("id") == member.get("id")), None)
        if idx is not None:
            members[idx] = member
        else:
            members.append(member)
        self._config.put_item(Item={
            "config_key":   self._members_key(ws_id),
            "records_json": json.dumps(members, default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })
        return member

    def delete_member(self, member_id: str, workspace_id: str) -> bool:
        members  = self.get_members(workspace_id)
        new_list = [m for m in members if m.get("id") != member_id]
        if len(new_list) == len(members):
            return False
        self._config.put_item(Item={
            "config_key":   self._members_key(workspace_id),
            "records_json": json.dumps(new_list, default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })
        return True

    def find_member_session_by_token_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        try:
            item = self._config.get_item(Key={"config_key": f"member_sessions_{workspace_id}"}).get("Item")
        except Exception:
            return None
        sessions = json.loads((item or {}).get("records_json", "[]"))
        return next((s for s in sessions if s.get("tokenHash") == token_hash), None)

    def save_member_session(self, session: dict) -> dict:
        ws_id = session["workspaceId"]
        try:
            item = self._config.get_item(Key={"config_key": f"member_sessions_{ws_id}"}).get("Item")
        except Exception:
            item = None
        sessions = json.loads((item or {}).get("records_json", "[]"))
        idx = next((i for i, s in enumerate(sessions) if s.get("id") == session.get("id")), None)
        if idx is not None:
            sessions[idx] = session
        else:
            sessions.append(session)
        self._config.put_item(Item={
            "config_key":   f"member_sessions_{ws_id}",
            "records_json": json.dumps(sessions, default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })
        return session

    def revoke_member_sessions(self, member_id: str, workspace_id: str) -> int:
        try:
            item = self._config.get_item(Key={"config_key": f"member_sessions_{workspace_id}"}).get("Item")
        except Exception:
            return 0
        sessions = json.loads((item or {}).get("records_json", "[]"))
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for s in sessions:
            if s.get("memberId") == member_id and not s.get("revokedAt"):
                s["revokedAt"] = now
                count += 1
        if count:
            self._config.put_item(Item={
                "config_key":   f"member_sessions_{workspace_id}",
                "records_json": json.dumps(sessions, default=_serial),
                "updated_at":   now,
            })
        return count

    def find_member_login_token_by_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        try:
            item = self._config.get_item(Key={"config_key": f"member_login_tokens_{workspace_id}"}).get("Item")
        except Exception:
            return None
        tokens = json.loads((item or {}).get("records_json", "[]"))
        return next((t for t in tokens if t.get("tokenHash") == token_hash), None)

    def get_member_login_tokens_for_member(self, member_id: str, workspace_id: str) -> list:
        try:
            item = self._config.get_item(Key={"config_key": f"member_login_tokens_{workspace_id}"}).get("Item")
        except Exception:
            return []
        tokens = json.loads((item or {}).get("records_json", "[]"))
        return [t for t in tokens if t.get("memberId") == member_id]

    def save_member_login_token(self, token: dict) -> dict:
        ws_id = token["workspaceId"]
        try:
            item = self._config.get_item(Key={"config_key": f"member_login_tokens_{ws_id}"}).get("Item")
        except Exception:
            item = None
        tokens = json.loads((item or {}).get("records_json", "[]"))
        idx = next((i for i, t in enumerate(tokens) if t.get("id") == token.get("id")), None)
        if idx is not None:
            tokens[idx] = token
        else:
            tokens.append(token)
        self._config.put_item(Item={
            "config_key":   f"member_login_tokens_{ws_id}",
            "records_json": json.dumps(tokens, default=_serial),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        })
        return token


    auth_run   = _auth_not_supported
    auth_query = _auth_not_supported
    auth_one   = _auth_not_supported


# ── S3 Backend ────────────────────────────────────────────────────────────────

class S3Backend:
    INVENTORY_KEY  = "eol/inventory.json"
    CONFIG_KEY     = "eol/config.json"
    ACCOUNTS_KEY   = "eol/accounts.json"
    WORKSPACES_KEY = "eol/workspaces.json"

    def __init__(self):
        import boto3
        if not EOL_BUCKET:
            raise ValueError("EOL_BUCKET env var is required when STORAGE_BACKEND=s3")
        self._s3     = boto3.client("s3")
        self._bucket = EOL_BUCKET

    def _read(self, key: str, default: Any) -> Any:
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=key)
            return json.loads(obj["Body"].read())
        except self._s3.exceptions.NoSuchKey:
            return default
        except Exception as exc:
            logger.warning("S3 read %s/%s failed: %s", self._bucket, key, exc)
            return default

    def _write(self, key: str, data: Any) -> None:
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=json.dumps(data, indent=2, default=_serial).encode(),
            ContentType="application/json",
        )

    def save_resources(self, resources: list) -> int:
        def _key(r: dict) -> str:
            return f"{r.get('workspace_id','')}#{r['resource_id']}#{r['service_type']}"

        existing = {_key(r): r for r in self._read(self.INVENTORY_KEY, [])}
        scanned_at = datetime.now(timezone.utc).isoformat()
        for r in resources:
            r = dict(r)
            r["scanned_at"] = scanned_at
            existing[_key(r)] = r

        # Evict records not seen in the last 90 days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        active = [v for v in existing.values() if (v.get("scanned_at") or "") >= cutoff]
        self._write(self.INVENTORY_KEY, active)
        return len(resources)

    def replace_resources_for_account(self, workspace_id: str, account_id: str,
                                       resources: list, scan_started_at: Optional[str] = None) -> int:
        all_inv = self._read(self.INVENTORY_KEY, [])
        # Stale-write guard: if existing inventory is from a newer scan, do not overwrite
        if scan_started_at:
            acct_recs = [r for r in all_inv
                         if _workspace_id(r) == workspace_id and _account_id(r) == account_id]
            if acct_recs:
                newest = max((r.get("scan_started_at") or "" for r in acct_recs), default="")
                if newest and newest > scan_started_at:
                    logger.warning("Stale write skipped account=%s existing=%s current=%s",
                                   account_id, newest, scan_started_at)
                    return 0
        existing = [r for r in all_inv
                    if not (_workspace_id(r) == workspace_id and _account_id(r) == account_id)]
        existing.extend(_stamp_resources(resources, scan_started_at=scan_started_at))
        self._write(self.INVENTORY_KEY, existing)
        return len(resources)

    def get_resources(self, filters: Optional[dict] = None) -> list:
        items = self._read(self.INVENTORY_KEY, [])
        if not filters:
            return items
        if filters.get("workspace_id"):
            items = [i for i in items if i.get("workspace_id") == filters["workspace_id"]]
        if filters.get("status"):
            items = [i for i in items if i.get("eol_status") == filters["status"].upper()]
        if filters.get("service"):
            q = filters["service"].lower()
            items = [i for i in items if q in i.get("service_type", "").lower()]
        if filters.get("region"):
            items = [i for i in items if filters["region"] in i.get("region", "")]
        if filters.get("account_id"):
            aid = filters["account_id"]
            items = [i for i in items if i.get("account_id") == aid or i.get("accountId") == aid]
        return items

    def get_resource_by_id(self, resource_id: str, workspace_id: Optional[str] = None) -> Optional[dict]:
        items = self._read(self.INVENTORY_KEY, [])
        return next(
            (i for i in items
             if i.get("resource_id") == resource_id
             and (not workspace_id or i.get("workspace_id") == workspace_id)),
            None)

    def get_config(self) -> dict:
        return _merge_config(self._read(self.CONFIG_KEY, {}))

    def save_config(self, config: dict) -> None:
        config = dict(config)
        config["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write(self.CONFIG_KEY, config)

    WORKSPACE_CONFIG_KEY = "eol/workspace_config.json"

    def get_workspace_config(self, workspace_id: str) -> dict:
        configs = self._read(self.WORKSPACE_CONFIG_KEY, {})
        return _merge_config(configs.get(workspace_id, {}))

    def save_workspace_config(self, workspace_id: str, config: dict) -> dict:
        configs = self._read(self.WORKSPACE_CONFIG_KEY, {})
        merged = _merge_config(config)
        merged["updated_at"] = datetime.now(timezone.utc).isoformat()
        configs[workspace_id] = merged
        self._write(self.WORKSPACE_CONFIG_KEY, configs)
        return merged

    def get_general_eol_cache(self) -> Optional[dict]:
        return self._read("eol/general_eol_cache.json", None)

    def save_general_eol_cache(self, records: list, refreshed_at: str, expires_at: str) -> None:
        self._write("eol/general_eol_cache.json", {
            "records":      records,
            "refreshed_at": refreshed_at,
            "expires_at":   expires_at,
        })

    # ── EOL overrides (S3) ────────────────────────────────────────────────────

    EOL_OVERRIDES_KEY = "eol/eol_overrides.json"

    def list_eol_overrides(self) -> list:
        return self._read(self.EOL_OVERRIDES_KEY, [])

    def get_eol_override(self, product: str, version: str) -> Optional[dict]:
        overrides = self.list_eol_overrides()
        return next((o for o in overrides if o.get("product") == product and o.get("version") == version), None)

    def save_eol_override(self, product: str, version: str, record: dict) -> dict:
        overrides = self.list_eol_overrides()
        idx = next((i for i, o in enumerate(overrides)
                    if o.get("product") == product and o.get("version") == version), None)
        record = {**record, "product": product, "version": version,
                  "updatedAt": datetime.now(timezone.utc).isoformat()}
        if idx is not None:
            overrides[idx] = record
        else:
            overrides.append(record)
        self._write(self.EOL_OVERRIDES_KEY, overrides)
        return record

    def delete_eol_override(self, product: str, version: str) -> bool:
        overrides = self.list_eol_overrides()
        new_list = [o for o in overrides if not (o.get("product") == product and o.get("version") == version)]
        if len(new_list) == len(overrides):
            return False
        self._write(self.EOL_OVERRIDES_KEY, new_list)
        return True

    # ── Verified lifecycle (S3) ───────────────────────────────────────────────

    VERIFIED_LIFECYCLE_KEY = "eol/verified_lifecycle.json"

    def list_verified_lifecycle(self) -> list:
        return self._read(self.VERIFIED_LIFECYCLE_KEY, [])

    def get_verified_lifecycle(self, product: str, version: str) -> Optional[dict]:
        return next((r for r in self.list_verified_lifecycle()
                     if r.get("product") == product and r.get("version") == version), None)

    def save_verified_lifecycle(self, product: str, version: str, record: dict) -> dict:
        records = self.list_verified_lifecycle()
        idx = next((i for i, r in enumerate(records)
                    if r.get("product") == product and r.get("version") == version), None)
        now = datetime.now(timezone.utc).isoformat()
        record = {**record, "product": product, "version": version,
                  "updatedAt": now, "createdAt": record.get("createdAt", now)}
        if idx is not None:
            records[idx] = record
        else:
            records.append(record)
        self._write(self.VERIFIED_LIFECYCLE_KEY, records)
        return record

    def delete_verified_lifecycle(self, product: str, version: str) -> bool:
        records = self.list_verified_lifecycle()
        new_list = [r for r in records if not (r.get("product") == product and r.get("version") == version)]
        if len(new_list) == len(records):
            return False
        self._write(self.VERIFIED_LIFECYCLE_KEY, new_list)
        return True

    # ── Upgrade guides (S3) ───────────────────────────────────────────────────

    GUIDES_KEY = "eol/upgrade_guides.json"

    def get_upgrade_guides(self) -> list:
        return self._read(self.GUIDES_KEY, [])

    def save_upgrade_guide(self, guide: dict) -> dict:
        guides = self.get_upgrade_guides()
        idx = next((i for i, g in enumerate(guides) if g.get("id") == guide.get("id")), None)
        if idx is not None:
            guides[idx] = guide
        else:
            guides.append(guide)
        self._write(self.GUIDES_KEY, guides)
        return guide

    def delete_upgrade_guide(self, guide_id: str) -> bool:
        guides = self.get_upgrade_guides()
        new_list = [g for g in guides if g.get("id") != guide_id]
        if len(new_list) == len(guides):
            return False
        self._write(self.GUIDES_KEY, new_list)
        return True

    # ── Workspaces ────────────────────────────────────────────────────────────

    def get_workspaces(self) -> list:
        return self._read(self.WORKSPACES_KEY, [])

    def get_workspace(self, workspace_id: str) -> Optional[dict]:
        return next((w for w in self.get_workspaces() if w.get("id") == workspace_id), None)

    def save_workspace(self, workspace: dict) -> dict:
        workspaces = self.get_workspaces()
        idx = next((i for i, w in enumerate(workspaces) if w.get("id") == workspace.get("id")), None)
        if idx is not None:
            workspaces[idx] = workspace
        else:
            workspaces.append(workspace)
        self._write(self.WORKSPACES_KEY, workspaces)
        return workspace

    def delete_workspace(self, workspace_id: str) -> bool:
        workspaces = self.get_workspaces()
        new_list   = [w for w in workspaces if w.get("id") != workspace_id]
        if len(new_list) == len(workspaces):
            return False
        self._write(self.WORKSPACES_KEY, new_list)
        return True

    # ── Connected accounts (workspace-scoped) ─────────────────────────────────

    def get_accounts(self, workspace_id: Optional[str] = None) -> list:
        accounts = self._read(self.ACCOUNTS_KEY, [])
        if workspace_id:
            return [a for a in accounts if a.get("workspace_id") == workspace_id]
        return accounts

    def save_account(self, account: dict) -> dict:
        accounts = self._read(self.ACCOUNTS_KEY, [])
        idx = next((i for i, a in enumerate(accounts) if a.get("id") == account.get("id")), None)
        if idx is not None:
            accounts[idx] = account
        else:
            accounts.append(account)
        self._write(self.ACCOUNTS_KEY, accounts)
        return account

    def delete_account(self, account_id: str, workspace_id: Optional[str] = None) -> bool:
        accounts = self._read(self.ACCOUNTS_KEY, [])
        new_list = [
            a for a in accounts
            if not (a.get("id") == account_id and
                    (workspace_id is None or a.get("workspace_id") == workspace_id))
        ]
        if len(new_list) == len(accounts):
            return False
        self._write(self.ACCOUNTS_KEY, new_list)
        return True

    # ── Organization scan records (S3) ───────────────────────────────────────

    ORG_CONNECTIONS_KEY = "eol/org_connections.json"
    ORG_ACCOUNTS_KEY    = "eol/org_accounts.json"
    ORG_SCAN_RUNS_KEY   = "eol/org_scan_runs.json"

    def get_org_connections(self, workspace_id: str) -> list:
        return [r for r in self._read(self.ORG_CONNECTIONS_KEY, []) if _workspace_id_camel(r) == workspace_id]

    def get_org_connection(self, workspace_id: str, conn_id: str) -> Optional[dict]:
        return next((r for r in self.get_org_connections(workspace_id) if r.get("id") == conn_id), None)

    def save_org_connection(self, conn: dict) -> dict:
        records = self._read(self.ORG_CONNECTIONS_KEY, [])
        idx = next((i for i, r in enumerate(records) if r.get("id") == conn.get("id")), None)
        if idx is not None:
            records[idx] = conn
        else:
            records.append(conn)
        self._write(self.ORG_CONNECTIONS_KEY, records)
        return conn

    def delete_org_connection(self, workspace_id: str, conn_id: str) -> bool:
        records = self._read(self.ORG_CONNECTIONS_KEY, [])
        new_records = [r for r in records if not (r.get("id") == conn_id and _workspace_id_camel(r) == workspace_id)]
        if len(new_records) == len(records):
            return False
        self._write(self.ORG_CONNECTIONS_KEY, new_records)
        return True

    def get_org_accounts(self, workspace_id: str, conn_id: Optional[str] = None) -> list:
        records = [r for r in self._read(self.ORG_ACCOUNTS_KEY, []) if _workspace_id_camel(r) == workspace_id]
        if conn_id:
            records = [r for r in records if _org_connection_id(r) == conn_id]
        return records

    def save_org_account(self, account: dict) -> dict:
        records = self._read(self.ORG_ACCOUNTS_KEY, [])
        idx = next((i for i, r in enumerate(records) if r.get("id") == account.get("id")), None)
        if idx is not None:
            records[idx] = account
        else:
            records.append(account)
        self._write(self.ORG_ACCOUNTS_KEY, records)
        return account

    def save_org_scan_run(self, run: dict) -> dict:
        records = self._read(self.ORG_SCAN_RUNS_KEY, [])
        idx = next((i for i, r in enumerate(records) if r.get("id") == run.get("id")), None)
        if idx is not None:
            records[idx] = run
        else:
            records.insert(0, run)
        self._write(self.ORG_SCAN_RUNS_KEY, records[:500])
        return run

    def get_org_scan_run(self, workspace_id: str, scan_id: str) -> Optional[dict]:
        return next((r for r in self._read(self.ORG_SCAN_RUNS_KEY, [])
                     if r.get("id") == scan_id and _workspace_id_camel(r) == workspace_id), None)

    def get_org_scan_runs(self, workspace_id: str, conn_id: Optional[str] = None, limit: int = 20) -> list:
        records = [r for r in self._read(self.ORG_SCAN_RUNS_KEY, []) if _workspace_id_camel(r) == workspace_id]
        if conn_id:
            records = [r for r in records if _org_connection_id(r) == conn_id]
        return records[:limit]

    def get_running_org_scan(self, workspace_id: str, conn_id: str) -> Optional[dict]:
        return next(
            (r for r in self._read(self.ORG_SCAN_RUNS_KEY, [])
             if _workspace_id_camel(r) == workspace_id
             and _org_connection_id(r) == conn_id
             and r.get("status") == "RUNNING"),
            None)

    def cleanup_stale_org_scans(self, workspace_id: str, timeout_minutes: int = 30) -> int:
        records = self._read(self.ORG_SCAN_RUNS_KEY, [])
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
        changed = 0
        for r in records:
            if (_workspace_id_camel(r) == workspace_id
                    and r.get("status") == "RUNNING"
                    and (r.get("startedAt") or "") < cutoff):
                r["status"] = "FAILED"
                r["completedAt"] = datetime.now(timezone.utc).isoformat()
                r["errorCode"] = "STALE_ORG_SCAN_TIMEOUT"
                r["error"] = "STALE_ORG_SCAN_TIMEOUT"
                changed += 1
        if changed:
            self._write(self.ORG_SCAN_RUNS_KEY, records[:500])
        return changed

    # ── Scan runs (S3) ────────────────────────────────────────────────────────

    RUNS_KEY = "eol/scan_runs.json"

    def save_scan_run(self, run: dict) -> dict:
        runs = self._read(self.RUNS_KEY, [])
        idx  = next((i for i, r in enumerate(runs) if r.get("scanId") == run.get("scanId")), None)
        if idx is not None:
            runs[idx] = run
        else:
            runs.insert(0, run)
        self._write(self.RUNS_KEY, runs[:200])
        return run

    def get_scan_run(self, scan_id: str) -> Optional[dict]:
        return next((r for r in self._read(self.RUNS_KEY, []) if r.get("scanId") == scan_id), None)

    def get_scan_runs(self, workspace_id: str, account_id: Optional[str] = None, limit: int = 20) -> list:
        runs = [r for r in self._read(self.RUNS_KEY, []) if r.get("workspaceId") == workspace_id]
        if account_id:
            runs = [r for r in runs if r.get("accountId") == account_id]
        return runs[:limit]

    def get_all_scan_runs_admin(self, workspace_id: Optional[str] = None,
                                status: Optional[str] = None, search: Optional[str] = None,
                                limit: int = 100, offset: int = 0) -> dict:
        runs = self._read(self.RUNS_KEY, [])
        if workspace_id:
            runs = [r for r in runs if r.get("workspaceId") == workspace_id]
        if status:
            runs = [r for r in runs if r.get("status") == status]
        if search:
            q = search.lower()
            runs = [r for r in runs if
                    q in (r.get("workspaceId") or "").lower() or
                    q in (r.get("accountId") or "").lower()]
        runs.sort(key=lambda r: r.get("startedAt") or "", reverse=True)
        total = len(runs)
        return {"runs": runs[offset:offset + limit], "total": total}

    def get_running_scan(self, workspace_id: str, account_id: str) -> Optional[dict]:
        return next(
            (r for r in self._read(self.RUNS_KEY, [])
             if r.get("workspaceId") == workspace_id
             and r.get("accountId") == account_id
             and r.get("status") == "RUNNING"),
            None)

    def cleanup_stale_scans(self, workspace_id: str, timeout_minutes: int = 30) -> int:
        runs   = self._read(self.RUNS_KEY, [])
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
        changed = 0
        for r in runs:
            if (r.get("workspaceId") == workspace_id
                    and r.get("status") == "RUNNING"
                    and (r.get("startedAt") or "") < cutoff):
                r["status"]      = "FAILED"
                r["completedAt"] = datetime.now(timezone.utc).isoformat()
                r["error"]       = "STALE_SCAN_TIMEOUT"
                changed += 1
        if changed:
            self._write(self.RUNS_KEY, runs)
        return changed

    def find_alert_by_resource(self, workspace_id: str, account_id: str,
                                resource_id: str, service: str) -> Optional[dict]:
        return next(
            (a for a in self._read(self.ALERTS_KEY, [])
             if a.get("workspaceId") == workspace_id
             and a.get("accountId") == account_id
             and a.get("resourceId") == resource_id
             and a.get("service") == service
             and a.get("status") != "RESOLVED"),
            None)

    # ── Alerts (S3) ───────────────────────────────────────────────────────────

    ALERTS_KEY = "eol/alerts.json"

    def save_alert(self, alert: dict) -> dict:
        alerts = self._read(self.ALERTS_KEY, [])
        idx    = next((i for i, a in enumerate(alerts) if a.get("id") == alert.get("id")), None)
        if idx is not None:
            alerts[idx] = alert
        else:
            alerts.insert(0, alert)
        self._write(self.ALERTS_KEY, alerts[:2000])
        return alert

    def get_alerts(self, workspace_id: str, account_id: Optional[str] = None,
                   status: Optional[str] = None, limit: int = 200) -> list:
        alerts = [a for a in self._read(self.ALERTS_KEY, []) if a.get("workspaceId") == workspace_id]
        if account_id:
            alerts = [a for a in alerts if a.get("accountId") == account_id]
        if status:
            alerts = [a for a in alerts if a.get("status") == status]
        return alerts[:limit]

    def get_alert(self, alert_id: str, workspace_id: str) -> Optional[dict]:
        return next((a for a in self._read(self.ALERTS_KEY, [])
                     if a.get("id") == alert_id and a.get("workspaceId") == workspace_id), None)

    # ── Notification settings (S3) ────────────────────────────────────────────

    NOTIF_SETTINGS_KEY = "eol/notification_settings.json"
    NOTIF_LOGS_KEY     = "eol/notification_logs.json"

    def get_notification_settings(self, workspace_id: str) -> dict:
        all_settings = self._read(self.NOTIF_SETTINGS_KEY, {})
        return all_settings.get(workspace_id, {})

    def save_notification_settings(self, workspace_id: str, settings: dict) -> dict:
        all_settings = self._read(self.NOTIF_SETTINGS_KEY, {})
        all_settings[workspace_id] = settings
        self._write(self.NOTIF_SETTINGS_KEY, all_settings)
        return settings

    def get_notification_logs(self, workspace_id: str, limit: int = 50) -> list:
        logs = [l for l in self._read(self.NOTIF_LOGS_KEY, [])
                if l.get("workspaceId") == workspace_id]
        return logs[:limit]

    def save_notification_log(self, log: dict) -> dict:
        logs = self._read(self.NOTIF_LOGS_KEY, [])
        logs.insert(0, log)
        self._write(self.NOTIF_LOGS_KEY, logs[:500])
        return log

    # ── API tokens (S3) ──────────────────────────────────────────────────────

    API_TOKENS_KEY = "eol/api_tokens.json"
    AUDIT_LOGS_KEY = "eol/audit_logs.json"

    def get_api_tokens(self, workspace_id: str) -> list:
        return self._read(self.API_TOKENS_KEY, {}).get(workspace_id, [])

    def save_api_token(self, token: dict) -> dict:
        ws_id   = token["workspaceId"]
        all_tok = self._read(self.API_TOKENS_KEY, {})
        tokens  = all_tok.get(ws_id, [])
        idx     = next((i for i, t in enumerate(tokens) if t.get("id") == token.get("id")), None)
        if idx is not None:
            tokens[idx] = token
        else:
            tokens.append(token)
        all_tok[ws_id] = tokens
        self._write(self.API_TOKENS_KEY, all_tok)
        return token

    def get_api_token_by_id(self, token_id: str, workspace_id: str) -> Optional[dict]:
        return next((t for t in self.get_api_tokens(workspace_id)
                     if t.get("id") == token_id), None)

    def find_api_token_by_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        return next((t for t in self.get_api_tokens(workspace_id)
                     if t.get("tokenHash") == token_hash), None)

    # ── Audit logs (S3) ──────────────────────────────────────────────────────

    def save_audit_log(self, log: dict) -> dict:
        all_logs = self._read(self.AUDIT_LOGS_KEY, {})
        ws_id    = log.get("workspaceId", "")
        ws_logs  = all_logs.get(ws_id, [])
        ws_logs.insert(0, log)
        all_logs[ws_id] = ws_logs[:1000]
        self._write(self.AUDIT_LOGS_KEY, all_logs)
        return log

    def get_audit_logs(self, workspace_id: str, limit: int = 50) -> list:
        return self._read(self.AUDIT_LOGS_KEY, {}).get(workspace_id, [])[:limit]

    # ── Report snapshots (S3) ────────────────────────────────────────────────

    REPORTS_KEY = "eol/reports.json"

    def save_report_snapshot(self, snapshot: dict) -> dict:
        snapshots = [s for s in self._read(self.REPORTS_KEY, []) if s.get("id") != snapshot.get("id")]
        snapshots.insert(0, snapshot)
        ws_id = snapshot.get("workspaceId", "")
        scoped = [s for s in snapshots if s.get("workspaceId") == ws_id][:500]
        other = [s for s in snapshots if s.get("workspaceId") != ws_id]
        self._write(self.REPORTS_KEY, scoped + other)
        return snapshot

    def get_report_snapshots(self, workspace_id: str, limit: int = 50) -> list:
        return [s for s in self._read(self.REPORTS_KEY, []) if s.get("workspaceId") == workspace_id][:limit]

    def get_report_snapshot(self, workspace_id: str, report_id: str) -> Optional[dict]:
        return next((s for s in self._read(self.REPORTS_KEY, [])
                     if s.get("workspaceId") == workspace_id and s.get("id") == report_id), None)

    # ── Members (S3) ──────────────────────────────────────────────────────────

    MEMBERS_KEY       = "eol/members.json"
    MEMBER_SESS_KEY   = "eol/member_sessions.json"
    MEMBER_LOGIN_KEY  = "eol/member_login_tokens.json"

    def get_members(self, workspace_id: str) -> list:
        return self._read(self.MEMBERS_KEY, {}).get(workspace_id, [])

    def get_member_by_id(self, member_id: str, workspace_id: str) -> Optional[dict]:
        return next((m for m in self.get_members(workspace_id) if m.get("id") == member_id), None)

    def find_member_by_invite_token_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        return next((m for m in self.get_members(workspace_id) if m.get("inviteTokenHash") == token_hash), None)

    def save_member(self, member: dict) -> dict:
        ws_id    = member["workspaceId"]
        all_data = self._read(self.MEMBERS_KEY, {})
        members  = all_data.get(ws_id, [])
        idx      = next((i for i, m in enumerate(members) if m.get("id") == member.get("id")), None)
        if idx is not None:
            members[idx] = member
        else:
            members.append(member)
        all_data[ws_id] = members
        self._write(self.MEMBERS_KEY, all_data)
        return member

    def delete_member(self, member_id: str, workspace_id: str) -> bool:
        all_data = self._read(self.MEMBERS_KEY, {})
        members  = all_data.get(workspace_id, [])
        new_list = [m for m in members if m.get("id") != member_id]
        if len(new_list) == len(members):
            return False
        all_data[workspace_id] = new_list
        self._write(self.MEMBERS_KEY, all_data)
        return True

    def find_member_session_by_token_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        sessions = self._read(self.MEMBER_SESS_KEY, {}).get(workspace_id, [])
        return next((s for s in sessions if s.get("tokenHash") == token_hash), None)

    def save_member_session(self, session: dict) -> dict:
        ws_id    = session["workspaceId"]
        all_data = self._read(self.MEMBER_SESS_KEY, {})
        sessions = all_data.get(ws_id, [])
        idx      = next((i for i, s in enumerate(sessions) if s.get("id") == session.get("id")), None)
        if idx is not None:
            sessions[idx] = session
        else:
            sessions.append(session)
        all_data[ws_id] = sessions
        self._write(self.MEMBER_SESS_KEY, all_data)
        return session

    def revoke_member_sessions(self, member_id: str, workspace_id: str) -> int:
        all_data = self._read(self.MEMBER_SESS_KEY, {})
        sessions = all_data.get(workspace_id, [])
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for s in sessions:
            if s.get("memberId") == member_id and not s.get("revokedAt"):
                s["revokedAt"] = now
                count += 1
        if count:
            all_data[workspace_id] = sessions
            self._write(self.MEMBER_SESS_KEY, all_data)
        return count

    def find_member_login_token_by_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        tokens = self._read(self.MEMBER_LOGIN_KEY, {}).get(workspace_id, [])
        return next((t for t in tokens if t.get("tokenHash") == token_hash), None)

    def get_member_login_tokens_for_member(self, member_id: str, workspace_id: str) -> list:
        tokens = self._read(self.MEMBER_LOGIN_KEY, {}).get(workspace_id, [])
        return [t for t in tokens if t.get("memberId") == member_id]

    def save_member_login_token(self, token: dict) -> dict:
        ws_id    = token["workspaceId"]
        all_data = self._read(self.MEMBER_LOGIN_KEY, {})
        tokens   = all_data.get(ws_id, [])
        idx      = next((i for i, t in enumerate(tokens) if t.get("id") == token.get("id")), None)
        if idx is not None:
            tokens[idx] = token
        else:
            tokens.append(token)
        all_data[ws_id] = tokens
        self._write(self.MEMBER_LOGIN_KEY, all_data)
        return token


    auth_run   = _auth_not_supported
    auth_query = _auth_not_supported
    auth_one   = _auth_not_supported


# ── File Backend ──────────────────────────────────────────────────────────────

class FileBackend:
    """Local JSON files — zero AWS required. Useful for development and CI."""

    def __init__(self):
        os.makedirs(EOL_DATA_DIR, exist_ok=True)
        self._inv_path           = os.path.join(EOL_DATA_DIR, "inventory.json")
        self._cfg_path           = os.path.join(EOL_DATA_DIR, "config.json")
        self._acct_path          = os.path.join(EOL_DATA_DIR, "accounts.json")
        self._ws_path            = os.path.join(EOL_DATA_DIR, "workspaces.json")
        self._runs_path          = os.path.join(EOL_DATA_DIR, "scan_runs.json")
        self._alerts_path        = os.path.join(EOL_DATA_DIR, "alerts.json")
        self._guides_path        = os.path.join(EOL_DATA_DIR, "upgrade_guides.json")
        self._notif_settings_path = os.path.join(EOL_DATA_DIR, "notification_settings.json")
        self._notif_logs_path    = os.path.join(EOL_DATA_DIR, "notification_logs.json")
        self._reports_path       = os.path.join(EOL_DATA_DIR, "reports.json")
        self._api_tokens_path    = os.path.join(EOL_DATA_DIR, "api_tokens.json")
        self._audit_logs_path    = os.path.join(EOL_DATA_DIR, "audit_logs.json")
        self._members_path           = os.path.join(EOL_DATA_DIR, "members.json")
        self._member_sessions_path   = os.path.join(EOL_DATA_DIR, "member_sessions.json")
        self._member_login_tok_path  = os.path.join(EOL_DATA_DIR, "member_login_tokens.json")
        self._org_connections_path   = os.path.join(EOL_DATA_DIR, "org_connections.json")
        self._org_accounts_path      = os.path.join(EOL_DATA_DIR, "org_accounts.json")
        self._org_scan_runs_path     = os.path.join(EOL_DATA_DIR, "org_scan_runs.json")
        self._eol_overrides_path          = os.path.join(EOL_DATA_DIR, "eol_overrides.json")
        self._verified_lifecycle_path     = os.path.join(EOL_DATA_DIR, "eol_verified_lifecycle.json")

    def _read(self, path: str, default: Any = None) -> Any:
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def _write(self, path: str, data: Any) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=_serial)
        os.replace(tmp, path)  # atomic on POSIX — safe against mid-write kill

    def save_resources(self, resources: list) -> int:
        def _key(r: dict) -> str:
            # workspace_id prefix isolates each workspace's inventory on disk
            return f"{r.get('workspace_id','')}#{r['resource_id']}#{r['service_type']}"

        existing = {_key(r): r for r in self._read(self._inv_path, [])}
        scanned_at = datetime.now(timezone.utc).isoformat()
        for r in resources:
            r = dict(r)
            r["scanned_at"] = scanned_at
            existing[_key(r)] = r
        self._write(self._inv_path, list(existing.values()))
        return len(resources)

    def replace_resources_for_account(self, workspace_id: str, account_id: str,
                                       resources: list, scan_started_at: Optional[str] = None) -> int:
        import fcntl
        lock_path = self._inv_path + ".lock"
        with open(lock_path, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                all_inv = self._read(self._inv_path, [])
                # Stale-write guard inside lock so read is consistent with other writers
                if scan_started_at:
                    acct_recs = [r for r in all_inv
                                 if _workspace_id(r) == workspace_id and _account_id(r) == account_id]
                    if acct_recs:
                        newest = max((r.get("scan_started_at") or "" for r in acct_recs), default="")
                        if newest and newest > scan_started_at:
                            logger.warning("Stale write skipped account=%s existing=%s current=%s",
                                           account_id, newest, scan_started_at)
                            return 0
                existing = [r for r in all_inv
                            if not (_workspace_id(r) == workspace_id and _account_id(r) == account_id)]
                existing.extend(_stamp_resources(resources, scan_started_at=scan_started_at))
                self._write(self._inv_path, existing)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
        return len(resources)

    def get_resources(self, filters: Optional[dict] = None) -> list:
        items = self._read(self._inv_path, [])
        if not filters:
            return items
        if filters.get("workspace_id"):
            items = [i for i in items if i.get("workspace_id") == filters["workspace_id"]]
        if filters.get("status"):
            items = [i for i in items if i.get("eol_status") == filters["status"].upper()]
        if filters.get("service"):
            q = filters["service"].lower()
            items = [i for i in items if q in i.get("service_type", "").lower()]
        if filters.get("region"):
            items = [i for i in items if filters["region"] in i.get("region", "")]
        if filters.get("account_id"):
            aid = filters["account_id"]
            items = [i for i in items if i.get("account_id") == aid or i.get("accountId") == aid]
        return items

    def get_resource_by_id(self, resource_id: str, workspace_id: Optional[str] = None) -> Optional[dict]:
        items = self._read(self._inv_path, [])
        return next(
            (i for i in items
             if i.get("resource_id") == resource_id
             and (not workspace_id or i.get("workspace_id") == workspace_id)),
            None)

    def get_config(self) -> dict:
        return _merge_config(self._read(self._cfg_path, {}))

    def save_config(self, config: dict) -> None:
        config = dict(config)
        config["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write(self._cfg_path, config)

    def get_workspace_config(self, workspace_id: str) -> dict:
        path = os.path.join(EOL_DATA_DIR, "workspace_config.json")
        configs = self._read(path, {})
        return _merge_config(configs.get(workspace_id, {}))

    def save_workspace_config(self, workspace_id: str, config: dict) -> dict:
        path = os.path.join(EOL_DATA_DIR, "workspace_config.json")
        configs = self._read(path, {})
        merged = _merge_config(config)
        merged["updated_at"] = datetime.now(timezone.utc).isoformat()
        configs[workspace_id] = merged
        self._write(path, configs)
        return merged

    def get_general_eol_cache(self) -> Optional[dict]:
        path = os.path.join(EOL_DATA_DIR, "general_eol_cache.json")
        return self._read(path, None)

    def save_general_eol_cache(self, records: list, refreshed_at: str, expires_at: str) -> None:
        path = os.path.join(EOL_DATA_DIR, "general_eol_cache.json")
        self._write(path, {"records": records, "refreshed_at": refreshed_at, "expires_at": expires_at})

    # ── EOL overrides (File) ──────────────────────────────────────────────────

    def list_eol_overrides(self) -> list:
        return self._read(self._eol_overrides_path, [])

    def get_eol_override(self, product: str, version: str) -> Optional[dict]:
        overrides = self.list_eol_overrides()
        return next((o for o in overrides if o.get("product") == product and o.get("version") == version), None)

    def save_eol_override(self, product: str, version: str, record: dict) -> dict:
        overrides = self.list_eol_overrides()
        idx = next((i for i, o in enumerate(overrides)
                    if o.get("product") == product and o.get("version") == version), None)
        record = {**record, "product": product, "version": version,
                  "updatedAt": datetime.now(timezone.utc).isoformat()}
        if idx is not None:
            overrides[idx] = record
        else:
            overrides.append(record)
        self._write(self._eol_overrides_path, overrides)
        return record

    def delete_eol_override(self, product: str, version: str) -> bool:
        overrides = self.list_eol_overrides()
        new_list = [o for o in overrides if not (o.get("product") == product and o.get("version") == version)]
        if len(new_list) == len(overrides):
            return False
        self._write(self._eol_overrides_path, new_list)
        return True

    # ── Verified lifecycle (File) ─────────────────────────────────────────────

    def list_verified_lifecycle(self) -> list:
        return self._read(self._verified_lifecycle_path, [])

    def get_verified_lifecycle(self, product: str, version: str) -> Optional[dict]:
        return next((r for r in self.list_verified_lifecycle()
                     if r.get("product") == product and r.get("version") == version), None)

    def save_verified_lifecycle(self, product: str, version: str, record: dict) -> dict:
        records = self.list_verified_lifecycle()
        idx = next((i for i, r in enumerate(records)
                    if r.get("product") == product and r.get("version") == version), None)
        now = datetime.now(timezone.utc).isoformat()
        record = {**record, "product": product, "version": version,
                  "updatedAt": now, "createdAt": record.get("createdAt", now)}
        if idx is not None:
            records[idx] = record
        else:
            records.append(record)
        self._write(self._verified_lifecycle_path, records)
        return record

    def delete_verified_lifecycle(self, product: str, version: str) -> bool:
        records = self.list_verified_lifecycle()
        new_list = [r for r in records if not (r.get("product") == product and r.get("version") == version)]
        if len(new_list) == len(records):
            return False
        self._write(self._verified_lifecycle_path, new_list)
        return True

    # ── Upgrade guides (File) ─────────────────────────────────────────────────

    def get_upgrade_guides(self) -> list:
        return self._read(self._guides_path, [])

    def save_upgrade_guide(self, guide: dict) -> dict:
        guides = self.get_upgrade_guides()
        idx = next((i for i, g in enumerate(guides) if g.get("id") == guide.get("id")), None)
        if idx is not None:
            guides[idx] = guide
        else:
            guides.append(guide)
        self._write(self._guides_path, guides)
        return guide

    def delete_upgrade_guide(self, guide_id: str) -> bool:
        guides = self.get_upgrade_guides()
        new_list = [g for g in guides if g.get("id") != guide_id]
        if len(new_list) == len(guides):
            return False
        self._write(self._guides_path, new_list)
        return True

    # ── Notification settings (File) ──────────────────────────────────────────

    def get_notification_settings(self, workspace_id: str) -> dict:
        return self._read(self._notif_settings_path, {}).get(workspace_id, {})

    def save_notification_settings(self, workspace_id: str, settings: dict) -> dict:
        all_settings = self._read(self._notif_settings_path, {})
        all_settings[workspace_id] = settings
        self._write(self._notif_settings_path, all_settings)
        return settings

    def get_notification_logs(self, workspace_id: str, limit: int = 50) -> list:
        logs = [l for l in self._read(self._notif_logs_path, [])
                if l.get("workspaceId") == workspace_id]
        return logs[:limit]

    def save_notification_log(self, log: dict) -> dict:
        logs = self._read(self._notif_logs_path, [])
        logs.insert(0, log)
        self._write(self._notif_logs_path, logs[:500])
        return log

    # ── API tokens (File) ─────────────────────────────────────────────────────

    def get_api_tokens(self, workspace_id: str) -> list:
        return self._read(self._api_tokens_path, {}).get(workspace_id, [])

    def save_api_token(self, token: dict) -> dict:
        ws_id   = token["workspaceId"]
        all_tok = self._read(self._api_tokens_path, {})
        tokens  = all_tok.get(ws_id, [])
        idx     = next((i for i, t in enumerate(tokens) if t.get("id") == token.get("id")), None)
        if idx is not None:
            tokens[idx] = token
        else:
            tokens.append(token)
        all_tok[ws_id] = tokens
        self._write(self._api_tokens_path, all_tok)
        return token

    def get_api_token_by_id(self, token_id: str, workspace_id: str) -> Optional[dict]:
        return next((t for t in self.get_api_tokens(workspace_id)
                     if t.get("id") == token_id), None)

    def find_api_token_by_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        return next((t for t in self.get_api_tokens(workspace_id)
                     if t.get("tokenHash") == token_hash), None)

    # ── Audit logs (File) ─────────────────────────────────────────────────────

    def save_audit_log(self, log: dict) -> dict:
        all_logs = self._read(self._audit_logs_path, {})
        ws_id    = log.get("workspaceId", "")
        ws_logs  = all_logs.get(ws_id, [])
        ws_logs.insert(0, log)
        all_logs[ws_id] = ws_logs[:1000]
        self._write(self._audit_logs_path, all_logs)
        return log

    def get_audit_logs(self, workspace_id: str, limit: int = 50) -> list:
        return self._read(self._audit_logs_path, {}).get(workspace_id, [])[:limit]

    # ── Report snapshots (File) ──────────────────────────────────────────────

    def save_report_snapshot(self, snapshot: dict) -> dict:
        snapshots = [s for s in self._read(self._reports_path, []) if s.get("id") != snapshot.get("id")]
        snapshots.insert(0, snapshot)
        ws_id = snapshot.get("workspaceId", "")
        scoped = [s for s in snapshots if s.get("workspaceId") == ws_id][:500]
        other = [s for s in snapshots if s.get("workspaceId") != ws_id]
        self._write(self._reports_path, scoped + other)
        return snapshot

    def get_report_snapshots(self, workspace_id: str, limit: int = 50) -> list:
        return [s for s in self._read(self._reports_path, []) if s.get("workspaceId") == workspace_id][:limit]

    def get_report_snapshot(self, workspace_id: str, report_id: str) -> Optional[dict]:
        return next((s for s in self._read(self._reports_path, [])
                     if s.get("workspaceId") == workspace_id and s.get("id") == report_id), None)

    # ── Members (workspace-scoped) ────────────────────────────────────────────

    def get_members(self, workspace_id: str) -> list:
        return self._read(self._members_path, {}).get(workspace_id, [])

    def get_member_by_id(self, member_id: str, workspace_id: str) -> Optional[dict]:
        return next((m for m in self.get_members(workspace_id) if m.get("id") == member_id), None)

    def find_member_by_invite_token_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        return next(
            (m for m in self.get_members(workspace_id)
             if m.get("inviteTokenHash") == token_hash),
            None,
        )

    def save_member(self, member: dict) -> dict:
        ws_id    = member["workspaceId"]
        all_data = self._read(self._members_path, {})
        members  = all_data.get(ws_id, [])
        idx      = next((i for i, m in enumerate(members) if m.get("id") == member.get("id")), None)
        if idx is not None:
            members[idx] = member
        else:
            members.append(member)
        all_data[ws_id] = members
        self._write(self._members_path, all_data)
        return member

    def delete_member(self, member_id: str, workspace_id: str) -> bool:
        all_data = self._read(self._members_path, {})
        members  = all_data.get(workspace_id, [])
        new_list = [m for m in members if m.get("id") != member_id]
        if len(new_list) == len(members):
            return False
        all_data[workspace_id] = new_list
        self._write(self._members_path, all_data)
        return True

    # ── Member sessions ───────────────────────────────────────────────────────

    def find_member_session_by_token_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        sessions = self._read(self._member_sessions_path, {}).get(workspace_id, [])
        return next((s for s in sessions if s.get("tokenHash") == token_hash), None)

    def save_member_session(self, session: dict) -> dict:
        ws_id    = session["workspaceId"]
        all_data = self._read(self._member_sessions_path, {})
        sessions = all_data.get(ws_id, [])
        idx      = next((i for i, s in enumerate(sessions) if s.get("id") == session.get("id")), None)
        if idx is not None:
            sessions[idx] = session
        else:
            sessions.append(session)
        all_data[ws_id] = sessions
        self._write(self._member_sessions_path, all_data)
        return session

    def revoke_member_sessions(self, member_id: str, workspace_id: str) -> int:
        all_data = self._read(self._member_sessions_path, {})
        sessions = all_data.get(workspace_id, [])
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for s in sessions:
            if s.get("memberId") == member_id and not s.get("revokedAt"):
                s["revokedAt"] = now
                count += 1
        if count:
            all_data[workspace_id] = sessions
            self._write(self._member_sessions_path, all_data)
        return count

    # ── Member login tokens (magic-link, one-time use) ────────────────────────

    def find_member_login_token_by_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        tokens = self._read(self._member_login_tok_path, {}).get(workspace_id, [])
        return next((t for t in tokens if t.get("tokenHash") == token_hash), None)

    def get_member_login_tokens_for_member(self, member_id: str, workspace_id: str) -> list:
        tokens = self._read(self._member_login_tok_path, {}).get(workspace_id, [])
        return [t for t in tokens if t.get("memberId") == member_id]

    def save_member_login_token(self, token: dict) -> dict:
        ws_id    = token["workspaceId"]
        all_data = self._read(self._member_login_tok_path, {})
        tokens   = all_data.get(ws_id, [])
        idx      = next((i for i, t in enumerate(tokens) if t.get("id") == token.get("id")), None)
        if idx is not None:
            tokens[idx] = token
        else:
            tokens.append(token)
        all_data[ws_id] = tokens
        self._write(self._member_login_tok_path, all_data)
        return token

    # ── Workspaces ────────────────────────────────────────────────────────────

    def get_workspaces(self) -> list:
        return self._read(self._ws_path, [])

    def get_workspace(self, workspace_id: str) -> Optional[dict]:
        return next((w for w in self.get_workspaces() if w.get("id") == workspace_id), None)

    def save_workspace(self, workspace: dict) -> dict:
        workspaces = self.get_workspaces()
        idx = next((i for i, w in enumerate(workspaces) if w.get("id") == workspace.get("id")), None)
        if idx is not None:
            workspaces[idx] = workspace
        else:
            workspaces.append(workspace)
        self._write(self._ws_path, workspaces)
        return workspace

    def delete_workspace(self, workspace_id: str) -> bool:
        workspaces = self.get_workspaces()
        new_list   = [w for w in workspaces if w.get("id") != workspace_id]
        if len(new_list) == len(workspaces):
            return False
        self._write(self._ws_path, new_list)
        return True

    # ── Connected accounts (workspace-scoped) ─────────────────────────────────

    def get_accounts(self, workspace_id: Optional[str] = None) -> list:
        accounts = self._read(self._acct_path, [])
        if workspace_id:
            return [a for a in accounts if a.get("workspace_id") == workspace_id]
        return accounts

    def save_account(self, account: dict) -> dict:
        accounts = self._read(self._acct_path, [])
        idx = next((i for i, a in enumerate(accounts) if a.get("id") == account.get("id")), None)
        if idx is not None:
            accounts[idx] = account
        else:
            accounts.append(account)
        self._write(self._acct_path, accounts)
        return account

    def delete_account(self, account_id: str, workspace_id: Optional[str] = None) -> bool:
        accounts = self._read(self._acct_path, [])
        new_list = [
            a for a in accounts
            if not (a.get("id") == account_id and
                    (workspace_id is None or a.get("workspace_id") == workspace_id))
        ]
        if len(new_list) == len(accounts):
            return False
        self._write(self._acct_path, new_list)
        return True

    # ── Organization scan records (File) ─────────────────────────────────────

    def get_org_connections(self, workspace_id: str) -> list:
        return [r for r in self._read(self._org_connections_path, []) if _workspace_id_camel(r) == workspace_id]

    def get_org_connection(self, workspace_id: str, conn_id: str) -> Optional[dict]:
        return next((r for r in self.get_org_connections(workspace_id) if r.get("id") == conn_id), None)

    def save_org_connection(self, conn: dict) -> dict:
        records = self._read(self._org_connections_path, [])
        idx = next((i for i, r in enumerate(records) if r.get("id") == conn.get("id")), None)
        if idx is not None:
            records[idx] = conn
        else:
            records.append(conn)
        self._write(self._org_connections_path, records)
        return conn

    def delete_org_connection(self, workspace_id: str, conn_id: str) -> bool:
        records = self._read(self._org_connections_path, [])
        new_records = [r for r in records if not (r.get("id") == conn_id and _workspace_id_camel(r) == workspace_id)]
        if len(new_records) == len(records):
            return False
        self._write(self._org_connections_path, new_records)
        return True

    def get_org_accounts(self, workspace_id: str, conn_id: Optional[str] = None) -> list:
        records = [r for r in self._read(self._org_accounts_path, []) if _workspace_id_camel(r) == workspace_id]
        if conn_id:
            records = [r for r in records if _org_connection_id(r) == conn_id]
        return records

    def save_org_account(self, account: dict) -> dict:
        records = self._read(self._org_accounts_path, [])
        idx = next((i for i, r in enumerate(records) if r.get("id") == account.get("id")), None)
        if idx is not None:
            records[idx] = account
        else:
            records.append(account)
        self._write(self._org_accounts_path, records)
        return account

    def save_org_scan_run(self, run: dict) -> dict:
        records = self._read(self._org_scan_runs_path, [])
        idx = next((i for i, r in enumerate(records) if r.get("id") == run.get("id")), None)
        if idx is not None:
            records[idx] = run
        else:
            records.insert(0, run)
        self._write(self._org_scan_runs_path, records[:500])
        return run

    def get_org_scan_run(self, workspace_id: str, scan_id: str) -> Optional[dict]:
        return next((r for r in self._read(self._org_scan_runs_path, [])
                     if r.get("id") == scan_id and _workspace_id_camel(r) == workspace_id), None)

    def get_org_scan_runs(self, workspace_id: str, conn_id: Optional[str] = None, limit: int = 20) -> list:
        records = [r for r in self._read(self._org_scan_runs_path, []) if _workspace_id_camel(r) == workspace_id]
        if conn_id:
            records = [r for r in records if _org_connection_id(r) == conn_id]
        return records[:limit]

    def get_running_org_scan(self, workspace_id: str, conn_id: str) -> Optional[dict]:
        return next(
            (r for r in self._read(self._org_scan_runs_path, [])
             if _workspace_id_camel(r) == workspace_id
             and _org_connection_id(r) == conn_id
             and r.get("status") == "RUNNING"),
            None)

    def cleanup_stale_org_scans(self, workspace_id: str, timeout_minutes: int = 30) -> int:
        records = self._read(self._org_scan_runs_path, [])
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
        changed = 0
        for r in records:
            if (_workspace_id_camel(r) == workspace_id
                    and r.get("status") == "RUNNING"
                    and (r.get("startedAt") or "") < cutoff):
                r["status"] = "FAILED"
                r["completedAt"] = datetime.now(timezone.utc).isoformat()
                r["errorCode"] = "STALE_ORG_SCAN_TIMEOUT"
                r["error"] = "STALE_ORG_SCAN_TIMEOUT"
                changed += 1
        if changed:
            self._write(self._org_scan_runs_path, records[:500])
        return changed

    # ── Scan runs (File) ──────────────────────────────────────────────────────

    def save_scan_run(self, run: dict) -> dict:
        runs = self._read(self._runs_path, [])
        idx  = next((i for i, r in enumerate(runs) if r.get("scanId") == run.get("scanId")), None)
        if idx is not None:
            runs[idx] = run
        else:
            runs.insert(0, run)
        self._write(self._runs_path, runs[:200])
        return run

    def get_scan_run(self, scan_id: str) -> Optional[dict]:
        return next((r for r in self._read(self._runs_path, []) if r.get("scanId") == scan_id), None)

    def get_scan_runs(self, workspace_id: str, account_id: Optional[str] = None, limit: int = 20) -> list:
        runs = [r for r in self._read(self._runs_path, []) if r.get("workspaceId") == workspace_id]
        if account_id:
            runs = [r for r in runs if r.get("accountId") == account_id]
        return runs[:limit]

    def get_all_scan_runs_admin(self, workspace_id: Optional[str] = None,
                                status: Optional[str] = None, search: Optional[str] = None,
                                limit: int = 100, offset: int = 0) -> dict:
        runs = self._read(self._runs_path, [])
        if workspace_id:
            runs = [r for r in runs if r.get("workspaceId") == workspace_id]
        if status:
            runs = [r for r in runs if r.get("status") == status]
        if search:
            q = search.lower()
            runs = [r for r in runs if
                    q in (r.get("workspaceId") or "").lower() or
                    q in (r.get("accountId") or "").lower()]
        runs.sort(key=lambda r: r.get("startedAt") or "", reverse=True)
        total = len(runs)
        return {"runs": runs[offset:offset + limit], "total": total}

    def get_running_scan(self, workspace_id: str, account_id: str) -> Optional[dict]:
        return next(
            (r for r in self._read(self._runs_path, [])
             if r.get("workspaceId") == workspace_id
             and r.get("accountId") == account_id
             and r.get("status") == "RUNNING"),
            None)

    def cleanup_stale_scans(self, workspace_id: str, timeout_minutes: int = 30) -> int:
        runs   = self._read(self._runs_path, [])
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
        changed = 0
        for r in runs:
            if (r.get("workspaceId") == workspace_id
                    and r.get("status") == "RUNNING"
                    and (r.get("startedAt") or "") < cutoff):
                r["status"]      = "FAILED"
                r["completedAt"] = datetime.now(timezone.utc).isoformat()
                r["error"]       = "STALE_SCAN_TIMEOUT"
                changed += 1
        if changed:
            self._write(self._runs_path, runs)
        return changed

    def find_alert_by_resource(self, workspace_id: str, account_id: str,
                                resource_id: str, service: str) -> Optional[dict]:
        return next(
            (a for a in self._read(self._alerts_path, [])
             if a.get("workspaceId") == workspace_id
             and a.get("accountId") == account_id
             and a.get("resourceId") == resource_id
             and a.get("service") == service
             and a.get("status") != "RESOLVED"),
            None)

    # ── Alerts (File) ─────────────────────────────────────────────────────────

    def save_alert(self, alert: dict) -> dict:
        alerts = self._read(self._alerts_path, [])
        idx    = next((i for i, a in enumerate(alerts) if a.get("id") == alert.get("id")), None)
        if idx is not None:
            alerts[idx] = alert
        else:
            alerts.insert(0, alert)
        self._write(self._alerts_path, alerts[:2000])
        return alert

    def get_alerts(self, workspace_id: str, account_id: Optional[str] = None,
                   status: Optional[str] = None, limit: int = 200) -> list:
        alerts = [a for a in self._read(self._alerts_path, []) if a.get("workspaceId") == workspace_id]
        if account_id:
            alerts = [a for a in alerts if a.get("accountId") == account_id]
        if status:
            alerts = [a for a in alerts if a.get("status") == status]
        return alerts[:limit]

    def get_alert(self, alert_id: str, workspace_id: str) -> Optional[dict]:
        return next((a for a in self._read(self._alerts_path, [])
                     if a.get("id") == alert_id and a.get("workspaceId") == workspace_id), None)

    auth_run   = _auth_not_supported
    auth_query = _auth_not_supported
    auth_one   = _auth_not_supported


# ── PostgreSQL Backend ────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")


class PostgresBackend:
    """
    PostgreSQL storage backend.
    Requires: pip install psycopg2-binary
    Configured via DATABASE_URL environment variable.
    Schema created by: python3 backend/scripts/setup_postgres.py
    """

    def __init__(self, database_url: str):
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            raise ImportError(
                "psycopg2-binary is required for STORAGE_BACKEND=postgres. "
                "Run: pip install psycopg2-binary"
            )
        self._pg     = psycopg2
        self._extras = psycopg2.extras
        self._url    = database_url
        self._conn: Any = None

    # ── Connection helpers ─────────────────────────────────────────────────────

    def _connect(self):
        conn = self._pg.connect(self._url)
        conn.autocommit = False
        return conn

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = self._connect()
        return self._conn

    def _run(self, sql: str, params=None) -> int:
        """Execute DML (INSERT/UPDATE/DELETE). Returns rowcount."""
        for attempt in range(2):
            conn = self._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rc = cur.rowcount
                conn.commit()
                return rc
            except self._pg.OperationalError:
                conn.rollback()
                self._conn = None
                if attempt:
                    raise
            except Exception:
                conn.rollback()
                raise
        return 0

    def _query(self, sql: str, params=None) -> list:
        """SELECT query → list of dicts."""
        for attempt in range(2):
            conn = self._get_conn()
            try:
                with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                    cur.execute(sql, params)
                    return [dict(r) for r in cur.fetchall()]
            except self._pg.OperationalError:
                conn.rollback()
                self._conn = None
                if attempt:
                    raise
            except Exception:
                conn.rollback()
                raise
        return []

    def _one(self, sql: str, params=None) -> Optional[dict]:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    def _j(self, d: Any) -> Any:
        return self._extras.Json(d)

    def _p(self, row: Optional[dict], key: str = "payload") -> Optional[dict]:
        if row is None:
            return None
        val = row.get(key)
        if val is None:
            return None
        if isinstance(val, (str, bytes)):
            return json.loads(val)
        return dict(val)

    # ── Workspaces ─────────────────────────────────────────────────────────────

    def get_workspaces(self) -> list:
        rows = self._query("SELECT payload FROM workspaces ORDER BY id")
        return [self._p(r) for r in rows]

    def get_workspace(self, workspace_id: str) -> Optional[dict]:
        row = self._one("SELECT payload FROM workspaces WHERE id = %s", (workspace_id,))
        return self._p(row)

    def save_workspace(self, workspace: dict) -> dict:
        self._run("""
            INSERT INTO workspaces (id, name, token_hash, payload)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                token_hash = EXCLUDED.token_hash,
                payload = EXCLUDED.payload
        """, (workspace.get("id", ""), workspace.get("name", ""),
              workspace.get("token_hash", ""), self._j(workspace)))
        return workspace

    def delete_workspace(self, workspace_id: str) -> bool:
        return self._run("DELETE FROM workspaces WHERE id = %s", (workspace_id,)) > 0

    # ── Connected accounts ─────────────────────────────────────────────────────

    def get_accounts(self, workspace_id: Optional[str] = None) -> list:
        if workspace_id:
            rows = self._query(
                "SELECT payload FROM connected_accounts WHERE workspace_id = %s", (workspace_id,))
        else:
            rows = self._query("SELECT payload FROM connected_accounts")
        return [self._p(r) for r in rows]

    def save_account(self, account: dict) -> dict:
        self._run("""
            INSERT INTO connected_accounts (id, workspace_id, payload)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                workspace_id = EXCLUDED.workspace_id,
                payload = EXCLUDED.payload
        """, (account.get("id", ""), account.get("workspace_id", ""), self._j(account)))
        return account

    def delete_account(self, account_id: str, workspace_id: Optional[str] = None) -> bool:
        if workspace_id:
            return self._run(
                "DELETE FROM connected_accounts WHERE id = %s AND workspace_id = %s",
                (account_id, workspace_id)) > 0
        return self._run("DELETE FROM connected_accounts WHERE id = %s", (account_id,)) > 0

    # ── Organization scan records ─────────────────────────────────────────────

    def get_org_connections(self, workspace_id: str) -> list:
        rows = self._query(
            "SELECT payload FROM org_connections WHERE workspace_id = %s ORDER BY id",
            (workspace_id,))
        return [self._p(r) for r in rows]

    def get_org_connection(self, workspace_id: str, conn_id: str) -> Optional[dict]:
        row = self._one(
            "SELECT payload FROM org_connections WHERE id = %s AND workspace_id = %s",
            (conn_id, workspace_id))
        return self._p(row)

    def save_org_connection(self, conn: dict) -> dict:
        self._run("""
            INSERT INTO org_connections (id, workspace_id, status, payload)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                workspace_id = EXCLUDED.workspace_id,
                status = EXCLUDED.status,
                payload = EXCLUDED.payload
        """, (conn.get("id", ""), _workspace_id_camel(conn), conn.get("status", ""), self._j(conn)))
        return conn

    def delete_org_connection(self, workspace_id: str, conn_id: str) -> bool:
        return self._run(
            "DELETE FROM org_connections WHERE id = %s AND workspace_id = %s",
            (conn_id, workspace_id)) > 0

    def get_org_accounts(self, workspace_id: str, conn_id: Optional[str] = None) -> list:
        if conn_id:
            rows = self._query("""
                SELECT payload FROM org_accounts
                WHERE workspace_id = %s AND org_connection_id = %s
                ORDER BY aws_account_id
            """, (workspace_id, conn_id))
        else:
            rows = self._query(
                "SELECT payload FROM org_accounts WHERE workspace_id = %s ORDER BY aws_account_id",
                (workspace_id,))
        return [self._p(r) for r in rows]

    def save_org_account(self, account: dict) -> dict:
        self._run("""
            INSERT INTO org_accounts (id, workspace_id, org_connection_id, aws_account_id, payload)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                workspace_id = EXCLUDED.workspace_id,
                org_connection_id = EXCLUDED.org_connection_id,
                aws_account_id = EXCLUDED.aws_account_id,
                payload = EXCLUDED.payload
        """, (account.get("id", ""), _workspace_id_camel(account),
              _org_connection_id(account), account.get("awsAccountId", ""), self._j(account)))
        return account

    def save_org_scan_run(self, run: dict) -> dict:
        self._run("""
            INSERT INTO org_scan_runs (id, workspace_id, org_connection_id, status, started_at, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                workspace_id = EXCLUDED.workspace_id,
                org_connection_id = EXCLUDED.org_connection_id,
                status = EXCLUDED.status,
                started_at = EXCLUDED.started_at,
                payload = EXCLUDED.payload
        """, (run.get("id", ""), _workspace_id_camel(run), _org_connection_id(run),
              run.get("status", ""), run.get("startedAt", ""), self._j(run)))
        return run

    def get_org_scan_run(self, workspace_id: str, scan_id: str) -> Optional[dict]:
        row = self._one(
            "SELECT payload FROM org_scan_runs WHERE id = %s AND workspace_id = %s",
            (scan_id, workspace_id))
        return self._p(row)

    def get_org_scan_runs(self, workspace_id: str, conn_id: Optional[str] = None, limit: int = 20) -> list:
        if conn_id:
            rows = self._query("""
                SELECT payload FROM org_scan_runs
                WHERE workspace_id = %s AND org_connection_id = %s
                ORDER BY started_at DESC
                LIMIT %s
            """, (workspace_id, conn_id, limit))
        else:
            rows = self._query("""
                SELECT payload FROM org_scan_runs
                WHERE workspace_id = %s
                ORDER BY started_at DESC
                LIMIT %s
            """, (workspace_id, limit))
        return [self._p(r) for r in rows]

    def get_running_org_scan(self, workspace_id: str, conn_id: str) -> Optional[dict]:
        row = self._one("""
            SELECT payload FROM org_scan_runs
            WHERE workspace_id = %s AND org_connection_id = %s AND status = 'RUNNING'
            ORDER BY started_at DESC LIMIT 1
        """, (workspace_id, conn_id))
        return self._p(row)

    def cleanup_stale_org_scans(self, workspace_id: str, timeout_minutes: int = 30) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
        stale = self._query("""
            SELECT id, payload FROM org_scan_runs
            WHERE workspace_id = %s AND status = 'RUNNING' AND started_at < %s
        """, (workspace_id, cutoff))
        count = 0
        for row in stale:
            run = self._p(row)
            if run:
                run["status"] = "FAILED"
                run["completedAt"] = datetime.now(timezone.utc).isoformat()
                run["errorCode"] = "STALE_ORG_SCAN_TIMEOUT"
                run["error"] = "STALE_ORG_SCAN_TIMEOUT"
                self.save_org_scan_run(run)
                count += 1
        return count

    # ── Inventory resources ────────────────────────────────────────────────────

    def save_resources(self, resources: list) -> int:
        stamped = _stamp_resources(resources)
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                for r in stamped:
                    cur.execute("""
                        INSERT INTO inventory_resources
                            (resource_id, workspace_id, account_id, service_type, eol_status, region, payload)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (resource_id, workspace_id) DO UPDATE SET
                            account_id   = EXCLUDED.account_id,
                            service_type = EXCLUDED.service_type,
                            eol_status   = EXCLUDED.eol_status,
                            region       = EXCLUDED.region,
                            payload      = EXCLUDED.payload
                    """, (r.get("resource_id", ""), _workspace_id(r), _account_id(r),
                          r.get("service_type", ""), r.get("eol_status", ""), r.get("region", ""),
                          self._j(r)))
            conn.commit()
            return len(resources)
        except Exception:
            conn.rollback()
            raise

    def replace_resources_for_account(self, workspace_id: str, account_id: str,
                                       resources: list, scan_started_at: Optional[str] = None) -> int:
        stamped = _stamp_resources(resources, scan_started_at=scan_started_at)
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                # Stale-write guard inside transaction for consistency
                if scan_started_at:
                    cur.execute("""
                        SELECT MAX(payload->>'scan_started_at') FROM inventory_resources
                        WHERE workspace_id = %s AND account_id = %s
                    """, (workspace_id, account_id))
                    row = cur.fetchone()
                    newest = row[0] if row else None
                    if newest and newest > scan_started_at:
                        logger.warning("Stale write skipped account=%s existing=%s current=%s",
                                       account_id, newest, scan_started_at)
                        conn.rollback()
                        return 0
                cur.execute(
                    "DELETE FROM inventory_resources WHERE workspace_id = %s AND account_id = %s",
                    (workspace_id, account_id))
                for r in stamped:
                    cur.execute("""
                        INSERT INTO inventory_resources
                            (resource_id, workspace_id, account_id, service_type, eol_status, region, payload)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (resource_id, workspace_id) DO UPDATE SET
                            account_id   = EXCLUDED.account_id,
                            service_type = EXCLUDED.service_type,
                            eol_status   = EXCLUDED.eol_status,
                            region       = EXCLUDED.region,
                            payload      = EXCLUDED.payload
                    """, (r.get("resource_id", ""), workspace_id, account_id,
                          r.get("service_type", ""), r.get("eol_status", ""), r.get("region", ""),
                          self._j(r)))
            conn.commit()
            return len(resources)
        except Exception:
            conn.rollback()
            raise

    def get_resources(self, filters: Optional[dict] = None) -> list:
        conditions: list = []
        params: list = []
        if filters:
            if filters.get("workspace_id"):
                conditions.append("workspace_id = %s")
                params.append(filters["workspace_id"])
            if filters.get("account_id"):
                conditions.append("account_id = %s")
                params.append(filters["account_id"])
            if filters.get("status"):
                conditions.append("eol_status = %s")
                params.append(filters["status"].upper())
            if filters.get("service"):
                conditions.append("service_type ILIKE %s")
                params.append(f"%{filters['service']}%")
            if filters.get("region"):
                conditions.append("region = %s")
                params.append(filters["region"])
        sql = "SELECT payload FROM inventory_resources"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        return [self._p(r) for r in self._query(sql, params or None)]

    def get_resource_by_id(self, resource_id: str, workspace_id: Optional[str] = None) -> Optional[dict]:
        if workspace_id:
            row = self._one(
                "SELECT payload FROM inventory_resources WHERE resource_id = %s AND workspace_id = %s LIMIT 1",
                (resource_id, workspace_id))
        else:
            row = self._one(
                "SELECT payload FROM inventory_resources WHERE resource_id = %s LIMIT 1",
                (resource_id,))
        return self._p(row)

    # ── Config ─────────────────────────────────────────────────────────────────

    def get_config(self) -> dict:
        row = self._one("SELECT config FROM global_config WHERE key = 'global'")
        return _merge_config(row["config"] if row else {})

    def save_config(self, config: dict) -> None:
        cfg = dict(config)
        cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._run("""
            INSERT INTO global_config (key, config, updated_at)
            VALUES ('global', %s, %s)
            ON CONFLICT (key) DO UPDATE SET config = EXCLUDED.config, updated_at = EXCLUDED.updated_at
        """, (self._j(cfg), cfg["updated_at"]))

    def get_workspace_config(self, workspace_id: str) -> dict:
        row = self._one(
            "SELECT config FROM workspace_config WHERE workspace_id = %s", (workspace_id,))
        return _merge_config(row["config"] if row else {})

    def save_workspace_config(self, workspace_id: str, config: dict) -> dict:
        merged = _merge_config(config)
        merged["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._run("""
            INSERT INTO workspace_config (workspace_id, config, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (workspace_id) DO UPDATE SET
                config = EXCLUDED.config, updated_at = EXCLUDED.updated_at
        """, (workspace_id, self._j(merged), merged["updated_at"]))
        return merged

    # ── Scan runs ──────────────────────────────────────────────────────────────

    def save_scan_run(self, run: dict) -> dict:
        self._run("""
            INSERT INTO scan_runs (id, workspace_id, account_id, status, started_at, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                status     = EXCLUDED.status,
                started_at = EXCLUDED.started_at,
                payload    = EXCLUDED.payload
        """, (run.get("scanId", ""), run.get("workspaceId", ""), run.get("accountId", ""),
              run.get("status", ""), run.get("startedAt", run.get("createdAt", "")),
              self._j(run)))
        return run

    def get_scan_run(self, scan_id: str) -> Optional[dict]:
        row = self._one("SELECT payload FROM scan_runs WHERE id = %s", (scan_id,))
        return self._p(row)

    def get_scan_runs(self, workspace_id: str, account_id: Optional[str] = None,
                      limit: int = 20) -> list:
        if account_id:
            rows = self._query("""
                SELECT payload FROM scan_runs
                WHERE workspace_id = %s AND account_id = %s
                ORDER BY started_at DESC LIMIT %s
            """, (workspace_id, account_id, limit))
        else:
            rows = self._query("""
                SELECT payload FROM scan_runs WHERE workspace_id = %s
                ORDER BY started_at DESC LIMIT %s
            """, (workspace_id, limit))
        return [self._p(r) for r in rows]

    def get_all_scan_runs_admin(self, workspace_id: Optional[str] = None,
                                status: Optional[str] = None, search: Optional[str] = None,
                                limit: int = 100, offset: int = 0) -> dict:
        conditions: list = []
        params: list = []
        if workspace_id:
            conditions.append("workspace_id = %s")
            params.append(workspace_id)
        if status:
            conditions.append("status = %s")
            params.append(status)
        # account_id search at SQL level; workspace name search is done after enrichment
        if search:
            conditions.append("account_id ILIKE %s")
            params.append(f"%{search}%")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        total_row = self._one(f"SELECT COUNT(*) AS n FROM scan_runs{where}", params or None)
        total = (total_row or {}).get("n", 0)
        sql = f"SELECT payload FROM scan_runs{where} ORDER BY started_at DESC LIMIT %s OFFSET %s"
        runs = [self._p(r) for r in self._query(sql, (params or []) + [limit, offset])]
        return {"runs": runs, "total": total}

    def get_running_scan(self, workspace_id: str, account_id: str) -> Optional[dict]:
        row = self._one("""
            SELECT payload FROM scan_runs
            WHERE workspace_id = %s AND account_id = %s AND status = 'RUNNING'
            ORDER BY started_at DESC LIMIT 1
        """, (workspace_id, account_id))
        return self._p(row)

    def cleanup_stale_scans(self, workspace_id: str, timeout_minutes: int = 30) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
        stale  = self._query("""
            SELECT id, payload FROM scan_runs
            WHERE workspace_id = %s AND status = 'RUNNING' AND started_at < %s
        """, (workspace_id, cutoff))
        count = 0
        for row in stale:
            run = self._p(row)
            if run:
                run["status"]      = "FAILED"
                run["completedAt"] = datetime.now(timezone.utc).isoformat()
                run["error"]       = "STALE_SCAN_TIMEOUT"
                self.save_scan_run(run)
                count += 1
        return count

    def find_alert_by_resource(self, workspace_id: str, account_id: str,
                                resource_id: str, service: str) -> Optional[dict]:
        row = self._one("""
            SELECT payload FROM alerts
            WHERE workspace_id = %s AND account_id = %s
            AND payload->>'resourceId' = %s AND payload->>'service' = %s
            AND status != 'RESOLVED'
            ORDER BY created_at DESC LIMIT 1
        """, (workspace_id, account_id, resource_id, service))
        return self._p(row)

    # ── Alerts ─────────────────────────────────────────────────────────────────

    def save_alert(self, alert: dict) -> dict:
        self._run("""
            INSERT INTO alerts (id, workspace_id, account_id, status, created_at, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                status     = EXCLUDED.status,
                created_at = EXCLUDED.created_at,
                payload    = EXCLUDED.payload
        """, (alert.get("id", ""), alert.get("workspaceId", ""), alert.get("accountId", ""),
              alert.get("status", ""), alert.get("createdAt", ""), self._j(alert)))
        return alert

    def get_alerts(self, workspace_id: str, account_id: Optional[str] = None,
                   status: Optional[str] = None, limit: int = 200) -> list:
        conditions = ["workspace_id = %s"]
        params: list = [workspace_id]
        if account_id:
            conditions.append("account_id = %s")
            params.append(account_id)
        if status:
            conditions.append("status = %s")
            params.append(status)
        params.append(limit)
        sql = (f"SELECT payload FROM alerts WHERE {' AND '.join(conditions)}"
               f" ORDER BY created_at DESC LIMIT %s")
        return [self._p(r) for r in self._query(sql, params)]

    def get_alert(self, alert_id: str, workspace_id: str) -> Optional[dict]:
        row = self._one(
            "SELECT payload FROM alerts WHERE id = %s AND workspace_id = %s",
            (alert_id, workspace_id))
        return self._p(row)

    # ── Notification settings ──────────────────────────────────────────────────

    def get_notification_settings(self, workspace_id: str) -> dict:
        row = self._one(
            "SELECT settings FROM notification_settings WHERE workspace_id = %s", (workspace_id,))
        if not row:
            return {}
        val = row["settings"]
        if isinstance(val, (str, bytes)):
            return json.loads(val)
        return dict(val) if val else {}

    def save_notification_settings(self, workspace_id: str, settings: dict) -> dict:
        self._run("""
            INSERT INTO notification_settings (workspace_id, settings, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (workspace_id) DO UPDATE SET
                settings = EXCLUDED.settings, updated_at = EXCLUDED.updated_at
        """, (workspace_id, self._j(settings), datetime.now(timezone.utc).isoformat()))
        return settings

    def get_notification_logs(self, workspace_id: str, limit: int = 50) -> list:
        rows = self._query("""
            SELECT payload FROM notification_logs WHERE workspace_id = %s
            ORDER BY created_at DESC LIMIT %s
        """, (workspace_id, limit))
        return [self._p(r) for r in rows]

    def save_notification_log(self, log: dict) -> dict:
        self._run("""
            INSERT INTO notification_logs (id, workspace_id, created_at, payload)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                created_at = EXCLUDED.created_at, payload = EXCLUDED.payload
        """, (log.get("id", ""), log.get("workspaceId", ""),
              log.get("createdAt", ""), self._j(log)))
        return log

    # ── API tokens ─────────────────────────────────────────────────────────────

    def get_api_tokens(self, workspace_id: str) -> list:
        rows = self._query(
            "SELECT payload FROM api_tokens WHERE workspace_id = %s", (workspace_id,))
        return [self._p(r) for r in rows]

    def save_api_token(self, token: dict) -> dict:
        self._run("""
            INSERT INTO api_tokens (id, workspace_id, token_hash, payload)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                token_hash = EXCLUDED.token_hash, payload = EXCLUDED.payload
        """, (token.get("id", ""), token.get("workspaceId", ""),
              token.get("tokenHash", ""), self._j(token)))
        return token

    def get_api_token_by_id(self, token_id: str, workspace_id: str) -> Optional[dict]:
        row = self._one(
            "SELECT payload FROM api_tokens WHERE id = %s AND workspace_id = %s",
            (token_id, workspace_id))
        return self._p(row)

    def find_api_token_by_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        row = self._one(
            "SELECT payload FROM api_tokens WHERE token_hash = %s AND workspace_id = %s",
            (token_hash, workspace_id))
        return self._p(row)

    # ── Audit logs ─────────────────────────────────────────────────────────────

    def save_audit_log(self, log: dict) -> dict:
        self._run("""
            INSERT INTO audit_logs (id, workspace_id, action, created_at, payload)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                action = EXCLUDED.action, created_at = EXCLUDED.created_at, payload = EXCLUDED.payload
        """, (log.get("id", ""), log.get("workspaceId", ""),
              log.get("action", ""), log.get("createdAt", ""), self._j(log)))
        return log

    def get_audit_logs(self, workspace_id: str, limit: int = 50) -> list:
        rows = self._query("""
            SELECT payload FROM audit_logs WHERE workspace_id = %s
            ORDER BY created_at DESC LIMIT %s
        """, (workspace_id, limit))
        return [self._p(r) for r in rows]

    # ── Report snapshots ───────────────────────────────────────────────────────

    def save_report_snapshot(self, snapshot: dict) -> dict:
        self._run("""
            INSERT INTO reports (id, workspace_id, created_at, payload)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                created_at = EXCLUDED.created_at, payload = EXCLUDED.payload
        """, (snapshot.get("id", ""), snapshot.get("workspaceId", ""),
              snapshot.get("createdAt", ""), self._j(snapshot)))
        return snapshot

    def get_report_snapshots(self, workspace_id: str, limit: int = 50) -> list:
        rows = self._query("""
            SELECT payload FROM reports WHERE workspace_id = %s
            ORDER BY created_at DESC LIMIT %s
        """, (workspace_id, limit))
        return [self._p(r) for r in rows]

    def get_report_snapshot(self, workspace_id: str, report_id: str) -> Optional[dict]:
        row = self._one(
            "SELECT payload FROM reports WHERE workspace_id = %s AND id = %s",
            (workspace_id, report_id))
        return self._p(row)

    # ── General EOL cache ──────────────────────────────────────────────────────

    def get_general_eol_cache(self) -> Optional[dict]:
        row = self._one("SELECT payload FROM general_eol_cache WHERE cache_key = 'general'")
        return self._p(row)

    def save_general_eol_cache(self, records: list, refreshed_at: str, expires_at: str) -> None:
        self._run("""
            INSERT INTO general_eol_cache (cache_key, payload)
            VALUES ('general', %s)
            ON CONFLICT (cache_key) DO UPDATE SET payload = EXCLUDED.payload
        """, (self._j({"records": records, "refreshed_at": refreshed_at, "expires_at": expires_at}),))

    # ── EOL overrides (Postgres) ──────────────────────────────────────────────

    def list_eol_overrides(self) -> list:
        rows = self._query("SELECT payload FROM eol_overrides ORDER BY product, version")
        return [self._p(r) for r in rows]

    def get_eol_override(self, product: str, version: str) -> Optional[dict]:
        row = self._one(
            "SELECT payload FROM eol_overrides WHERE product = %s AND version = %s",
            (product, version),
        )
        return self._p(row)

    def save_eol_override(self, product: str, version: str, record: dict) -> dict:
        record = {**record, "product": product, "version": version,
                  "updatedAt": datetime.now(timezone.utc).isoformat()}
        self._run("""
            INSERT INTO eol_overrides (product, version, payload)
            VALUES (%s, %s, %s)
            ON CONFLICT (product, version) DO UPDATE SET payload = EXCLUDED.payload
        """, (product, version, self._j(record)))
        return record

    def delete_eol_override(self, product: str, version: str) -> bool:
        return self._run(
            "DELETE FROM eol_overrides WHERE product = %s AND version = %s",
            (product, version),
        ) > 0

    # ── Verified lifecycle (Postgres) ─────────────────────────────────────────
    # Table DDL (run once via migration or CREATE IF NOT EXISTS at startup):
    #   CREATE TABLE IF NOT EXISTS verified_lifecycle (
    #     product    TEXT NOT NULL,
    #     version    TEXT NOT NULL,
    #     payload    JSONB NOT NULL,
    #     created_at TIMESTAMPTZ DEFAULT now(),
    #     updated_at TIMESTAMPTZ DEFAULT now(),
    #     PRIMARY KEY (product, version)
    #   );

    def _ensure_verified_lifecycle_table(self) -> None:
        try:
            self._run("""
                CREATE TABLE IF NOT EXISTS verified_lifecycle (
                    product    TEXT NOT NULL,
                    version    TEXT NOT NULL,
                    payload    JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ DEFAULT now(),
                    PRIMARY KEY (product, version)
                )
            """)
        except Exception as exc:
            logger.warning("verified_lifecycle table ensure failed: %s", exc)

    def list_verified_lifecycle(self) -> list:
        try:
            rows = self._query("SELECT payload FROM verified_lifecycle ORDER BY product, version")
            return [self._p(r) for r in rows]
        except Exception:
            return []

    def get_verified_lifecycle(self, product: str, version: str) -> Optional[dict]:
        try:
            row = self._one(
                "SELECT payload FROM verified_lifecycle WHERE product = %s AND version = %s",
                (product, version),
            )
            return self._p(row)
        except Exception:
            return None

    def save_verified_lifecycle(self, product: str, version: str, record: dict) -> dict:
        self._ensure_verified_lifecycle_table()
        now = datetime.now(timezone.utc).isoformat()
        record = {**record, "product": product, "version": version,
                  "updatedAt": now, "createdAt": record.get("createdAt", now)}
        self._run("""
            INSERT INTO verified_lifecycle (product, version, payload, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (product, version) DO UPDATE
                SET payload = EXCLUDED.payload, updated_at = now()
        """, (product, version, self._j(record)))
        return record

    def delete_verified_lifecycle(self, product: str, version: str) -> bool:
        return self._run(
            "DELETE FROM verified_lifecycle WHERE product = %s AND version = %s",
            (product, version),
        ) > 0

    # ── Upgrade guides ─────────────────────────────────────────────────────────

    def get_upgrade_guides(self) -> list:
        rows = self._query("SELECT payload FROM upgrade_guides ORDER BY id")
        return [self._p(r) for r in rows]

    def save_upgrade_guide(self, guide: dict) -> dict:
        self._run("""
            INSERT INTO upgrade_guides (id, payload)
            VALUES (%s, %s)
            ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload
        """, (guide.get("id", ""), self._j(guide)))
        return guide

    def delete_upgrade_guide(self, guide_id: str) -> bool:
        return self._run("DELETE FROM upgrade_guides WHERE id = %s", (guide_id,)) > 0

    # ── Members ────────────────────────────────────────────────────────────────

    def get_members(self, workspace_id: str) -> list:
        rows = self._query(
            "SELECT payload FROM members WHERE workspace_id = %s", (workspace_id,))
        return [self._p(r) for r in rows]

    def get_member_by_id(self, member_id: str, workspace_id: str) -> Optional[dict]:
        row = self._one(
            "SELECT payload FROM members WHERE id = %s AND workspace_id = %s",
            (member_id, workspace_id))
        return self._p(row)

    def find_member_by_invite_token_hash(self, token_hash: str, workspace_id: str) -> Optional[dict]:
        row = self._one(
            "SELECT payload FROM members WHERE invite_token_hash = %s AND workspace_id = %s",
            (token_hash, workspace_id))
        return self._p(row)

    def save_member(self, member: dict) -> dict:
        self._run("""
            INSERT INTO members (id, workspace_id, email, status, invite_token_hash, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                email             = EXCLUDED.email,
                status            = EXCLUDED.status,
                invite_token_hash = EXCLUDED.invite_token_hash,
                payload           = EXCLUDED.payload
        """, (member.get("id", ""), member.get("workspaceId", ""), member.get("email", ""),
              member.get("status", ""), member.get("inviteTokenHash", "") or "",
              self._j(member)))
        return member

    def delete_member(self, member_id: str, workspace_id: str) -> bool:
        return self._run(
            "DELETE FROM members WHERE id = %s AND workspace_id = %s",
            (member_id, workspace_id)) > 0

    # ── Member sessions ────────────────────────────────────────────────────────

    def find_member_session_by_token_hash(self, token_hash: str,
                                          workspace_id: str) -> Optional[dict]:
        row = self._one(
            "SELECT payload FROM member_sessions WHERE token_hash = %s AND workspace_id = %s",
            (token_hash, workspace_id))
        return self._p(row)

    def save_member_session(self, session: dict) -> dict:
        self._run("""
            INSERT INTO member_sessions (id, workspace_id, member_id, token_hash, payload)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                member_id  = EXCLUDED.member_id,
                token_hash = EXCLUDED.token_hash,
                payload    = EXCLUDED.payload
        """, (session.get("id", ""), session.get("workspaceId", ""), session.get("memberId", ""),
              session.get("tokenHash", ""), self._j(session)))
        return session

    def revoke_member_sessions(self, member_id: str, workspace_id: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        rows = self._query(
            """
            SELECT id, payload FROM member_sessions
            WHERE member_id = %s AND workspace_id = %s
            """,
            (member_id, workspace_id))
        count = 0
        for row in (rows or []):
            payload = self._p(row)
            if payload and not payload.get("revokedAt"):
                payload["revokedAt"] = now
                self._run(
                    "UPDATE member_sessions SET payload = %s WHERE id = %s",
                    (self._j(payload), payload.get("id", "")))
                count += 1
        return count

    # ── Member login tokens ────────────────────────────────────────────────────

    def find_member_login_token_by_hash(self, token_hash: str,
                                        workspace_id: str) -> Optional[dict]:
        row = self._one(
            "SELECT payload FROM member_login_tokens WHERE token_hash = %s AND workspace_id = %s",
            (token_hash, workspace_id))
        return self._p(row)

    def get_member_login_tokens_for_member(self, member_id: str, workspace_id: str) -> list:
        rows = self._query(
            "SELECT payload FROM member_login_tokens WHERE workspace_id = %s",
            (workspace_id,))
        return [self._p(r) for r in (rows or [])
                if self._p(r) and self._p(r).get("memberId") == member_id]

    def save_member_login_token(self, token: dict) -> dict:
        self._run("""
            INSERT INTO member_login_tokens (id, workspace_id, token_hash, payload)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                token_hash = EXCLUDED.token_hash, payload = EXCLUDED.payload
        """, (token.get("id", ""), token.get("workspaceId", ""),
              token.get("tokenHash", ""), self._j(token)))
        return token


    # ── Auth tables (feature-flagged; postgres-only) ───────────────────────────
    # Called by auth_handler.py only when AUTH_* flags are enabled.
    # Non-postgres backends raise NotImplementedError to fail clearly.

    def auth_run(self, sql: str, params=None) -> int:
        return self._run(sql, params)

    def auth_query(self, sql: str, params=None) -> list:
        return self._query(sql, params)

    def auth_one(self, sql: str, params=None):
        return self._one(sql, params)




# ── Factory ───────────────────────────────────────────────────────────────────
# Module-level singleton — avoids creating a new DB connection on every call.
_storage_instance: Any = None


def get_storage():
    """Return the configured storage backend singleton."""
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    backend = STORAGE_BACKEND
    if backend in ("postgres", "postgresql", "db"):
        if not DATABASE_URL:
            raise ValueError(
                "DATABASE_URL is required when STORAGE_BACKEND=postgres. "
                "Example: DATABASE_URL=postgresql://eol_app:<password>@host:5432/eol_monitor"
            )
        logger.info("Storage backend: PostgreSQL")
        _storage_instance = PostgresBackend(DATABASE_URL)
    elif backend == "s3":
        logger.info("Storage backend: S3 (bucket=%s)", EOL_BUCKET)
        _storage_instance = S3Backend()
    elif backend == "file":
        logger.info("Storage backend: File (dir=%s)", EOL_DATA_DIR)
        _storage_instance = FileBackend()
    else:
        logger.info("Storage backend: DynamoDB (table=%s)", DYNAMODB_TABLE)
        _storage_instance = DynamoDBBackend()

    return _storage_instance
