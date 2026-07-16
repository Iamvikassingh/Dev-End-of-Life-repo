"""
saml_handler.py — Feature-flagged SSO/SAML 2.0 endpoints for AWS EOL Monitor.

All functionality is disabled unless AUTH_SAML_ENABLED=true.
Existing workspace-token and email/Google session auth are unchanged.

Endpoints:
  GET  /auth/saml/metadata  — SP metadata XML (public when SAML enabled)
  GET  /auth/saml/login     — initiate SAML login (redirect to IdP)
  POST /auth/saml/acs       — Assertion Consumer Service (IdP posts here)
  POST /auth/saml/logout    — clear local session (+ SLO redirect if configured)

Security invariants:
  * Raw SAMLResponse is NEVER logged.
  * NameID is stored only as SHA-256 hash.
  * No assertion XML, certificates, or private keys are logged.
  * strict=True always — signature/audience/recipient/expiry all validated.
  * ACS with invalid or unsigned assertion always returns 400.
  * Rollback: set AUTH_SAML_ENABLED=false — all routes return 403.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading as _threading
import time as _time
from collections import defaultdict as _defaultdict
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# ── Feature flags (read at import time, like auth_handler) ───────────────────

def _flag(key: str, default: str = "false") -> bool:
    return os.environ.get(key, default).lower() in ("1", "true", "yes")


AUTH_SAML_ENABLED           = _flag("AUTH_SAML_ENABLED")
AUTH_SAML_AUTO_PROVISION    = _flag("AUTH_SAML_AUTO_PROVISION_USERS")
AUTH_SAML_REQUIRE_VERIFIED  = _flag("AUTH_SAML_REQUIRE_VERIFIED_EMAIL", "true")

APP_ENV          = os.environ.get("APP_ENV", "development").lower()
APP_PUBLIC_URL   = os.environ.get("APP_PUBLIC_URL", "").rstrip("/")
ALLOWED_ORIGIN   = os.environ.get("ALLOWED_ORIGIN", "*")
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "12"))

# SP URLs — required when SAML is enabled
SAML_ENTITY_ID = os.environ.get("SAML_ENTITY_ID", "")
SAML_ACS_URL   = os.environ.get("SAML_ACS_URL",   "")
SAML_SLO_URL   = os.environ.get("SAML_SLO_URL",   "")

# IdP config — required when SAML is enabled
SAML_IDP_ENTITY_ID = os.environ.get("SAML_IDP_ENTITY_ID", "")
SAML_IDP_SSO_URL   = os.environ.get("SAML_IDP_SSO_URL",   "")
SAML_IDP_SLO_URL   = os.environ.get("SAML_IDP_SLO_URL",   "")
SAML_IDP_X509_CERT = os.environ.get("SAML_IDP_X509_CERT", "")

# Role strings must match api_handler._ROLE_ORDER: ADMIN | EDITOR | VIEWER
_ROLE_MAP = {"owner": "ADMIN", "admin": "ADMIN", "editor": "EDITOR", "viewer": "VIEWER"}
_raw_default = os.environ.get("SAML_DEFAULT_WORKSPACE_ROLE", "viewer").lower()
SAML_DEFAULT_ROLE = _ROLE_MAP.get(_raw_default, "VIEWER")
_raw_domains = os.environ.get("SAML_ALLOWED_DOMAINS", "").strip()
SAML_ALLOWED_DOMAINS: set[str] = (
    {d.strip().lower() for d in _raw_domains.split(",") if d.strip()}
    if _raw_domains else set()
)

# Group-to-role mapping — comma-separated group names per role tier
# Priority: owner > editor > viewer > SAML_DEFAULT_ROLE
def _parse_groups_env(key: str) -> set:
    raw = os.environ.get(key, "").strip()
    return {g.strip() for g in raw.split(",") if g.strip()} if raw else set()

SAML_GROUPS_OWNER:  set = _parse_groups_env("SAML_GROUP_OWNER")
SAML_GROUPS_EDITOR: set = _parse_groups_env("SAML_GROUP_EDITOR")
SAML_GROUPS_VIEWER: set = _parse_groups_env("SAML_GROUP_VIEWER")

# Attribute mapping — which IdP attributes carry user info
SAML_ATTR_EMAIL      = os.environ.get("SAML_ATTRIBUTE_EMAIL",      "email")
SAML_ATTR_NAME       = os.environ.get("SAML_ATTRIBUTE_NAME",       "name")
SAML_ATTR_FIRST_NAME = os.environ.get("SAML_ATTRIBUTE_FIRST_NAME", "firstName")
SAML_ATTR_LAST_NAME  = os.environ.get("SAML_ATTRIBUTE_LAST_NAME",  "lastName")
SAML_ATTR_GROUPS     = os.environ.get("SAML_ATTRIBUTE_GROUPS",     "groups")

# Warn at import when SAML is enabled but misconfigured
if AUTH_SAML_ENABLED:
    _missing = [k for k, v in [
        ("SAML_ENTITY_ID",    SAML_ENTITY_ID),
        ("SAML_ACS_URL",      SAML_ACS_URL),
        ("SAML_IDP_ENTITY_ID",SAML_IDP_ENTITY_ID),
        ("SAML_IDP_SSO_URL",  SAML_IDP_SSO_URL),
        ("SAML_IDP_X509_CERT",SAML_IDP_X509_CERT),
    ] if not v]
    if _missing:
        logger.warning("AUTH_SAML_ENABLED=true but missing env vars: %s", ", ".join(_missing))

# python3-saml import (graceful fallback so SAML_ENABLED=false never breaks startup)
try:
    from onelogin.saml2.auth     import OneLogin_Saml2_Auth
    from onelogin.saml2.settings import OneLogin_Saml2_Settings
    _SAML_LIB_OK = True
except ImportError:
    _SAML_LIB_OK = False
    if AUTH_SAML_ENABLED:
        logger.error("python3-saml not installed. Run: pip install python3-saml")

# ── Per-module in-memory rate limiter ─────────────────────────────────────────

_rl_lock  = _threading.Lock()
_rl_store: dict = _defaultdict(list)

_SAML_LOGIN_LIMIT  = int(os.environ.get("SAML_LOGIN_RATE_LIMIT",  "20"))
_SAML_LOGIN_WINDOW = int(os.environ.get("SAML_LOGIN_RATE_WINDOW", "3600"))
_SAML_ACS_LIMIT    = int(os.environ.get("SAML_ACS_RATE_LIMIT",    "20"))
_SAML_ACS_WINDOW   = int(os.environ.get("SAML_ACS_RATE_WINDOW",   "3600"))


def _rl_check(key: str, limit: int, window: int) -> tuple:
    now    = _time.monotonic()
    cutoff = now - window
    with _rl_lock:
        hits = [t for t in _rl_store[key] if t > cutoff]
        _rl_store[key] = hits
        if len(hits) >= limit:
            return False, max(int(hits[0] + window - now) + 1, 1)
        _rl_store[key].append(now)
        return True, 0

# ── RelayState: HMAC-signed, no server-side storage needed ───────────────────

# Read from env so PM2 restarts don't invalidate in-flight SAML logins.
# Falls back to a random key only if env var is missing (development mode).
_RELAY_KEY: str = os.environ.get("SAML_RELAY_SIGNING_KEY") or secrets.token_hex(32)
if AUTH_SAML_ENABLED and not os.environ.get("SAML_RELAY_SIGNING_KEY"):
    logger.warning("SAML_RELAY_SIGNING_KEY not set — relay key is ephemeral and will "
                   "invalidate in-flight logins on process restart. Set this env var.")


def _make_relay_state(workspace_id: str, next_url: str) -> str:
    payload = json.dumps({
        "w": workspace_id or "",
        "n": next_url or "/overview",
        "t": int(_time.time()),
    }, separators=(",", ":"))
    sig = hmac.new(_RELAY_KEY.encode(), payload.encode(), "sha256").hexdigest()
    raw = f"{payload}|||{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _parse_relay_state(relay_state: str) -> dict:
    try:
        decoded = base64.urlsafe_b64decode(relay_state.encode() + b"==").decode()
        payload_str, _, sig = decoded.rpartition("|||")
        expected = hmac.new(_RELAY_KEY.encode(), payload_str.encode(), "sha256").hexdigest()
        if not hmac.compare_digest(sig, expected):
            return {}
        payload = json.loads(payload_str)
        if _time.time() - payload.get("t", 0) > 600:   # 10-min TTL
            return {}
        return payload
    except Exception:
        return {}

# ── Response helpers ──────────────────────────────────────────────────────────

def _base_headers() -> dict:
    return {
        "Content-Type":                     "application/json",
        "Access-Control-Allow-Origin":      ALLOWED_ORIGIN,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Headers":
            "Authorization,Content-Type,X-Workspace-Token,X-Admin-Token,X-API-Token",
        "Access-Control-Allow-Methods": "GET,PUT,POST,DELETE,PATCH,OPTIONS",
    }


def _saml_err(status: int, code: str, message: str) -> dict:
    return {
        "statusCode": status,
        "headers": _base_headers(),
        "body": json.dumps({"ok": False, "error": code, "message": message}),
    }


def _saml_disabled() -> dict:
    return _saml_err(403, "AUTH_FEATURE_DISABLED",
                     "SSO/SAML is not enabled in this deployment.")


def _saml_rate_limited(retry_after: int) -> dict:
    r = _saml_err(429, "RATE_LIMITED", "Too many requests. Please try again later.")
    r["headers"]["Retry-After"] = str(retry_after)
    return r


def _redirect(location: str, cookie: str | None = None) -> dict:
    hdrs = {
        "Location":      location,
        "Cache-Control": "no-store, no-cache",
        "Pragma":        "no-cache",
        **_base_headers(),
    }
    if cookie:
        hdrs["Set-Cookie"] = cookie
    return {"statusCode": 302, "headers": hdrs, "body": ""}


def _error_redirect(code: str) -> dict:
    url = f"{APP_PUBLIC_URL}/auth/saml/error?error={code}" if APP_PUBLIC_URL else "/auth/saml/error"
    return _redirect(url)

# ── Session cookie helpers (mirrors auth_handler, no cross-import) ─────────────

_SESSION_COOKIE = "eolm_session"


def _make_session_cookie(token: str, max_age: int) -> str:
    secure = "; Secure" if APP_ENV == "production" else ""
    return f"{_SESSION_COOKIE}={token}; HttpOnly{secure}; SameSite=Lax; Path=/; Max-Age={max_age}"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

# ── python3-saml settings builder ────────────────────────────────────────────

def _saml_settings() -> dict:
    sp_slo: dict = {}
    if SAML_SLO_URL:
        sp_slo = {
            "url":     SAML_SLO_URL,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }

    idp_slo: dict = {}
    if SAML_IDP_SLO_URL:
        idp_slo = {
            "url":     SAML_IDP_SLO_URL,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }

    # Strip PEM headers if present — python3-saml expects raw base64
    cert = SAML_IDP_X509_CERT
    if cert:
        cert = (cert
                .replace("-----BEGIN CERTIFICATE-----", "")
                .replace("-----END CERTIFICATE-----", "")
                .replace("\n", "").replace("\r", "").strip())

    settings: dict = {
        "strict": True,
        "debug":  APP_ENV != "production",
        "sp": {
            "entityId": SAML_ENTITY_ID,
            "assertionConsumerService": {
                "url":     SAML_ACS_URL,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            "x509cert":     "",
            "privateKey":   "",
        },
        "idp": {
            "entityId":             SAML_IDP_ENTITY_ID,
            "singleSignOnService":  {
                "url":     SAML_IDP_SSO_URL,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": cert,
        },
    }
    if sp_slo:
        settings["sp"]["singleLogoutService"] = sp_slo
    if idp_slo:
        settings["idp"]["singleLogoutService"] = idp_slo

    return settings


def _make_saml_request(script_name: str,
                       get_data: dict | None = None,
                       post_data: dict | None = None) -> dict:
    """Build the request dict that python3-saml expects."""
    parsed    = urlparse(SAML_ACS_URL or "https://localhost/auth/saml/acs")
    http_host = parsed.hostname or "localhost"
    is_https  = parsed.scheme == "https"
    port      = parsed.port
    if not port:
        port = 443 if is_https else 80
    return {
        "https":        "on" if is_https else "off",
        "http_host":    http_host,
        "server_port":  str(port),
        "script_name":  script_name,
        "get_data":     get_data  or {},
        "post_data":    post_data or {},
        "request_uri":  script_name,
        "query_string": "",
    }

# ── Attribute extraction helpers ─────────────────────────────────────────────

def _attr_first(attributes: dict, name: str) -> str:
    vals = attributes.get(name, [])
    if isinstance(vals, list) and vals:
        return str(vals[0]).strip()
    if isinstance(vals, str):
        return vals.strip()
    return ""


def _extract_email(attributes: dict, name_id: str) -> str:
    email = _attr_first(attributes, SAML_ATTR_EMAIL)
    if not email:
        email = name_id or ""
    return email.strip().lower()


def _extract_name(attributes: dict) -> str:
    name = _attr_first(attributes, SAML_ATTR_NAME)
    if not name:
        first = _attr_first(attributes, SAML_ATTR_FIRST_NAME)
        last  = _attr_first(attributes, SAML_ATTR_LAST_NAME)
        name  = f"{first} {last}".strip()
    return name


def _safe_attributes(attributes: dict) -> dict:
    """Return attributes dict with only string/list-of-strings values (no sensitive keys)."""
    safe = {}
    skip = {"password", "secret", "token", "key", "credential"}
    for k, v in attributes.items():
        if any(s in str(k).lower() for s in skip):
            continue
        if isinstance(v, list):
            safe[k] = [str(x) for x in v][:10]
        else:
            safe[k] = str(v)
    return safe


def _extract_groups(attributes: dict) -> list:
    """Return list of group strings from the configured groups attribute."""
    vals = attributes.get(SAML_ATTR_GROUPS, [])
    if isinstance(vals, list):
        return [str(g).strip() for g in vals if g]
    if isinstance(vals, str) and vals:
        return [vals.strip()]
    return []


def _resolve_role_from_groups(groups: list) -> str:
    """Map IdP group membership to EOL Monitor role string (ADMIN/EDITOR/VIEWER)."""
    if groups:
        group_set = set(groups)
        if SAML_GROUPS_OWNER  and group_set & SAML_GROUPS_OWNER:
            return "ADMIN"
        if SAML_GROUPS_EDITOR and group_set & SAML_GROUPS_EDITOR:
            return "EDITOR"
        if SAML_GROUPS_VIEWER and group_set & SAML_GROUPS_VIEWER:
            return "VIEWER"
    return SAML_DEFAULT_ROLE

# ── DB helpers (thin wrappers; auth tables required) ─────────────────────────

def _db_one(sql: str, params=None):
    from auth_handler import _one
    return _one(sql, params)


def _db_run(sql: str, params=None) -> int:
    from auth_handler import _run
    return _run(sql, params)


def _create_session(user_id: str) -> str:
    from auth_handler import _create_session as _cs
    return _cs(user_id)


def _upsert_workspace_member(workspace_id: str, user_id: str, role: str) -> None:
    """Add user to workspace if not already a member. Never downgrades an existing role."""
    if not workspace_id or not user_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    _ROLE_RANK = {"ADMIN": 3, "EDITOR": 2, "VIEWER": 1}
    existing = _db_one(
        "SELECT role FROM auth_user_workspace_memberships"
        " WHERE user_id = %s AND workspace_id = %s",
        (user_id, workspace_id),
    )
    if existing:
        current_rank = _ROLE_RANK.get(existing["role"], 0)
        new_rank     = _ROLE_RANK.get(role, 0)
        if new_rank > current_rank:
            _db_run(
                "UPDATE auth_user_workspace_memberships SET role = %s"
                " WHERE user_id = %s AND workspace_id = %s",
                (role, user_id, workspace_id),
            )
            logger.info("SAML workspace role upgraded user=…%s ws=%s role=%s",
                        user_id[-6:], workspace_id, role)
    else:
        _db_run(
            "INSERT INTO auth_user_workspace_memberships"
            " (user_id, workspace_id, role, created_at) VALUES (%s, %s, %s, %s)",
            (user_id, workspace_id, role, now),
        )
        logger.info("SAML workspace membership added user=…%s ws=%s role=%s",
                    user_id[-6:], workspace_id, role)

# ── User provisioning ─────────────────────────────────────────────────────────

def _provision_user(email: str, name: str, name_id: str, attributes: dict,
                    workspace_id: str = "", resolved_role: str = ""):
    """
    Look up or create auth_user for the SAML-authenticated email.
    If workspace_id is given, ensures user has membership at resolved_role (never downgrades).
    Returns (plain_session_token, user_id) on success, or a dict with "error" key.
    """
    now = datetime.now(timezone.utc).isoformat()
    role = resolved_role or SAML_DEFAULT_ROLE

    # 1. Find by email
    user = _db_one("SELECT id, status FROM auth_users WHERE email = %s", (email,))

    if user:
        if user.get("status") != "active":
            return {"error": "SAML_ACCOUNT_DISABLED"}
        user_id = user["id"]
    elif AUTH_SAML_AUTO_PROVISION:
        user_id = f"user_{secrets.token_hex(8)}"
        _db_run(
            "INSERT INTO auth_users"
            " (id, email, name, email_verified, status, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, email, name or email, True, "active", now, now),
        )
        logger.info("SAML auto-provisioned user email=****@%s", email.split("@")[-1])
    else:
        return {"error": "SSO_USER_NOT_PROVISIONED"}

    # 2. Upsert saml identity (store only hash of NameID)
    name_id_hash = _sha(name_id or email)
    safe_attrs   = _safe_attributes(attributes)
    saml_id      = f"saml_{secrets.token_hex(8)}"
    try:
        _db_run(
            "INSERT INTO auth_saml_identities"
            " (id, user_id, idp_entity_id, name_id_hash, email, attributes_json, created_at, last_login_at)"
            " VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)"
            " ON CONFLICT (idp_entity_id, name_id_hash)"
            "   DO UPDATE SET last_login_at = EXCLUDED.last_login_at,"
            "                 email         = EXCLUDED.email",
            (saml_id, user_id, SAML_IDP_ENTITY_ID, name_id_hash, email,
             json.dumps(safe_attrs), now, now),
        )
    except Exception as exc:
        logger.warning("SAML identity upsert failed (non-fatal): %s", type(exc).__name__)

    # 3. Assign workspace membership at resolved role (never downgrades)
    if workspace_id:
        try:
            _upsert_workspace_member(workspace_id, user_id, role)
        except Exception as exc:
            logger.warning("SAML workspace membership failed (non-fatal): %s", type(exc).__name__)

    # 4. Create session
    token = _create_session(user_id)
    return token, user_id

# ── Handlers ──────────────────────────────────────────────────────────────────

def handle_saml_metadata() -> dict:
    if not AUTH_SAML_ENABLED:
        return _saml_disabled()
    if not _SAML_LIB_OK:
        return _saml_err(503, "SAML_LIB_MISSING", "SAML library not installed on server.")
    if not SAML_IDP_X509_CERT:
        return _saml_err(503, "SAML_NOT_CONFIGURED", "SAML IdP certificate not configured.")

    try:
        request  = _make_saml_request("/auth/saml/metadata")
        saml_auth = OneLogin_Saml2_Auth(request, old_settings=_saml_settings())
        settings = saml_auth.get_settings()
        metadata = settings.get_sp_metadata()
        errors   = settings.validate_metadata(metadata)
        if errors:
            logger.error("SAML SP metadata invalid: %s", errors)
            return _saml_err(500, "SAML_METADATA_INVALID", "SP metadata validation failed.")
        return {
            "statusCode": 200,
            "headers": {
                **_base_headers(),
                "Content-Type": "application/xml; charset=utf-8",
                "Cache-Control": "public, max-age=3600",
            },
            "body": metadata,
        }
    except Exception as exc:
        logger.error("SAML metadata generation failed: %s", type(exc).__name__)
        return _saml_err(500, "SAML_METADATA_ERROR", "Failed to generate SP metadata.")


def handle_saml_login(params: dict, client_ip: str) -> dict:
    if not AUTH_SAML_ENABLED:
        return _saml_disabled()
    if not _SAML_LIB_OK:
        return _saml_err(503, "SAML_LIB_MISSING", "SAML library not installed on server.")
    if not SAML_IDP_SSO_URL or not SAML_IDP_X509_CERT:
        return _saml_err(503, "SAML_NOT_CONFIGURED", "SAML IdP not fully configured.")

    ok, retry = _rl_check(f"saml_login:{client_ip}", _SAML_LOGIN_LIMIT, _SAML_LOGIN_WINDOW)
    if not ok:
        return _saml_rate_limited(retry)

    workspace_id = (params.get("workspace_id") or "").strip()
    next_url     = (params.get("next") or "/overview").strip()

    # Sanitize next_url (relative paths only)
    if not next_url.startswith("/"):
        next_url = "/overview"

    relay_state = _make_relay_state(workspace_id, next_url)

    try:
        request  = _make_saml_request("/auth/saml/login", get_data=params)
        saml_auth = OneLogin_Saml2_Auth(request, old_settings=_saml_settings())
        login_url = saml_auth.login(return_to=relay_state)
        logger.info("SAML login initiated ip=%s", client_ip)
        return _redirect(login_url)
    except Exception as exc:
        logger.error("SAML login initiation failed: %s", type(exc).__name__)
        return _saml_err(500, "SAML_LOGIN_ERROR", "Failed to initiate SAML login.")


def handle_saml_acs(body_raw: str, client_ip: str) -> dict:
    """
    Assertion Consumer Service endpoint.
    Called by the IdP via browser redirect (POST binding).
    body_raw is application/x-www-form-urlencoded containing SAMLResponse + RelayState.
    Returns a 302 redirect with Set-Cookie on success.
    """
    if not AUTH_SAML_ENABLED:
        return _saml_disabled()
    if not _SAML_LIB_OK:
        return _saml_err(503, "SAML_LIB_MISSING", "SAML library not installed on server.")
    if not SAML_IDP_X509_CERT:
        return _saml_err(503, "SAML_NOT_CONFIGURED", "SAML IdP certificate not configured.")

    # Parse form-encoded body (ACS receives browser POST, not JSON)
    parsed_form  = parse_qs(body_raw or "", keep_blank_values=False)
    saml_response = (parsed_form.get("SAMLResponse") or [""])[0]
    relay_str     = (parsed_form.get("RelayState")   or [""])[0]

    if not saml_response:
        return _saml_err(400, "SAML_MISSING_RESPONSE", "SAMLResponse field is required.")

    # Per-IP ACS failure rate limit
    ok, retry = _rl_check(f"saml_acs:{client_ip}", _SAML_ACS_LIMIT, _SAML_ACS_WINDOW)
    if not ok:
        return _saml_rate_limited(retry)

    # Process and validate the SAML response
    post_data: dict = {"SAMLResponse": saml_response}
    if relay_str:
        post_data["RelayState"] = relay_str

    try:
        request  = _make_saml_request("/auth/saml/acs", post_data=post_data)
        saml_auth = OneLogin_Saml2_Auth(request, old_settings=_saml_settings())
        saml_auth.process_response()
        errors = saml_auth.get_errors()
        if errors:
            reason = saml_auth.get_last_error_reason() or "signature/validation error"
            logger.warning("SAML ACS validation failed ip=%s reason=%s", client_ip, reason[:120])
            return _error_redirect("SAML_VALIDATION_FAILED")
    except Exception as exc:
        logger.warning("SAML ACS processing error ip=%s type=%s", client_ip, type(exc).__name__)
        return _error_redirect("SAML_PROCESSING_ERROR")

    # Parse relay state early — need workspace_id before provisioning
    relay        = _parse_relay_state(relay_str) if relay_str else {}
    workspace_id = relay.get("w") or ""
    next_url     = relay.get("n") or "/overview"
    if not next_url.startswith("/"):
        next_url = "/overview"

    # Extract user info from validated assertion
    name_id    = saml_auth.get_nameid() or ""
    attributes = saml_auth.get_attributes() or {}
    email      = _extract_email(attributes, name_id)
    name       = _extract_name(attributes)

    if not email or "@" not in email:
        logger.warning("SAML ACS no valid email ip=%s", client_ip)
        return _error_redirect("SAML_NO_EMAIL")

    # Domain allowlist check
    if SAML_ALLOWED_DOMAINS:
        domain = email.split("@")[-1]
        if domain not in SAML_ALLOWED_DOMAINS:
            logger.info("SAML domain blocked ip=%s domain=%s", client_ip, domain)
            return _error_redirect("SAML_DOMAIN_NOT_ALLOWED")

    # Resolve workspace role from IdP groups (falls back to SAML_DEFAULT_ROLE)
    groups        = _extract_groups(attributes)
    resolved_role = _resolve_role_from_groups(groups)

    # Look up / provision user + assign workspace membership
    try:
        result = _provision_user(email, name, name_id, attributes,
                                 workspace_id=workspace_id,
                                 resolved_role=resolved_role)
    except Exception as exc:
        logger.error("SAML user provisioning error ip=%s type=%s", client_ip, type(exc).__name__)
        return _error_redirect("SAML_PROVISIONING_ERROR")

    if isinstance(result, dict) and "error" in result:
        logger.info("SAML login blocked ip=%s code=%s", client_ip, result["error"])
        return _error_redirect(result["error"])

    token, _user_id = result

    complete_url = f"{APP_PUBLIC_URL}/auth/saml/complete?next={next_url}"
    cookie       = _make_session_cookie(token, SESSION_TTL_HOURS * 3600)
    logger.info("SAML login success ip=%s email=****@%s", client_ip, email.split("@")[-1])
    return _redirect(complete_url, cookie=cookie)


def handle_saml_logout(headers: dict) -> dict:
    """Clear local session. SLO redirect to IdP if configured."""
    if not AUTH_SAML_ENABLED:
        return _saml_disabled()

    # Delete local session (reuse auth_handler logic)
    try:
        from auth_handler import handle_auth_logout
        return handle_auth_logout(headers)
    except Exception as exc:
        logger.warning("SAML logout session clear failed: %s", type(exc).__name__)

    # Fallback: clear cookie without DB (session will expire naturally)
    secure = "; Secure" if APP_ENV == "production" else ""
    clear_cookie = f"{_SESSION_COOKIE}=; HttpOnly{secure}; SameSite=Lax; Path=/; Max-Age=0"
    if SAML_IDP_SLO_URL and _SAML_LIB_OK:
        try:
            request   = _make_saml_request("/auth/saml/logout")
            saml_auth = OneLogin_Saml2_Auth(request, old_settings=_saml_settings())
            slo_url   = saml_auth.logout()
            return _redirect(slo_url, cookie=clear_cookie)
        except Exception:
            pass  # fall through to simple redirect

    return {
        "statusCode": 200,
        "headers": {**_base_headers(), "Set-Cookie": clear_cookie},
        "body": json.dumps({"ok": True, "message": "Logged out."}),
    }
