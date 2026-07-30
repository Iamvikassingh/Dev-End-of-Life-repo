"""
AWS EOL Monitor — SNS Email Subscription Models & Dedup Logic

Provides the data models and business logic for managing per-workspace
email subscriptions through AWS SNS, including:
  - Subscription lifecycle (PENDING → VERIFIED → UNSUBSCRIBED)
  - Notification history recording
  - Duplicate-suppression within configurable cooldown windows
"""
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Cooldown: don't re-alert the same resource+severity within N hours
DEFAULT_COOLDOWN_HOURS = int(__import__("os").environ.get("SNS_ALERT_COOLDOWN_HOURS", "24"))

# Subscription status values
STATUS_PENDING      = "PENDING"
STATUS_VERIFIED     = "VERIFIED"
STATUS_UNSUBSCRIBED = "UNSUBSCRIBED"


# ── Validators ────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def validate_email(email: str) -> bool:
    """Return True if the email address looks valid."""
    return bool(email and _EMAIL_RE.match(email.strip()))


# ── Factory helpers ───────────────────────────────────────────────────────────

def new_subscription_id() -> str:
    return f"sns_sub_{secrets.token_hex(10)}"


def new_history_id() -> str:
    return f"sns_notif_{secrets.token_hex(10)}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Subscription model ────────────────────────────────────────────────────────

def make_subscription(workspace_id: str, email: str, topic_arn: str,
                      subscription_arn: str = "") -> dict:
    """
    Build a new EmailSubscription record dict.

    Fields:
      id              — unique subscription ID
      workspace_id    — owning workspace
      email           — subscriber email address
      topic_arn       — SNS topic ARN
      subscription_arn — SNS subscription ARN (empty until confirmed)
      status          — PENDING | VERIFIED | UNSUBSCRIBED
      created_at      — ISO timestamp
      updated_at      — ISO timestamp
    """
    now = _now_iso()
    return {
        "id":               new_subscription_id(),
        "workspace_id":     workspace_id,
        "email":            email.strip().lower(),
        "topic_arn":        topic_arn,
        "subscription_arn": subscription_arn,
        "status":           STATUS_PENDING,
        "created_at":       now,
        "updated_at":       now,
    }


def update_subscription_status(sub: dict, status: str,
                                subscription_arn: Optional[str] = None) -> dict:
    """Return a copy of sub with updated status (and optionally arn)."""
    updated = dict(sub)
    updated["status"]     = status
    updated["updated_at"] = _now_iso()
    if subscription_arn is not None:
        updated["subscription_arn"] = subscription_arn
    return updated


# ── Notification history model ────────────────────────────────────────────────

def make_notification_history(workspace_id: str, resource: dict,
                               email: str, status: str,
                               message_id: str = "") -> dict:
    """
    Build a NotificationHistory record dict.

    Fields:
      id             — unique record ID
      workspace_id   — owning workspace
      resource_id    — scanned resource identifier
      resource_name  — human-readable name
      service_type   — e.g. Lambda, EKS
      current_version — detected version
      severity       — HIGH | MEDIUM
      email          — recipient address
      status         — SENT | FAILED | SUPPRESSED
      sent_at        — ISO timestamp
      message_id     — SNS MessageId (empty on failure/suppression)
      cooldown_key   — dedup key used for suppression check
    """
    resource_id  = resource.get("resource_id") or resource.get("resourceId") or ""
    service      = resource.get("service_type") or resource.get("service") or ""
    severity     = resource.get("severity", "")
    return {
        "id":              new_history_id(),
        "workspace_id":    workspace_id,
        "resource_id":     resource_id,
        "resource_name":   resource.get("resource_name") or resource.get("resourceName") or resource_id,
        "service_type":    service,
        "current_version": resource.get("version", ""),
        "severity":        severity,
        "email":           email,
        "status":          status,
        "sent_at":         _now_iso(),
        "message_id":      message_id,
        "cooldown_key":    _cooldown_key(workspace_id, resource_id, severity),
    }


# ── Dedup / cooldown helpers ──────────────────────────────────────────────────

def _cooldown_key(workspace_id: str, resource_id: str, severity: str) -> str:
    return f"{workspace_id}|{resource_id}|{severity}"


def is_within_cooldown(history_records: list, workspace_id: str,
                        resource_id: str, severity: str,
                        cooldown_hours: int = DEFAULT_COOLDOWN_HOURS) -> bool:
    """
    Return True if a SENT notification was already delivered for this
    workspace + resource + severity within the cooldown window.
    """
    key    = _cooldown_key(workspace_id, resource_id, severity)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)

    for record in history_records:
        if record.get("cooldown_key") != key:
            continue
        if record.get("status") != "SENT":
            continue
        try:
            sent_at = datetime.fromisoformat(record["sent_at"])
            # Ensure timezone-aware
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            if sent_at > cutoff:
                logger.debug("Cooldown active for key=%s (sent at %s)", key, sent_at.isoformat())
                return True
        except (KeyError, ValueError):
            continue
    return False


# ── Severity filter ───────────────────────────────────────────────────────────

ALERTABLE_SEVERITIES = {"HIGH", "MEDIUM"}


def should_alert(resource: dict) -> bool:
    """
    Return True if this resource meets the severity threshold for email alerts.

    Rules:
      HIGH   — EOL reached, deprecated, or < 30 days remaining
      MEDIUM — 31–90 days remaining
      LOW    — skip
    """
    severity = resource.get("severity", "").upper()
    return severity in ALERTABLE_SEVERITIES


# ── Alert type classifier ─────────────────────────────────────────────────────

def classify_alert_type(resource: dict) -> str:
    """
    Classify the alert type for subject-line purposes.

    Returns one of:
      DEPRECATED_RESOURCE
      ALREADY_EOL
      UPCOMING_EOL_CRITICAL   (< 30 days)
      UPCOMING_EOL_WARNING    (31–90 days)
    """
    lifecycle = (resource.get("lifecycleStatus") or resource.get("eol_status") or "").upper()
    severity  = resource.get("severity", "").upper()
    days_raw  = resource.get("days_to_eol") or resource.get("daysToEol")

    try:
        days = int(days_raw)
    except (TypeError, ValueError):
        days = None

    if lifecycle in ("EOL", "DEPRECATED"):
        if days is not None and days < 0:
            return "ALREADY_EOL"
        return "DEPRECATED_RESOURCE"

    if severity == "HIGH" or (days is not None and days <= 30):
        return "UPCOMING_EOL_CRITICAL"
    return "UPCOMING_EOL_WARNING"
