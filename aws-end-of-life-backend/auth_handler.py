"""
auth_handler.py — Feature-flagged auth endpoints for AWS EOL Monitor.

All auth features default to disabled.  Existing workspace-token access is
unchanged; this module only activates when the relevant AUTH_* env vars are
set to true.

Endpoints (all prefixed /auth/):
  GET  /auth/config               — public: returns enabled flags + captcha site key
  POST /auth/signup               — requires AUTH_EMAIL_SIGNUP_ENABLED=true
  POST /auth/verify-email         — requires AUTH_EMAIL_SIGNUP_ENABLED=true
  GET  /auth/google/start         — requires AUTH_GOOGLE_SIGNUP_ENABLED=true
  GET  /auth/google/callback      — requires AUTH_GOOGLE_SIGNUP_ENABLED=true
  GET  /auth/me                   — returns current session user
  POST /auth/logout               — clears session cookie

Security invariants (never break these):
  * Raw tokens are never stored.  Only SHA-256 hashes are written to the DB.
  * Tokens, Google access/ID tokens, secret keys are never logged.
  * All new auth features are disabled by default.
  * Workspace token flow remains the single auth primitive when all flags=false.
"""

import hashlib
import json
import logging
import os
import re
import secrets
import threading as _threading
import time as _time
from collections import defaultdict as _defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# ── Feature flags ─────────────────────────────────────────────────────────────

def _flag(key: str, default: str = "false") -> bool:
    return os.environ.get(key, default).lower() in ("1", "true", "yes")

AUTH_EMAIL_SIGNUP_ENABLED        = _flag("AUTH_EMAIL_SIGNUP_ENABLED")
AUTH_GOOGLE_SIGNUP_ENABLED       = _flag("AUTH_GOOGLE_SIGNUP_ENABLED")
AUTH_CAPTCHA_ENABLED             = _flag("AUTH_CAPTCHA_ENABLED")
AUTH_EMAIL_VERIFICATION_REQUIRED = _flag("AUTH_EMAIL_VERIFICATION_REQUIRED")
AUTH_SESSION_COOKIE_ENABLED      = _flag("AUTH_SESSION_COOKIE_ENABLED", "true")
AUTH_SAML_ENABLED                = _flag("AUTH_SAML_ENABLED")
ANONYMOUS_WORKSPACE_CREATE       = _flag("ANONYMOUS_WORKSPACE_CREATE_ENABLED", "true")
ENABLE_ORG_SCAN                  = _flag("ENABLE_ORG_SCAN")

GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID",     "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.environ.get("GOOGLE_REDIRECT_URI",  "")

EMAIL_VERIFICATION_TOKEN_TTL = int(os.environ.get("EMAIL_VERIFICATION_TOKEN_TTL_MINUTES", "30"))
SESSION_TTL_HOURS            = int(os.environ.get("SESSION_TTL_HOURS", "24"))
APP_PUBLIC_URL               = os.environ.get("APP_PUBLIC_URL", "")
ALLOWED_ORIGIN               = os.environ.get("ALLOWED_ORIGIN", "*")
APP_ENV                      = os.environ.get("APP_ENV", "development").lower()
MEMBER_LOGIN_DEV_LINKS       = os.environ.get("MEMBER_LOGIN_DEV_LINKS", "").lower() in ("1", "true", "yes")

# ── Startup configuration warnings ────────────────────────────────────────────
_HAS_EMAIL_DELIVERY = bool(os.environ.get("SMTP_HOST") or os.environ.get("SES_REGION") or os.environ.get("EMAIL_PROVIDER"))

if AUTH_EMAIL_VERIFICATION_REQUIRED and not _HAS_EMAIL_DELIVERY and not MEMBER_LOGIN_DEV_LINKS:
    logger.warning(
        "AUTH_EMAIL_VERIFICATION_REQUIRED=true but no email provider is configured "
        "(SMTP_HOST, SES_REGION, or EMAIL_PROVIDER). "
        "Verification emails will not be delivered — users cannot verify their accounts. "
        "Set MEMBER_LOGIN_DEV_LINKS=true in development, or configure an email provider."
    )

if AUTH_EMAIL_SIGNUP_ENABLED and APP_ENV == "production" and not _HAS_EMAIL_DELIVERY and AUTH_EMAIL_VERIFICATION_REQUIRED:
    logger.error(
        "PRODUCTION MISCONFIGURATION: AUTH_EMAIL_VERIFICATION_REQUIRED=true with no "
        "email delivery configured. Email signups will be stuck at verification. "
        "Configure SMTP_HOST or SES_REGION before enabling this in production."
    )

# ── Per-module in-memory rate limiter ─────────────────────────────────────────
# Independent of the workspace rate limiter in api_handler.py.
# Resets on process restart; upgrade to Redis for multi-process deployments.

_rl_lock  = _threading.Lock()
_rl_store: dict = _defaultdict(list)

_AUTH_SIGNUP_IP_LIMIT     = int(os.environ.get("AUTH_SIGNUP_IP_RATE_LIMIT",     "5"))
_AUTH_SIGNUP_IP_WINDOW    = int(os.environ.get("AUTH_SIGNUP_IP_RATE_WINDOW",    "3600"))
_AUTH_SIGNUP_EMAIL_LIMIT  = int(os.environ.get("AUTH_SIGNUP_EMAIL_RATE_LIMIT",  "3"))
_AUTH_SIGNUP_EMAIL_WINDOW = int(os.environ.get("AUTH_SIGNUP_EMAIL_RATE_WINDOW", "86400"))
_AUTH_VERIFY_IP_LIMIT     = int(os.environ.get("AUTH_VERIFY_IP_RATE_LIMIT",     "10"))
_AUTH_VERIFY_IP_WINDOW    = int(os.environ.get("AUTH_VERIFY_IP_RATE_WINDOW",    "3600"))
_AUTH_GOOGLE_IP_LIMIT     = int(os.environ.get("AUTH_GOOGLE_IP_RATE_LIMIT",     "10"))
_AUTH_GOOGLE_IP_WINDOW    = int(os.environ.get("AUTH_GOOGLE_IP_RATE_WINDOW",    "3600"))


def _rl_check(key: str, limit: int, window: int) -> tuple:
    """Sliding-window check + record. Returns (allowed, retry_after_seconds)."""
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

# ── Response helpers ──────────────────────────────────────────────────────────

def _resp(status: int, body: dict, extra_headers: dict | None = None) -> dict:
    headers = {
        "Content-Type":                       "application/json",
        "Access-Control-Allow-Origin":        ALLOWED_ORIGIN,
        "Access-Control-Allow-Headers":
            "Authorization,Content-Type,X-Workspace-Token,X-Admin-Token,X-API-Token",
        "Access-Control-Allow-Methods":       "GET,PUT,POST,DELETE,PATCH,OPTIONS",
        "Access-Control-Allow-Credentials":   "true",
    }
    if extra_headers:
        headers.update(extra_headers)
    return {"statusCode": status, "headers": headers, "body": json.dumps(body)}


def _err(status: int, code: str, message: str) -> dict:
    return _resp(status, {"ok": False, "error": code, "message": message})


def _feature_disabled(feature: str) -> dict:
    return _err(403, "AUTH_FEATURE_DISABLED",
                f"{feature} is not enabled in this deployment.")


def _rate_limited(retry_after: int) -> dict:
    r = _err(429, "RATE_LIMITED", "Too many requests. Please try again later.")
    r["headers"]["Retry-After"] = str(retry_after)
    return r

# ── Token / hash helpers ──────────────────────────────────────────────────────

def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _mask(value: str) -> str:
    if not value or len(value) < 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires(hours: int = 0, minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours, minutes=minutes)).isoformat()

# ── Cookie helpers ────────────────────────────────────────────────────────────

_SESSION_COOKIE = "eolm_session"


def _make_cookie(token: str, max_age: int) -> str:
    secure = "; Secure" if APP_ENV == "production" else ""
    return f"{_SESSION_COOKIE}={token}; HttpOnly{secure}; SameSite=Lax; Path=/; Max-Age={max_age}"


def _clear_cookie() -> str:
    return f"{_SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"


def _get_session_token(headers: dict) -> str:
    """Extract eolm_session value from the Cookie header."""
    cookie = (headers or {}).get("cookie", "") or (headers or {}).get("Cookie", "")
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(f"{_SESSION_COOKIE}="):
            return part[len(_SESSION_COOKIE) + 1:]
    return ""

# ── DB helpers (thin wrappers over PostgresBackend public methods) ─────────────

def _db():
    from storage import get_storage
    return get_storage()


def _one(sql: str, params=None) -> dict | None:
    return _db().auth_one(sql, params)


def _run(sql: str, params=None) -> int:
    return _db().auth_run(sql, params)


def _query(sql: str, params=None) -> list:
    return _db().auth_query(sql, params)

# ── Session management ────────────────────────────────────────────────────────

def _create_session(user_id: str) -> str:
    """Create a new session for user_id. Returns the plain (unhashed) token."""
    token      = secrets.token_hex(32)
    session_id = f"sess_{secrets.token_hex(8)}"
    now        = _now()
    expires    = _expires(hours=SESSION_TTL_HOURS)
    _run(
        "INSERT INTO auth_sessions"
        " (id, user_id, session_hash, expires_at, created_at, last_seen_at)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (session_id, user_id, _sha(token), expires, now, now),
    )
    logger.info("auth session created user_id=%s session=%s", user_id, _mask(session_id))
    return token


def lookup_session(headers: dict) -> dict | None:
    """
    Look up the session cookie in headers.
    Returns a row with user fields merged, or None if no valid session.
    """
    token = _get_session_token(headers)
    if not token:
        return None
    now = _now()
    row = _one(
        "SELECT s.id AS session_id, s.user_id, s.expires_at,"
        "       u.email, u.name, u.avatar_url, u.email_verified, u.status"
        " FROM auth_sessions s JOIN auth_users u ON u.id = s.user_id"
        " WHERE s.session_hash = %s AND s.expires_at > %s AND u.status = 'active'",
        (_sha(token), now),
    )
    if not row:
        return None
    # Refresh last_seen_at without blocking
    try:
        _run("UPDATE auth_sessions SET last_seen_at = %s WHERE id = %s",
             (now, row["session_id"]))
    except Exception:
        pass
    return row


def lookup_session_membership(headers: dict, workspace_id: str) -> dict | None:
    """
    Return membership info if the session cookie owner is a member of workspace_id.
    Used by _verify_workspace_ex to accept session-based workspace access.
    """
    token = _get_session_token(headers)
    if not token:
        return None
    now = _now()
    return _one(
        "SELECT m.role, m.user_id, u.email"
        " FROM auth_sessions  s"
        " JOIN auth_users u ON u.id = s.user_id"
        " JOIN auth_user_workspace_memberships m ON m.user_id = s.user_id"
        " WHERE s.session_hash = %s AND s.expires_at > %s"
        "   AND u.status = 'active' AND m.workspace_id = %s",
        (_sha(token), now, workspace_id),
    )

# ── /auth/config ──────────────────────────────────────────────────────────────

def handle_auth_config() -> dict:
    """Public — returns which auth features are enabled plus the captcha site key.
    Never exposes secret keys or credentials."""
    captcha_site_key = (
        os.environ.get("CAPTCHA_SITE_KEY", "") if AUTH_CAPTCHA_ENABLED else ""
    )
    return _resp(200, {
        "ok": True,
        "auth": {
            "emailSignupEnabled":        AUTH_EMAIL_SIGNUP_ENABLED,
            "googleSignupEnabled":       AUTH_GOOGLE_SIGNUP_ENABLED,
            "captchaEnabled":            AUTH_CAPTCHA_ENABLED,
            "emailVerificationRequired": AUTH_EMAIL_VERIFICATION_REQUIRED,
            "sessionEnabled":            AUTH_SESSION_COOKIE_ENABLED,
            "samlEnabled":               AUTH_SAML_ENABLED,
            "samlLoginUrl":              "/auth/saml/login" if AUTH_SAML_ENABLED else None,
            "anonymousWorkspaceCreate":  ANONYMOUS_WORKSPACE_CREATE,
            "orgScanEnabled":            ENABLE_ORG_SCAN,
            "captchaProvider":           (
                os.environ.get("CAPTCHA_PROVIDER", "turnstile")
                if AUTH_CAPTCHA_ENABLED else None
            ),
            "captchaSiteKey": captcha_site_key,
        },
    })

# ── /auth/signup ──────────────────────────────────────────────────────────────

def handle_auth_signup(body: dict, client_ip: str) -> dict:
    if not AUTH_EMAIL_SIGNUP_ENABLED:
        return _feature_disabled("Email signup")

    # IP-level rate limit
    ok, retry = _rl_check(
        f"auth_signup_ip:{client_ip}", _AUTH_SIGNUP_IP_LIMIT, _AUTH_SIGNUP_IP_WINDOW
    )
    if not ok:
        return _rate_limited(retry)

    email = (body.get("email") or "").strip().lower()
    name  = (body.get("name")  or "").strip()

    if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return _err(400, "INVALID_EMAIL", "A valid email address is required.")
    if not name:
        return _err(400, "NAME_REQUIRED", "Name is required.")

    # Per-email rate limit (prevent re-signup flooding)
    ok_e, retry_e = _rl_check(
        f"auth_signup_email:{_sha(email)}", _AUTH_SIGNUP_EMAIL_LIMIT, _AUTH_SIGNUP_EMAIL_WINDOW
    )
    if not ok_e:
        return _rate_limited(retry_e)

    # CAPTCHA
    if AUTH_CAPTCHA_ENABLED:
        captcha_token = body.get("captchaToken", "")
        if not captcha_token:
            return _err(400, "CAPTCHA_REQUIRED", "CAPTCHA verification is required.")
        from captcha import verify_captcha
        if not verify_captcha(captcha_token, client_ip):
            return _err(400, "CAPTCHA_INVALID", "CAPTCHA verification failed. Please try again.")

    now      = _now()
    existing = _one("SELECT id, email_verified FROM auth_users WHERE email = %s", (email,))

    if existing:
        user_id = existing["id"]
        already_verified = existing.get("email_verified") or False

        if AUTH_EMAIL_VERIFICATION_REQUIRED and not already_verified:
            # Resend verification for users who never completed it
            return _send_verification(user_id, email)

        # User already registered — do NOT create a session without credential proof.
        # Signing up again with someone else's email must not grant access.
        return _resp(200, {"ok": True, "status": "already_registered",
                           "message": "An account with this email already exists. "
                                      "Please log in instead.", "email": email})

    # New user
    user_id        = f"usr_{secrets.token_hex(8)}"
    email_verified = not AUTH_EMAIL_VERIFICATION_REQUIRED

    _run(
        "INSERT INTO auth_users"
        " (id, email, name, provider, email_verified, status, created_at, last_login_at)"
        " VALUES (%s, %s, %s, 'email', %s, 'active', %s, %s)",
        (user_id, email, name, email_verified, now, now),
    )
    logger.info("auth user created user_id=%s provider=email", user_id)

    if not AUTH_EMAIL_VERIFICATION_REQUIRED:
        if AUTH_SESSION_COOKIE_ENABLED:
            token   = _create_session(user_id)
            max_age = SESSION_TTL_HOURS * 3600
            return _resp(201, {"ok": True, "status": "created", "email": email},
                         {"Set-Cookie": _make_cookie(token, max_age)})
        return _resp(201, {"ok": True, "status": "created", "email": email})

    return _send_verification(user_id, email)


def _send_verification(user_id: str, email: str) -> dict:
    """Create a verification token and (in dev) log the link."""
    vtoken  = secrets.token_hex(32)
    vtok_id = f"evtok_{secrets.token_hex(8)}"
    now     = _now()
    expires = _expires(minutes=EMAIL_VERIFICATION_TOKEN_TTL)

    _run(
        "INSERT INTO auth_email_verification_tokens"
        " (id, user_id, token_hash, expires_at, created_at)"
        " VALUES (%s, %s, %s, %s, %s)",
        (vtok_id, user_id, _sha(vtoken), expires, now),
    )

    if APP_PUBLIC_URL and MEMBER_LOGIN_DEV_LINKS:
        verify_link = f"{APP_PUBLIC_URL}/auth/verify-email?token={vtoken}"
        logger.warning("DEV: email verify link user_id=%s → %s", user_id, verify_link)

    return _resp(202, {
        "ok":     True,
        "status": "verification_required",
        "message": (
            f"Check your email for a verification link."
            f" It expires in {EMAIL_VERIFICATION_TOKEN_TTL} minutes."
        ),
        "email": email,
    })

# ── /auth/verify-email ────────────────────────────────────────────────────────

def handle_auth_verify_email(body: dict, client_ip: str) -> dict:
    if not AUTH_EMAIL_SIGNUP_ENABLED:
        return _feature_disabled("Email signup")

    ok, retry = _rl_check(
        f"auth_verify_ip:{client_ip}", _AUTH_VERIFY_IP_LIMIT, _AUTH_VERIFY_IP_WINDOW
    )
    if not ok:
        return _rate_limited(retry)

    token = (body.get("token") or "").strip()
    if not token:
        return _err(400, "TOKEN_REQUIRED", "Verification token is required.")

    now = _now()
    row = _one(
        "SELECT id, user_id, used_at, expires_at"
        " FROM auth_email_verification_tokens WHERE token_hash = %s",
        (_sha(token),),
    )

    if not row:
        return _err(400, "TOKEN_INVALID", "Verification token is invalid.")
    if row.get("used_at"):
        return _err(400, "TOKEN_USED", "This verification link has already been used.")
    if row["expires_at"] < now:
        return _err(400, "TOKEN_EXPIRED",
                    "This verification link has expired. Please request a new one.")

    _run("UPDATE auth_email_verification_tokens SET used_at = %s WHERE id = %s",
         (now, row["id"]))
    _run("UPDATE auth_users SET email_verified = TRUE, last_login_at = %s WHERE id = %s",
         (now, row["user_id"]))

    user = _one("SELECT id, email, name FROM auth_users WHERE id = %s", (row["user_id"],))
    memberships = _query(
        "SELECT workspace_id, role FROM auth_user_workspace_memberships WHERE user_id = %s",
        (row["user_id"],),
    )

    extra = {}
    if AUTH_SESSION_COOKIE_ENABLED:
        sess_token = _create_session(row["user_id"])
        extra["Set-Cookie"] = _make_cookie(sess_token, SESSION_TTL_HOURS * 3600)

    return _resp(200, {
        "ok":   True,
        "user": {"id": user["id"], "email": user["email"], "name": user["name"]},
        "workspaces": [
            {"workspaceId": m["workspace_id"], "role": m["role"]} for m in memberships
        ],
    }, extra or None)

# ── /auth/google/start ────────────────────────────────────────────────────────

# In-memory OAuth state store (prevents CSRF).
# State entries expire after 10 minutes; single PM2 process OK.
_oauth_states: dict = {}


def handle_auth_google_start(client_ip: str) -> dict:
    if not AUTH_GOOGLE_SIGNUP_ENABLED:
        return _feature_disabled("Google signup")
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        return _err(503, "GOOGLE_NOT_CONFIGURED",
                    "Google OAuth is not configured on this server.")

    ok, retry = _rl_check(
        f"auth_google_ip:{client_ip}", _AUTH_GOOGLE_IP_LIMIT, _AUTH_GOOGLE_IP_WINDOW
    )
    if not ok:
        return _rate_limited(retry)

    # Purge expired states to prevent unbounded memory growth
    now_mono = _time.monotonic()
    expired_keys = [k for k, exp in _oauth_states.items() if exp < now_mono]
    for k in expired_keys:
        _oauth_states.pop(k, None)

    state = secrets.token_hex(16)
    _oauth_states[state] = now_mono + 600  # 10-minute TTL

    params = urlencode({
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "online",
        "state":         state,
        "prompt":        "select_account",
    })
    return {
        "statusCode": 302,
        "headers": {
            "Location":                       f"https://accounts.google.com/o/oauth2/v2/auth?{params}",
            "Access-Control-Allow-Origin":    ALLOWED_ORIGIN,
            "Access-Control-Allow-Credentials": "true",
        },
        "body": "",
    }

# ── /auth/google/callback ─────────────────────────────────────────────────────

def handle_auth_google_callback(params: dict) -> dict:
    if not AUTH_GOOGLE_SIGNUP_ENABLED:
        return _feature_disabled("Google signup")
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        return _err(503, "GOOGLE_NOT_CONFIGURED", "Google OAuth is not configured.")

    error = params.get("error", "")
    code  = params.get("code",  "")
    state = params.get("state", "")

    if error:
        return _frontend_error("google_error", error)
    if not code or not state:
        return _frontend_error("google_error", "missing_params")

    # Validate CSRF state
    expiry = _oauth_states.pop(state, None)
    if expiry is None or _time.monotonic() > expiry:
        return _frontend_error("google_error", "invalid_state")

    # Exchange code → tokens
    token_data = _google_exchange_code(code)
    if not token_data:
        return _frontend_error("google_error", "token_exchange_failed")

    # Get user info from Google (access_token, not ID token, to avoid jwt parsing dep)
    user_info = _google_userinfo(token_data.get("access_token", ""))
    if not user_info:
        return _frontend_error("google_error", "userinfo_failed")

    google_sub     = user_info.get("sub", "")
    email          = (user_info.get("email") or "").lower().strip()
    name           = user_info.get("name", "") or email.split("@")[0]
    avatar_url     = user_info.get("picture", "")
    email_verified = bool(user_info.get("email_verified"))

    if not google_sub or not email:
        return _frontend_error("google_error", "incomplete_profile")

    now = _now()
    existing = _one(
        "SELECT id FROM auth_users WHERE provider = 'google' AND provider_subject = %s",
        (google_sub,),
    ) or _one("SELECT id FROM auth_users WHERE email = %s", (email,))

    if existing:
        user_id = existing["id"]
        _run(
            "UPDATE auth_users SET name = %s, avatar_url = %s, email_verified = %s,"
            " last_login_at = %s, provider = 'google', provider_subject = %s"
            " WHERE id = %s",
            (name, avatar_url, email_verified, now, google_sub, user_id),
        )
    else:
        user_id = f"usr_{secrets.token_hex(8)}"
        _run(
            "INSERT INTO auth_users"
            " (id, email, name, avatar_url, provider, provider_subject,"
            "  email_verified, status, created_at, last_login_at)"
            " VALUES (%s,%s,%s,%s,'google',%s,%s,'active',%s,%s)",
            (user_id, email, name, avatar_url, google_sub, email_verified, now, now),
        )
        logger.info("auth user created user_id=%s provider=google", user_id)

    sess_token  = _create_session(user_id)
    frontend_url = APP_PUBLIC_URL or ""
    return {
        "statusCode": 302,
        "headers": {
            "Location":                         f"{frontend_url}/auth/google/complete",
            "Set-Cookie":                        _make_cookie(sess_token, SESSION_TTL_HOURS * 3600),
            "Access-Control-Allow-Origin":      ALLOWED_ORIGIN,
            "Access-Control-Allow-Credentials": "true",
        },
        "body": "",
    }


def _frontend_error(error_type: str, detail: str) -> dict:
    url = f"{APP_PUBLIC_URL}/auth/error?type={error_type}&detail={detail}"
    return {"statusCode": 302, "headers": {"Location": url}, "body": ""}


def _google_exchange_code(code: str) -> dict | None:
    import urllib.request
    import urllib.parse
    data = urllib.parse.urlencode({
        "code":          code,
        "client_id":     GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "grant_type":    "authorization_code",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=data, method="POST"
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as exc:
        logger.error("google token exchange failed: %s", type(exc).__name__)
        return None


def _google_userinfo(access_token: str) -> dict | None:
    import urllib.request
    req = urllib.request.Request("https://www.googleapis.com/oauth2/v3/userinfo")
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as exc:
        logger.error("google userinfo failed: %s", type(exc).__name__)
        return None

# ── /auth/me ─────────────────────────────────────────────────────────────────

def handle_auth_me(headers: dict) -> dict:
    user = lookup_session(headers)
    if not user:
        return _err(401, "AUTH_SESSION_MISSING", "No active session. Please sign in.")
    memberships = _query(
        "SELECT workspace_id, role FROM auth_user_workspace_memberships WHERE user_id = %s",
        (user["user_id"],),
    )
    return _resp(200, {
        "ok": True,
        "user": {
            "id":            user["user_id"],
            "email":         user["email"],
            "name":          user["name"],
            "avatarUrl":     user.get("avatar_url", ""),
            "emailVerified": bool(user.get("email_verified")),
        },
        "workspaces": [
            {"workspaceId": m["workspace_id"], "role": m["role"]} for m in memberships
        ],
    })

# ── /auth/logout ──────────────────────────────────────────────────────────────

def handle_auth_logout(headers: dict) -> dict:
    token = _get_session_token(headers)
    if token:
        try:
            _run("DELETE FROM auth_sessions WHERE session_hash = %s", (_sha(token),))
        except Exception:
            pass
    return _resp(200, {"ok": True}, {"Set-Cookie": _clear_cookie()})
