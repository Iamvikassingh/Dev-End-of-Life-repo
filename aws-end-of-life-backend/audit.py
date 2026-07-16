"""
Audit log helpers for AWS EOL Monitor.

Creates structured, workspace-scoped audit records.
NEVER include secrets (tokens, passwords, credentials) in audit metadata.
"""
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class AuditAction:
    WORKSPACE_CREATED              = "WORKSPACE_CREATED"
    WORKSPACE_ACCESSED             = "WORKSPACE_ACCESSED"
    ACCOUNT_CONNECTED              = "ACCOUNT_CONNECTED"
    ACCOUNT_UPDATED                = "ACCOUNT_UPDATED"
    ACCOUNT_DELETED                = "ACCOUNT_DELETED"
    SCAN_STARTED                   = "SCAN_STARTED"
    SCAN_COMPLETED                 = "SCAN_COMPLETED"
    SCAN_FAILED                    = "SCAN_FAILED"
    ALERT_ACKNOWLEDGED             = "ALERT_ACKNOWLEDGED"
    ALERT_SNOOZED                  = "ALERT_SNOOZED"
    ALERT_RESOLVED                 = "ALERT_RESOLVED"
    REPORT_SNAPSHOT_CREATED        = "REPORT_SNAPSHOT_CREATED"
    NOTIFICATION_SETTINGS_UPDATED  = "NOTIFICATION_SETTINGS_UPDATED"
    NOTIFICATION_TEST_SENT         = "NOTIFICATION_TEST_SENT"
    WORKSPACE_TOKEN_ROTATED        = "WORKSPACE_TOKEN_ROTATED"
    API_TOKEN_CREATED              = "API_TOKEN_CREATED"
    API_TOKEN_REVOKED              = "API_TOKEN_REVOKED"
    API_TOKEN_UPDATED              = "API_TOKEN_UPDATED"
    SETTINGS_UPDATED               = "SETTINGS_UPDATED"
    REPORT_CSV_DOWNLOADED          = "REPORT_CSV_DOWNLOADED"
    MEMBER_INVITED                 = "MEMBER_INVITED"
    MEMBER_ROLE_CHANGED            = "MEMBER_ROLE_CHANGED"
    MEMBER_DISABLED                = "MEMBER_DISABLED"
    MEMBER_ENABLED                 = "MEMBER_ENABLED"
    MEMBER_REMOVED                 = "MEMBER_REMOVED"
    MEMBER_INVITE_ACCEPTED         = "MEMBER_INVITE_ACCEPTED"
    MEMBER_SESSION_CREATED         = "MEMBER_SESSION_CREATED"
    MEMBER_LOGIN_LINK_SENT         = "MEMBER_LOGIN_LINK_SENT"
    MEMBER_LOGIN_COMPLETED         = "MEMBER_LOGIN_COMPLETED"
    MEMBER_SESSIONS_REVOKED        = "MEMBER_SESSIONS_REVOKED"


def make_audit_log(
    workspace_id: str,
    action: str,
    message: str,
    actor_type: str = "WORKSPACE_TOKEN",
    actor_id:   str = "workspace",
    actor_label: str = "Workspace session",
    resource_type: Optional[str] = None,
    resource_id:   Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """
    Build an audit log dict.  Never pass secrets via metadata.
    """
    return {
        "id":          f"audit_{secrets.token_hex(10)}",
        "workspaceId": workspace_id,
        "actor": {
            "type":  actor_type,
            "id":    actor_id,
            "label": actor_label,
        },
        "action":       action,
        "resourceType": resource_type,
        "resourceId":   resource_id,
        "message":      message,
        "metadata":     metadata or {},
        "createdAt":    datetime.now(timezone.utc).isoformat(),
    }


def write_audit(storage, workspace_id: str, action: str, message: str, **kwargs) -> None:
    """Fire-and-forget audit write. Never raises — errors are logged only."""
    try:
        log = make_audit_log(workspace_id, action, message, **kwargs)
        storage.save_audit_log(log)
    except Exception as exc:
        logger.warning("Audit write failed (non-fatal): %s", exc)
