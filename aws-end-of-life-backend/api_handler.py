"""
AWS EOL Monitor — API Gateway Lambda Handler
Serves the React dashboard via REST endpoints.
Storage backend is controlled by STORAGE_BACKEND env var (dynamodb | s3 | file).
"""
import functools
import hashlib
import hmac
import inspect
import json
import logging
import os
import re
import secrets
import csv
import io
import threading as _threading
import time as _time
from collections import defaultdict as _defaultdict
from urllib.parse import unquote, quote
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

from storage import get_storage
import general_eol as _general_eol

logger = logging.getLogger()
logger.setLevel(logging.INFO)

COLLECTOR_FUNCTION    = os.environ.get("COLLECTOR_FUNCTION", "aws-eol-collector")
ALLOWED_ORIGIN        = os.environ.get("ALLOWED_ORIGIN", "http://localhost:3000")
ORG_MEMBER_ROLE_NAME  = os.environ.get("ORG_MEMBER_ROLE_NAME", "EOLMonitorReadOnly")
BACKEND_SCANNER_ROLE  = os.environ.get("BACKEND_SCANNER_ROLE_ARN",
                                       "arn:aws:iam::495234635788:role/EOLMonitorBackendEC2Role")
APP_ENV            = os.environ.get("APP_ENV", "development").lower()
_IS_PRODUCTION     = APP_ENV == "production"
def _ff(key: str, default: str = "false") -> bool:
    return os.environ.get(key, default).lower() in ("1", "true", "yes")

FEATURE_FLAGS = {
    "orgScan":                   _ff("ENABLE_ORG_SCAN"),
    "remediation":               _ff("ENABLE_REMEDIATION"),
    "sso":                       _ff("ENABLE_SSO"),
    "billing":                   _ff("ENABLE_BILLING"),
    "cicdScan":                  _ff("ENABLE_CICD_SCAN"),
    # Auth feature flags (all false by default)
    "authEmailSignup":           _ff("AUTH_EMAIL_SIGNUP_ENABLED"),
    "authGoogleSignup":          _ff("AUTH_GOOGLE_SIGNUP_ENABLED"),
    "authCaptcha":               _ff("AUTH_CAPTCHA_ENABLED"),
    "authEmailVerification":     _ff("AUTH_EMAIL_VERIFICATION_REQUIRED"),
    "authSessionCookie":         _ff("AUTH_SESSION_COOKIE_ENABLED", "true"),
    "authSaml":                  _ff("AUTH_SAML_ENABLED"),
    "anonymousWorkspaceCreate":  _ff("ANONYMOUS_WORKSPACE_CREATE_ENABLED", "true"),
}
if ALLOWED_ORIGIN == "*":
    if _IS_PRODUCTION:
        raise RuntimeError(
            "FATAL: ALLOWED_ORIGIN='*' is not allowed when APP_ENV=production. "
            "Set ALLOWED_ORIGIN to your exact frontend domain "
            "(e.g. ALLOWED_ORIGIN=https://yourdomain.com)."
        )
    logger.warning(
        "SECURITY: CORS wildcard (*) is active. "
        "Set ALLOWED_ORIGIN to your exact frontend domain in production "
        "(e.g. ALLOWED_ORIGIN=https://yourdomain.com)."
    )

# ── In-memory rate limiter ─────────────────────────────────────────────────────
# Limits reset on process restart. Sufficient for single PM2 instance.
# Upgrade to Redis when running multiple backend instances.

_WS_CREATE_LIMIT      = int(os.environ.get("WORKSPACE_CREATE_RATE_LIMIT",          "10"))
_WS_CREATE_WINDOW     = int(os.environ.get("WORKSPACE_CREATE_RATE_WINDOW_SECONDS", "3600"))
_WS_AUTH_FAIL_LIMIT   = int(os.environ.get("WORKSPACE_AUTH_FAIL_LIMIT",            "20"))
_WS_AUTH_FAIL_WINDOW  = int(os.environ.get("WORKSPACE_AUTH_FAIL_WINDOW_SECONDS",   "900"))

_rl_lock  = _threading.Lock()
_rl_store: dict = _defaultdict(list)   # key → [monotonic timestamps]
_request_local = _threading.local()    # per-request client IP


def _extract_client_ip(event: dict) -> str:
    """Extract client IP from Lambda event. Prefers API-GW sourceIp, then X-Forwarded-For."""
    try:
        src_ip = ((event.get("requestContext") or {}).get("identity") or {}).get("sourceIp", "")
        if src_ip and src_ip not in ("test-invoke-source-ip", ""):
            return src_ip.strip()
    except Exception:
        pass
    raw_headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    xff = raw_headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return raw_headers.get("x-real-ip", "unknown").strip() or "unknown"


def _get_client_ip() -> str:
    """Return client IP stored in thread-local by lambda_handler."""
    return getattr(_request_local, "client_ip", "unknown")


def _mask_token(token: str) -> str:
    """Return first-4…last-4 representation; never log the full token."""
    if not token or len(token) < 12:
        return "****"
    return f"{token[:4]}...{token[-4:]}"


def _rl_check(key: str, limit: int, window: int) -> tuple:
    """Sliding-window check + record. Returns (allowed: bool, retry_after: int)."""
    now    = _time.monotonic()
    cutoff = now - window
    with _rl_lock:
        hits = [t for t in _rl_store[key] if t > cutoff]
        _rl_store[key] = hits
        if len(hits) >= limit:
            retry_after = int(hits[0] + window - now) + 1
            return False, max(retry_after, 1)
        _rl_store[key].append(now)
        return True, 0


def _rl_record(key: str, window: int) -> int:
    """Record one event without checking the limit. Returns current count in window."""
    now    = _time.monotonic()
    cutoff = now - window
    with _rl_lock:
        hits = [t for t in _rl_store[key] if t > cutoff]
        hits.append(now)
        _rl_store[key] = hits
        return len(hits)


def _rl_count(key: str, window: int) -> int:
    """Return current hit count without recording."""
    now    = _time.monotonic()
    cutoff = now - window
    with _rl_lock:
        return len([t for t in _rl_store[key] if t > cutoff])


def _rate_limited_resp(retry_after: int, message: str) -> dict:
    r = resp(429, {"ok": False, "error": "RATE_LIMITED",
                   "message": message, "retryAfterSeconds": retry_after})
    r["headers"]["Retry-After"] = str(retry_after)
    return r

# ── Admin token resolution ────────────────────────────────────────────────────
# Production:   set ADMIN_PORTAL_SECRET_ID to an AWS Secrets Manager secret ID.
#               The backend loads the token from Secrets Manager and caches it
#               for _ADMIN_SECRET_CACHE_TTL_S seconds to limit API calls.
#               Fails closed if the secret cannot be loaded — admin access is
#               disabled rather than falling back to an insecure path.
# Development:  ADMIN_PORTAL_TOKEN env var is accepted as a convenience fallback.
#               File-based fallback is also supported for self-hosted EC2.
#
# NEVER log the token value. Log only the secret ID or file path.

_ADMIN_SECRET_CACHE_TTL_S = int(os.environ.get("ADMIN_SECRET_CACHE_TTL_S", "300"))
_admin_secret_cache: dict = {"token": None, "loaded_at": 0.0}  # process-level cache
_admin_secret_lock  = _threading.Lock()


def _load_token_from_secrets_manager(secret_id: str) -> str:
    """Fetch admin token from AWS Secrets Manager. Returns plain token or raises."""
    client = boto3.client("secretsmanager",
                          region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    response = client.get_secret_value(SecretId=secret_id)
    raw = response.get("SecretString") or ""
    if not raw:
        raise ValueError("Secret value is empty")
    # Accept plain string OR JSON {"ADMIN_PORTAL_TOKEN": "..."}
    if raw.startswith("{"):
        import json as _json
        parsed = _json.loads(raw)
        token  = parsed.get("ADMIN_PORTAL_TOKEN") or parsed.get("token") or ""
        if not token:
            raise ValueError("JSON secret does not contain ADMIN_PORTAL_TOKEN key")
        return token
    return raw.strip()


def _get_admin_token() -> str:
    """Return the current admin token, refreshing from Secrets Manager if needed.

    Resolution order:
      1. Secrets Manager (ADMIN_PORTAL_SECRET_ID set)  — required in production;
         cached for _ADMIN_SECRET_CACHE_TTL_S seconds.
      2. ADMIN_PORTAL_TOKEN env var                     — local / dev only.
      3. File ({EOL_DATA_DIR}/secrets/initial-admin-token) — self-hosted fallback.
      4. Auto-generate and persist to file              — first-boot convenience.

    In production (APP_ENV=production) with ADMIN_PORTAL_SECRET_ID set, steps
    2–4 are never reached. If the secret fails to load, an empty string is
    returned → admin access disabled (fail-closed).
    """
    secret_id = os.environ.get("ADMIN_PORTAL_SECRET_ID", "").strip()

    if secret_id:
        now = _time.monotonic()
        with _admin_secret_lock:
            if (_admin_secret_cache["token"] is not None and
                    now - _admin_secret_cache["loaded_at"] < _ADMIN_SECRET_CACHE_TTL_S):
                return _admin_secret_cache["token"]
        # Outside lock: fetch from Secrets Manager (concurrent fetches are harmless)
        try:
            token = _load_token_from_secrets_manager(secret_id)
            with _admin_secret_lock:
                _admin_secret_cache["token"]     = token
                _admin_secret_cache["loaded_at"] = _time.monotonic()
            logger.info("Admin token loaded from Secrets Manager secret_id=%s", secret_id)
            return token
        except Exception as exc:
            logger.error("Failed to load admin token from Secrets Manager secret_id=%s err=%s",
                         secret_id, exc)
            if _IS_PRODUCTION:
                # Fail closed: never fall back to env var or file in production
                logger.error("FATAL: admin token unavailable in production — "
                             "admin access is disabled")
                return ""
            logger.warning("Falling back to ADMIN_PORTAL_TOKEN env var (non-production only)")

    # Dev / self-hosted fallback path (never reached in production with ADMIN_PORTAL_SECRET_ID)
    env_token = os.environ.get("ADMIN_PORTAL_TOKEN", "")
    if env_token:
        return env_token

    data_dir   = os.environ.get("EOL_DATA_DIR", "/var/lib/eol-data")
    token_file = os.path.join(data_dir, "secrets", "initial-admin-token")
    if os.path.isfile(token_file):
        try:
            token = open(token_file).read().strip()
            if token:
                logger.info("Admin token loaded from file path=%s", token_file)
                return token
        except Exception as exc:
            logger.error("Failed to read admin token file path=%s err=%s", token_file, exc)

    # Auto-generate on first boot (dev / self-hosted only)
    try:
        token = f"eolm_admin_{secrets.token_hex(24)}"
        os.makedirs(os.path.dirname(token_file), exist_ok=True)
        with open(token_file, "w") as fh:
            fh.write(token)
        try:
            os.chmod(token_file, 0o600)
        except Exception:
            pass
        logger.info("=" * 56)
        logger.info("AWS EOL Monitor — Initial Admin Token Generated")
        logger.info("Retrieve token from file: path=%s", token_file)
        logger.info("Set ADMIN_PORTAL_SECRET_ID (production) or ADMIN_PORTAL_TOKEN (dev).")
        logger.info("=" * 56)
        return token
    except Exception as exc:
        logger.error("Cannot generate admin token err=%s. "
                     "Set ADMIN_PORTAL_SECRET_ID or ADMIN_PORTAL_TOKEN.", exc)
        return ""


def _resolve_admin_token() -> str:
    """Compatibility shim — called once at module load for the cached hash."""
    return _get_admin_token()


ADMIN_PORTAL_TOKEN        = _resolve_admin_token()
_ADMIN_TOKEN_HASH         = hashlib.sha256(ADMIN_PORTAL_TOKEN.encode()).hexdigest() if ADMIN_PORTAL_TOKEN else ""
MEMBER_SESSION_TTL_HOURS  = int(os.environ.get("MEMBER_SESSION_TTL_HOURS", "24"))


def _serial(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError


def resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type":                     "application/json",
            "Access-Control-Allow-Origin":      ALLOWED_ORIGIN,
            "Access-Control-Allow-Headers":
                "Authorization,Content-Type,X-Workspace-Token,X-Admin-Token,X-API-Token,X-Member-Session-Token",
            "Access-Control-Allow-Methods":     "GET,PUT,POST,DELETE,PATCH,OPTIONS",
            "Access-Control-Allow-Credentials": "true",
        },
        "body": json.dumps(body, default=_serial),
    }


def text_resp(status: int, body: str, content_type: str = "text/plain",
              extra_headers: dict | None = None) -> dict:
    headers = {
        "Content-Type": content_type,
        "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
        "Access-Control-Allow-Headers": "Authorization,Content-Type,X-Workspace-Token,X-Admin-Token,X-API-Token,X-Member-Session-Token",
        "Access-Control-Allow-Methods": "GET,PUT,POST,DELETE,PATCH,OPTIONS",
    }
    if extra_headers:
        headers.update(extra_headers)
    return {"statusCode": status, "headers": headers, "body": body}


def _error_resp(status: int, code: str, message: str, details=None) -> dict:
    """Standard error envelope — frontend reads error.code for session decisions."""
    body = {
        "success": False,
        "data":    None,
        "error":   {"code": code, "message": message},
        "meta":    {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "requestId": secrets.token_hex(8),
        },
    }
    if details is not None:
        body["error"]["details"] = str(details)
    return resp(status, body)


# ── Workspace auth decorator ──────────────────────────────────────────────────
# Defence-in-depth: every handle_ws_* function that touches workspace data must
# be decorated. If the internal _verify_workspace_access call is ever omitted,
# the decorator catches it and blocks unauthenticated access.
#
# Usage:
#   @workspace_auth("VIEWER")
#   def handle_ws_something(workspace_id, headers, ...):
#       ...
#
# Intentionally NOT decorated (see routing comments):
#   - /health, /, /eol/general* — public endpoints
#   - /auth/* — pre-workspace bootstrap; no token yet
#   - POST /workspaces — workspace creation; no token yet
#   - GET /workspaces/:wsId/validate — credential test endpoint
#   - Admin-only routes — protected by _verify_admin() separately
#   - handle_ws_member_accept_invite, handle_ws_member_login_link,
#     handle_ws_member_complete_login — invite/magic-link flows (no session yet)
#
# NOTE: _verify_workspace_access is defined later in this file. The wrapper
# closure references it by name; Python resolves names at call time, so the
# forward reference is safe.

_request_ctx = _threading.local()   # per-request verified ws + actor


def workspace_auth(required_role: str = "VIEWER"):
    """Decorator factory. Enforces workspace auth before the handler body runs.

    On success: stores (ws, actor) in _request_ctx thread-local.
    On failure: returns 401/403 — handler body never executes.
    """
    def decorator(fn):
        sig         = inspect.signature(fn)
        param_names = list(sig.parameters.keys())
        ws_idx      = param_names.index("workspace_id") if "workspace_id" in param_names else -1
        hdr_idx     = param_names.index("headers")      if "headers"      in param_names else -1

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            workspace_id = (args[ws_idx]  if ws_idx  >= 0 and ws_idx  < len(args)
                            else kwargs.get("workspace_id", ""))
            hdrs         = (args[hdr_idx] if hdr_idx >= 0 and hdr_idx < len(args)
                            else kwargs.get("headers", {}))

            ws, actor, err = _verify_workspace_access(workspace_id, hdrs, required_role)
            if not ws:
                status = 403 if err == "INSUFFICIENT_ROLE" else 401
                return _error_resp(status, err, "Workspace authentication required")

            _request_ctx.ws    = ws
            _request_ctx.actor = actor
            return fn(*args, **kwargs)

        wrapper._workspace_auth_role = required_role
        wrapper._workspace_auth      = True
        return wrapper
    return decorator


# ── Route Handlers ────────────────────────────────────────────────────────────

def handle_inventory(params: dict) -> dict:
    storage = get_storage()
    filters = {k: params.get(k) for k in ("service", "status", "region") if params.get(k)}
    items = storage.get_resources(filters or None)
    return resp(200, {"items": items, "count": len(items)})


def handle_summary() -> dict:
    storage = get_storage()
    items = storage.get_resources()

    summary: dict = {}
    totals: dict = {"EOL": 0, "EXPIRING_SOON": 0, "EXTENDED_SUPPORT": 0, "SUPPORTED": 0, "UNKNOWN": 0}
    regions: set = set()
    last_scanned: str = ""

    for item in items:
        svc = item.get("service_type", "Unknown")
        sts = item.get("eol_status", "UNKNOWN")
        summary.setdefault(svc, {"EOL": 0, "EXPIRING_SOON": 0, "EXTENDED_SUPPORT": 0, "SUPPORTED": 0, "UNKNOWN": 0})
        summary[svc][sts] = summary[svc].get(sts, 0) + 1
        totals[sts] = totals.get(sts, 0) + 1
        if item.get("region"):
            regions.add(item["region"])
        scanned_at = str(item.get("scanned_at") or "")
        if scanned_at > last_scanned:
            last_scanned = scanned_at

    return resp(200, {
        "by_service":     summary,
        "totals":         totals,
        "resources_count": len(items),
        "regions_count":  len(regions),
        "last_scanned":   last_scanned or None,
    })


# ── CK Upgrade Guide matching ─────────────────────────────────────────────────

_SVC_NORM = {
    "lambda":      "Lambda",    "ec2":         "EC2",
    "eks":         "EKS",       "rds":         "RDS",
    "elasticache": "ElastiCache","opensearch":  "OpenSearch",
    "documentdb":  "DocumentDB","neptune":     "Neptune",
    "glue":        "Glue",      "msk":         "MSK",
    "codebuild":   "CodeBuild", "elasticbeanstalk": "ElasticBeanstalk",
    "elastic beanstalk": "ElasticBeanstalk", "emr": "EMR",
    "cloudfrontfunctions": "CloudFrontFunctions", "cloudfront functions": "CloudFrontFunctions",
    "ecr":         "ECR",
    "aurora":      "Aurora",
}

def _norm_svc(svc: str) -> str:
    low = (svc or "").lower().strip()
    if low.startswith("rds_") or low.startswith("rds/"):
        return "RDS"
    if low.startswith("aurora"):
        return "Aurora"
    return _SVC_NORM.get(low, svc)


def match_upgrade_guide(service: str, version: str, storage) -> dict:
    """Return the best PUBLISHED CK guide for a resource, or None."""
    guides = storage.get_upgrade_guides()
    published = [
        g for g in guides
        if g.get("status") == "PUBLISHED" and g.get("guideType", "CK_GUIDE") == "CK_GUIDE"
    ]
    if not published:
        return None

    norm = _norm_svc(service)
    ver  = (version or "").strip()

    # Tier 1 — exact service + exact versionPattern
    t1 = [g for g in published
          if _norm_svc(g.get("service", "")) == norm and ver and g.get("versionPattern", "") == ver]
    if t1:
        return max(t1, key=lambda g: g.get("updatedAt", ""))

    # Tier 2 — service + wildcard/prefix versionPattern
    t2 = []
    for g in published:
        if _norm_svc(g.get("service", "")) != norm:
            continue
        pattern = (g.get("versionPattern") or "").strip()
        if not pattern or pattern == "*":
            continue
        if pattern.endswith("*") and ver.startswith(pattern[:-1]):
            t2.append(g)
        elif ver and (ver.startswith(pattern + ".") or ver.startswith(pattern + "-")):
            t2.append(g)
    if t2:
        return max(t2, key=lambda g: g.get("updatedAt", ""))

    # Tier 3 — service-level fallback (versionPattern="*" or empty)
    t3 = [g for g in published
          if _norm_svc(g.get("service", "")) == norm
          and (not g.get("versionPattern") or g.get("versionPattern") == "*")]
    if t3:
        return max(t3, key=lambda g: g.get("updatedAt", ""))

    return None



@workspace_auth("VIEWER")
def handle_ws_resource(workspace_id: str, resource_id: str, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    decoded_id = unquote(resource_id)
    storage = get_storage()
    item = storage.get_resource_by_id(decoded_id, workspace_id)
    if not item:
        return resp(404, {"error": "Resource not found"})

    ck_guide = match_upgrade_guide(
        item.get("service_type", ""), item.get("version", ""), storage
    )
    return resp(200, {"item": item, "ckGuide": ck_guide})


def handle_alerts(params: dict) -> dict:
    storage = get_storage()
    limit = int(params.get("limit", 100))
    items = (
        storage.get_resources({"status": "EOL"}) +
        storage.get_resources({"status": "EXPIRING_SOON"}) +
        storage.get_resources({"status": "EXTENDED_SUPPORT"})
    )
    items = sorted(items, key=lambda x: x.get("scanned_at", ""), reverse=True)[:limit]
    return resp(200, {"items": items, "count": len(items)})


def handle_config_get() -> dict:
    storage = get_storage()
    config = storage.get_config()
    return resp(200, config)


def handle_config_put(body: dict) -> dict:
    storage = get_storage()
    body.pop("config_key", None)
    storage.save_config(body)
    return resp(200, {"message": "Config saved"})


def _sanitize_config_patch(body: dict) -> dict:
    allowed = {
        "warn_days",
        "scan_schedule",
        "scan_org",
        "enabled_services",
        "external_id",
    }
    patch = {k: body[k] for k in allowed if k in body}
    if "warn_days" in patch:
        try:
            warn_days = int(patch["warn_days"])
        except (TypeError, ValueError):
            raise ValueError("Warning window must be a number of days.")
        if warn_days < 1 or warn_days > 1095:
            raise ValueError("Warning window must be between 1 and 1095 days.")
        patch["warn_days"] = warn_days
    if "enabled_services" in patch and not isinstance(patch["enabled_services"], list):
        raise ValueError("enabled_services must be a list.")
    if "scan_org" in patch:
        patch["scan_org"] = bool(patch["scan_org"])
    if "external_id" in patch:
        ext_id = str(patch["external_id"]).strip()
        if not ext_id or len(ext_id) > 100:
            raise ValueError("external_id must be a non-empty string (max 100 chars).")
        patch["external_id"] = ext_id
    return patch


@workspace_auth("VIEWER")
def handle_ws_config_get(workspace_id: str, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    config = get_storage().get_workspace_config(workspace_id)
    return resp(200, {**config, "workspace_id": workspace_id})


@workspace_auth("ADMIN")
def handle_ws_config_patch(workspace_id: str, body: dict, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    try:
        patch = _sanitize_config_patch(body)
    except ValueError as exc:
        return _error_resp(400, "CONFIG_INVALID", str(exc))
    storage = get_storage()
    existing = storage.get_workspace_config(workspace_id)
    config = storage.save_workspace_config(workspace_id, {**existing, **patch})
    return resp(200, {**config, "workspace_id": workspace_id})


def handle_general_eol(params: dict) -> dict:
    """Cache-first — never blocks on external network. Returns instantly."""
    storage = get_storage()
    result  = _general_eol.get_cached_only(storage)

    if result.is_empty:
        return resp(503, {"ok": False, "error": {
            "code":    "CACHE_EMPTY",
            "message": "Lifecycle cache is empty. Run POST /eol/general/refresh to load data.",
            "details": {"refreshEndpoint": "/eol/general/refresh"},
        }})

    # Overlay verified_lifecycle records (no network — DB read only)
    merged_records, overlay_count = _general_eol.merge_verified_lifecycle(result.records, storage)

    include_legacy = params.get("includeLegacy", "false").lower() == "true"
    filtered = _general_eol.filter_records(
        merged_records,
        service=params.get("service", ""),
        status=params.get("status", ""),
        search=params.get("search", ""),
        include_legacy=include_legacy,
    )

    logger.info("GET /eol/general filtered=%d includeLegacy=%s stale=%s verified_overlay=%d",
                len(filtered), include_legacy, result.is_stale, overlay_count)

    return resp(200, {
        "ok": True,
        "data": filtered,
        "meta": {
            "total":                  len(filtered),
            "refreshed_at":           result.refreshed_at,
            "source":                 "mixed" if overlay_count > 0 else "endoflife.date",
            "sources":                ["endoflife.date", "verified_lifecycle"] if overlay_count > 0 else ["endoflife.date"],
            "verified_overlay_count": overlay_count,
            "endoflife_count":        len(result.records),
            "include_legacy":         include_legacy,
            "stale":                  result.is_stale,
            "refresh_recommended":    result.is_stale,
        },
    })


def handle_general_eol_summary(params: dict = None) -> dict:
    """Cache-first — returns instantly from cache."""
    params  = params or {}
    storage = get_storage()
    result  = _general_eol.get_cached_only(storage)

    if result.is_empty:
        return resp(503, {"ok": False, "error": {
            "code":    "CACHE_EMPTY",
            "message": "Lifecycle cache is empty. Run POST /eol/general/refresh to load data.",
            "details": {"refreshEndpoint": "/eol/general/refresh"},
        }})

    include_legacy = params.get("includeLegacy", "false").lower() == "true"
    filtered = _general_eol.filter_records(result.records, include_legacy=include_legacy)
    counts   = _general_eol.compute_summary(filtered)
    return resp(200, {
        "ok": True,
        "data": counts,
        "meta": {
            "total":               sum(counts.values()),
            "refreshed_at":        result.refreshed_at,
            "include_legacy":      include_legacy,
            "stale":               result.is_stale,
            "refresh_recommended": result.is_stale,
        },
    })


def handle_general_eol_refresh() -> dict:
    """Fetch fresh lifecycle data from endoflife.date and update cache. May take 15–30s."""
    storage = get_storage()
    try:
        records, refreshed_at = _general_eol.refresh(storage)
    except Exception as exc:
        logger.error("General EOL refresh failed: %s", exc)
        return resp(502, {"ok": False, "error": {
            "code":    "DATA_SOURCE_ERROR",
            "message": "Refresh failed — endoflife.date may be unreachable",
        }})
    return resp(200, {"ok": True, "meta": {"total": len(records), "refreshed_at": refreshed_at}})


# ── Admin middleware ──────────────────────────────────────────────────────────

def _verify_admin(headers: dict) -> bool:
    """Constant-time hash-compare incoming X-Admin-Token against the live token.

    Uses _get_admin_token() so Secrets Manager cache refreshes are honoured at
    runtime (e.g. after secret rotation) without requiring a process restart.
    """
    current_token = _get_admin_token()
    if not current_token:
        return False
    incoming = headers.get("x-admin-token", "")
    if not incoming:
        return False
    incoming_hash = hashlib.sha256(incoming.encode()).hexdigest()
    current_hash  = hashlib.sha256(current_token.encode()).hexdigest()
    return hmac.compare_digest(incoming_hash, current_hash)

# ── Admin route handlers ──────────────────────────────────────────────────────

def handle_admin_validate(headers: dict) -> dict:
    if not _get_admin_token():
        return _error_resp(503, "ADMIN_NOT_CONFIGURED",
                           "Admin portal not configured. Set ADMIN_PORTAL_SECRET_ID "
                           "(production) or ADMIN_PORTAL_TOKEN (development).")
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Invalid admin token.")
    return resp(200, {"valid": True})

def handle_admin_workspaces_list(headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    storage    = get_storage()
    workspaces = storage.get_workspaces()
    accounts   = storage.get_accounts()
    result = []
    for ws in workspaces:
        acct_count = sum(1 for a in accounts if a.get("workspace_id") == ws.get("id"))
        result.append({
            "id":            ws["id"],
            "name":          ws.get("name", ""),
            "created_at":    ws.get("created_at", ""),
            "rotated_at":    ws.get("rotated_at"),
            "account_count": acct_count,
        })
    return resp(200, {"workspaces": result, "count": len(result)})

def handle_admin_workspace_rotate(workspace_id: str, headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    storage   = get_storage()
    workspace = storage.get_workspace(workspace_id)
    if not workspace:
        return _error_resp(404, "WORKSPACE_NOT_FOUND", "Workspace not found")
    new_token              = f"eolm_live_{secrets.token_hex(20)}"
    workspace["token_hash"] = _hash_token(new_token)
    workspace["rotated_at"] = datetime.now(timezone.utc).isoformat()
    storage.save_workspace(workspace)
    return resp(200, {
        "rotated": True,
        "token":   new_token,
        "note":    "Save this token — it will not be shown again.",
    })

def handle_admin_workspace_delete(workspace_id: str, headers: dict, params: dict | None = None) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    storage      = get_storage()
    workspace    = storage.get_workspace(workspace_id)
    if not workspace:
        return _error_resp(404, "WORKSPACE_NOT_FOUND", "Workspace not found")
    # Require caller to confirm by echoing back the workspace name or ID.
    # Frontend sends ?confirmation=<name> or confirmation in query params.
    confirmation = (params or {}).get("confirmation", "").strip()
    ws_name      = (workspace.get("name") or "").strip()
    accepted     = {workspace_id, ws_name} - {""}
    if not confirmation or confirmation not in accepted:
        return _error_resp(400, "CONFIRMATION_REQUIRED",
                           "Send ?confirmation=<workspace name or id> to confirm deletion")
    deleted = storage.delete_workspace(workspace_id)
    if not deleted:
        return _error_resp(500, "DELETE_FAILED", "Delete failed unexpectedly")
    return resp(200, {"deleted": True, "id": workspace_id})


def handle_admin_scans_list(headers: dict, params: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    workspace_id = params.get("workspaceId")
    status       = params.get("status") or None
    search       = params.get("search", "").strip() or None
    limit        = min(int(params.get("limit",  25)), 200)
    offset       = max(int(params.get("offset",  0)),   0)
    storage      = get_storage()
    result       = storage.get_all_scan_runs_admin(
        workspace_id=workspace_id, status=status, search=search,
        limit=limit, offset=offset,
    )
    runs  = result["runs"]
    total = result["total"]
    # Enrich with workspace name and apply workspace-name search (Postgres only filters accountId)
    ws_cache: dict = {}
    for run in runs:
        wid = run.get("workspaceId", "")
        if wid and wid not in ws_cache:
            ws = storage.get_workspace(wid)
            ws_cache[wid] = ws.get("name", wid) if ws else wid
        run["workspaceName"] = ws_cache.get(wid, wid)
    # For Postgres the search matched accountId; also apply workspace-name match so the
    # frontend's "filter by workspace name" works even when the DB returns the full page.
    if search:
        q = search.lower()
        runs = [r for r in runs if
                q in (r.get("workspaceName") or "").lower() or
                q in (r.get("workspaceId")   or "").lower() or
                q in (r.get("accountId")      or "").lower()]
    return resp(200, {
        "scans":       runs,
        "total":       total,
        "limit":       limit,
        "offset":      offset,
        "hasMore":     offset + len(runs) < total,
        "count":       len(runs),          # backwards-compat alias
        "failedCount": sum(1 for r in runs if r.get("status") == "FAILED"),
    })


def handle_admin_system(headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    from storage import STORAGE_BACKEND
    storage = get_storage()
    # EOL cache status
    cache_result = _general_eol.get_cached_only(storage)
    now_iso  = datetime.now(timezone.utc).isoformat()
    # Total scan runs (limit=200 for system overview stats only)
    runs_result = storage.get_all_scan_runs_admin(limit=200)
    all_runs    = runs_result["runs"]
    runs_total  = runs_result["total"]
    return resp(200, {
        "backend": {
            "status":         "ok",
            "storage":        STORAGE_BACKEND,
            "timestamp":      now_iso,
        },
        "eolCache": {
            "isEmpty":        cache_result.is_empty,
            "isStale":        cache_result.is_stale,
            "refreshedAt":    cache_result.refreshed_at or None,
            "recordCount":    len(cache_result.records),
        },
        "scanRuns": {
            "total":          runs_total,
            "failed":         sum(1 for r in all_runs if r.get("status") == "FAILED"),
            "running":        sum(1 for r in all_runs if r.get("status") == "RUNNING"),
        },
        "featureFlags": {
            "organizationScan": FEATURE_FLAGS["orgScan"],
            "remediation":      FEATURE_FLAGS["remediation"],
            "ssoSaml":          FEATURE_FLAGS["sso"],
            "billing":          FEATURE_FLAGS["billing"],
            "cicdScanOnPush":   FEATURE_FLAGS["cicdScan"],
        },
    })


def handle_admin_eol_refresh(headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    return handle_general_eol_refresh()


# ── Admin upgrade guide CRUD ──────────────────────────────────────────────────

_GUIDE_ERR = {
    "GUIDE_TITLE_REQUIRED":   "Guide title is required.",
    "GUIDE_SERVICE_REQUIRED": "Service is required.",
    "GUIDE_URL_REQUIRED":     "Guide URL is required.",
    "GUIDE_URL_INVALID":      "Guide URL must start with http:// or https://",
    "GUIDE_DUPLICATE":        "",  # message built dynamically
}

def _validate_guide_body(body: dict) -> str:
    """Return error code or empty string."""
    if not (body.get("title") or "").strip():
        return "GUIDE_TITLE_REQUIRED"
    if not (body.get("service") or "").strip():
        return "GUIDE_SERVICE_REQUIRED"
    url = (body.get("guideUrl") or "").strip()
    if not url:
        return "GUIDE_URL_REQUIRED"
    if not (url.startswith("http://") or url.startswith("https://")):
        return "GUIDE_URL_INVALID"
    return ""


def handle_admin_guides_list(headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    guides = get_storage().get_upgrade_guides()
    guides = sorted(guides, key=lambda g: g.get("updatedAt", ""), reverse=True)
    return resp(200, {"guides": guides, "count": len(guides)})


def handle_admin_guide_get(guide_id: str, headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    guide = next((g for g in get_storage().get_upgrade_guides() if g.get("id") == guide_id), None)
    if not guide:
        return _error_resp(404, "GUIDE_NOT_FOUND", "Upgrade guide not found")
    return resp(200, {"guide": guide})


def handle_admin_guide_create(body: dict, headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    err = _validate_guide_body(body)
    if err:
        return _error_resp(400, err, _GUIDE_ERR[err])

    # Prevent duplicate guide for same service + versionPattern
    new_svc = _norm_svc((body.get("service") or "").strip())
    new_ver = (body.get("versionPattern") or "").strip()
    existing = next(
        (g for g in get_storage().get_upgrade_guides()
         if _norm_svc(g.get("service", "")) == new_svc
         and (g.get("versionPattern") or "") == new_ver),
        None,
    )
    if existing:
        label = f"{(body.get('service') or '').strip()} {new_ver}".strip()
        return _error_resp(
            409, "GUIDE_DUPLICATE",
            f"A guide for '{label}' already exists (id: {existing['id']}, "
            f"status: {existing.get('status', 'DRAFT')}). Update the existing guide instead.",
        )

    now   = datetime.now(timezone.utc).isoformat()
    status = body.get("status", "DRAFT")
    guide = {
        "id":             f"guide_{secrets.token_hex(10)}",
        "title":          (body.get("title") or "").strip(),
        "service":        (body.get("service") or "").strip(),
        "versionPattern": (body.get("versionPattern") or "").strip(),
        "targetVersion":  (body.get("targetVersion") or "").strip(),
        "guideUrl":       (body.get("guideUrl") or "").strip(),
        "guideType":      body.get("guideType", "CK_GUIDE"),
        "testedInLab":    bool(body.get("testedInLab", False)),
        "status":         status if status in ("DRAFT", "PUBLISHED") else "DRAFT",
        "summary":        (body.get("summary") or "").strip(),
        "createdAt":      now,
        "updatedAt":      now,
    }
    return resp(201, {"guide": get_storage().save_upgrade_guide(guide)})


def handle_admin_guide_update(guide_id: str, body: dict, headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    storage  = get_storage()
    existing = next((g for g in storage.get_upgrade_guides() if g.get("id") == guide_id), None)
    if not existing:
        return _error_resp(404, "GUIDE_NOT_FOUND", "Upgrade guide not found")
    updated = dict(existing)
    for field in ("title", "service", "versionPattern", "targetVersion", "guideUrl", "summary"):
        if field in body:
            updated[field] = (body[field] or "").strip()
    if "guideType"   in body: updated["guideType"]   = body["guideType"]
    if "testedInLab" in body: updated["testedInLab"] = bool(body["testedInLab"])
    if "status"      in body:
        s = body["status"]
        updated["status"] = s if s in ("DRAFT", "PUBLISHED") else "DRAFT"
    updated["updatedAt"] = datetime.now(timezone.utc).isoformat()
    err = _validate_guide_body(updated)
    if err:
        return _error_resp(400, err, _GUIDE_ERR[err])
    return resp(200, {"guide": storage.save_upgrade_guide(updated)})


def handle_admin_guide_delete(guide_id: str, headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    if not get_storage().delete_upgrade_guide(guide_id):
        return _error_resp(404, "GUIDE_NOT_FOUND", "Upgrade guide not found")
    return resp(200, {"deleted": True, "id": guide_id})


# ── Admin MCP lifecycle validation ───────────────────────────────────────────

def handle_admin_eol_validate_mcp(body: dict, headers: dict) -> dict:
    """POST /admin/eol/validate-mcp — validate a product/version against AWS official docs.

    Safety contract:
    - Admin token required; never exposed publicly.
    - Calls aws_mcp_validator only (never boto3 account scan).
    - Does NOT access customer AWS accounts.
    - Only saves record when validationStatus="verified".
    - Returns validator result even when not saving.
    """
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")

    product = (body.get("product") or "").strip()
    version = (body.get("version") or "").strip()
    if not product or not version:
        return _error_resp(400, "MISSING_FIELDS", "product and version are required")

    # Fetch current endoflife.date value for conflict detection (read-only, no scan)
    endoflife_eol_date = None
    try:
        import requests as _req
        eol_api = os.environ.get("EOL_API_BASE", "https://endoflife.date/api")
        r = _req.get(f"{eol_api}/{product}/{version}.json", timeout=10)
        if r.status_code == 200:
            raw = r.json()
            endoflife_eol_date = raw.get("eolFrom") or raw.get("eol") or None
            if endoflife_eol_date is False:
                endoflife_eol_date = None
    except Exception as exc:
        logger.debug("endoflife.date fetch for conflict detection failed: %s", exc)

    # Call MCP validator (stub returns not_configured; real MCP when AWS_MCP_ENABLED=true)
    try:
        from lifecycle.aws_mcp_validator import validate_lifecycle_with_aws_mcp
        result = validate_lifecycle_with_aws_mcp(product, version,
                                                  endoflife_eol_date=endoflife_eol_date)
    except Exception as exc:
        logger.error("MCP validator error for %s/%s: %s", product, version, exc)
        return _error_resp(500, "MCP_VALIDATOR_ERROR", f"Validator error: {exc}")

    # Only persist when fully verified — do not save needs_review/not_configured/not_found
    saved = False
    if result.get("validationStatus") == "verified":
        try:
            get_storage().save_verified_lifecycle(product, version, result)
            saved = True
            logger.info("Verified lifecycle saved: %s/%s source=%s conflict=%s",
                        product, version, result.get("lifecycle_source"), result.get("conflict"))
        except Exception as exc:
            logger.error("Failed to save verified lifecycle %s/%s: %s", product, version, exc)
            return _error_resp(500, "STORAGE_ERROR", f"Failed to save verified lifecycle: {exc}")

    return resp(200, {
        "product":         product,
        "version":         version,
        "saved":           saved,
        "validationResult": result,
    })


# ── Admin EOL overrides ───────────────────────────────────────────────────────

def handle_admin_eol_override_list(headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    overrides = get_storage().list_eol_overrides()
    return resp(200, {"overrides": overrides, "total": len(overrides)})


def handle_admin_eol_override_create(body: dict, headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    product = (body.get("product") or "").strip()
    version = (body.get("version") or "").strip()
    if not product or not version:
        return _error_resp(400, "MISSING_FIELDS", "product and version are required")
    record = {
        "eolDate":          body.get("eolDate"),
        "supportEndDate":   body.get("supportEndDate"),
        "finalEolDate":     body.get("finalEolDate"),
        "sourceUrl":        (body.get("sourceUrl") or "").strip(),
        "reason":           (body.get("reason") or "").strip(),
        "updatedBy":        (body.get("updatedBy") or headers.get("x-admin-user", "admin")).strip(),
    }
    saved = get_storage().save_eol_override(product, version, record)
    # Invalidate in-memory override cache so next fetch picks up the new record
    try:
        import eol_collector as _ec
        _ec._OVERRIDES_LOADED = False
    except Exception:
        pass
    return resp(201, {"override": saved})


def handle_admin_eol_override_delete(product: str, version: str, headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
    deleted = get_storage().delete_eol_override(product, version)
    if not deleted:
        return _error_resp(404, "OVERRIDE_NOT_FOUND", "EOL override not found")
    try:
        import eol_collector as _ec
        _ec._OVERRIDES_LOADED = False
    except Exception:
        pass
    return resp(200, {"deleted": True, "product": product, "version": version})


# ── Workspace helpers ─────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def _verify_workspace(workspace_id: str, headers: dict):
    """Return workspace dict if credentials valid, else None (legacy signature)."""
    ws, _ = _verify_workspace_ex(workspace_id, headers)
    return ws

def _verify_workspace_ex(workspace_id: str, headers: dict):
    """Return (workspace_dict, None) on success or (None, error_code) on failure.
    Accepts either:
      A) X-Workspace-Token header (existing flow — always tried first)
      B) eolm_session cookie with a valid workspace membership (new auth flow)
    Error codes match the SESSION_ERROR_CODES set in the frontend interceptor."""
    token = headers.get("x-workspace-token", "")

    if token:
        # ── Path A: workspace token (existing, unchanged) ──────────────────────
        storage   = get_storage()
        workspace = storage.get_workspace(workspace_id)
        if not workspace:
            return None, "WORKSPACE_NOT_FOUND"
        if _hash_token(token) != workspace.get("token_hash", ""):
            return None, "WORKSPACE_TOKEN_INVALID"
        return workspace, None

    # ── Path B: session cookie + membership ────────────────────────────────────
    if FEATURE_FLAGS.get("authSessionCookie"):
        try:
            from auth_handler import lookup_session_membership
            membership = lookup_session_membership(headers, workspace_id)
            if membership:
                storage   = get_storage()
                workspace = storage.get_workspace(workspace_id)
                if workspace:
                    workspace = dict(workspace)  # don't mutate cached object
                    workspace["_auth_role"] = membership["role"]
                    workspace["_auth_user"] = membership.get("email", "")
                    return workspace, None
        except Exception as _exc:
            logger.warning("session workspace lookup failed: %s", type(_exc).__name__)

    return None, "WORKSPACE_TOKEN_MISSING"

# ── Workspace route handlers ──────────────────────────────────────────────────

def handle_workspace_create(body: dict, headers: dict, client_ip: str = "unknown") -> dict:
    if not FEATURE_FLAGS.get("anonymousWorkspaceCreate", True):
        # When disabled, only authenticated users (session cookie) may create workspaces.
        from auth_handler import lookup_session
        if not lookup_session(headers):
            return _error_resp(403, "ANONYMOUS_CREATE_DISABLED",
                               "Workspace creation requires a logged-in account.")

    allowed, retry_after = _rl_check(
        f"ws_create:{client_ip}", _WS_CREATE_LIMIT, _WS_CREATE_WINDOW
    )
    if not allowed:
        logger.warning(
            "workspace create rate limited ip=%s retry_after=%ds", client_ip, retry_after
        )
        return _rate_limited_resp(
            retry_after,
            "Too many workspace creation attempts. Please try again later.",
        )
    name = (body.get("name") or "").strip()
    if not name:
        return resp(400, {"error": "name is required"})
    token       = f"eolm_live_{secrets.token_hex(20)}"
    workspace   = {
        "id":          f"ws_{secrets.token_hex(8)}",
        "name":        name,
        "token_hash":  _hash_token(token),
        "created_at":  datetime.now(timezone.utc).isoformat(),
    }
    get_storage().save_workspace(workspace)
    return resp(201, {
        "workspace_id": workspace["id"],
        "name":         workspace["name"],
        "token":        token,
        "note":         "Save this token — it will not be shown again.",
    })

def handle_workspace_validate(workspace_id: str, headers: dict) -> dict:
    ws = _verify_workspace(workspace_id, headers)
    if not ws:
        return resp(401, {"error": "Invalid workspace ID or token"})
    return resp(200, {"valid": True, "workspace": {"id": ws["id"], "name": ws["name"]}})

# ── Scan helpers ──────────────────────────────────────────────────────────────

def _summary_from_resources(resources: list) -> dict:
    counts = {"total": len(resources), "EOL": 0, "EXPIRING_SOON": 0, "EXTENDED_SUPPORT": 0,
              "SUPPORTED": 0, "UNKNOWN": 0, "NEEDS_INSPECTION": 0, "LIFECYCLE_NOT_TRACKED": 0}
    for r in resources:
        status = r.get("eol_status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    return counts

def _warnings_from_resources(resources: list) -> list:
    warnings = []
    seen = set()
    for r in resources:
        warning = (r.get("scan_warning") or "").strip()
        if warning and warning not in seen:
            warnings.append({"code": "SCAN_WARNING", "message": warning})
            seen.add(warning)
    return warnings

def _combined_scan_warnings(resources: list) -> list:
    warnings = _warnings_from_resources(resources)
    seen = {(w.get("code"), w.get("message")) for w in warnings if isinstance(w, dict)}
    try:
        from eol_collector import get_scan_warnings
        for warning in get_scan_warnings():
            key = (warning.get("code"), warning.get("message"))
            if key not in seen:
                warnings.append(warning)
                seen.add(key)
    except Exception:
        pass
    return warnings

def _resolve_account_regions(account: dict) -> list | None:
    """Return region list, or None to signal 'scan all enabled regions'."""
    # New canonical format: explicit scanAllRegions flag
    if account.get("scanAllRegions") is True:
        logger.info("Scan config: scanAllRegions=True → all enabled regions")
        return None

    regions = account.get("regions")

    # New canonical format: regions is a list
    if isinstance(regions, list):
        if regions:
            logger.info("Scan config: regions=%s, scanAllRegions=False", regions)
            return regions
        logger.info("Scan config: regions=[] → all enabled regions")
        return None

    # Legacy string format
    if regions == "all":
        logger.info("Scan config: legacy regions='all' → all enabled regions")
        return None
    if regions == "selected":
        r = account.get("selectedRegions") or []
        if r:
            logger.info("Scan config: legacy selected regions=%s", r)
            return r

    sr = account.get("singleRegion") or "us-east-1"
    logger.info("Scan config: single region=%s", sr)
    return [sr]

# ── Workspace-scoped account scan ─────────────────────────────────────────────

# ── Workspace-scoped account handlers ─────────────────────────────────────────

_ACCOUNTS_LIST_LIMIT = int(os.environ.get("ACCOUNTS_LIST_LIMIT", "500"))

@workspace_auth("VIEWER")
def handle_ws_accounts_list(workspace_id: str, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    accounts = get_storage().get_accounts(workspace_id)
    truncated = len(accounts) > _ACCOUNTS_LIST_LIMIT
    if truncated:
        accounts = accounts[:_ACCOUNTS_LIST_LIMIT]
    return resp(200, {"accounts": accounts, "count": len(accounts), "truncated": truncated})

def _sts_validate_role(role_arn: str, external_id: str, account_id: str) -> tuple:
    """Attempt STS AssumeRole + GetCallerIdentity. Returns (ok, error_code, safe_message)."""
    try:
        creds = boto3.client("sts").assume_role(
            RoleArn=role_arn,
            RoleSessionName="eol-monitor-validate",
            ExternalId=external_id,
        )["Credentials"]
        identity = boto3.client(
            "sts",
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        ).get_caller_identity()
        if identity.get("Account", "") != account_id:
            return False, "ROLE_ACCOUNT_MISMATCH", \
                   "Assumed identity does not match the provided AWS account ID."
        return True, "", ""
    except Exception as exc:
        err = str(exc)
        logger.error("AssumeRole validation failed: role=%s err=%s", role_arn[:60], err)
        if "AccessDenied" in err:
            return False, "ACCESS_DENIED", \
                   "Access denied. Verify the IAM role trust policy allows this account."
        if "ExternalId" in err or "external" in err.lower():
            return False, "EXTERNAL_ID_MISMATCH", \
                   "ExternalId mismatch. The trust policy ExternalId must match exactly."
        return False, "ASSUME_ROLE_FAILED", \
               "Unable to assume this role. Check the trust policy, ExternalId, and role ARN."


@workspace_auth("ADMIN")
def handle_ws_account_validate_role(workspace_id: str, body: dict, headers: dict) -> dict:
    """POST /workspaces/:wsId/accounts/validate-role — STS AssumeRole test before saving."""
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    role_arn    = (body.get("roleArn") or "").strip()
    external_id = (body.get("externalId") or "").strip()
    account_id  = (body.get("awsAccountId") or "").strip()

    if not re.fullmatch(r'\d{12}', account_id):
        return _error_resp(400, "INVALID_ACCOUNT_ID", "awsAccountId must be exactly 12 digits")
    arn_m = re.fullmatch(r'arn:aws:iam::(\d{12}):role/.+', role_arn)
    if not arn_m:
        return _error_resp(400, "INVALID_ROLE_ARN",
                           "roleArn must match arn:aws:iam::123456789012:role/RoleName")
    if arn_m.group(1) != account_id:
        return _error_resp(400, "ROLE_ACCOUNT_MISMATCH",
                           "Account ID in Role ARN does not match awsAccountId")
    if not external_id:
        return _error_resp(400, "VALIDATION_FAILED", "externalId is required")

    logger.info("Validating role: workspace=%s arn=%s account=%s",
                workspace_id, role_arn[:60], account_id)
    ok, code, msg = _sts_validate_role(role_arn, external_id, account_id)
    if not ok:
        return _error_resp(403, code, msg)

    logger.info("Role validation OK: workspace=%s account=%s", workspace_id, account_id)
    return resp(200, {
        "ok": True, "validated": True,
        "accountId": account_id, "roleArn": role_arn,
        "message": "Role validated successfully.",
    })


@workspace_auth("ADMIN")
def handle_ws_account_save(workspace_id: str, body: dict, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    if not body.get("id") or not body.get("accountId") or not body.get("roleArn"):
        return resp(400, {"error": "Missing required fields: id, accountId, roleArn"})

    # Re-validate before saving to prevent frontend bypass
    role_arn    = (body.get("roleArn") or "").strip()
    external_id = (body.get("externalId") or "").strip()
    account_id  = (body.get("accountId") or "").strip()
    arn_m = re.fullmatch(r'arn:aws:iam::(\d{12}):role/.+', role_arn)
    if not arn_m or arn_m.group(1) != account_id:
        return _error_resp(400, "INVALID_ROLE_ARN",
                           "Invalid Role ARN or account ID mismatch")
    ok, code, msg = _sts_validate_role(role_arn, external_id, account_id)
    if not ok:
        return _error_resp(403, code, msg)

    body["workspace_id"] = workspace_id
    account = get_storage().save_account(body)
    return resp(200, {"account": account})

@workspace_auth("ADMIN")
def handle_ws_account_update(workspace_id: str, account_id: str, body: dict, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    storage  = get_storage()
    existing = next((a for a in storage.get_accounts(workspace_id) if a.get("id") == account_id), None)
    if not existing:
        return resp(404, {"error": "Account not found"})
    merged = {**existing, **body, "id": account_id, "workspace_id": workspace_id}

    # Re-validate STS if roleArn or externalId changed (prevents silent ARN swap)
    new_arn = merged.get("roleArn", "")
    new_ext = merged.get("externalId", "")
    new_aid = merged.get("accountId", "")
    if body.get("roleArn") or body.get("externalId"):
        arn_m = re.fullmatch(r'arn:aws:iam::(\d{12}):role/.+', new_arn)
        if not arn_m or arn_m.group(1) != new_aid:
            return _error_resp(400, "INVALID_ROLE_ARN", "Invalid Role ARN or account ID mismatch")
        ok, code, msg = _sts_validate_role(new_arn, new_ext, new_aid)
        if not ok:
            return _error_resp(403, code, msg)

    account = storage.save_account(merged)
    return resp(200, {"account": account})

@workspace_auth("ADMIN")
def handle_ws_account_delete(workspace_id: str, account_id: str, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    storage = get_storage()
    deleted = storage.delete_account(account_id, workspace_id)
    if not deleted:
        return resp(404, {"error": "Account not found"})
    now = datetime.now(timezone.utc).isoformat()
    try:
        for alert in storage.get_alerts(workspace_id, account_id=account_id, limit=500):
            if alert.get("status") in ("ACTIVE", "ACKNOWLEDGED", "SNOOZED"):
                alert["status"]           = "RESOLVED"
                alert["resolvedAt"]       = now
                alert["resolvedReason"]   = "Account deleted"
                alert["resolutionSource"] = "account_deletion"
                storage.save_alert(alert)
    except Exception as _e:
        logger.warning("Alert cleanup on account delete partial: account=%s err=%s", account_id, _e)
    return resp(200, {"deleted": True, "id": account_id})


# ── Organization Scan (feature-gated foundation) ──────────────────────────────

def _org_feature_disabled() -> dict:
    return _error_resp(403, "FEATURE_DISABLED",
                       "Organization Scan is not enabled in this deployment.")


def _named_feature_disabled(name: str) -> dict:
    return _error_resp(403, "FEATURE_DISABLED",
                       f"{name} is not enabled in this deployment.")


def _require_org_feature():
    return None if FEATURE_FLAGS["orgScan"] else _org_feature_disabled()


def _safe_aws_error_code(exc: Exception, default: str) -> str:
    text = str(exc)
    if "AccessDenied" in text or "AccessDeniedException" in text:
        return "ORG_DISCOVERY_ACCESS_DENIED"
    if "NoSuchEntity" in text:
        return "MEMBER_ROLE_NOT_FOUND"
    return default


def _validate_org_role_input(body: dict) -> tuple[dict | None, dict | None]:
    name       = (body.get("name") or "AWS Organization").strip()
    account_id = (body.get("managementAccountId") or body.get("awsAccountId") or "").strip()
    role_arn   = (body.get("roleArn") or body.get("managementRoleArn") or "").strip()
    external_id = (body.get("externalId") or "").strip()
    regions    = body.get("regions", [])

    if not re.fullmatch(r"\d{12}", account_id):
        return None, _error_resp(400, "INVALID_ACCOUNT_ID",
                                 "managementAccountId must be exactly 12 digits")
    arn_m = re.fullmatch(r"arn:aws:iam::(\d{12}):role/.+", role_arn)
    if not arn_m:
        return None, _error_resp(400, "INVALID_ROLE_ARN",
                                 "roleArn must match arn:aws:iam::123456789012:role/RoleName")
    if arn_m.group(1) != account_id:
        return None, _error_resp(400, "ROLE_ACCOUNT_MISMATCH",
                                 "Account ID in Role ARN does not match managementAccountId")
    if not external_id:
        return None, _error_resp(400, "VALIDATION_FAILED", "externalId is required")
    if not isinstance(regions, list) or not all(isinstance(r, str) and r for r in regions):
        return None, _error_resp(400, "INVALID_REGIONS", "regions must be a list of region strings (empty = all regions)")

    return {
        "name": name,
        "managementAccountId": account_id,
        "roleArn": role_arn,
        "externalId": external_id,
        "regions": regions,
    }, None


@workspace_auth("VIEWER")
def handle_ws_org_status(workspace_id: str, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    storage = get_storage()
    connections = storage.get_org_connections(workspace_id)
    return resp(200, {
        "enabled": True,
        "configured": len(connections) > 0,
        "connectionsCount": len(connections),
    })


@workspace_auth("ADMIN")
def handle_ws_org_validate_role(workspace_id: str, body: dict, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    data, err = _validate_org_role_input(body)
    if err:
        return err
    ok, code, msg = _sts_validate_role(data["roleArn"], data["externalId"], data["managementAccountId"])
    if not ok:
        return _error_resp(403, code, msg)
    return resp(200, {
        "ok": True,
        "validated": True,
        "managementAccountId": data["managementAccountId"],
        "roleArn": data["roleArn"],
        "message": "Organization management role validated successfully.",
    })


@workspace_auth("VIEWER")
def handle_ws_org_connections_list(workspace_id: str, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    connections = get_storage().get_org_connections(workspace_id)
    return resp(200, {"connections": connections, "count": len(connections)})


@workspace_auth("VIEWER")
def handle_ws_org_connection_get(workspace_id: str, conn_id: str, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    conn = get_storage().get_org_connection(workspace_id, conn_id)
    if not conn:
        return _error_resp(404, "ORG_CONNECTION_NOT_FOUND", "Organization connection not found")
    return resp(200, {"connection": conn})


@workspace_auth("ADMIN")
def handle_ws_org_connection_create(workspace_id: str, body: dict, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    data, err = _validate_org_role_input(body)
    if err:
        return err
    ok, code, msg = _sts_validate_role(data["roleArn"], data["externalId"], data["managementAccountId"])
    now = datetime.now(timezone.utc).isoformat()
    conn = {
        "id":                  body.get("id") or f"org_conn_{secrets.token_hex(10)}",
        "workspaceId":         workspace_id,
        "name":                data["name"],
        "managementAccountId": data["managementAccountId"],
        "roleArn":             data["roleArn"],
        "externalId":          data["externalId"],
        "regions":             data["regions"],
        "status":              "CONNECTED" if ok else "VALIDATION_FAILED",
        "createdAt":           now,
        "updatedAt":           now,
        "lastDiscoveryAt":     None,
        "lastScanAt":          None,
        "lastScanId":          None,
        "lastScanStatus":      None,
        "lastScanSummary":     {},
        "lastErrorCode":       None if ok else code,
        "lastError":           None if ok else msg,
    }
    if not ok:
        return _error_resp(403, code, msg)
    get_storage().save_org_connection(conn)
    return resp(201, {"connection": conn})


@workspace_auth("ADMIN")
def handle_ws_org_connection_delete(workspace_id: str, conn_id: str, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    storage = get_storage()
    # Wipe inventory resources and resolve alerts for every member account under this connection.
    now = datetime.now(timezone.utc).isoformat()
    try:
        org_accounts = storage.get_org_accounts(workspace_id, conn_id)
        for acct in org_accounts:
            aws_id = acct.get("awsAccountId") or acct.get("aws_account_id") or ""
            if aws_id:
                storage.replace_resources_for_account(workspace_id, aws_id, [])
                for alert in storage.get_alerts(workspace_id, account_id=aws_id, limit=500):
                    if alert.get("status") in ("ACTIVE", "ACKNOWLEDGED", "SNOOZED"):
                        alert["status"]           = "RESOLVED"
                        alert["resolvedAt"]       = now
                        alert["resolvedReason"]   = "Organization connection deleted"
                        alert["resolutionSource"] = "account_deletion"
                        storage.save_alert(alert)
    except Exception as cleanup_exc:
        logger.warning("Org connection cleanup partial: conn=%s err=%s", conn_id, cleanup_exc)
    deleted = storage.delete_org_connection(workspace_id, conn_id)
    if not deleted:
        return _error_resp(404, "ORG_CONNECTION_NOT_FOUND", "Organization connection not found")
    return resp(200, {"deleted": True, "id": conn_id})


@workspace_auth("ADMIN")
def handle_ws_org_connection_patch(workspace_id: str, conn_id: str, body: dict, headers: dict) -> dict:
    """Soft-update a connection — status: DISCONNECTED | CONNECTED and/or regions: list."""
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    storage = get_storage()
    conn = storage.get_org_connection(workspace_id, conn_id)
    if not conn:
        return _error_resp(404, "ORG_CONNECTION_NOT_FOUND", "Organization connection not found")

    new_status  = body.get("status")
    new_regions = body.get("regions")  # None means not updating regions

    if new_status is None and new_regions is None:
        return _error_resp(400, "INVALID_REQUEST", "Provide status or regions to update")

    updated = {**conn, "updatedAt": datetime.now(timezone.utc).isoformat()}

    if new_status is not None:
        if new_status not in ("DISCONNECTED", "CONNECTED"):
            return _error_resp(400, "INVALID_STATUS", "status must be DISCONNECTED or CONNECTED")
        updated["status"] = new_status

    if new_regions is not None:
        if not isinstance(new_regions, list) or not all(isinstance(r, str) and r for r in new_regions):
            return _error_resp(400, "INVALID_REGIONS", "regions must be a list of region strings (empty = all regions)")
        updated["regions"] = new_regions

    storage.save_org_connection(updated)
    return resp(200, {"connection": updated})


def _assume_role_client(role_arn: str, external_id: str, service: str):
    creds = boto3.client("sts").assume_role(
        RoleArn=role_arn,
        RoleSessionName="eol-monitor-org",
        ExternalId=external_id,
    )["Credentials"]
    return boto3.client(
        service,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


def _assume_role_session(role_arn: str, external_id: str, account_id: str) -> boto3.Session:
    creds = boto3.client("sts").assume_role(
        RoleArn=role_arn,
        RoleSessionName=f"eol-monitor-org-{account_id}"[:64],
        ExternalId=external_id,
    )["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


@workspace_auth("ADMIN")
def handle_ws_org_discover(workspace_id: str, conn_id: str, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    storage = get_storage()
    conn = storage.get_org_connection(workspace_id, conn_id)
    if not conn:
        return _error_resp(404, "ORG_CONNECTION_NOT_FOUND", "Organization connection not found")
    try:
        org = _assume_role_client(conn["roleArn"], conn["externalId"], "organizations")
        paginator = org.get_paginator("list_accounts")
        # Build lookup of existing accounts to preserve scan history across rediscovery
        existing_accounts = {a["awsAccountId"]: a for a in storage.get_org_accounts(workspace_id, conn_id)}
        discovered = []
        now = datetime.now(timezone.utc).isoformat()
        mgmt_account_id = conn.get("managementAccountId", "")
        for page in paginator.paginate():
            for acct in page.get("Accounts", []):
                aws_id   = acct.get("Id", "")
                existing = existing_accounts.get(aws_id, {})
                rec = {
                    **existing,
                    "id":              f"org_acct_{conn_id}_{aws_id}",
                    "workspaceId":     workspace_id,
                    "orgConnectionId": conn_id,
                    "awsAccountId":    aws_id,
                    "name":            acct.get("Name", aws_id),
                    "email":           acct.get("Email", ""),
                    "status":          acct.get("Status", "ACTIVE"),
                    "accountType":     "MANAGEMENT" if aws_id == mgmt_account_id else "MEMBER",
                    "ouPath":          "/Root",
                    "joinedMethod":    acct.get("JoinedMethod"),
                    "discoveredAt":    now,
                }
                if "lastScanAt"      not in rec: rec["lastScanAt"]      = None
                if "lastScanId"      not in rec: rec["lastScanId"]      = None
                if "lastScanSummary" not in rec: rec["lastScanSummary"] = {}
                storage.save_org_account(rec)
                discovered.append(rec)
        storage.save_org_connection({
            **conn,
            "status": "CONNECTED",
            "updatedAt": now,
            "lastDiscoveryAt": now,
            "lastErrorCode": None,
            "lastError": None,
        })
        return resp(200, {"accounts": discovered, "count": len(discovered)})
    except Exception as exc:
        code = _safe_aws_error_code(exc, "ORG_DISCOVERY_FAILED")
        logger.error("Org discovery failed: workspace=%s conn=%s code=%s err=%s",
                     workspace_id, conn_id, code, exc)
        storage.save_org_connection({
            **conn,
            "status": "VALIDATION_FAILED",
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "lastErrorCode": code,
            "lastError": "Unable to discover organization accounts. Check Organizations permissions and trust policy.",
        })
        return _error_resp(403, code,
                           "Unable to discover organization accounts. Check Organizations permissions and trust policy.")


@workspace_auth("VIEWER")
def handle_ws_org_accounts_list(workspace_id: str, conn_id: str, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    storage = get_storage()
    if not storage.get_org_connection(workspace_id, conn_id):
        return _error_resp(404, "ORG_CONNECTION_NOT_FOUND", "Organization connection not found")
    accounts = storage.get_org_accounts(workspace_id, conn_id)
    return resp(200, {"accounts": accounts, "count": len(accounts)})


def _empty_org_summary() -> dict:
    return {"totalResources": 0, "eol": 0, "expiringSoon": 0,
            "extendedSupport": 0, "supported": 0, "unknown": 0}


def _org_summary_from_raw(raw_org_sum: dict) -> dict:
    return {
        "totalResources": raw_org_sum.get("total", 0),
        "eol":            raw_org_sum.get("EOL", 0),
        "expiringSoon":   raw_org_sum.get("EXPIRING_SOON", 0),
        "extendedSupport":raw_org_sum.get("EXTENDED_SUPPORT", 0),
        "supported":      raw_org_sum.get("SUPPORTED", 0),
        "unknown":        raw_org_sum.get("UNKNOWN", 0),
    }


def _initial_org_scan_run(workspace_id: str, conn_id: str, scan_id: str,
                          started_at: str, accounts_total: int) -> dict:
    return {
        "id":               scan_id,
        "workspaceId":      workspace_id,
        "orgConnectionId":  conn_id,
        "status":           "RUNNING",
        "startedAt":        started_at,
        "completedAt":      None,
        "accountsTotal":    accounts_total,
        "accountsScanned":  0,
        "accountsFailed":   0,
        "summary":          _empty_org_summary(),
        "warnings":         [],
        "errorCode":        None,
        "error":            None,
    }


def run_org_scan_worker(workspace_id: str, conn_id: str, scan_id: str) -> dict:
    storage = get_storage()
    conn = storage.get_org_connection(workspace_id, conn_id)
    if not conn:
        logger.error("Org scan worker missing connection: workspace=%s conn=%s scan=%s",
                     workspace_id, conn_id, scan_id)
        return {}
    accounts = [a for a in storage.get_org_accounts(workspace_id, conn_id) if a.get("status") == "ACTIVE"]
    now = datetime.now(timezone.utc).isoformat()
    run = storage.get_org_scan_run(workspace_id, scan_id) or _initial_org_scan_run(
        workspace_id, conn_id, scan_id, now, len(accounts)
    )
    warnings = []
    scanned = 0
    failed = 0
    all_resources: list[dict] = []

    from eol_collector import run_all_collectors, get_scan_warnings, OrgScanCancelled
    import concurrent.futures as _cf

    external_id = conn.get("externalId", "")
    regions     = conn.get("regions") or None

    # Per-account scan timeout (seconds). Prevents one hung account from blocking the whole run.
    _ACCT_TIMEOUT = int(os.environ.get("ORG_SCAN_ACCOUNT_TIMEOUT_SECONDS", "300"))

    def _should_cancel() -> bool:
        """Reads cancel flag from storage. Safe to call from the collector thread."""
        try:
            r = get_storage().get_org_scan_run(workspace_id, scan_id)
            return bool(r and r.get("cancelRequested"))
        except Exception:
            return False

    def _scan_one_account(acct: dict) -> tuple[dict, list, str, list]:
        """Returns (acct, resources, status_str, collector_warnings). Runs in thread pool."""
        aws_account_id  = acct.get("awsAccountId", "")
        member_role_arn = f"arn:aws:iam::{aws_account_id}:role/{ORG_MEMBER_ROLE_NAME}"
        session  = _assume_role_session(member_role_arn, external_id, aws_account_id)
        res_list = run_all_collectors(
            session, aws_account_id, regions=regions, cancel_check=_should_cancel
        )
        coll_warns = get_scan_warnings()          # captured after run_all_collectors clears + repopulates
        for r in res_list:
            r["workspace_id"]    = workspace_id
            r["workspaceId"]     = workspace_id
            r["account_id"]      = aws_account_id
            r["accountId"]       = aws_account_id
            r["scan_id"]         = scan_id
            r["scanId"]          = scan_id
            r["org_scan_id"]     = scan_id
            r["orgScanId"]       = scan_id
            r["orgConnectionId"] = conn_id
            r["scan_source"]     = "ORG_SCAN"
        return acct, res_list, "SUCCESS", coll_warns

    _POOL_SIZE = int(os.environ.get("ORG_SCAN_WORKER_POOL_SIZE", "1"))

    def _scan_with_timeout(acct: dict) -> tuple:
        """Enforce per-account wall-clock timeout via a nested single-worker executor."""
        with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
            _f = _ex.submit(_scan_one_account, acct)
            return _f.result(timeout=_ACCT_TIMEOUT)

    # Submit up to _POOL_SIZE accounts simultaneously; stop early if cancel already requested.
    future_to_acct: dict = {}
    with _cf.ThreadPoolExecutor(max_workers=_POOL_SIZE) as pool:
        for acct in accounts:
            if _should_cancel():
                logger.info("Org scan cancel requested before submit: workspace=%s scan=%s completed=%d/%d",
                            workspace_id, scan_id, scanned, len(accounts))
                run["cancelRequested"] = True
                break
            future_to_acct[pool.submit(_scan_with_timeout, acct)] = acct

    # Process results as they complete. as_completed yields one future at a time so
    # shared state (all_resources, warnings, scanned, failed) needs no lock here.
    for future in _cf.as_completed(future_to_acct):
        acct            = future_to_acct[future]
        aws_account_id  = acct.get("awsAccountId", "")
        member_role_arn = f"arn:aws:iam::{aws_account_id}:role/{ORG_MEMBER_ROLE_NAME}"
        patch = {**acct, "lastScanAt": now, "lastScanId": scan_id}
        try:
            _, resources, _, coll_warns = future.result()
            storage.replace_resources_for_account(workspace_id, aws_account_id, resources)
            all_resources.extend(resources)
            try:
                _generate_alerts_from_scan(workspace_id, aws_account_id, resources, storage)
            except Exception as _alert_exc:
                logger.warning("Org alert generation failed (non-fatal): account=%s err=%s",
                               aws_account_id, _alert_exc)
            raw_sum = _summary_from_resources(resources)
            patch["lastScanStatus"]    = "SUCCESS"
            patch["lastScanSummary"]   = raw_sum
            patch["lastErrorCode"]     = None
            patch["lastError"]         = None
            patch["lastRoleArn"]       = None
            patch["collectorWarnings"] = coll_warns
            for cw in coll_warns:
                entry = {**cw, "awsAccountId": aws_account_id, "type": "COLLECTOR_PERMISSION"}
                if entry not in warnings:
                    warnings.append(entry)
            scanned += 1
        except OrgScanCancelled:
            logger.info("Org scan cancel observed mid-account: account=%s scan=%s scanned_so_far=%d",
                        aws_account_id, scan_id, scanned)
            patch["lastScanStatus"]    = "CANCELLED"
            patch["lastScanSummary"]   = {}
            patch["lastErrorCode"]     = None
            patch["lastError"]         = None
            patch["collectorWarnings"] = []
            storage.save_org_account(patch)
            run["cancelRequested"] = True
            continue  # skip bottom save + progress flush for this account
        except _cf.TimeoutError:
            logger.warning("Org member scan timed out: account=%s timeout=%ds",
                           aws_account_id, _ACCT_TIMEOUT)
            patch["lastScanStatus"]    = "FAILED"
            patch["lastScanSummary"]   = {}
            patch["lastErrorCode"]     = "MEMBER_SCAN_TIMEOUT"
            patch["lastError"]         = f"Scan timed out after {_ACCT_TIMEOUT}s."
            patch["lastRoleArn"]       = member_role_arn
            patch["collectorWarnings"] = []
            warnings.append({
                "code":         "MEMBER_SCAN_TIMEOUT",
                "awsAccountId": aws_account_id,
                "roleArn":      member_role_arn,
                "message":      f"Scan timed out after {_ACCT_TIMEOUT}s.",
                "type":         "ACCOUNT_ERROR",
            })
            failed += 1
        except Exception as exc:
            err_text = str(exc)
            if "AccessDenied" in err_text or "AccessDeniedException" in err_text:
                safe_code = "ASSUME_ROLE_ACCESS_DENIED"
                safe_msg  = (
                    f"Cannot assume role {member_role_arn}. "
                    f"Check trust policy allows {BACKEND_SCANNER_ROLE} and ExternalId matches."
                )
            elif "NoSuchEntity" in err_text:
                if acct.get("accountType") == "MANAGEMENT":
                    safe_code = "MANAGEMENT_ROLE_MISSING"
                    safe_msg  = (
                        f"Scan role not found in management account {aws_account_id}. "
                        f"StackSets do not deploy to the management account by default. "
                        f"Create EOLMonitorReadOnly there manually to enable scanning."
                    )
                else:
                    safe_code = "MEMBER_ROLE_NOT_FOUND"
                    safe_msg  = f"Role not found: {member_role_arn}. Deploy the member StackSet to this account."
            else:
                safe_code = "MEMBER_SCAN_FAILED"
                safe_msg  = f"Scan failed for account {aws_account_id}."
            logger.warning("Org member scan failed: account=%s code=%s err=%s",
                           aws_account_id, safe_code, type(exc).__name__)
            patch["lastScanStatus"]    = "FAILED"
            patch["lastScanSummary"]   = {}
            patch["lastErrorCode"]     = safe_code
            patch["lastError"]         = safe_msg
            patch["lastRoleArn"]       = member_role_arn
            patch["collectorWarnings"] = []
            warnings.append({
                "code":         safe_code,
                "awsAccountId": aws_account_id,
                "roleArn":      member_role_arn,
                "message":      safe_msg,
                "type":         "ACCOUNT_ERROR",
            })
            failed += 1
        storage.save_org_account(patch)
        raw_org_sum = _summary_from_resources(all_resources)
        run.update({
            "status":          "RUNNING",
            "accountsTotal":   len(accounts),
            "accountsScanned": scanned,
            "accountsFailed":  failed,
            "summary":         _org_summary_from_raw(raw_org_sum),
            "warnings":        warnings,
        })
        storage.save_org_scan_run(run)

    completed_at = datetime.now(timezone.utc).isoformat()
    raw_org_sum  = _summary_from_resources(all_resources)
    org_summary  = _org_summary_from_raw(raw_org_sum)
    if run.get("cancelRequested"):
        status = "CANCELLED"
    else:
        status = "SUCCESS" if failed == 0 else ("PARTIAL_SUCCESS" if scanned > 0 else "FAILED")
    run.update({
        "status":           status,
        "completedAt":      completed_at,
        "accountsTotal":    len(accounts),
        "accountsScanned":  scanned,
        "accountsFailed":   failed,
        "summary":          org_summary,
        "warnings":         warnings,
        "errorCode":        None if status not in ("FAILED",) else "ORG_SCAN_NO_ACCOUNTS_ACCESSIBLE",
        "error":            None if status not in ("FAILED",) else "No member accounts could be scanned.",
    })
    storage.save_org_scan_run(run)
    storage.save_org_connection({
        **conn,
        "updatedAt":       run["completedAt"],
        "lastScanAt":      run["completedAt"],
        "lastScanId":      scan_id,
        "lastScanStatus":  status,
        "lastScanSummary": org_summary,
    })
    return run


def dispatch_org_scan_worker(workspace_id: str, conn_id: str, scan_id: str) -> None:
    mode = os.environ.get("ORG_SCAN_ASYNC_MODE", "thread").lower()
    if mode == "sync":
        run_org_scan_worker(workspace_id, conn_id, scan_id)
        return
    if mode == "lambda_event":
        function_name = os.environ.get("ORG_SCAN_WORKER_FUNCTION") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        if not function_name:
            raise RuntimeError("ORG_SCAN_ASYNC_MODE=lambda_event requires ORG_SCAN_WORKER_FUNCTION or AWS_LAMBDA_FUNCTION_NAME")
        boto3.client("lambda").invoke(
            FunctionName=function_name,
            InvocationType="Event",
            Payload=json.dumps({
                "type": "ORG_SCAN_WORKER",
                "workspaceId": workspace_id,
                "orgConnectionId": conn_id,
                "orgScanId": scan_id,
            }).encode("utf-8"),
        )
        return
    worker = _threading.Thread(
        target=run_org_scan_worker,
        args=(workspace_id, conn_id, scan_id),
        daemon=True,
    )
    worker.start()


def handle_org_scan_worker_event(event: dict) -> dict:
    if event.get("type") != "ORG_SCAN_WORKER":
        return _error_resp(400, "INVALID_WORKER_EVENT", "Invalid worker event")
    workspace_id = event.get("workspaceId")
    conn_id = event.get("orgConnectionId")
    scan_id = event.get("orgScanId")
    if not workspace_id or not conn_id or not scan_id:
        return _error_resp(400, "INVALID_WORKER_EVENT", "Missing worker event fields")
    run = run_org_scan_worker(workspace_id, conn_id, scan_id)
    return resp(200, {"ok": True, "orgScanId": scan_id, "status": run.get("status")})


@workspace_auth("EDITOR")
def handle_ws_org_scan_create(workspace_id: str, conn_id: str, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "EDITOR")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    storage = get_storage()
    conn = storage.get_org_connection(workspace_id, conn_id)
    if not conn:
        return _error_resp(404, "ORG_CONNECTION_NOT_FOUND", "Organization connection not found")
    if conn.get("status") == "DISCONNECTED":
        return _error_resp(409, "ORG_CONNECTION_DISCONNECTED",
                          "Organization connection is paused. Reconnect before starting a scan.")
    storage.cleanup_stale_org_scans(workspace_id)
    running = storage.get_running_org_scan(workspace_id, conn_id)
    if running:
        return resp(409, {
            "success": False,
            "data": None,
            "error": {
                "code": "ORG_SCAN_IN_PROGRESS",
                "message": "An organization scan is already running for this connection. Please wait for it to complete.",
            },
            "runningScan": {"orgScanId": running.get("id"), "startedAt": running.get("startedAt")},
        })

    accounts = [a for a in storage.get_org_accounts(workspace_id, conn_id) if a.get("status") == "ACTIVE"]
    started_at = datetime.now(timezone.utc).isoformat()
    scan_id = f"org_scan_{secrets.token_hex(12)}"
    run = _initial_org_scan_run(workspace_id, conn_id, scan_id, started_at, len(accounts))
    storage.save_org_scan_run(run)
    for acct in accounts:
        storage.save_org_account({
            **acct,
            "lastScanAt": started_at,
            "lastScanId": scan_id,
            "lastScanStatus": "RUNNING",
            "lastScanSummary": {},
            "lastErrorCode": None,
            "lastError": None,
        })
    try:
        dispatch_org_scan_worker(workspace_id, conn_id, scan_id)
    except Exception as exc:
        completed_at = datetime.now(timezone.utc).isoformat()
        run.update({
            "status": "FAILED",
            "completedAt": completed_at,
            "errorCode": "ORG_SCAN_DISPATCH_FAILED",
            "error": "Unable to start organization scan worker.",
        })
        storage.save_org_scan_run(run)
        logger.error("Org scan dispatch failed: workspace=%s conn=%s scan=%s err=%s",
                     workspace_id, conn_id, scan_id, exc)
        return _error_resp(500, "ORG_SCAN_DISPATCH_FAILED", "Unable to start organization scan worker.")
    return resp(202, {"orgScanId": scan_id, "status": "RUNNING", "run": run})


@workspace_auth("VIEWER")
def handle_ws_org_scan_get(workspace_id: str, scan_id: str, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    run = get_storage().get_org_scan_run(workspace_id, scan_id)
    if not run:
        return _error_resp(404, "ORG_SCAN_NOT_FOUND", "Organization scan not found")
    accounts = get_storage().get_org_accounts(workspace_id, run.get("orgConnectionId"))
    return resp(200, {"run": run, "accounts": accounts})


@workspace_auth("ADMIN")
def handle_ws_org_scan_cancel(workspace_id: str, scan_id: str, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    storage = get_storage()
    run = storage.get_org_scan_run(workspace_id, scan_id)
    if not run:
        return _error_resp(404, "ORG_SCAN_NOT_FOUND", "Organization scan not found")
    if run.get("status") != "RUNNING":
        return _error_resp(409, "ORG_SCAN_NOT_RUNNING",
                           f"Cannot cancel scan with status '{run.get('status')}'")
    now = datetime.now(timezone.utc).isoformat()
    run["cancelRequested"]   = True
    run["cancelRequestedAt"] = now
    storage.save_org_scan_run(run)
    logger.info("Org scan cancel requested via API: workspace=%s scan=%s", workspace_id, scan_id)
    return resp(202, {"ok": True, "orgScanId": scan_id, "status": "CANCEL_REQUESTED"})


@workspace_auth("VIEWER")
def handle_ws_org_connection_scans(workspace_id: str, conn_id: str, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    storage = get_storage()
    if not storage.get_org_connection(workspace_id, conn_id):
        return _error_resp(404, "ORG_CONNECTION_NOT_FOUND", "Organization connection not found")
    runs = storage.get_org_scan_runs(workspace_id, conn_id, limit=50)
    return resp(200, {"runs": runs, "count": len(runs)})


@workspace_auth("VIEWER")
def handle_ws_org_summary(workspace_id: str, headers: dict) -> dict:
    disabled = _require_org_feature()
    if disabled:
        return disabled
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    storage = get_storage()
    connections = storage.get_org_connections(workspace_id)
    # Scope accounts to the active connection only — using workspace-wide query causes
    # stale counts when a connection was deleted/replaced and old accounts remain.
    active_conn_id = connections[0].get("id") if connections else None
    accounts = storage.get_org_accounts(workspace_id, active_conn_id) if active_conn_id else []
    runs = storage.get_org_scan_runs(workspace_id, conn_id=active_conn_id, limit=20)
    latest = runs[0] if runs else None
    top_risky = []
    risk_by_ou: dict[str, dict] = {}
    for acct in accounts:
        ou = acct.get("ouPath") or "/Root"
        risk_by_ou.setdefault(ou, {"ouPath": ou, "accounts": 0, "eol": 0, "expiringSoon": 0})
        risk_by_ou[ou]["accounts"] += 1
        summary = acct.get("lastScanSummary") or {}
        if summary:
            top_risky.append({"account": acct, "summary": summary})
            risk_by_ou[ou]["eol"]          += summary.get("eol", 0) or summary.get("EOL", 0)
            risk_by_ou[ou]["expiringSoon"] += summary.get("expiringSoon", 0) or summary.get("EXPIRING_SOON", 0)
    # Derive scanned/failed counts from live account records, not stale scan run totals.
    live_scanned = sum(1 for a in accounts if a.get("lastScanStatus") == "SUCCESS")
    live_failed  = sum(1 for a in accounts if a.get("lastScanStatus") == "FAILED")
    return resp(200, {
        "connections":     connections,
        "accountsTotal":   len(accounts),
        "accountsScanned": live_scanned,
        "accountsFailed":  live_failed,
        "summary": latest.get("summary", _empty_org_summary()) if latest else _empty_org_summary(),
        "topRiskyAccounts": top_risky[:10],
        "riskByOu": list(risk_by_ou.values()),
        "riskByService": [],
        "latestRun": latest,
    })

# ── Scan run model ────────────────────────────────────────────────────────────

def _normalize_summary(raw: dict) -> dict:
    """Convert internal EOL status keys to camelCase summary used by scan runs."""
    return {
        "total":               raw.get("total", 0),
        "eol":                 raw.get("EOL", 0),
        "expiringSoon":        raw.get("EXPIRING_SOON", 0),
        "extendedSupport":     raw.get("EXTENDED_SUPPORT", 0),
        "supported":           raw.get("SUPPORTED", 0),
        "unknown":             raw.get("UNKNOWN", 0),
        "needsInspection":     raw.get("NEEDS_INSPECTION", 0),
        "lifecycleNotTracked": raw.get("LIFECYCLE_NOT_TRACKED", 0),
    }


@workspace_auth("EDITOR")
def handle_ws_scan_create(workspace_id: str, account_id: str, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "EDITOR")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    storage  = get_storage()
    accounts = storage.get_accounts(workspace_id)
    account  = next((a for a in accounts if a.get("id") == account_id), None)
    if not account:
        return _error_resp(404, "ACCOUNT_NOT_FOUND", "Account not found")

    role_arn    = account.get("roleArn", "")
    external_id = account.get("externalId", "")
    target_acct = account.get("accountId", "")

    if not role_arn or not external_id or not target_acct:
        return _error_resp(400, "ACCOUNT_MISCONFIGURED",
                           "Account missing roleArn, externalId, or accountId")

    # Expire stuck scans older than 30 min, then block duplicate concurrent scans
    storage.cleanup_stale_scans(workspace_id)
    running = storage.get_running_scan(workspace_id, account_id)
    if running:
        return resp(409, {
            "success":    False,
            "data":       None,
            "error":      {"code": "SCAN_IN_PROGRESS",
                           "message": "A scan is already running for this account. Please wait for it to complete."},
            "runningScan": {"scanId": running.get("scanId"), "startedAt": running.get("startedAt")},
        })

    scan_id    = f"scan_{secrets.token_hex(12)}"
    started_at = datetime.now(timezone.utc).isoformat()
    regions    = _resolve_account_regions(account)
    logger.info("Scan config: account=%s regions=%s", account_id, regions or "all_enabled")

    scan_run = {
        "scanId":      scan_id,
        "workspaceId": workspace_id,
        "accountId":   account_id,
        "status":      "RUNNING",
        "regions":     regions if regions is not None else [],
        "startedAt":   started_at,
        "completedAt": None,
        "error":       None,
        "summary":     {"total": 0, "eol": 0, "expiringSoon": 0, "extendedSupport": 0,
                        "supported": 0, "unknown": 0, "needsInspection": 0, "lifecycleNotTracked": 0},
    }
    storage.save_scan_run(scan_run)

    def _fail_scan(err_code: str, exc: Exception) -> dict:
        error_msg    = str(exc)
        completed_at = datetime.now(timezone.utc).isoformat()
        scan_run.update({"status": "FAILED", "completedAt": completed_at, "error": error_msg})
        storage.save_scan_run(scan_run)
        storage.save_account({
            **account,
            "lastScanAt":        started_at,
            "lastScanStatus":    "failed",
            "lastScanError":     error_msg,
            "lastScanErrorCode": err_code,
            "lastScanId":        scan_id,
        })
        logger.error("Scan FAILED %s [%s]: %s", scan_id, err_code, exc)
        return _error_resp(500, err_code, "Scan failed")

    # Step 1: Assume IAM role — failures here are always ASSUME_ROLE_FAILED
    logger.info("Scan start: ws=%s account=%s role=%s", workspace_id, account_id, role_arn[:50])
    try:
        creds = boto3.client("sts").assume_role(
            RoleArn=role_arn,
            RoleSessionName=f"eol-monitor-{account_id}"[:64],
            ExternalId=external_id,
        )["Credentials"]
    except Exception as exc:
        return _fail_scan("ASSUME_ROLE_FAILED", exc)

    session = boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )

    # Step 2: Collect resources — permission errors here are SERVICE_ACCESS_DENIED
    try:
        from eol_collector import run_all_collectors
        resources = run_all_collectors(session, target_acct, regions=regions)
        # Tag every resource so inventory reads are workspace-isolated
        for r in resources:
            r["workspace_id"] = workspace_id
            r["account_id"]   = account_id
            r["scan_id"]      = scan_id
            r["workspaceId"]  = workspace_id
            r["accountId"]    = account_id
            r["scanId"]       = scan_id
            r["scan_source"]  = "ACCOUNT_SCAN"
    except Exception as exc:
        error_msg = str(exc)
        if "AccessDenied" in error_msg or "is not authorized" in error_msg:
            return _fail_scan("SERVICE_ACCESS_DENIED", exc)
        return _fail_scan("SCAN_FAILED", exc)

    try:
        written  = storage.replace_resources_for_account(workspace_id, account_id, resources,
                                                           scan_started_at=started_at)
        raw_sum  = _summary_from_resources(resources)
        summary  = _normalize_summary(raw_sum)
        warnings = _combined_scan_warnings(resources)

        completed_at = datetime.now(timezone.utc).isoformat()
        scan_run.update({"status": "SUCCESS", "completedAt": completed_at, "summary": summary, "warnings": warnings})
        storage.save_scan_run(scan_run)

        updated_account = {
            **account,
            "lastScanAt":        started_at,
            "lastScanStatus":    "success",
            "lastScanSummary":   raw_sum,
            "lastScanWarnings":  warnings,
            "lastScanError":     None,
            "lastScanErrorCode": None,
            "lastScanId":        scan_id,
        }
        storage.save_account(updated_account)

        try:
            _generate_alerts_from_scan(workspace_id, account_id, resources, storage)
        except Exception as alert_exc:
            logger.warning("Alert generation failed (non-fatal): %s", alert_exc)

        _trigger_scan_notifications(workspace_id, ws, account, scan_id, summary, resources)

        logger.info("Scan SUCCESS: %d resources, %d written for %s", len(resources), written, scan_id)
        return resp(200, {"scanId": scan_id, "status": "SUCCESS", "summary": summary, "warnings": warnings})

    except Exception as exc:
        return _fail_scan("SCAN_FAILED", exc)


@workspace_auth("VIEWER")
def handle_ws_scan_get(workspace_id: str, scan_id: str, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    storage = get_storage()
    run = storage.get_scan_run(scan_id)
    if not run or run.get("workspaceId") != workspace_id:
        return _error_resp(404, "SCAN_NOT_FOUND", "Scan run not found")

    return resp(200, {"scan": run})


@workspace_auth("VIEWER")
def handle_ws_account_latest_scan(workspace_id: str, account_id: str, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    runs = get_storage().get_scan_runs(workspace_id, account_id=account_id, limit=1)
    return resp(200, {"scan": runs[0] if runs else None})


@workspace_auth("VIEWER")
def handle_ws_account_scan_list(workspace_id: str, account_id: str, headers: dict, params: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    limit = min(int(params.get("limit", 20)), 100)
    runs  = get_storage().get_scan_runs(workspace_id, account_id=account_id, limit=limit)
    return resp(200, {"scans": runs, "count": len(runs)})


# ── Source helpers ─────────────────────────────────────────────────────────────

def _get_org_member_account_ids(storage, workspace_id: str) -> set:
    """Return set of active org member AWS account IDs across all connected org connections."""
    ids: set = set()
    for oc in storage.get_org_connections(workspace_id):
        if oc.get("status") == "CONNECTED":
            for oa in storage.get_org_accounts(workspace_id, oc["id"]):
                aid = oa.get("awsAccountId", "")
                if aid:
                    ids.add(aid)
    return ids


_ACTIVE_SCAN_SOURCES = {"ACCOUNT_SCAN", "ORG_SCAN"}

def _is_reportable(r: dict, active_acct_ids: set, active_org_ids: set) -> bool:
    """Keep only resources from live account/org scans; exclude stale lifecycle-only data."""
    explicit = r.get("scan_source")
    if explicit:
        return explicit in _ACTIVE_SCAN_SOURCES
    # Legacy resource (no scan_source tag): include only if account is still active
    acct_id = r.get("account_id") or ""
    return acct_id in active_acct_ids or acct_id in active_org_ids


def _matches_scan_source(resource: dict, scan_source_filter: str, org_account_ids: set) -> bool:
    """
    Return True if resource matches the requested scan source.
    Explicit scan_source tag wins; for legacy resources without it,
    infer from whether the account_id is in org member accounts.
    """
    explicit = resource.get("scan_source")
    if explicit:
        return explicit == scan_source_filter
    # Legacy resource — infer from account_id membership
    account_id = resource.get("account_id") or ""
    is_org = account_id in org_account_ids
    if scan_source_filter == "ORG_SCAN":
        return is_org
    if scan_source_filter == "ACCOUNT_SCAN":
        return not is_org
    return True


# ── Workspace summary ──────────────────────────────────────────────────────────

@workspace_auth("VIEWER")
def handle_ws_summary(workspace_id: str, headers: dict, params: dict = None) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    storage   = get_storage()
    accounts  = storage.get_accounts(workspace_id)
    resources = storage.get_resources({"workspace_id": workspace_id})

    # All discovered org member account IDs (used for source inference on legacy resources)
    org_account_ids = _get_org_member_account_ids(storage, workspace_id)
    # Active-only subset used for the accounts.org count shown in the UI
    org_active_ids: set = set()
    for oc in storage.get_org_connections(workspace_id):
        if oc.get("status") == "CONNECTED":
            for oa in storage.get_org_accounts(workspace_id, oc["id"]):
                if oa.get("status") == "ACTIVE":
                    aid = oa.get("awsAccountId", "")
                    if aid:
                        org_active_ids.add(aid)

    # Exclude stale NO_SOURCE resources so Dashboard totals match Reports.
    active_acct_ids = {a.get("id") for a in accounts if a.get("id")}
    resources = [r for r in resources if _is_reportable(r, active_acct_ids, org_account_ids)]

    # Optional source filter — uses _matches_scan_source for backward compat with
    # legacy org resources that pre-date the scan_source field.
    scan_source_filter = (params or {}).get("scan_source") or None
    if scan_source_filter:
        resources = [r for r in resources
                     if _matches_scan_source(r, scan_source_filter, org_account_ids)]

    totals = {"total": len(resources), "eol": 0, "expiringSoon": 0, "extendedSupport": 0,
              "supported": 0, "unknown": 0, "needsInspection": 0, "lifecycleNotTracked": 0}
    by_service: dict = {}
    for r in resources:
        status = r.get("eol_status", "UNKNOWN")
        if status == "EOL":                      totals["eol"] += 1
        elif status == "EXPIRING_SOON":          totals["expiringSoon"] += 1
        elif status == "EXTENDED_SUPPORT":       totals["extendedSupport"] += 1
        elif status == "SUPPORTED":              totals["supported"] += 1
        elif status == "NEEDS_INSPECTION":       totals["needsInspection"] += 1
        elif status == "LIFECYCLE_NOT_TRACKED":  totals["lifecycleNotTracked"] += 1
        else:                                    totals["unknown"] += 1

        svc = r.get("service_type", "Unknown")
        if svc not in by_service:
            by_service[svc] = {"service": svc, "total": 0, "eol": 0, "expiringSoon": 0,
                                "extendedSupport": 0, "supported": 0, "unknown": 0,
                                "needsInspection": 0, "lifecycleNotTracked": 0}
        by_service[svc]["total"] += 1
        if status == "EOL":                      by_service[svc]["eol"] += 1
        elif status == "EXPIRING_SOON":          by_service[svc]["expiringSoon"] += 1
        elif status == "EXTENDED_SUPPORT":       by_service[svc]["extendedSupport"] += 1
        elif status == "SUPPORTED":              by_service[svc]["supported"] += 1
        elif status == "NEEDS_INSPECTION":       by_service[svc]["needsInspection"] += 1
        elif status == "LIFECYCLE_NOT_TRACKED":  by_service[svc]["lifecycleNotTracked"] += 1
        else:                                    by_service[svc]["unknown"] += 1

    last_scans = storage.get_scan_runs(workspace_id, limit=1)
    latest     = last_scans[0] if last_scans else None

    top_risks = sorted(
        [r for r in resources if r.get("eol_status") in ("EOL", "EXPIRING_SOON")],
        key=lambda x: x.get("days_to_eol") or x.get("daysToEol") or 9999
    )[:5]

    return resp(200, {
        "workspace": {
            "id":       ws["id"],
            "name":     ws.get("name", ""),
            "expiresAt": ws.get("expires_at") or ws.get("expiresAt"),
        },
        "accounts": {
            "total":     len(accounts),
            "connected": len([a for a in accounts if a.get("lastScanStatus") == "success"]),
            "org":       len(org_active_ids),
        },
        "lastScan": {
            "status":      latest["status"],
            "completedAt": latest.get("completedAt"),
            "accountId":   latest.get("accountId"),
            "scanId":      latest.get("scanId"),
        } if latest else None,
        "resources":       totals,
        "serviceBreakdown": list(by_service.values()),
        "topRisks":        top_risks,
    })


# ── Workspace inventory ────────────────────────────────────────────────────────

@workspace_auth("VIEWER")
def handle_ws_inventory(workspace_id: str, headers: dict, params: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    filters = {k: params.get(k) for k in ("service", "status", "region", "account_id") if params.get(k)}
    filters["workspace_id"] = workspace_id
    items = get_storage().get_resources(filters)

    scan_source_filter = params.get("scan_source") or None
    if scan_source_filter:
        org_ids = _get_org_member_account_ids(get_storage(), workspace_id)
        items = [r for r in items if _matches_scan_source(r, scan_source_filter, org_ids)]

    return resp(200, {"items": items, "count": len(items)})


# ── Reports ──────────────────────────────────────────────────────────────────

def _risk_score(counts: dict) -> int:
    raw = (
        int(counts.get("eol", 0)) * 10 +
        int(counts.get("expiringSoon", 0)) * 4 +
        int(counts.get("extendedSupport", 0)) * 3 +
        int(counts.get("unknown", 0)) * 1
    )
    return min(100, raw)


def _risk_level(score: int) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 50:
        return "HIGH"
    if score >= 20:
        return "MEDIUM"
    return "LOW"


def _empty_report_counts() -> dict:
    return {
        "total": 0, "eol": 0, "expiringSoon": 0, "extendedSupport": 0,
        "supported": 0, "unknown": 0,
        "needsInspection": 0, "lifecycleNotTracked": 0,
    }


def _add_status(counts: dict, status: str) -> None:
    counts["total"] += 1
    if status == "EOL":
        counts["eol"] += 1
    elif status == "EXPIRING_SOON":
        counts["expiringSoon"] += 1
    elif status == "EXTENDED_SUPPORT":
        counts["extendedSupport"] += 1
    elif status == "SUPPORTED":
        counts["supported"] += 1
    elif status == "NEEDS_INSPECTION":
        counts["needsInspection"] += 1
    elif status == "LIFECYCLE_NOT_TRACKED":
        counts["lifecycleNotTracked"] += 1
    else:
        counts["unknown"] += 1


def _finalize_counts(counts: dict) -> dict:
    score = _risk_score(counts)
    return {**counts, "riskScore": score, "riskLevel": _risk_level(score)}


def _current_workspace_resources(storage, workspace_id: str) -> list:
    return storage.get_resources({"workspace_id": workspace_id})


def _build_report_summary(workspace_id: str, source: str = "LIVE",
                           scope: str = "workspace", filter_account_id: str = "") -> dict:
    storage = get_storage()
    ws = storage.get_workspace(workspace_id) or {"id": workspace_id, "name": workspace_id}
    accounts = storage.get_accounts(workspace_id)
    # Connected accounts keyed by their id (= AWS account ID)
    account_map = {a.get("id"): a for a in accounts}
    # Org member accounts keyed by awsAccountId
    org_account_map: dict = {}
    for oc in storage.get_org_connections(workspace_id):
        if oc.get("status") == "CONNECTED":
            for oa in storage.get_org_accounts(workspace_id, oc["id"]):
                aid = oa.get("awsAccountId", "")
                if aid:
                    org_account_map[aid] = oa
    resources = _current_workspace_resources(storage, workspace_id)

    # Exclude stale lifecycle-only resources (NO_SOURCE, VERIFIED_AWS_OFFICIAL, etc.).
    # Keep only resources that came from live account or org scans.
    active_acct_ids = {a_id for a_id in account_map if a_id}
    active_org_ids  = set(org_account_map.keys())
    resources = [r for r in resources if _is_reportable(r, active_acct_ids, active_org_ids)]

    # Apply report scope filter
    if scope == "account-scan":
        resources = [r for r in resources
                     if _matches_scan_source(r, "ACCOUNT_SCAN", active_org_ids)]
    elif scope == "org-scan":
        resources = [r for r in resources
                     if _matches_scan_source(r, "ORG_SCAN", active_org_ids)]
    elif scope == "account" and filter_account_id:
        resources = [r for r in resources
                     if (r.get("account_id") or r.get("accountId") or "") == filter_account_id]

    summary_counts = _empty_report_counts()
    by_account: dict = {}
    by_service: dict = {}
    top_risks = []

    for r in resources:
        status = r.get("eol_status") or r.get("status") or "UNKNOWN"
        acct_id = r.get("account_id") or r.get("accountId") or ""
        svc = r.get("service_type") or r.get("service") or "Unknown"

        _add_status(summary_counts, status)
        if acct_id not in by_account:
            acct = account_map.get(acct_id)
            org_acct = org_account_map.get(acct_id)
            if acct:
                acct_name   = acct.get("accountName") or acct.get("name") or acct_id
                aws_acct_id = acct.get("accountId") or ""
                scan_src    = "ACCOUNT_SCAN"
            elif org_acct:
                acct_name   = org_acct.get("name") or acct_id
                aws_acct_id = org_acct.get("awsAccountId") or acct_id
                scan_src    = "ORG_SCAN"
            else:
                acct_name   = acct_id
                aws_acct_id = ""
                scan_src    = "ACCOUNT_SCAN"
            by_account[acct_id] = {
                "accountId":    acct_id,
                "accountName":  acct_name,
                "awsAccountId": aws_acct_id,
                "scanSource":   scan_src,
                **_empty_report_counts(),
            }
        _add_status(by_account[acct_id], status)

        if svc not in by_service:
            by_service[svc] = {"service": svc, **_empty_report_counts()}
        _add_status(by_service[svc], status)

        if status in ("EOL", "EXPIRING_SOON", "EXTENDED_SUPPORT"):
            top_risks.append({
                "resourceId": r.get("resource_id") or r.get("resourceId") or "",
                "resourceName": r.get("resource_name") or r.get("resourceName") or "",
                "service": svc,
                "accountId": acct_id,
                "accountName": by_account.get(acct_id, {}).get("accountName", acct_id),
                "region": r.get("region") or "",
                "version": r.get("version") or "",
                "status": status,
                "eolDate": r.get("eol_date") or r.get("eolDate") or "",
                "daysToEol": r.get("days_to_eol") if r.get("days_to_eol") is not None else r.get("daysToEol"),
                "recommendation": r.get("recommendation") or r.get("recommendedAction") or "",
            })

    def risk_sort(item):
        priority = {"EOL": 0, "EXPIRING_SOON": 1, "EXTENDED_SUPPORT": 2}
        days = item.get("daysToEol")
        return (priority.get(item.get("status"), 9), days if days is not None else 999999)

    top_risks = sorted(top_risks, key=risk_sort)[:10]
    return {
        "workspace": {"id": workspace_id, "name": ws.get("name", "")},
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "period": datetime.now(timezone.utc).strftime("%Y-%m"),
        "source": source,
        "summary": _finalize_counts(summary_counts),
        "byAccount": [_finalize_counts(v) for v in by_account.values()],
        "byService": [_finalize_counts(v) for v in by_service.values()],
        "topRisks": top_risks,
        "resources": resources,
    }


def _snapshot_from_summary(workspace_id: str, summary: dict, source: str) -> dict:
    return {
        "id": f"report_{secrets.token_hex(12)}",
        "workspaceId": workspace_id,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "period": summary.get("period") or datetime.now(timezone.utc).strftime("%Y-%m"),
        "source": source,
        "summary": summary["summary"],
        "byAccount": summary["byAccount"],
        "byService": summary["byService"],
        "topRisks": summary["topRisks"],
    }


@workspace_auth("VIEWER")
def handle_ws_reports_summary(workspace_id: str, headers: dict, params: dict = None) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err, "Authentication failed")
    scope      = (params or {}).get("scope", "workspace")
    acct_id    = (params or {}).get("accountId", "")
    summary = _build_report_summary(workspace_id, scope=scope, filter_account_id=acct_id)
    snapshots = get_storage().get_report_snapshots(workspace_id, limit=12)
    summary["trend"] = [
        {"id": s.get("id"), "createdAt": s.get("createdAt"), "period": s.get("period"),
         "eol": s.get("summary", {}).get("eol", 0),
         "expiringSoon": s.get("summary", {}).get("expiringSoon", 0),
         "riskScore": s.get("summary", {}).get("riskScore", 0)}
        for s in snapshots
    ]
    summary.pop("resources", None)
    return resp(200, summary)


@workspace_auth("EDITOR")
def handle_ws_report_snapshot_create(workspace_id: str, headers: dict, source: str = "MANUAL") -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "EDITOR")
    if not ws:
        return _error_resp(401, err, "Authentication failed")
    storage = get_storage()
    summary = _build_report_summary(workspace_id, source=source)
    snapshot = _snapshot_from_summary(workspace_id, summary, source)
    storage.save_report_snapshot(snapshot)
    if actor["type"] in ("API_TOKEN", "MEMBER"):
        from audit import write_audit, AuditAction
        write_audit(
            storage, workspace_id,
            AuditAction.REPORT_SNAPSHOT_CREATED,
            f"Report snapshot created via {actor['type'].lower().replace('_', ' ')} '{actor['label']}'",
            actor_type=actor["type"],
            actor_id=actor["id"],
            actor_label=actor["label"],
            resource_type="report_snapshot",
            resource_id=snapshot["id"],
            metadata={"source": source, "token_role": actor["role"]},
        )
    return resp(201, {"snapshot": snapshot})


@workspace_auth("VIEWER")
def handle_ws_report_snapshots_list(workspace_id: str, headers: dict) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err, "Authentication failed")
    snapshots = get_storage().get_report_snapshots(workspace_id, limit=50)
    return resp(200, {"snapshots": snapshots, "count": len(snapshots)})


@workspace_auth("VIEWER")
def handle_ws_report_snapshot_get(workspace_id: str, report_id: str, headers: dict) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err, "Authentication failed")
    snapshot = get_storage().get_report_snapshot(workspace_id, report_id)
    if not snapshot:
        return _error_resp(404, "REPORT_NOT_FOUND", "Report snapshot not found")
    return resp(200, {"snapshot": snapshot})


_CSV_STATUS_LABEL = {
    "EOL":                   "EOL",
    "EXPIRING_SOON":         "Expiring Soon",
    "EXTENDED_SUPPORT":      "Extended Support",
    "LIFECYCLE_NOT_TRACKED": "Lifecycle Not Tracked",
    "SUPPORTED":             "Supported",
    "UNKNOWN":               "Unknown",
    "NEEDS_INSPECTION":      "Needs Inspection",
}

_CSV_SCAN_SOURCE_LABEL = {
    "ACCOUNT_SCAN": "Account Scan",
    "ORG_SCAN":     "Organization Scan",
}


def _csv_lifecycle_message(days_to_eol, status: str) -> str:
    if status == "LIFECYCLE_NOT_TRACKED":
        return "No published EOL schedule"
    if status in ("SUPPORTED", "EXTENDED_SUPPORT", "EXPIRING_SOON"):
        if days_to_eol is not None:
            label = "In extended support · " if status == "EXTENDED_SUPPORT" else ""
            return f"{label}{int(days_to_eol)} days remaining"
        return _CSV_STATUS_LABEL.get(status, status)
    if status == "EOL":
        if days_to_eol is not None:
            return f"{abs(int(days_to_eol))} days past EOL"
        return "Past EOL"
    return ""


def _csv_fallback_recommendation(service: str, version: str, status: str) -> str:
    svc = (service or "").upper().replace("_", "").replace("-", "")
    ver = (version or "").lower()
    if "LAMBDA" in svc:
        if "nodejs18" in ver or "node18" in ver:
            return "Upgrade Lambda runtime from nodejs18.x to nodejs22.x."
        if "nodejs20" in ver or "node20" in ver:
            return "Upgrade Lambda runtime from nodejs20.x to nodejs22.x."
        if "nodejs14" in ver or "nodejs12" in ver:
            return "Upgrade Lambda runtime to nodejs22.x (current LTS)."
        if "nodejs" in ver or "node" in ver:
            return "Upgrade Lambda runtime to a supported Node.js version (nodejs22.x recommended)."
        if "python3.9" in ver:
            return "Upgrade Lambda runtime from python3.9 to python3.13 or a supported runtime."
        if "python3.10" in ver:
            return "Plan upgrade to a supported Python runtime before EOL (python3.13 recommended)."
        if "python3.8" in ver or "python3.7" in ver:
            return "Upgrade Lambda runtime immediately — python3.8/3.7 is past EOL. Use python3.13."
        if "python" in ver:
            return "Upgrade Lambda runtime to a supported Python version (python3.13 recommended)."
        if "ruby" in ver:
            return "Upgrade Lambda runtime to a supported Ruby version."
        if "java" in ver or "corretto" in ver:
            return "Upgrade Lambda runtime to java21 (Amazon Corretto 21)."
        if "go1" in ver or "golang" in ver:
            return "Upgrade Lambda Go runtime to provided.al2023."
        if "dotnet" in ver:
            return "Upgrade Lambda runtime to a supported .NET version."
    if "EKS" in svc and status in ("EOL", "EXPIRING_SOON"):
        return "Plan EKS cluster control plane upgrade to a supported Kubernetes version."
    if ("RDS" in svc or "AURORA" in svc) and status == "EXTENDED_SUPPORT":
        return "Upgrade database engine to avoid extended support charges."
    if ("RDS" in svc or "AURORA" in svc) and status in ("EOL", "EXPIRING_SOON"):
        return "Upgrade database engine to a supported major version immediately."
    if "ELASTICACHE" in svc and status in ("EOL", "EXPIRING_SOON"):
        return "Upgrade ElastiCache engine to a supported version."
    if "MSK" in svc and status in ("EOL", "EXPIRING_SOON"):
        return "Upgrade MSK cluster to a supported Apache Kafka version."
    if status == "EOL":
        return "This resource version is past end-of-life. Plan an immediate upgrade."
    if status == "EXPIRING_SOON":
        return "This resource version approaches end-of-life. Plan an upgrade before the EOL date."
    if status == "EXTENDED_SUPPORT":
        return "This resource is in extended support. Upgrade to avoid additional charges."
    return ""


def _csv_detection_source(service: str, existing: str) -> str:
    if existing:
        return existing
    svc = (service or "").upper().replace("_", "").replace("-", "")
    if "LAMBDA" in svc:
        return "AWS Lambda ListFunctions – runtime field"
    if "RDS" in svc or "AURORA" in svc:
        return "AWS RDS DescribeDBInstances – engine version"
    if "EKS" in svc:
        return "AWS EKS DescribeClusters – version field"
    if "ELASTICACHE" in svc:
        return "AWS ElastiCache DescribeCacheClusters – engine version"
    if "EC2" in svc:
        return "AMI metadata / EC2 DescribeInstances"
    if "ECR" in svc:
        return "ECR image metadata"
    if "MSK" in svc:
        return "AWS MSK DescribeCluster – Kafka version"
    if "OPENSEARCH" in svc:
        return "AWS OpenSearch DescribeDomains – engine version"
    if "EMR" in svc:
        return "AWS EMR DescribeCluster – release version"
    if "CODEBUILD" in svc:
        return "AWS CodeBuild – image/runtime version"
    if "GLUE" in svc:
        return "AWS Glue – Python shell/Spark version"
    if "DOCUMENTDB" in svc:
        return "AWS DocumentDB DescribeDBClusters – engine version"
    if "NEPTUNE" in svc:
        return "AWS Neptune DescribeDBClusters – engine version"
    return ""


def _report_csv(workspace_id: str, scope: str = "workspace", filter_account_id: str = "") -> tuple[str, str]:
    storage = get_storage()
    data = _build_report_summary(workspace_id, scope=scope, filter_account_id=filter_account_id)
    ws = data["workspace"]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Workspace Name", "Account Name", "AWS Account ID", "Source Type",
        "Resource Name", "Service", "Region", "Version",
        "Status", "Lifecycle Message", "Days To EOL", "EOL Date",
        "Risk Level", "Recommendation", "Upgrade Guide URL",
        "Detection Source", "Confidence", "Last Scanned At",
    ])
    account_by_id = {a["accountId"]: a for a in data["byAccount"]}
    for r in data["resources"]:
        acct_id   = r.get("account_id") or r.get("accountId") or ""
        acct      = account_by_id.get(acct_id, {})
        service   = r.get("service_type") or ""
        version   = r.get("version") or ""
        status    = r.get("eol_status") or "UNKNOWN"
        days_eol  = r.get("days_to_eol")
        raw_src   = r.get("scan_source") or "ACCOUNT_SCAN"
        existing_rec = r.get("recommendation") or r.get("recommendedAction") or ""
        recommendation = existing_rec or _csv_fallback_recommendation(service, version, status)
        ck_guide  = match_upgrade_guide(service, version, storage)
        guide_url = ck_guide.get("guideUrl", "") if ck_guide else ""
        risk_level = (
            "CRITICAL" if status == "EOL" else
            "HIGH"     if status == "EXPIRING_SOON" else
            "MEDIUM"   if status == "EXTENDED_SUPPORT" else
            "LOW"
        )
        writer.writerow([
            ws.get("name", ""),
            acct.get("accountName", acct_id),
            acct.get("awsAccountId", ""),
            _CSV_SCAN_SOURCE_LABEL.get(raw_src, raw_src),
            r.get("resource_name") or r.get("resourceName") or "",
            service,
            r.get("region") or "",
            version,
            _CSV_STATUS_LABEL.get(status, status),
            _csv_lifecycle_message(days_eol, status),
            days_eol if days_eol is not None else "",
            r.get("eol_date") or "",
            risk_level,
            recommendation,
            guide_url,
            _csv_detection_source(service, r.get("detection_source") or ""),
            r.get("confidence") or "",
            r.get("scanned_at") or "",
        ])
    safe_ws   = quote((ws.get("name") or workspace_id).replace(" ", "-"))
    date_str  = datetime.now(timezone.utc).date().isoformat()
    if scope == "account-scan":
        scope_slug = "account-scan"
    elif scope == "org-scan":
        scope_slug = "org-scan"
    elif scope == "account" and filter_account_id:
        acct_name = account_by_id.get(filter_account_id, {}).get("accountName", filter_account_id)
        scope_slug = quote(acct_name.lower().replace(" ", "-"))
    else:
        scope_slug = None
    if scope_slug:
        filename = f"aws-eol-risk-report-{safe_ws}-{scope_slug}-{date_str}.csv"
    else:
        filename = f"aws-eol-risk-report-{safe_ws}-{date_str}.csv"
    return output.getvalue(), filename


@workspace_auth("VIEWER")
def handle_ws_report_csv(workspace_id: str, headers: dict, params: dict = None) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err, "Authentication failed")
    scope   = (params or {}).get("scope", "workspace")
    acct_id = (params or {}).get("accountId", "")
    body, filename = _report_csv(workspace_id, scope=scope, filter_account_id=acct_id)
    if actor["type"] == "API_TOKEN":
        from audit import write_audit, AuditAction
        write_audit(
            get_storage(), workspace_id,
            AuditAction.REPORT_CSV_DOWNLOADED,
            f"CSV report downloaded via API token '{actor['label']}'",
            actor_type=actor["type"],
            actor_id=actor["id"],
            actor_label=actor["label"],
            resource_type="report_csv",
            metadata={"filename": filename, "token_role": actor["role"]},
        )
    return text_resp(200, body, "text/csv; charset=utf-8", {
        "Content-Disposition": f'attachment; filename="{filename}"',
    })


# ── Alert generation ──────────────────────────────────────────────────────────

ALERT_SEVERITY = {"EOL": "HIGH", "EXPIRING_SOON": "MEDIUM", "EXTENDED_SUPPORT": "LOW"}


def _alert_reason(r: dict, status: str) -> str:
    service  = r.get("service_type", "")
    version  = r.get("version", "")
    eol_date = r.get("eol_date", "")
    days     = r.get("days_to_eol")
    vstr     = f" {version}" if version else ""
    dstr     = f" ({eol_date})" if eol_date else ""
    if status == "EOL":
        return f"{service}{vstr} has reached end of life{dstr}."
    if status == "EXPIRING_SOON":
        if days is not None:
            return f"{service}{vstr} expires in {days} days{dstr}."
        return f"{service}{vstr} is expiring soon{dstr}."
    return f"{service}{vstr} is in AWS Extended Support{dstr}."


def _generate_alerts_from_scan(workspace_id: str, account_id: str,
                                resources: list, storage) -> None:
    now = datetime.now(timezone.utc).isoformat()

    # Index existing non-resolved alerts for this account so we can upsert
    existing = {
        f"{a['resourceId']}#{a['service']}": a
        for a in storage.get_alerts(workspace_id, account_id=account_id)
        if a.get("status") != "RESOLVED"
    }

    scanned_keys: set = set()     # risky-status resources (create/update alerts)
    all_scanned_keys: set = set() # every resource in this scan (stale reconciliation)

    for r in resources:
        resource_id = r.get("resource_id", "")
        service     = r.get("service_type", "")
        key         = f"{resource_id}#{service}"
        all_scanned_keys.add(key)

        status = r.get("eol_status", "UNKNOWN")
        if status not in ALERT_SEVERITY:
            continue
        scanned_keys.add(key)
        severity = ALERT_SEVERITY[status]
        reason   = _alert_reason(r, status)

        if key in existing:
            alert = dict(existing[key])
            alert.update({
                "lastSeenAt":      now,
                "lifecycleStatus": status,
                "severity":        severity,
                "reason":          reason,
                "eolDate":         r.get("eol_date"),
                "version":         r.get("version", alert.get("version", "")),
            })
            if alert["status"] == "RESOLVED":
                alert["status"]     = "ACTIVE"
                alert["resolvedAt"] = None
            storage.save_alert(alert)
        else:
            # Re-check in case a concurrent scan created this alert since we loaded `existing`
            concurrent = storage.find_alert_by_resource(workspace_id, account_id, resource_id, service)
            if concurrent:
                alert = dict(concurrent)
                alert.update({
                    "lastSeenAt":      now,
                    "lifecycleStatus": status,
                    "severity":        severity,
                    "reason":          reason,
                    "eolDate":         r.get("eol_date"),
                    "version":         r.get("version", concurrent.get("version", "")),
                })
                if alert["status"] == "RESOLVED":
                    alert["status"]     = "ACTIVE"
                    alert["resolvedAt"] = None
                storage.save_alert(alert)
            else:
                storage.save_alert({
                    "id":              f"alert_{secrets.token_hex(10)}",
                    "workspaceId":     workspace_id,
                    "accountId":       account_id,
                    "resourceId":      resource_id,
                    "service":         service,
                    "resourceName":    r.get("resource_name", resource_id),
                    "region":          r.get("region", ""),
                    "version":         r.get("version", ""),
                    "lifecycleStatus": status,
                    "severity":        severity,
                    "reason":          reason,
                    "eolDate":         r.get("eol_date"),
                    "scanSource":      r.get("scan_source", "ACCOUNT_SCAN"),
                    "status":          "ACTIVE",
                    "createdAt":       now,
                    "lastSeenAt":      now,
                    "acknowledgedAt":  None,
                    "snoozedUntil":    None,
                    "resolvedAt":      None,
                })

    # Auto-resolve alerts for resources whose lifecycle has improved (now SUPPORTED/UNKNOWN).
    # Resolves ACTIVE, ACKNOWLEDGED, and SNOOZED — the resource is no longer risky
    # regardless of whether the user had previously acknowledged or snoozed it.
    for r in resources:
        status      = r.get("eol_status", "UNKNOWN")
        resource_id = r.get("resource_id", "")
        service     = r.get("service_type", "")
        key         = f"{resource_id}#{service}"
        if status in ALERT_SEVERITY or key not in existing:
            continue
        if existing[key].get("status") in ("ACTIVE", "ACKNOWLEDGED", "SNOOZED"):
            alert = dict(existing[key])
            alert["status"]           = "RESOLVED"
            alert["resolvedAt"]       = now
            alert["resolutionSource"] = "scan_reconciliation"
            storage.save_alert(alert)

    # Auto-resolve alerts for resources entirely absent from this scan.
    # These were present in a previous scan but are no longer discoverable —
    # either deleted from AWS or moved out of the scanned scope.
    # ACKNOWLEDGED and SNOOZED are also resolved: the resource is gone, so
    # there is nothing left to action regardless of prior user intent.
    # Use all_scanned_keys (not scanned_keys) so resources that improved to
    # SUPPORTED are not incorrectly marked stale — they ARE in the scan.
    for key, alert in existing.items():
        if key in all_scanned_keys:
            continue  # resource still present in this scan — handled above
        if alert.get("status") not in ("ACTIVE", "ACKNOWLEDGED", "SNOOZED"):
            continue  # already resolved — skip
        alert = dict(alert)
        alert["status"]           = "RESOLVED"
        alert["resolvedAt"]       = now
        alert["resolvedReason"]   = "Resource not found in latest scan"
        alert["resolutionSource"] = "scan_reconciliation"
        storage.save_alert(alert)


# ── Alert API handlers ────────────────────────────────────────────────────────

@workspace_auth("VIEWER")
def handle_ws_alerts_list(workspace_id: str, headers: dict, params: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    status     = params.get("status")                             # ACTIVE|ACKNOWLEDGED|SNOOZED|RESOLVED
    account_id = params.get("accountId")
    limit      = min(int(params.get("limit", 200)), 500)         # server-side cap prevents runaway queries
    now        = datetime.now(timezone.utc).isoformat()

    storage = get_storage()
    alerts  = storage.get_alerts(workspace_id, account_id=account_id,
                                 status=status, limit=limit)

    # Auto-expire snoozed alerts whose snoozedUntil has passed.
    # Write back immediately so Postgres stays consistent with what the UI shows.
    for a in alerts:
        if a.get("status") == "SNOOZED" and (a.get("snoozedUntil") or "") < now:
            a["status"] = "ACTIVE"
            storage.save_alert(a)

    counts = {
        "total":          len(alerts),
        "active":         sum(1 for a in alerts if a.get("status") == "ACTIVE"),
        "acknowledged":   sum(1 for a in alerts if a.get("status") == "ACKNOWLEDGED"),
        "snoozed":        sum(1 for a in alerts if a.get("status") == "SNOOZED"),
        "resolved":       sum(1 for a in alerts if a.get("status") == "RESOLVED"
                                                and not a.get("resolvedReason")),
        "stale":          sum(1 for a in alerts if a.get("status") == "RESOLVED"
                                                and a.get("resolvedReason")),
        "high":           sum(1 for a in alerts if a.get("severity") == "HIGH"),
        "medium":         sum(1 for a in alerts if a.get("severity") == "MEDIUM"),
    }
    return resp(200, {"alerts": alerts, "counts": counts})


@workspace_auth("EDITOR")
def handle_ws_alert_action(workspace_id: str, alert_id: str,
                           action: str, body: dict, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "EDITOR")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    storage = get_storage()
    alert   = storage.get_alert(alert_id, workspace_id)
    if not alert:
        return _error_resp(404, "ALERT_NOT_FOUND", "Alert not found")

    now = datetime.now(timezone.utc).isoformat()

    if action == "acknowledge":
        alert["status"]         = "ACKNOWLEDGED"
        alert["acknowledgedAt"] = now
    elif action == "snooze":
        snooze_until = (body.get("snoozeUntil") or body.get("snoozedUntil") or "").strip()
        if not snooze_until:
            return _error_resp(400, "MISSING_SNOOZE_UNTIL", "snoozeUntil is required")
        if not re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', snooze_until) or snooze_until > "2099-01-01":
            return _error_resp(400, "INVALID_SNOOZE_UNTIL", "snoozeUntil must be a valid ISO datetime")
        if snooze_until <= now:
            return _error_resp(400, "SNOOZE_DATE_IN_PAST", "snoozeUntil must be a future date")
        alert["status"]       = "SNOOZED"
        alert["snoozedUntil"] = snooze_until
        alert["snoozedAt"]    = now
    elif action == "resolve":
        alert["status"]     = "RESOLVED"
        alert["resolvedAt"] = now
    elif action == "reopen":
        alert["status"]         = "ACTIVE"
        alert["acknowledgedAt"] = None
        alert["snoozedUntil"]   = None
        alert["snoozedAt"]      = None
        alert["resolvedAt"]     = None
    else:
        return _error_resp(400, "UNKNOWN_ACTION", f"Unknown action: {action}")

    storage.save_alert(alert)
    return resp(200, {"alert": alert})


# ── Workspace token rotate (workspace-scoped) ──────────────────────────────────

@workspace_auth("ADMIN")
def handle_ws_token_rotate(workspace_id: str, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    new_token        = f"eolm_live_{secrets.token_hex(20)}"
    ws["token_hash"] = _hash_token(new_token)
    ws["rotated_at"] = datetime.now(timezone.utc).isoformat()
    storage = get_storage()
    storage.save_workspace(ws)

    from audit import write_audit, AuditAction
    write_audit(storage, workspace_id, AuditAction.WORKSPACE_TOKEN_ROTATED,
                "Workspace token rotated",
                resource_type="TOKEN", resource_id=workspace_id)

    return resp(200, {
        "success":  True,
        "newToken": new_token,
        "note":     "Save this token — it will not be shown again.",
    })


# ── Role model + API token auth ───────────────────────────────────────────────

_ROLE_ORDER = {"VIEWER": 0, "EDITOR": 1, "ADMIN": 2}
_VALID_ROLES = {"VIEWER", "EDITOR", "ADMIN"}


def _has_role(actual: str, required: str) -> bool:
    return _ROLE_ORDER.get(actual, -1) >= _ROLE_ORDER.get(required, 99)


def _extract_api_token(headers: dict) -> str:
    """Extract raw API token from X-API-Token or Authorization: Bearer headers."""
    explicit = headers.get("x-api-token", "").strip()
    if explicit:
        return explicit
    auth = headers.get("authorization", "")
    if auth.startswith("Bearer eolm_api_"):
        return auth[len("Bearer "):].strip()
    return ""


def _extract_member_session_token(headers: dict) -> str:
    """Extract raw member session token from X-Member-Session-Token or Authorization: Bearer eolm_member_..."""
    explicit = headers.get("x-member-session-token", "").strip()
    if explicit:
        return explicit
    auth = headers.get("authorization", "")
    if auth.startswith("Bearer eolm_member_"):
        return auth[len("Bearer "):].strip()
    return ""


def _verify_workspace_access(workspace_id: str, headers: dict, required_role: str = "VIEWER"):
    """
    Returns (workspace_dict, actor_dict, None) on success.
    Returns (None, None, error_code_str) on failure.
    Supports:
      X-Workspace-Token           → ADMIN
      X-API-Token: eolm_api_xxx   → token's stored role
      Authorization: Bearer eolm_api_xxx → same
    """
    storage       = get_storage()
    raw_api_token = _extract_api_token(headers)

    if raw_api_token:
        if not raw_api_token.startswith("eolm_api_"):
            return None, None, "API_TOKEN_INVALID"
        token_hash = hashlib.sha256(raw_api_token.encode()).hexdigest()
        token_rec  = storage.find_api_token_by_hash(token_hash, workspace_id)
        if not token_rec:
            return None, None, "API_TOKEN_INVALID"
        if token_rec.get("revokedAt"):
            return None, None, "API_TOKEN_REVOKED"
        expires_at = token_rec.get("expiresAt") or ""
        if expires_at and expires_at < datetime.now(timezone.utc).isoformat():
            return None, None, "API_TOKEN_EXPIRED"
        token_role = token_rec.get("role", "VIEWER")
        if not _has_role(token_role, required_role):
            return None, None, "INSUFFICIENT_ROLE"
        ws = storage.get_workspace(workspace_id)
        if not ws:
            return None, None, "WORKSPACE_NOT_FOUND"
        # Update lastUsedAt non-blocking
        try:
            storage.save_api_token({**token_rec,
                                     "lastUsedAt": datetime.now(timezone.utc).isoformat()})
        except Exception:
            pass
        actor = {
            "type":  "API_TOKEN",
            "id":    token_rec["id"],
            "label": token_rec.get("name", "API Token"),
            "role":  token_role,
        }
        return ws, actor, None

    # Check member session token
    raw_member_token = _extract_member_session_token(headers)
    if raw_member_token:
        if not raw_member_token.startswith("eolm_member_"):
            return None, None, "MEMBER_SESSION_INVALID"
        token_hash = hashlib.sha256(raw_member_token.encode()).hexdigest()
        session    = storage.find_member_session_by_token_hash(token_hash, workspace_id)
        if not session:
            return None, None, "MEMBER_SESSION_INVALID"
        if session.get("revokedAt"):
            return None, None, "MEMBER_SESSION_REVOKED"
        expires_at = session.get("expiresAt") or ""
        if expires_at and expires_at < datetime.now(timezone.utc).isoformat():
            return None, None, "MEMBER_SESSION_EXPIRED"
        member = storage.get_member_by_id(session["memberId"], workspace_id)
        if not member or member.get("status") != "ACTIVE":
            return None, None, "MEMBER_DISABLED"
        session_role = session.get("role", "VIEWER")
        if not _has_role(session_role, required_role):
            return None, None, "INSUFFICIENT_ROLE"
        ws = storage.get_workspace(workspace_id)
        if not ws:
            return None, None, "WORKSPACE_NOT_FOUND"
        try:
            storage.save_member_session({**session,
                                         "lastUsedAt": datetime.now(timezone.utc).isoformat()})
        except Exception:
            pass
        actor = {
            "type":  "MEMBER",
            "id":    member["id"],
            "label": member.get("name") or member.get("email", "member"),
            "role":  session_role,
        }
        return ws, actor, None

    # Fall back to workspace token
    ws, err_code = _verify_workspace_ex(workspace_id, headers)
    if not ws:
        if err_code == "WORKSPACE_TOKEN_INVALID":
            ip       = _get_client_ip()
            fail_key = f"ws_auth_fail:{ip}:{workspace_id}"
            fails    = _rl_record(fail_key, _WS_AUTH_FAIL_WINDOW)
            logger.warning(
                "workspace auth failed ip=%s workspace=%s reason=%s token=%s "
                "fails_in_window=%d limit=%d",
                ip, workspace_id, err_code,
                _mask_token(headers.get("x-workspace-token", "")),
                fails, _WS_AUTH_FAIL_LIMIT,
            )
        return None, None, err_code
    actor = {
        "type":  "WORKSPACE_TOKEN",
        "id":    "workspace",
        "label": "Workspace session",
        "role":  "ADMIN",
    }
    return ws, actor, None


# ── API token handlers (workspace-scoped) ─────────────────────────────────────

@workspace_auth("ADMIN")
def handle_ws_api_tokens_list(workspace_id: str, headers: dict) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err, "Authentication failed")
    tokens = get_storage().get_api_tokens(workspace_id)
    # Strip hash before returning to client
    safe = [{k: v for k, v in t.items() if k != "tokenHash"} for t in tokens]
    return resp(200, {"tokens": safe, "count": len(safe)})


@workspace_auth("ADMIN")
def handle_ws_api_token_create(workspace_id: str, body: dict, headers: dict) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err, "Authentication failed")

    name = (body.get("name") or "").strip()
    if not name:
        return _error_resp(400, "MISSING_NAME", "Token name is required")
    if len(name) > 80:
        return _error_resp(400, "NAME_TOO_LONG", "Token name max 80 characters")

    role = (body.get("role") or "VIEWER").upper()
    if role not in _VALID_ROLES:
        return _error_resp(400, "INVALID_ROLE", f"role must be one of: {', '.join(_VALID_ROLES)}")

    expires_at = (body.get("expiresAt") or "").strip()
    if expires_at:
        if not re.match(r'^\d{4}-\d{2}-\d{2}', expires_at):
            return _error_resp(400, "INVALID_EXPIRES_AT", "expiresAt must be ISO date")
        if expires_at < datetime.now(timezone.utc).isoformat():
            return _error_resp(400, "EXPIRES_IN_PAST", "expiresAt must be in the future")

    raw_token  = f"eolm_api_{secrets.token_hex(24)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    prefix     = raw_token[:18] + "..."
    token_id   = f"api_tok_{secrets.token_hex(10)}"
    now        = datetime.now(timezone.utc).isoformat()

    token_rec = {
        "id":          token_id,
        "workspaceId": workspace_id,
        "name":        name,
        "role":        role,
        "tokenHash":   token_hash,
        "prefix":      prefix,
        "lastUsedAt":  None,
        "createdAt":   now,
        "expiresAt":   expires_at or None,
        "revokedAt":   None,
        "createdBy":   actor["label"],
    }
    get_storage().save_api_token(token_rec)

    from audit import write_audit, AuditAction
    write_audit(get_storage(), workspace_id, AuditAction.API_TOKEN_CREATED,
                f"API token '{name}' created with role {role}",
                actor_type=actor["type"], actor_id=actor["id"], actor_label=actor["label"],
                resource_type="TOKEN", resource_id=token_id,
                metadata={"name": name, "role": role})

    # Return raw token ONCE — never stored
    safe = {k: v for k, v in token_rec.items() if k != "tokenHash"}
    return resp(201, {"token": safe, "rawToken": raw_token,
                      "note": "Save this token — it will not be shown again."})


@workspace_auth("ADMIN")
def handle_ws_api_token_revoke(workspace_id: str, token_id: str, headers: dict) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err, "Authentication failed")

    storage   = get_storage()
    token_rec = storage.get_api_token_by_id(token_id, workspace_id)
    if not token_rec:
        return _error_resp(404, "TOKEN_NOT_FOUND", "API token not found")
    if token_rec.get("revokedAt"):
        return _error_resp(409, "ALREADY_REVOKED", "Token is already revoked")

    token_rec["revokedAt"] = datetime.now(timezone.utc).isoformat()
    storage.save_api_token(token_rec)

    from audit import write_audit, AuditAction
    write_audit(storage, workspace_id, AuditAction.API_TOKEN_REVOKED,
                f"API token '{token_rec.get('name', token_id)}' revoked",
                actor_type=actor["type"], actor_id=actor["id"], actor_label=actor["label"],
                resource_type="TOKEN", resource_id=token_id)

    return resp(200, {"success": True, "id": token_id, "revokedAt": token_rec["revokedAt"]})


@workspace_auth("ADMIN")
def handle_ws_api_token_update(workspace_id: str, token_id: str, body: dict, headers: dict) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err, "Authentication failed")

    storage   = get_storage()
    token_rec = storage.get_api_token_by_id(token_id, workspace_id)
    if not token_rec:
        return _error_resp(404, "TOKEN_NOT_FOUND", "API token not found")

    if "name" in body:
        name = body["name"].strip()
        if not name or len(name) > 80:
            return _error_resp(400, "INVALID_NAME", "Token name must be 1–80 characters")
        token_rec["name"] = name

    if "role" in body:
        role = body["role"].upper()
        if role not in _VALID_ROLES:
            return _error_resp(400, "INVALID_ROLE", f"role must be one of: {', '.join(_VALID_ROLES)}")
        token_rec["role"] = role

    storage.save_api_token(token_rec)

    from audit import write_audit, AuditAction
    write_audit(storage, workspace_id, AuditAction.API_TOKEN_UPDATED,
                f"API token '{token_rec.get('name', token_id)}' updated",
                actor_type=actor["type"], actor_id=actor["id"], actor_label=actor["label"],
                resource_type="TOKEN", resource_id=token_id)

    safe = {k: v for k, v in token_rec.items() if k != "tokenHash"}
    return resp(200, {"token": safe})


@workspace_auth("VIEWER")
def handle_ws_audit_logs(workspace_id: str, headers: dict, params: dict) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err, "Authentication failed")
    limit = min(int(params.get("limit", 50)), 200)
    logs  = get_storage().get_audit_logs(workspace_id, limit=limit)
    return resp(200, {"logs": logs, "count": len(logs)})


@workspace_auth("VIEWER")
def handle_ws_access_summary(workspace_id: str, headers: dict) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err, "Authentication failed")

    storage = get_storage()
    tokens  = storage.get_api_tokens(workspace_id)
    active  = [t for t in tokens if not t.get("revokedAt") and
               (not t.get("expiresAt") or t.get("expiresAt", "") > datetime.now(timezone.utc).isoformat())]
    logs    = storage.get_audit_logs(workspace_id, limit=5)
    members = storage.get_members(workspace_id)

    return resp(200, {
        "currentSessionRole":  actor["role"],
        "apiTokensTotal":      len(tokens),
        "apiTokensActive":     len(active),
        "auditLogCount":       len(storage.get_audit_logs(workspace_id, limit=1000)),
        "membersCount":        len([m for m in members if m.get("status") != "REMOVED"]),
        "latestAuditEvents":   logs,
    })


# ── Members (workspace-scoped) ────────────────────────────────────────────────

_MEMBER_STATUSES = {"INVITED", "ACTIVE", "DISABLED"}
_INVITE_EXPIRY_DAYS = 7


def _safe_member(m: dict) -> dict:
    """Strip invite token hash before returning to client."""
    return {k: v for k, v in m.items() if k != "inviteTokenHash"}


@workspace_auth("ADMIN")
def handle_ws_members_list(workspace_id: str, headers: dict) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err, "Authentication failed")
    members = get_storage().get_members(workspace_id)
    visible = [_safe_member(m) for m in members if m.get("status") != "REMOVED"]
    return resp(200, {"members": visible, "count": len(visible)})


@workspace_auth("ADMIN")
def handle_ws_member_invite(workspace_id: str, body: dict, headers: dict) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err, "Authentication failed")

    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return _error_resp(400, "INVALID_EMAIL", "A valid email address is required")
    if len(email) > 254:
        return _error_resp(400, "EMAIL_TOO_LONG", "Email address too long")

    role = (body.get("role") or "VIEWER").upper()
    if role not in _VALID_ROLES:
        return _error_resp(400, "INVALID_ROLE", f"role must be one of: {', '.join(sorted(_VALID_ROLES))}")

    storage = get_storage()
    # Reject duplicate active invite for same email
    existing = [
        m for m in storage.get_members(workspace_id)
        if m.get("email") == email and m.get("status") in ("INVITED", "ACTIVE")
    ]
    if existing:
        return _error_resp(409, "MEMBER_ALREADY_EXISTS",
                           "A member with this email already exists in this workspace")

    raw_token  = f"inv_{secrets.token_hex(32)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc).replace(microsecond=0)
                  + timedelta(days=_INVITE_EXPIRY_DAYS)).isoformat()
    member_id  = f"mbr_{secrets.token_hex(10)}"
    now        = datetime.now(timezone.utc).isoformat()

    member = {
        "id":               member_id,
        "workspaceId":      workspace_id,
        "email":            email,
        "name":             (body.get("name") or "").strip(),
        "role":             role,
        "status":           "INVITED",
        "inviteTokenHash":  token_hash,
        "inviteExpiresAt":  expires_at,
        "invitedAt":        now,
        "invitedBy":        actor["label"],
        "acceptedAt":       None,
        "disabledAt":       None,
    }
    storage.save_member(member)

    from audit import write_audit, AuditAction
    write_audit(
        storage, workspace_id,
        AuditAction.MEMBER_INVITED,
        f"'{email}' invited as {role}",
        actor_type=actor["type"], actor_id=actor["id"], actor_label=actor["label"],
        resource_type="member", resource_id=member_id,
        metadata={"email": email, "role": role},
    )

    return resp(201, {
        "member":      _safe_member(member),
        "inviteToken": raw_token,
        "note":        "Share this invite link with the member. Token expires in 7 days.",
    })


def handle_ws_member_accept_invite(workspace_id: str, body: dict) -> dict:
    """Public endpoint — no workspace auth required. Validates invite token."""
    raw_token = (body.get("token") or "").strip()
    if not raw_token.startswith("inv_"):
        return _error_resp(400, "INVALID_INVITE_TOKEN", "Invalid invite token")

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    storage    = get_storage()
    ws         = storage.get_workspace(workspace_id)
    if not ws:
        return _error_resp(404, "WORKSPACE_NOT_FOUND", "Workspace not found")

    member = storage.find_member_by_invite_token_hash(token_hash, workspace_id)
    if not member:
        return _error_resp(404, "INVITE_NOT_FOUND", "Invite not found or already used")
    if member.get("status") == "ACTIVE":
        return _error_resp(409, "ALREADY_ACCEPTED", "Invite already accepted")
    if member.get("status") == "DISABLED":
        return _error_resp(403, "MEMBER_DISABLED", "This member account has been disabled")

    expires_at = member.get("inviteExpiresAt") or ""
    if expires_at and expires_at < datetime.now(timezone.utc).isoformat():
        return _error_resp(410, "INVITE_EXPIRED", "Invite has expired — ask the admin to re-invite you")

    name = (body.get("name") or "").strip()
    now  = datetime.now(timezone.utc).isoformat()
    updated = {
        **member,
        "status":     "ACTIVE",
        "name":       name or member.get("name", ""),
        "acceptedAt": now,
    }
    storage.save_member(updated)

    # Create member session — raw token shown once, only hash stored
    raw_session_token  = f"eolm_member_{secrets.token_hex(32)}"
    session_hash       = hashlib.sha256(raw_session_token.encode()).hexdigest()
    session_id         = f"mem_sess_{secrets.token_hex(10)}"
    session_expires_at = (datetime.now(timezone.utc) + timedelta(hours=MEMBER_SESSION_TTL_HOURS)).isoformat()
    session_rec = {
        "id":          session_id,
        "workspaceId": workspace_id,
        "memberId":    updated["id"],
        "role":        updated["role"],
        "tokenHash":   session_hash,
        "createdAt":   now,
        "expiresAt":   session_expires_at,
        "lastUsedAt":  None,
        "revokedAt":   None,
    }
    storage.save_member_session(session_rec)

    from audit import write_audit, AuditAction
    write_audit(
        storage, workspace_id,
        AuditAction.MEMBER_INVITE_ACCEPTED,
        f"'{updated['email']}' accepted their invite",
        actor_type="MEMBER", actor_id=updated["id"],
        actor_label=updated.get("name") or updated["email"],
        resource_type="member", resource_id=updated["id"],
        metadata={"email": updated["email"], "role": updated["role"]},
    )
    write_audit(
        storage, workspace_id,
        AuditAction.MEMBER_SESSION_CREATED,
        f"Member session created for '{updated['email']}'",
        actor_type="MEMBER", actor_id=updated["id"],
        actor_label=updated.get("name") or updated["email"],
        resource_type="member_session", resource_id=session_id,
        metadata={"email": updated["email"], "role": updated["role"]},
    )

    return resp(200, {
        "member":             _safe_member(updated),
        "workspaceId":        workspace_id,
        "workspaceName":      ws.get("name", ""),
        "memberId":           updated["id"],
        "memberName":         updated.get("name") or updated.get("email", ""),
        "role":               updated["role"],
        "memberSessionToken": raw_session_token,
        "expiresAt":          session_expires_at,
        "message":            "Invite accepted. Redirecting to your workspace...",
    })


@workspace_auth("ADMIN")
def handle_ws_member_update(workspace_id: str, member_id: str, body: dict, headers: dict) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err, "Authentication failed")

    storage = get_storage()
    member  = storage.get_member_by_id(member_id, workspace_id)
    if not member or member.get("status") == "REMOVED":
        return _error_resp(404, "MEMBER_NOT_FOUND", "Member not found")

    from audit import write_audit, AuditAction

    if "role" in body:
        new_role = body["role"].upper()
        if new_role not in _VALID_ROLES:
            return _error_resp(400, "INVALID_ROLE", f"role must be one of: {', '.join(sorted(_VALID_ROLES))}")
        old_role = member["role"]
        member   = {**member, "role": new_role}
        storage.save_member(member)
        write_audit(
            storage, workspace_id,
            AuditAction.MEMBER_ROLE_CHANGED,
            f"'{member['email']}' role changed {old_role} → {new_role}",
            actor_type=actor["type"], actor_id=actor["id"], actor_label=actor["label"],
            resource_type="member", resource_id=member_id,
            metadata={"email": member["email"], "old_role": old_role, "new_role": new_role},
        )
        # Revoke existing sessions so stale role cannot be used after downgrade
        if old_role != new_role:
            revoke_count = storage.revoke_member_sessions(member_id, workspace_id)
            if revoke_count:
                write_audit(
                    storage, workspace_id,
                    AuditAction.MEMBER_SESSIONS_REVOKED,
                    f"Revoked {revoke_count} active session(s) for '{member['email']}' after role change",
                    actor_type=actor["type"], actor_id=actor["id"], actor_label=actor["label"],
                    resource_type="member", resource_id=member_id,
                    metadata={"email": member["email"], "reason": "role_change", "count": revoke_count},
                )

    if "status" in body:
        new_status = body["status"].upper()
        if new_status not in _MEMBER_STATUSES:
            return _error_resp(400, "INVALID_STATUS", f"status must be one of: {', '.join(sorted(_MEMBER_STATUSES))}")
        now    = datetime.now(timezone.utc).isoformat()
        update = {"status": new_status}
        if new_status == "DISABLED":
            update["disabledAt"] = now
            audit_action  = AuditAction.MEMBER_DISABLED
            audit_message = f"'{member['email']}' disabled"
        else:
            update["disabledAt"] = None
            audit_action  = AuditAction.MEMBER_ENABLED
            audit_message = f"'{member['email']}' re-enabled"
        member = {**member, **update}
        storage.save_member(member)
        write_audit(
            storage, workspace_id, audit_action, audit_message,
            actor_type=actor["type"], actor_id=actor["id"], actor_label=actor["label"],
            resource_type="member", resource_id=member_id,
            metadata={"email": member["email"], "new_status": new_status},
        )
        # Revoke active sessions immediately when member is disabled
        if new_status == "DISABLED":
            storage.revoke_member_sessions(member_id, workspace_id)

    return resp(200, {"member": _safe_member(member)})


@workspace_auth("ADMIN")
def handle_ws_member_remove(workspace_id: str, member_id: str, headers: dict) -> dict:
    ws, actor, err = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err, "Authentication failed")

    storage = get_storage()
    member  = storage.get_member_by_id(member_id, workspace_id)
    if not member or member.get("status") == "REMOVED":
        return _error_resp(404, "MEMBER_NOT_FOUND", "Member not found")

    storage.revoke_member_sessions(member_id, workspace_id)
    storage.delete_member(member_id, workspace_id)

    from audit import write_audit, AuditAction
    write_audit(
        storage, workspace_id,
        AuditAction.MEMBER_REMOVED,
        f"'{member['email']}' removed from workspace",
        actor_type=actor["type"], actor_id=actor["id"], actor_label=actor["label"],
        resource_type="member", resource_id=member_id,
        metadata={"email": member["email"], "role": member.get("role")},
    )
    return resp(200, {"removed": True, "memberId": member_id})


# ── Member magic-link login ───────────────────────────────────────────────────

_LOGIN_TOKEN_EXPIRY_MINUTES = 15
_MEMBER_LOGIN_DEV_LINKS     = os.environ.get("MEMBER_LOGIN_DEV_LINKS", "").lower() in ("1", "true", "yes")
if _MEMBER_LOGIN_DEV_LINKS and _IS_PRODUCTION:
    raise RuntimeError(
        "FATAL: MEMBER_LOGIN_DEV_LINKS=true is not allowed when APP_ENV=production. "
        "Set MEMBER_LOGIN_DEV_LINKS=false before starting."
    )
_APP_PUBLIC_URL             = (os.environ.get("APP_PUBLIC_URL") or os.environ.get("APP_URL", "")).rstrip("/")


def _safe_request_origin(headers: dict | None) -> str:
    if not headers:
        return ""
    origin = (headers.get("origin") or "").strip().rstrip("/")
    if re.fullmatch(r"https?://[^/\s]+(?::\d+)?", origin):
        return origin
    host = (headers.get("host") or "").strip()
    proto = (headers.get("x-forwarded-proto") or "").strip() or "https"
    if proto in ("http", "https") and re.fullmatch(r"[^/\s]+(?::\d+)?", host):
        return f"{proto}://{host}"
    return ""


def _build_member_login_link(workspace_id: str, raw_token: str, headers: dict | None = None) -> str:
    base_url = _APP_PUBLIC_URL or _safe_request_origin(headers)
    if not base_url:
        if _MEMBER_LOGIN_DEV_LINKS:
            logger.warning("APP_PUBLIC_URL not set; cannot build member login link")
        return ""
    return f"{base_url}/member-login/complete?wsId={workspace_id}&token={raw_token}"


def _create_member_session_for(storage, workspace_id: str, member: dict) -> tuple[str, str]:
    """Create member session, return (raw_token, expires_at)."""
    raw_token          = f"eolm_member_{secrets.token_hex(32)}"
    session_hash       = hashlib.sha256(raw_token.encode()).hexdigest()
    session_expires_at = (datetime.now(timezone.utc) + timedelta(hours=MEMBER_SESSION_TTL_HOURS)).isoformat()
    storage.save_member_session({
        "id":          f"mem_sess_{secrets.token_hex(10)}",
        "workspaceId": workspace_id,
        "memberId":    member["id"],
        "role":        member["role"],
        "tokenHash":   session_hash,
        "createdAt":   datetime.now(timezone.utc).isoformat(),
        "expiresAt":   session_expires_at,
        "lastUsedAt":  None,
        "revokedAt":   None,
    })
    return raw_token, session_expires_at


def handle_ws_member_login_link(workspace_id: str, body: dict, headers: dict | None = None) -> dict:
    """Public endpoint — request a magic login link via email."""
    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return _error_resp(400, "INVALID_EMAIL", "A valid email address is required")

    storage = get_storage()
    ws      = storage.get_workspace(workspace_id)
    if not ws:
        return _error_resp(404, "WORKSPACE_NOT_FOUND", "Workspace not found")

    # Look up active member — do not reveal whether email exists in response
    member = next(
        (m for m in storage.get_members(workspace_id)
         if m.get("email") == email and m.get("status") == "ACTIVE"),
        None,
    )

    if member:
        now_dt     = datetime.now(timezone.utc)
        # Expire any outstanding unused tokens for this member before issuing a new one
        existing_tokens = storage.get_member_login_tokens_for_member(member["id"], workspace_id)
        expired_marker  = now_dt.isoformat()
        for tok in (existing_tokens or []):
            if not tok.get("usedAt") and tok.get("expiresAt", "") > expired_marker:
                storage.save_member_login_token({**tok, "expiresAt": expired_marker})

        raw_token  = f"login_{secrets.token_hex(32)}"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = (now_dt + timedelta(minutes=_LOGIN_TOKEN_EXPIRY_MINUTES)).isoformat()
        storage.save_member_login_token({
            "id":          f"login_tok_{secrets.token_hex(10)}",
            "workspaceId": workspace_id,
            "memberId":    member["id"],
            "tokenHash":   token_hash,
            "createdAt":   now_dt.isoformat(),
            "expiresAt":   expires_at,
            "usedAt":      None,
        })

        full_link = _build_member_login_link(workspace_id, raw_token, headers)

        # Try to send email if provider is configured.
        email_configured = False
        email_sent = False
        if full_link:
            try:
                from notifications import send_email, is_email_configured
                email_configured = is_email_configured()
                if email_configured:
                    ws_name  = ws.get("name", workspace_id)
                    subject  = f"Your login link for {ws_name}"
                    html_body = (
                        f"<p>Hi {member.get('name') or email},</p>"
                        f"<p>Click the link below to sign in to <strong>{ws_name}</strong>. "
                        f"This link expires in {_LOGIN_TOKEN_EXPIRY_MINUTES} minutes.</p>"
                        f'<p><a href="{full_link}">Sign in to {ws_name}</a></p>'
                        f"<p>If you didn't request this, you can ignore this email.</p>"
                    )
                    text_body = (
                        f"Sign in to {ws_name}:\n{full_link}\n\n"
                        f"This link expires in {_LOGIN_TOKEN_EXPIRY_MINUTES} minutes."
                    )
                    result    = send_email([email], subject, html_body, text_body)
                    email_sent = result.get("success", False)
            except Exception:
                pass

        if _MEMBER_LOGIN_DEV_LINKS and full_link:
            # Log link for dev convenience — token is masked so it never appears in log streams.
            safe_link = full_link.split("?")[0] + "?token=<masked>"
            logger.warning(
                "DEV ONLY - Member magic login link generated\n"
                "Workspace: %s\n"
                "Member: %s\n"
                "Expires in: %s minutes\n"
                "Link: %s",
                workspace_id,
                email,
                _LOGIN_TOKEN_EXPIRY_MINUTES,
                safe_link,
            )

        from audit import write_audit, AuditAction
        write_audit(
            storage, workspace_id,
            AuditAction.MEMBER_LOGIN_LINK_SENT,
            f"Login link sent to '{email}'",
            actor_type="MEMBER", actor_id=member["id"],
            actor_label=member.get("name") or email,
            resource_type="member", resource_id=member["id"],
            metadata={"email": email, "emailSent": email_sent},
        )

    return resp(200, {
        "ok": True,
        "message": "If this email is an active member, a login link has been sent.",
    })


def handle_ws_member_complete_login(workspace_id: str, body: dict) -> dict:
    """Public endpoint — validate magic-link token, return member session."""
    raw_token = (body.get("token") or "").strip()
    if not raw_token.startswith("login_"):
        return _error_resp(400, "INVALID_LOGIN_TOKEN", "Invalid login token")

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    storage    = get_storage()
    ws         = storage.get_workspace(workspace_id)
    if not ws:
        return _error_resp(404, "WORKSPACE_NOT_FOUND", "Workspace not found")

    login_rec = storage.find_member_login_token_by_hash(token_hash, workspace_id)
    if not login_rec:
        return _error_resp(404, "LOGIN_TOKEN_NOT_FOUND", "Login token not found or already used")
    if login_rec.get("usedAt"):
        return _error_resp(410, "LOGIN_TOKEN_USED", "This login link has already been used")
    expires_at = login_rec.get("expiresAt") or ""
    if expires_at and expires_at < datetime.now(timezone.utc).isoformat():
        return _error_resp(410, "LOGIN_TOKEN_EXPIRED",
                           f"Login link expired — request a new one")

    member = storage.get_member_by_id(login_rec["memberId"], workspace_id)
    if not member or member.get("status") != "ACTIVE":
        return _error_resp(403, "MEMBER_DISABLED", "This member account is not active")

    # Mark token used
    storage.save_member_login_token({**login_rec, "usedAt": datetime.now(timezone.utc).isoformat()})

    # Create member session
    raw_sess, sess_expires = _create_member_session_for(storage, workspace_id, member)

    from audit import write_audit, AuditAction
    write_audit(
        storage, workspace_id,
        AuditAction.MEMBER_SESSION_CREATED,
        f"Member session created for '{member['email']}'",
        actor_type="MEMBER", actor_id=member["id"],
        actor_label=member.get("name") or member["email"],
        resource_type="member_session", resource_id=member["id"],
        metadata={"email": member["email"], "role": member["role"]},
    )
    write_audit(
        storage, workspace_id,
        AuditAction.MEMBER_LOGIN_COMPLETED,
        f"'{member['email']}' completed magic-link login",
        actor_type="MEMBER", actor_id=member["id"],
        actor_label=member.get("name") or member["email"],
        resource_type="member", resource_id=member["id"],
        metadata={"email": member["email"], "role": member["role"]},
    )

    return resp(200, {
        "workspaceId":        workspace_id,
        "workspaceName":      ws.get("name", ""),
        "memberId":           member["id"],
        "memberName":         member.get("name") or member.get("email", ""),
        "role":               member["role"],
        "memberSessionToken": raw_sess,
        "expiresAt":          sess_expires,
        "message":            "Login successful. Redirecting to your workspace...",
    })


# ── Notification settings (workspace-scoped) ──────────────────────────────────

_DEFAULT_NOTIF_SETTINGS = {
    "email": {
        "enabled":           False,
        "recipients":        [],
        "sendImmediate":     True,
        "sendWeeklyDigest":  True,
        "sendMonthlyReport": True,
    },
    "slack": {
        "enabled":           False,
        "webhookUrl":        "",
        "sendImmediate":     True,
        "sendWeeklyDigest":  True,
        "sendMonthlyReport": True,
    },
    "thresholds": {
        "sendEol":              True,
        "sendExpiringSoon":     True,
        "sendExtendedSupport":  False,
        "sendUnknown":          False,
    },
    "lastUpdatedAt": None,
}


def _merge_notif_settings(stored: dict) -> dict:
    merged = {k: dict(v) if isinstance(v, dict) else v
              for k, v in _DEFAULT_NOTIF_SETTINGS.items()}
    for key, val in stored.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = {**merged[key], **val}
        else:
            merged[key] = val
    return merged


@workspace_auth("VIEWER")
def handle_ws_notification_settings_get(workspace_id: str, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    stored   = get_storage().get_notification_settings(workspace_id)
    settings = _merge_notif_settings(stored)
    from notifications import is_email_configured, is_slack_configured
    return resp(200, {
        "settings":          settings,
        "emailConfigured":   is_email_configured(),
        "slackConfigurable": True,
    })


@workspace_auth("ADMIN")
def handle_ws_notification_settings_patch(workspace_id: str, body: dict, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    storage  = get_storage()
    existing = _merge_notif_settings(storage.get_notification_settings(workspace_id))

    # Validate email recipients
    if "email" in body:
        recipients = body["email"].get("recipients", existing["email"]["recipients"])
        if not isinstance(recipients, list):
            return _error_resp(400, "INVALID_RECIPIENTS", "recipients must be a list")
        if len(recipients) > 10:
            return _error_resp(400, "TOO_MANY_RECIPIENTS", "Maximum 10 email recipients")
        for addr in recipients:
            if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', str(addr)):
                return _error_resp(400, "INVALID_EMAIL", f"Invalid email address: {addr}")
        existing["email"] = {**existing["email"], **body["email"], "recipients": recipients}

    if "slack" in body:
        webhook_url = body["slack"].get("webhookUrl", existing["slack"]["webhookUrl"])
        if webhook_url and not webhook_url.startswith("https://hooks.slack.com/"):
            return _error_resp(400, "INVALID_WEBHOOK_URL",
                               "Slack webhook URL must start with https://hooks.slack.com/")
        existing["slack"] = {**existing["slack"], **body["slack"], "webhookUrl": webhook_url}

    if "thresholds" in body:
        _ALLOWED_THRESHOLD_KEYS = {"sendEol", "sendExpiringSoon", "sendUnknown", "sendExtendedSupport"}
        unknown_keys = set(body["thresholds"].keys()) - _ALLOWED_THRESHOLD_KEYS
        if unknown_keys:
            return _error_resp(400, "INVALID_THRESHOLD_KEY",
                               f"Unknown threshold keys: {', '.join(sorted(unknown_keys))}")
        existing["thresholds"] = {**existing["thresholds"], **{
            k: v for k, v in body["thresholds"].items() if k in _ALLOWED_THRESHOLD_KEYS
        }}

    existing["lastUpdatedAt"] = datetime.now(timezone.utc).isoformat()
    settings = storage.save_notification_settings(workspace_id, existing)
    return resp(200, {"settings": settings})


@workspace_auth("ADMIN")
def handle_ws_notifications_test(workspace_id: str, body: dict, headers: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "ADMIN")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")

    channel = (body.get("channel") or "").upper()
    if channel not in ("EMAIL", "SLACK"):
        return _error_resp(400, "INVALID_CHANNEL", "channel must be EMAIL or SLACK")

    storage  = get_storage()
    settings = _merge_notif_settings(storage.get_notification_settings(workspace_id))
    ws_name  = ws.get("name", workspace_id)

    from notifications import (
        build_email_test, build_slack_test,
        send_email, send_slack,
        is_email_configured, is_slack_configured,
        make_delivery_log,
    )

    if channel == "EMAIL":
        recipients = settings["email"].get("recipients", [])
        if not recipients:
            return _error_resp(400, "NO_RECIPIENTS", "No email recipients configured")
        if not is_email_configured():
            return _error_resp(503, "EMAIL_NOT_CONFIGURED",
                               "Email delivery is not configured on this server")
        subject, html_body, text_body = build_email_test(ws_name)
        result = send_email(recipients, subject, html_body, text_body)
        log = make_delivery_log(workspace_id, "TEST", "EMAIL",
                                "SUCCESS" if result["success"] else "FAILED",
                                recipient=", ".join(recipients),
                                error=result.get("error"))
        storage.save_notification_log(log)
        if not result["success"]:
            return _error_resp(502, "EMAIL_SEND_FAILED", result.get("error", "Send failed"))
        return resp(200, {"success": True, "channel": "EMAIL", "recipients": recipients})

    # SLACK
    webhook_url = settings["slack"].get("webhookUrl", "")
    if not webhook_url:
        return _error_resp(400, "NO_WEBHOOK_URL", "No Slack webhook URL configured")
    if not is_slack_configured(webhook_url):
        return _error_resp(400, "INVALID_WEBHOOK_URL", "Invalid Slack webhook URL")
    payload = build_slack_test(ws_name)
    result  = send_slack(webhook_url, payload)
    log = make_delivery_log(workspace_id, "TEST", "SLACK",
                            "SUCCESS" if result["success"] else "FAILED",
                            error=result.get("error"))
    storage.save_notification_log(log)
    if not result["success"]:
        return _error_resp(502, "SLACK_SEND_FAILED", result.get("error", "Send failed"))
    return resp(200, {"success": True, "channel": "SLACK"})


@workspace_auth("VIEWER")
def handle_ws_notifications_logs(workspace_id: str, headers: dict, params: dict) -> dict:
    ws, actor, err_code = _verify_workspace_access(workspace_id, headers, "VIEWER")
    if not ws:
        return _error_resp(401, err_code, "Workspace authentication failed")
    limit = min(int(params.get("limit", 50)), 100)
    logs  = get_storage().get_notification_logs(workspace_id, limit=limit)
    return resp(200, {"logs": logs, "count": len(logs)})


def handle_admin_weekly_digest(headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")

    storage    = get_storage()
    workspaces = storage.get_workspaces()
    sent       = 0
    errors     = []

    from notifications import (
        build_email_weekly_digest, build_slack_weekly_digest,
        send_email, send_slack,
        is_email_configured, is_slack_configured,
        make_delivery_log,
    )

    for ws in workspaces:
        ws_id   = ws.get("id", "")
        ws_name = ws.get("name", ws_id)
        if not ws_id:
            continue

        settings = _merge_notif_settings(storage.get_notification_settings(ws_id))
        all_alerts = storage.get_alerts(ws_id, limit=500)
        active = [a for a in all_alerts if a.get("status") == "ACTIVE"]

        if not active:
            continue

        if settings["email"].get("enabled") and settings["email"].get("sendWeeklyDigest"):
            recipients = settings["email"].get("recipients", [])
            if recipients and is_email_configured():
                subject, html_body, text_body = build_email_weekly_digest(ws_name, active)
                result = send_email(recipients, subject, html_body, text_body)
                log = make_delivery_log(ws_id, "WEEKLY_DIGEST", "EMAIL",
                                        "SUCCESS" if result["success"] else "FAILED",
                                        recipient=", ".join(recipients),
                                        alert_count=len(active),
                                        error=result.get("error"))
                storage.save_notification_log(log)
                if result["success"]:
                    sent += 1
                else:
                    errors.append(f"{ws_id}:email:{result.get('error')}")

        if settings["slack"].get("enabled") and settings["slack"].get("sendWeeklyDigest"):
            webhook_url = settings["slack"].get("webhookUrl", "")
            if is_slack_configured(webhook_url):
                payload = build_slack_weekly_digest(ws_name, active)
                result  = send_slack(webhook_url, payload)
                log = make_delivery_log(ws_id, "WEEKLY_DIGEST", "SLACK",
                                        "SUCCESS" if result["success"] else "FAILED",
                                        alert_count=len(active),
                                        error=result.get("error"))
                storage.save_notification_log(log)
                if result["success"]:
                    sent += 1
                else:
                    errors.append(f"{ws_id}:slack:{result.get('error')}")

    return resp(200, {
        "success":     True,
        "workspaces":  len(workspaces),
        "sent":        sent,
        "errors":      errors,
    })


def _monthly_report_messages(ws_name: str, snapshot: dict) -> tuple[str, str, str, dict]:
    summary = snapshot.get("summary", {})
    top = snapshot.get("topRisks", [])[:5]
    month = datetime.now(timezone.utc).strftime("%B %Y")
    subject = f"AWS EOL Monthly Risk Report — {ws_name} — {month}"
    rows = "".join(
        f"<tr><td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>{r.get('resourceName','')}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>{r.get('service','')}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>{r.get('version','')}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>{r.get('status','')}</td></tr>"
        for r in top
    )
    html = f"""<!DOCTYPE html><html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#0f172a">
<h1>AWS EOL Monthly Risk Report</h1>
<p>Workspace: <strong>{ws_name}</strong></p>
<p>Risk score: <strong>{summary.get('riskScore', 0)}</strong> ({summary.get('riskLevel', 'LOW')})</p>
<p>EOL: {summary.get('eol', 0)} · Expiring Soon: {summary.get('expiringSoon', 0)} · Total: {summary.get('total', 0)}</p>
<h2>Top risks</h2><table style="border-collapse:collapse">{rows or '<tr><td>No EOL risks found.</td></tr>'}</table>
<p>Open the Reports page in AWS EOL Monitor for CSV export and print-ready detail.</p>
<p style="font-size:12px;color:#64748b">Use this report as supporting evidence for lifecycle risk reviews. Final compliance interpretation depends on your control environment.</p>
</body></html>"""
    text = (
        f"AWS EOL Monthly Risk Report\nWorkspace: {ws_name}\n"
        f"Risk score: {summary.get('riskScore', 0)} ({summary.get('riskLevel', 'LOW')})\n"
        f"EOL: {summary.get('eol', 0)} | Expiring Soon: {summary.get('expiringSoon', 0)} | Total: {summary.get('total', 0)}\n"
        "Open the Reports page in AWS EOL Monitor for CSV export and print-ready detail."
    )
    slack = {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "AWS EOL Monthly Risk Report"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Workspace*\n{ws_name}"},
                {"type": "mrkdwn", "text": f"*Risk Score*\n{summary.get('riskScore', 0)} ({summary.get('riskLevel', 'LOW')})"},
                {"type": "mrkdwn", "text": f"*EOL*\n{summary.get('eol', 0)}"},
                {"type": "mrkdwn", "text": f"*Expiring Soon*\n{summary.get('expiringSoon', 0)}"},
            ]},
        ]
    }
    return subject, html, text, slack


def handle_admin_monthly_reports(headers: dict) -> dict:
    if not _verify_admin(headers):
        return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")

    storage = get_storage()
    workspaces = storage.get_workspaces()
    created = 0
    sent = 0
    errors = []

    from notifications import (
        send_email, send_slack, is_email_configured, is_slack_configured,
        make_delivery_log,
    )

    for ws in workspaces:
        ws_id = ws.get("id", "")
        ws_name = ws.get("name", ws_id)
        if not ws_id:
            continue
        summary = _build_report_summary(ws_id, source="SCHEDULED")
        snapshot = _snapshot_from_summary(ws_id, summary, "SCHEDULED")
        storage.save_report_snapshot(snapshot)
        created += 1

        settings = _merge_notif_settings(storage.get_notification_settings(ws_id))
        subject, html, text, slack_payload = _monthly_report_messages(ws_name, snapshot)

        if settings["email"].get("enabled") and settings["email"].get("sendMonthlyReport"):
            recipients = settings["email"].get("recipients", [])
            if recipients and is_email_configured():
                result = send_email(recipients, subject, html, text)
                storage.save_notification_log(make_delivery_log(
                    ws_id, "MONTHLY_REPORT", "EMAIL",
                    "SUCCESS" if result["success"] else "FAILED",
                    recipient=", ".join(recipients),
                    alert_count=snapshot.get("summary", {}).get("total", 0),
                    error=result.get("error"),
                ))
                sent += 1 if result["success"] else 0
                if not result["success"]:
                    errors.append(f"{ws_id}:email:{result.get('error')}")

        if settings["slack"].get("enabled") and settings["slack"].get("sendMonthlyReport"):
            webhook = settings["slack"].get("webhookUrl", "")
            if is_slack_configured(webhook):
                result = send_slack(webhook, slack_payload)
                storage.save_notification_log(make_delivery_log(
                    ws_id, "MONTHLY_REPORT", "SLACK",
                    "SUCCESS" if result["success"] else "FAILED",
                    alert_count=snapshot.get("summary", {}).get("total", 0),
                    error=result.get("error"),
                ))
                sent += 1 if result["success"] else 0
                if not result["success"]:
                    errors.append(f"{ws_id}:slack:{result.get('error')}")

    return resp(200, {"success": True, "workspaces": len(workspaces), "created": created, "sent": sent, "errors": errors})


def _trigger_scan_notifications(workspace_id: str, ws: dict, account: dict,
                                 scan_id: str, summary: dict, resources: list) -> None:
    """Fire-and-forget: send scan-complete notifications. Errors are logged, not raised."""
    try:
        storage  = get_storage()
        settings = _merge_notif_settings(storage.get_notification_settings(workspace_id))
        ws_name  = ws.get("name", workspace_id)
        acct_name = account.get("name", account.get("accountId", ""))

        alerts = storage.get_alerts(workspace_id, account_id=account.get("id"), limit=200)
        active = [a for a in alerts if a.get("status") == "ACTIVE"]

        from notifications import (
            build_email_scan_summary, build_slack_scan_summary,
            send_email, send_slack,
            is_email_configured, is_slack_configured,
            make_delivery_log,
        )

        if settings["email"].get("enabled") and settings["email"].get("sendImmediate"):
            recipients = settings["email"].get("recipients", [])
            thresholds = settings.get("thresholds", {})
            filtered   = [a for a in active if (
                (a.get("severity") == "HIGH"   and thresholds.get("sendEol", True)) or
                (a.get("severity") == "MEDIUM" and thresholds.get("sendExpiringSoon", True)) or
                (a.get("severity") == "LOW"    and thresholds.get("sendExtendedSupport", False))
            )]
            if recipients and is_email_configured() and filtered:
                subject, html, text = build_email_scan_summary(
                    ws_name, scan_id, acct_name, summary, filtered
                )
                result = send_email(recipients, subject, html, text)
                log = make_delivery_log(workspace_id, "SCAN_COMPLETE", "EMAIL",
                                        "SUCCESS" if result["success"] else "FAILED",
                                        recipient=", ".join(recipients),
                                        scan_id=scan_id,
                                        alert_count=len(filtered),
                                        error=result.get("error"))
                storage.save_notification_log(log)

        if settings["slack"].get("enabled") and settings["slack"].get("sendImmediate"):
            webhook_url = settings["slack"].get("webhookUrl", "")
            thresholds  = settings.get("thresholds", {})
            filtered    = [a for a in active if (
                (a.get("severity") == "HIGH"   and thresholds.get("sendEol", True)) or
                (a.get("severity") == "MEDIUM" and thresholds.get("sendExpiringSoon", True)) or
                (a.get("severity") == "LOW"    and thresholds.get("sendExtendedSupport", False))
            )]
            if is_slack_configured(webhook_url) and filtered:
                payload = build_slack_scan_summary(ws_name, scan_id, acct_name, summary, filtered)
                result  = send_slack(webhook_url, payload)
                log = make_delivery_log(workspace_id, "SCAN_COMPLETE", "SLACK",
                                        "SUCCESS" if result["success"] else "FAILED",
                                        scan_id=scan_id,
                                        alert_count=len(filtered),
                                        error=result.get("error"))
                storage.save_notification_log(log)
    except Exception as exc:
        logger.warning("Notification trigger failed (non-fatal): %s", exc)


# ── Legacy (unscoped) account handlers — kept for backward compatibility ──────

def handle_accounts_list() -> dict:
    storage = get_storage()
    accounts = storage.get_accounts()
    return resp(200, {"accounts": accounts, "count": len(accounts)})


def handle_account_save(body: dict) -> dict:
    if not body.get("id") or not body.get("accountId") or not body.get("roleArn"):
        return resp(400, {"error": "Missing required fields: id, accountId, roleArn"})
    storage = get_storage()
    account = storage.save_account(body)
    return resp(200, {"account": account})


def handle_account_update(account_id: str, body: dict) -> dict:
    storage = get_storage()
    accounts = storage.get_accounts()
    existing = next((a for a in accounts if a.get("id") == account_id), None)
    if not existing:
        return resp(404, {"error": "Account not found"})
    merged = {**existing, **body, "id": account_id}
    account = storage.save_account(merged)
    return resp(200, {"account": account})


def handle_account_delete(account_id: str) -> dict:
    storage = get_storage()
    deleted = storage.delete_account(account_id)
    if not deleted:
        return resp(404, {"error": "Account not found"})
    return resp(200, {"deleted": True, "id": account_id})


def handle_health() -> dict:
    storage_backend = os.environ.get("STORAGE_BACKEND", "file")
    base = {
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "storage_backend": storage_backend,
    }
    try:
        get_storage().get_alerts("__health__", limit=1)
        return resp(200, {**base, "status": "ok", "storage": "ok"})
    except Exception as exc:
        logger.error("Health check: storage unreachable: %s", exc)
        return resp(503, {**base, "status": "degraded", "storage": "error"})


def handle_scan_trigger() -> dict:
    try:
        boto3.client("lambda").invoke(
            FunctionName=COLLECTOR_FUNCTION,
            InvocationType="Event",
            Payload=b"{}",
        )
        return resp(202, {"message": "Scan triggered"})
    except ClientError as e:
        logger.error("Lambda invoke error: %s", e)
        return resp(500, {"error": "Scan trigger failed"})


# ── Router ────────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    if event.get("type") == "ORG_SCAN_WORKER":
        return handle_org_scan_worker_event(event)

    method   = event.get("httpMethod", "GET")
    path     = event.get("path", "/")
    params   = event.get("queryStringParameters") or {}
    body_raw = event.get("body") or "{}"
    # Normalize headers to lowercase keys for consistent access
    headers  = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    # Store client IP in thread-local so rate limiter helpers can read it
    _request_local.client_ip = _extract_client_ip(event)

    if method == "OPTIONS":
        return resp(200, {})

    try:
        body = json.loads(body_raw) if body_raw else {}
    except json.JSONDecodeError:
        body = {}

    logger.info("%s %s params=%s", method, path, params)

    # ── Workspace auth rate limit gate ────────────────────────────────────────
    # Block IPs that have exceeded failed auth attempts BEFORE hitting any handler.
    # Applied to all /workspaces/:wsId/* routes (not /workspaces POST = creation).
    if path.startswith("/workspaces/"):
        _parts = path.split("/")
        if len(_parts) >= 3:
            _ws_id   = _parts[2]
            _ip      = _get_client_ip()
            _fail_key = f"ws_auth_fail:{_ip}:{_ws_id}"
            _fails   = _rl_count(_fail_key, _WS_AUTH_FAIL_WINDOW)
            if _fails >= _WS_AUTH_FAIL_LIMIT:
                with _rl_lock:
                    _entries = [t for t in _rl_store[_fail_key]
                                if t > _time.monotonic() - _WS_AUTH_FAIL_WINDOW]
                _retry = int((_entries[0] if _entries else _time.monotonic())
                             + _WS_AUTH_FAIL_WINDOW - _time.monotonic()) + 1
                logger.warning(
                    "workspace auth rate limited ip=%s workspace=%s fails=%d",
                    _ip, _ws_id, _fails
                )
                return _rate_limited_resp(
                    max(_retry, 1),
                    "Too many failed access attempts. Please try again later.",
                )

    # ── Auth routes (feature-flagged; /auth/config is always public) ──────────
    if path == "/auth/config" and method == "GET":
        from auth_handler import handle_auth_config
        return handle_auth_config()
    if path == "/auth/signup" and method == "POST":
        from auth_handler import handle_auth_signup
        return handle_auth_signup(body, _get_client_ip())
    if path == "/auth/verify-email" and method == "POST":
        from auth_handler import handle_auth_verify_email
        return handle_auth_verify_email(body, _get_client_ip())
    if path == "/auth/google/start" and method == "GET":
        from auth_handler import handle_auth_google_start
        return handle_auth_google_start(_get_client_ip())
    if path == "/auth/google/callback" and method == "GET":
        from auth_handler import handle_auth_google_callback
        return handle_auth_google_callback(params)
    if path == "/auth/me" and method == "GET":
        from auth_handler import handle_auth_me
        return handle_auth_me(headers)
    if path == "/auth/logout" and method == "POST":
        from auth_handler import handle_auth_logout
        return handle_auth_logout(headers)

    # SAML/SSO routes — all return 403 when AUTH_SAML_ENABLED=false
    if path == "/auth/saml/metadata" and method == "GET":
        from saml_handler import handle_saml_metadata
        return handle_saml_metadata()
    if path == "/auth/saml/login" and method == "GET":
        from saml_handler import handle_saml_login
        return handle_saml_login(params, _get_client_ip())
    if path == "/auth/saml/acs" and method == "POST":
        from saml_handler import handle_saml_acs
        return handle_saml_acs(body_raw, _get_client_ip())
    if path == "/auth/saml/logout" and method == "POST":
        from saml_handler import handle_saml_logout
        return handle_saml_logout(headers)

    if path in ("/", "") and method == "GET":
        return resp(200, {"status": "ok"})
    if path == "/health" and method == "GET":
        return handle_health()
    if path == "/eol/general" and method == "GET":
        return handle_general_eol(params)
    if path == "/eol/general/summary" and method == "GET":
        return handle_general_eol_summary(params)
    if path == "/eol/general/refresh" and method == "POST":
        if not _verify_admin(headers):
            return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
        return handle_general_eol_refresh()
    # Legacy unscoped routes — deprecated; workspace users must use /workspaces/:wsId/* equivalents
    if path == "/eol/inventory" and method == "GET":
        return _error_resp(410, "ROUTE_DEPRECATED",
                           "This legacy route is deprecated. Use GET /workspaces/:wsId/inventory")
    if path == "/eol/summary" and method == "GET":
        return _error_resp(410, "ROUTE_DEPRECATED",
                           "This legacy route is deprecated. Use GET /workspaces/:wsId/summary")
    if path.startswith("/eol/resource/") and method == "GET":
        return _error_resp(410, "ROUTE_DEPRECATED",
                           "This legacy route is deprecated. Use GET /workspaces/:wsId/resource/:id")
    if path == "/eol/alerts" and method == "GET":
        return _error_resp(410, "ROUTE_DEPRECATED",
                           "This legacy route is deprecated. Use GET /workspaces/:wsId/alerts")
    if path == "/eol/config" and method == "GET":
        if not _verify_admin(headers):
            return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
        return handle_config_get()
    if path == "/eol/config" and method == "PUT":
        if not _verify_admin(headers):
            return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
        return handle_config_put(body)
    if path == "/eol/scan" and method == "POST":
        if not _verify_admin(headers):
            return _error_resp(401, "ADMIN_TOKEN_INVALID", "Admin token required")
        return handle_scan_trigger()

    # ── Workspace routes ──────────────────────────────────────────────────────
    if path == "/workspaces" and method == "POST":
        return handle_workspace_create(body, headers, _get_client_ip())

    # /workspaces/:wsId/validate
    m = re.fullmatch(r"/workspaces/([^/]+)/validate", path)
    if m and method == "GET":
        return handle_workspace_validate(m.group(1), headers)

    # /workspaces/:wsId/summary
    m = re.fullmatch(r"/workspaces/([^/]+)/summary", path)
    if m and method == "GET":
        return handle_ws_summary(m.group(1), headers, params)

    # /workspaces/:wsId/config
    m = re.fullmatch(r"/workspaces/([^/]+)/config", path)
    if m:
        if method == "GET":   return handle_ws_config_get(m.group(1), headers)
        if method == "PATCH": return handle_ws_config_patch(m.group(1), body, headers)

    # /workspaces/:wsId/inventory
    m = re.fullmatch(r"/workspaces/([^/]+)/inventory", path)
    if m and method == "GET":
        return handle_ws_inventory(m.group(1), headers, params)

    # /workspaces/:wsId/reports/*
    m = re.fullmatch(r"/workspaces/([^/]+)/reports/summary", path)
    if m and method == "GET":
        return handle_ws_reports_summary(m.group(1), headers, params)
    m = re.fullmatch(r"/workspaces/([^/]+)/reports/export\.csv", path)
    if m and method == "GET":
        return handle_ws_report_csv(m.group(1), headers, params)
    m = re.fullmatch(r"/workspaces/([^/]+)/reports/snapshots", path)
    if m:
        if method == "GET":  return handle_ws_report_snapshots_list(m.group(1), headers)
        if method == "POST": return handle_ws_report_snapshot_create(m.group(1), headers)
    m = re.fullmatch(r"/workspaces/([^/]+)/reports/snapshots/([^/]+)", path)
    if m and method == "GET":
        return handle_ws_report_snapshot_get(m.group(1), m.group(2), headers)

    # /workspaces/:wsId/resource/:resourceId
    m = re.fullmatch(r"/workspaces/([^/]+)/resource/(.+)", path)
    if m and method == "GET":
        return handle_ws_resource(m.group(1), m.group(2), headers)

    # /workspaces/:wsId/token/rotate
    m = re.fullmatch(r"/workspaces/([^/]+)/token/rotate", path)
    if m and method == "POST":
        return handle_ws_token_rotate(m.group(1), headers)

    # /workspaces/:wsId/access/summary
    m = re.fullmatch(r"/workspaces/([^/]+)/access/summary", path)
    if m and method == "GET":
        return handle_ws_access_summary(m.group(1), headers)

    # /workspaces/:wsId/audit-logs
    m = re.fullmatch(r"/workspaces/([^/]+)/audit-logs", path)
    if m and method == "GET":
        return handle_ws_audit_logs(m.group(1), headers, params)

    # /workspaces/:wsId/org-scan/status
    m = re.fullmatch(r"/workspaces/([^/]+)/org-scan/status", path)
    if m and method == "GET":
        return handle_ws_org_status(m.group(1), headers)

    # /workspaces/:wsId/org-summary
    m = re.fullmatch(r"/workspaces/([^/]+)/org-summary", path)
    if m and method == "GET":
        return handle_ws_org_summary(m.group(1), headers)

    # /workspaces/:wsId/org-scans/:orgScanId/cancel
    m = re.fullmatch(r"/workspaces/([^/]+)/org-scans/([^/]+)/cancel", path)
    if m and method == "POST":
        return handle_ws_org_scan_cancel(m.group(1), m.group(2), headers)

    # /workspaces/:wsId/org-scans/:orgScanId
    m = re.fullmatch(r"/workspaces/([^/]+)/org-scans/([^/]+)", path)
    if m and method == "GET":
        return handle_ws_org_scan_get(m.group(1), m.group(2), headers)

    # /workspaces/:wsId/org-connections/validate-role
    m = re.fullmatch(r"/workspaces/([^/]+)/org-connections/validate-role", path)
    if m and method == "POST":
        return handle_ws_org_validate_role(m.group(1), body, headers)

    # /workspaces/:wsId/org-connections
    m = re.fullmatch(r"/workspaces/([^/]+)/org-connections", path)
    if m:
        if method == "GET":  return handle_ws_org_connections_list(m.group(1), headers)
        if method == "POST": return handle_ws_org_connection_create(m.group(1), body, headers)

    # /workspaces/:wsId/org-connections/:orgConnId/*
    m = re.fullmatch(r"/workspaces/([^/]+)/org-connections/([^/]+)/discover", path)
    if m and method == "POST":
        return handle_ws_org_discover(m.group(1), m.group(2), headers)
    m = re.fullmatch(r"/workspaces/([^/]+)/org-connections/([^/]+)/accounts", path)
    if m and method == "GET":
        return handle_ws_org_accounts_list(m.group(1), m.group(2), headers)
    m = re.fullmatch(r"/workspaces/([^/]+)/org-connections/([^/]+)/scans", path)
    if m:
        if method == "GET":  return handle_ws_org_connection_scans(m.group(1), m.group(2), headers)
        if method == "POST": return handle_ws_org_scan_create(m.group(1), m.group(2), headers)
    m = re.fullmatch(r"/workspaces/([^/]+)/org-connections/([^/]+)", path)
    if m:
        if method == "GET":    return handle_ws_org_connection_get(m.group(1), m.group(2), headers)
        if method == "PATCH":  return handle_ws_org_connection_patch(m.group(1), m.group(2), body, headers)
        if method == "DELETE": return handle_ws_org_connection_delete(m.group(1), m.group(2), headers)

    # Future feature placeholders — disabled until explicitly implemented/enabled.
    m = re.fullmatch(r"/workspaces/([^/]+)/(remediation|sso|billing|cicd-scan)(?:/.*)?", path)
    if m:
        feature_name = {
            "remediation": "Remediation Tracking",
            "sso": "SSO/SAML",
            "billing": "SaaS/Billing",
            "cicd-scan": "CI/CD Scan-on-push",
        }.get(m.group(2), "Feature")
        return _named_feature_disabled(feature_name)

    # /workspaces/:wsId/members/accept-invite  (public — no auth)
    m = re.fullmatch(r"/workspaces/([^/]+)/members/accept-invite", path)
    if m and method == "POST":
        return handle_ws_member_accept_invite(m.group(1), body)

    # /workspaces/:wsId/members/login-link  (public — no auth)
    m = re.fullmatch(r"/workspaces/([^/]+)/members/login-link", path)
    if m and method == "POST":
        return handle_ws_member_login_link(m.group(1), body, headers)

    # /workspaces/:wsId/members/complete-login  (public — no auth)
    m = re.fullmatch(r"/workspaces/([^/]+)/members/complete-login", path)
    if m and method == "POST":
        return handle_ws_member_complete_login(m.group(1), body)

    # /workspaces/:wsId/members/:memberId
    m = re.fullmatch(r"/workspaces/([^/]+)/members/([^/]+)", path)
    if m:
        ws_id, mbr_id = m.group(1), m.group(2)
        if method == "PATCH":  return handle_ws_member_update(ws_id, mbr_id, body, headers)
        if method == "DELETE": return handle_ws_member_remove(ws_id, mbr_id, headers)

    # /workspaces/:wsId/members
    m = re.fullmatch(r"/workspaces/([^/]+)/members", path)
    if m:
        if method == "GET":  return handle_ws_members_list(m.group(1), headers)
        if method == "POST": return handle_ws_member_invite(m.group(1), body, headers)

    # /workspaces/:wsId/api-tokens/:tokenId
    m = re.fullmatch(r"/workspaces/([^/]+)/api-tokens/([^/]+)", path)
    if m:
        ws_id, tok_id = m.group(1), m.group(2)
        if method == "DELETE": return handle_ws_api_token_revoke(ws_id, tok_id, headers)
        if method == "PATCH":  return handle_ws_api_token_update(ws_id, tok_id, body, headers)

    # /workspaces/:wsId/api-tokens
    m = re.fullmatch(r"/workspaces/([^/]+)/api-tokens", path)
    if m:
        if method == "GET":  return handle_ws_api_tokens_list(m.group(1), headers)
        if method == "POST": return handle_ws_api_token_create(m.group(1), body, headers)

    # /workspaces/:wsId/notification-settings
    m = re.fullmatch(r"/workspaces/([^/]+)/notification-settings", path)
    if m:
        if method == "GET":   return handle_ws_notification_settings_get(m.group(1), headers)
        if method == "PATCH": return handle_ws_notification_settings_patch(m.group(1), body, headers)

    # /workspaces/:wsId/notifications/test
    m = re.fullmatch(r"/workspaces/([^/]+)/notifications/test", path)
    if m and method == "POST":
        return handle_ws_notifications_test(m.group(1), body, headers)

    # /workspaces/:wsId/notifications/logs
    m = re.fullmatch(r"/workspaces/([^/]+)/notifications/logs", path)
    if m and method == "GET":
        return handle_ws_notifications_logs(m.group(1), headers, params)

    # /workspaces/:wsId/alerts
    m = re.fullmatch(r"/workspaces/([^/]+)/alerts", path)
    if m and method == "GET":
        return handle_ws_alerts_list(m.group(1), headers, params)

    # /workspaces/:wsId/alerts/:alertId/:action
    m = re.fullmatch(r"/workspaces/([^/]+)/alerts/([^/]+)/(acknowledge|snooze|resolve|reopen)", path)
    if m and method == "POST":
        return handle_ws_alert_action(m.group(1), m.group(2), m.group(3), body, headers)

    # /workspaces/:wsId/scans/:scanId
    m = re.fullmatch(r"/workspaces/([^/]+)/scans/([^/]+)", path)
    if m and method == "GET":
        return handle_ws_scan_get(m.group(1), m.group(2), headers)

    # /workspaces/:wsId/accounts/:acctId/scans  (new scan run model)
    m = re.fullmatch(r"/workspaces/([^/]+)/accounts/([^/]+)/scans", path)
    if m and method == "POST":
        return handle_ws_scan_create(m.group(1), m.group(2), headers)
    if m and method == "GET":
        return handle_ws_account_scan_list(m.group(1), m.group(2), headers, params)

    # /workspaces/:wsId/accounts/:acctId/latest-scan
    m = re.fullmatch(r"/workspaces/([^/]+)/accounts/([^/]+)/latest-scan", path)
    if m and method == "GET":
        return handle_ws_account_latest_scan(m.group(1), m.group(2), headers)

    # /workspaces/:wsId/accounts/:acctId/scan  (deprecated — redirect to /scans)
    m = re.fullmatch(r"/workspaces/([^/]+)/accounts/([^/]+)/scan", path)
    if m and method == "POST":
        return _error_resp(410, "ROUTE_DEPRECATED",
                           "POST /scan is deprecated; use POST /scans instead")

    # /workspaces/:wsId/accounts/validate-role
    m = re.fullmatch(r"/workspaces/([^/]+)/accounts/validate-role", path)
    if m and method == "POST":
        return handle_ws_account_validate_role(m.group(1), body, headers)

    # /workspaces/:wsId/accounts[/:acctId]
    m = re.fullmatch(r"/workspaces/([^/]+)/accounts(?:/([^/]+))?", path)
    if m:
        ws_id, acct_id = m.group(1), m.group(2)
        if method == "GET"    and not acct_id: return handle_ws_accounts_list(ws_id, headers)
        if method == "POST"   and not acct_id: return handle_ws_account_save(ws_id, body, headers)
        if method == "PUT"    and acct_id:     return handle_ws_account_update(ws_id, acct_id, body, headers)
        if method == "DELETE" and acct_id:     return handle_ws_account_delete(ws_id, acct_id, headers)

    # ── Legacy unscoped account routes — deprecated; use /workspaces/:wsId/accounts
    if path == "/accounts" or path.startswith("/accounts/"):
        return _error_resp(410, "ROUTE_DEPRECATED",
                           "These legacy routes are deprecated. Use /workspaces/:wsId/accounts")

    # ── Admin routes (X-Admin-Token required, never accepts workspace token) ────
    if path == "/admin/validate" and method == "GET":
        return handle_admin_validate(headers)
    if path == "/admin/workspaces" and method == "GET":
        return handle_admin_workspaces_list(headers)
    m = re.fullmatch(r"/admin/workspaces/([^/]+)/rotate-token", path)
    if m and method == "POST":
        return handle_admin_workspace_rotate(m.group(1), headers)
    m = re.fullmatch(r"/admin/workspaces/([^/]+)", path)
    if m and method == "DELETE":
        return handle_admin_workspace_delete(m.group(1), headers, params)
    if path == "/admin/scans" and method == "GET":
        return handle_admin_scans_list(headers, params)
    if path == "/admin/system" and method == "GET":
        return handle_admin_system(headers)
    if path == "/admin/general-eol/refresh" and method == "POST":
        return handle_admin_eol_refresh(headers)

    # Admin weekly digest trigger
    if path == "/admin/notifications/weekly-digest/run" and method == "POST":
        return handle_admin_weekly_digest(headers)

    if path == "/admin/reports/monthly/run" and method == "POST":
        return handle_admin_monthly_reports(headers)

    # Admin upgrade guides CRUD
    if path == "/admin/upgrade-guides" and method == "GET":
        return handle_admin_guides_list(headers)
    if path == "/admin/upgrade-guides" and method == "POST":
        return handle_admin_guide_create(body, headers)
    m = re.fullmatch(r"/admin/upgrade-guides/([^/]+)", path)
    if m:
        guide_id = m.group(1)
        if method == "GET":    return handle_admin_guide_get(guide_id, headers)
        if method == "PATCH":  return handle_admin_guide_update(guide_id, body, headers)
        if method == "DELETE": return handle_admin_guide_delete(guide_id, headers)

    # Admin MCP lifecycle validation
    if path == "/admin/eol/validate-mcp" and method == "POST":
        return handle_admin_eol_validate_mcp(body, headers)

    # Admin EOL overrides CRUD
    if path == "/admin/eol-overrides" and method == "GET":
        return handle_admin_eol_override_list(headers)
    if path == "/admin/eol-overrides" and method == "POST":
        return handle_admin_eol_override_create(body, headers)
    m = re.fullmatch(r"/admin/eol-overrides/([^/]+)/([^/]+)", path)
    if m:
        product, version = m.group(1), m.group(2)
        if method == "DELETE": return handle_admin_eol_override_delete(product, version, headers)

    return resp(404, {"error": f"No route for {method} {path}"})
