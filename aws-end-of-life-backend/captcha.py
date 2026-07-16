"""
CAPTCHA verification abstraction for AWS EOL Monitor.
Supports Cloudflare Turnstile (default) and Google reCAPTCHA.
Called only when AUTH_CAPTCHA_ENABLED=true.
Never logs tokens or the secret key.
"""
import json
import logging
import os
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

CAPTCHA_PROVIDER   = os.environ.get("CAPTCHA_PROVIDER",   "turnstile").lower()
CAPTCHA_SECRET_KEY = os.environ.get("CAPTCHA_SECRET_KEY", "")

_TURNSTILE_URL  = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_RECAPTCHA_URL  = "https://www.google.com/recaptcha/api/siteverify"


def verify_captcha(token: str, client_ip: str = "") -> bool:
    """
    Verify a CAPTCHA response token server-side.
    Returns True if the token is valid, False otherwise.
    Never logs the token, secret key, or IP.
    """
    if not CAPTCHA_SECRET_KEY:
        logger.error("captcha.verify: CAPTCHA_SECRET_KEY not configured — failing closed")
        return False
    if not token:
        return False

    if CAPTCHA_PROVIDER == "turnstile":
        return _verify_turnstile(token, client_ip)
    if CAPTCHA_PROVIDER in ("recaptcha", "recaptchav2", "recaptchav3"):
        return _verify_recaptcha(token, client_ip)

    logger.error("captcha.verify: unknown CAPTCHA_PROVIDER=%s", CAPTCHA_PROVIDER)
    return False


def _post(url: str, data: dict) -> dict:
    encoded = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return json.loads(r.read().decode())
    except Exception as exc:
        logger.error("captcha http error provider=%s type=%s", CAPTCHA_PROVIDER, type(exc).__name__)
        return {}


def _verify_turnstile(token: str, client_ip: str) -> bool:
    payload = {"secret": CAPTCHA_SECRET_KEY, "response": token}
    if client_ip:
        payload["remoteip"] = client_ip
    result  = _post(_TURNSTILE_URL, payload)
    success = bool(result.get("success"))
    if not success:
        logger.warning("captcha turnstile rejected codes=%s", result.get("error-codes", []))
    return success


def _verify_recaptcha(token: str, client_ip: str) -> bool:
    payload = {"secret": CAPTCHA_SECRET_KEY, "response": token}
    if client_ip:
        payload["remoteip"] = client_ip
    result  = _post(_RECAPTCHA_URL, payload)
    success = bool(result.get("success"))
    if not success:
        logger.warning("captcha recaptcha rejected codes=%s", result.get("error-codes", []))
    return success
