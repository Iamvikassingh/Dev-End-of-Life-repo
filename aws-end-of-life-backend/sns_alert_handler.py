"""
AWS EOL Monitor — SNS Alert Handler

Orchestrates the full EOL alert dispatch cycle:
  1. Load all active alerts for a workspace from storage
  2. Filter HIGH and MEDIUM severity
  3. Check dedup / cooldown window
  4. Build professional HTML email
  5. Publish via SNS to all VERIFIED subscribers
  6. Record notification history

Called by:
  - alert_scheduler.py  (background timer — every 12 h)
  - api_handler.py      (POST /workspaces/:wsId/alerts/email-notify)
  - api_handler.py      (POST /workspaces/:wsId/alerts/email-test)
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

APP_URL = os.environ.get("APP_URL", os.environ.get("APP_PUBLIC_URL", "")).rstrip("/")
COOLDOWN_HOURS = int(os.environ.get("SNS_ALERT_COOLDOWN_HOURS", "24"))


# ── HTML email builder ────────────────────────────────────────────────────────

def build_eol_alert_html(resource: dict, workspace_name: str,
                          alert_type: str) -> tuple[str, str, str]:
    """
    Build a professional responsive HTML email for an EOL alert.

    Returns (subject, html_body, text_body).
    """
    service      = resource.get("service_type") or resource.get("service") or "Unknown Service"
    resource_id  = resource.get("resource_id") or resource.get("resourceId") or ""
    resource_name = resource.get("resource_name") or resource.get("resourceName") or resource_id
    version      = resource.get("version") or "—"
    eol_date     = resource.get("eol_date") or resource.get("eolDate") or "—"
    severity     = resource.get("severity", "HIGH").upper()
    region       = resource.get("region") or "—"
    account_id   = resource.get("account_id") or resource.get("accountId") or "—"
    days_raw     = resource.get("days_to_eol") or resource.get("daysToEol")
    lifecycle    = resource.get("lifecycleStatus") or resource.get("eol_status") or "EOL"

    try:
        days = int(days_raw)
    except (TypeError, ValueError):
        days = None

    # Severity colours
    sev_color = "#dc2626" if severity == "HIGH" else "#d97706"
    sev_bg    = "#fef2f2" if severity == "HIGH" else "#fffbeb"

    # Subject line
    type_label = {
        "ALREADY_EOL":           "Already End of Life",
        "DEPRECATED_RESOURCE":   "Deprecated Resource",
        "UPCOMING_EOL_CRITICAL": "Critical — Approaching EOL",
        "UPCOMING_EOL_WARNING":  "Warning — Approaching EOL",
    }.get(alert_type, "End of Life Alert")

    subject = f"[{severity}] AWS EOL Alert: {service} {version} — {type_label} | {workspace_name}"

    # Days remaining badge
    if days is not None and days < 0:
        days_label = f"{abs(days)} days past EOL"
        days_color = "#dc2626"
    elif days is not None:
        days_label = f"{days} days remaining"
        days_color = "#d97706" if days <= 90 else "#16a34a"
    else:
        days_label = lifecycle
        days_color = sev_color

    # Recommended action
    if alert_type == "ALREADY_EOL":
        action = "This resource has passed its End of Life date. Upgrade immediately to avoid security vulnerabilities."
    elif alert_type == "DEPRECATED_RESOURCE":
        action = "This resource has been deprecated. Plan an immediate upgrade to a supported version."
    elif alert_type == "UPCOMING_EOL_CRITICAL":
        action = f"Upgrade within {days or '?'} days before this resource reaches End of Life."
    else:
        action = f"Schedule an upgrade — this resource approaches End of Life in {days or '?'} days."

    dashboard_link = f"{APP_URL}/alerts" if APP_URL else "#"

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AWS EOL Alert — {workspace_name}</title>
</head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;
                    border:1px solid #e2e8f0;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.07);">

        <!-- Header -->
        <tr>
          <td style="background:#0f172a;padding:24px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td>
                  <p style="margin:0;font-size:18px;font-weight:800;color:#ffffff;letter-spacing:-0.02em;">
                    AWS EOL Monitor
                  </p>
                  <p style="margin:4px 0 0;font-size:12px;color:#94a3b8;">End of Life Alert Notification</p>
                </td>
                <td align="right">
                  <span style="display:inline-block;background:{sev_bg};color:{sev_color};
                               font-size:11px;font-weight:800;padding:4px 10px;border-radius:20px;
                               text-transform:uppercase;letter-spacing:.05em;">{severity}</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Severity banner -->
        <tr>
          <td style="background:{sev_bg};border-bottom:3px solid {sev_color};padding:16px 32px;">
            <p style="margin:0;font-size:14px;font-weight:700;color:{sev_color};">
              &#9888; {type_label}
            </p>
            <p style="margin:4px 0 0;font-size:13px;color:{sev_color};opacity:.85;">{action}</p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:28px 32px;">

            <!-- Workspace + Account -->
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
              <tr>
                <td width="50%" style="padding-right:8px;">
                  <p style="margin:0;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#94a3b8;font-weight:600;">Workspace</p>
                  <p style="margin:2px 0 0;font-size:14px;font-weight:600;color:#1e293b;">{workspace_name}</p>
                </td>
                <td width="50%">
                  <p style="margin:0;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#94a3b8;font-weight:600;">AWS Account</p>
                  <p style="margin:2px 0 0;font-size:14px;font-weight:600;color:#1e293b;font-family:monospace;">{account_id}</p>
                </td>
              </tr>
            </table>

            <!-- Resource details table -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;margin-bottom:20px;">
              <tr style="background:#f8fafc;">
                <td colspan="2" style="padding:10px 16px;border-bottom:1px solid #e2e8f0;">
                  <p style="margin:0;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#64748b;font-weight:700;">Resource Details</p>
                </td>
              </tr>
              {_detail_row("Resource Name", resource_name)}
              {_detail_row("Service", service)}
              {_detail_row("Region", region)}
              {_detail_row("Current Version", f'<span style="font-family:monospace;">{version}</span>')}
              {_detail_row("EOL Date", eol_date)}
              {_detail_row("Days Remaining", f'<span style="color:{days_color};font-weight:700;">{days_label}</span>')}
              {_detail_row("Severity", f'<span style="color:{sev_color};font-weight:700;">{severity}</span>')}
            </table>

            <!-- CTA Button -->
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
              <tr>
                <td align="center">
                  <a href="{dashboard_link}"
                     style="display:inline-block;background:#6366f1;color:#ffffff;text-decoration:none;
                            font-size:14px;font-weight:700;padding:12px 28px;border-radius:10px;
                            letter-spacing:.01em;">
                    View in Dashboard &rarr;
                  </a>
                </td>
              </tr>
            </table>

          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:16px 32px;">
            <p style="margin:0;font-size:11px;color:#94a3b8;text-align:center;">
              You are receiving this alert because you subscribed to EOL notifications for workspace
              <strong>{workspace_name}</strong>.<br/>
              To unsubscribe, visit your workspace <a href="{APP_URL}/settings" style="color:#6366f1;">notification settings</a>.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text_body = (
        f"AWS EOL Monitor — {type_label}\n"
        f"{'=' * 50}\n\n"
        f"Severity:         {severity}\n"
        f"Workspace:        {workspace_name}\n"
        f"AWS Account:      {account_id}\n\n"
        f"Resource Name:    {resource_name}\n"
        f"Service:          {service}\n"
        f"Region:           {region}\n"
        f"Current Version:  {version}\n"
        f"EOL Date:         {eol_date}\n"
        f"Days Remaining:   {days_label}\n\n"
        f"RECOMMENDED ACTION:\n{action}\n\n"
        f"View in Dashboard: {dashboard_link}\n\n"
        f"---\n"
        f"You are subscribed to EOL notifications for workspace {workspace_name}.\n"
        f"To unsubscribe, visit your notification settings: {APP_URL}/settings\n"
    )

    return subject, html_body, text_body


def _detail_row(label: str, value: str) -> str:
    return (
        f"<tr>"
        f"<td style='padding:10px 16px;border-bottom:1px solid #f1f5f9;width:40%;'>"
        f"<p style='margin:0;font-size:12px;color:#64748b;font-weight:600;'>{label}</p></td>"
        f"<td style='padding:10px 16px;border-bottom:1px solid #f1f5f9;'>"
        f"<p style='margin:0;font-size:13px;color:#1e293b;'>{value}</p></td>"
        f"</tr>"
    )


# ── Dispatch logic ────────────────────────────────────────────────────────────

def evaluate_and_dispatch(workspace_id: str,
                           workspace_name: str = "",
                           dry_run: bool = False) -> dict:
    """
    Main entry point.

    Loads active alerts for a workspace, filters by severity, deduplicates,
    then publishes via SNS to VERIFIED subscribers.

    Returns a summary dict: {dispatched, skipped_dedup, skipped_no_subs, errors}.
    """
    from storage import get_storage
    from sns_subscriptions import should_alert, classify_alert_type, make_notification_history

    storage = get_storage()

    # Load VERIFIED subscriptions for this workspace
    subs = [s for s in storage.get_sns_subscriptions(workspace_id)
            if s.get("status") == "VERIFIED"]

    if not subs:
        logger.info("SNS dispatch workspace=%s — no verified subscribers, skipping", workspace_id)
        return {"dispatched": 0, "skipped_dedup": 0, "skipped_no_subs": 1, "errors": 0}

    topic_arn = subs[0].get("topic_arn", "")
    if not topic_arn:
        logger.warning("SNS dispatch workspace=%s — no topic_arn on subscription", workspace_id)
        return {"dispatched": 0, "skipped_dedup": 0, "skipped_no_subs": 1, "errors": 0}

    # Load active alerts
    alerts = storage.get_alerts(workspace_id, status="ACTIVE")
    if not alerts:
        logger.info("SNS dispatch workspace=%s — no active alerts", workspace_id)
        return {"dispatched": 0, "skipped_dedup": 0, "skipped_no_subs": 0, "errors": 0}

    dispatched = skipped_dedup = errors = 0

    for alert in alerts:
        # Convert alert dict to resource-like dict for compatibility
        resource = {
            "resource_id":   alert.get("resourceId") or alert.get("resource_id") or "",
            "resource_name": alert.get("resourceName") or alert.get("resource_name") or "",
            "service_type":  alert.get("service") or alert.get("service_type") or "",
            "version":       alert.get("version") or "",
            "eol_date":      alert.get("eolDate") or alert.get("eol_date") or "",
            "severity":      alert.get("severity") or "",
            "region":        alert.get("region") or "",
            "account_id":    alert.get("accountId") or alert.get("account_id") or "",
            "lifecycleStatus": alert.get("lifecycleStatus") or "",
            "days_to_eol":   alert.get("daysToEol") or alert.get("days_to_eol"),
        }

        if not should_alert(resource):
            continue

        resource_id = resource["resource_id"]
        severity    = resource["severity"]

        # Dedup check
        if storage.is_duplicate_sns_alert(workspace_id, resource_id, severity, COOLDOWN_HOURS):
            logger.debug("Cooldown active — skipping resource=%s severity=%s", resource_id, severity)
            skipped_dedup += 1
            continue

        alert_type = classify_alert_type(resource)
        subject, html_body, text_body = build_eol_alert_html(
            resource, workspace_name or workspace_id, alert_type
        )

        if dry_run:
            logger.info("[DRY RUN] Would publish alert for %s (%s)", resource_id, severity)
            dispatched += 1
            continue

        try:
            import sns_service
            message_id = sns_service.publish_alert(topic_arn, subject, html_body, text_body)

            # Record history
            record = make_notification_history(
                workspace_id, resource, "all_subscribers", "SENT", message_id
            )
            storage.save_sns_notification_history(record)
            dispatched += 1
            logger.info("SNS alert dispatched resource=%s severity=%s msgId=%s",
                        resource_id, severity, message_id)

        except Exception as exc:
            logger.error("SNS publish failed resource=%s: %s", resource_id, exc)
            # Record failure
            from sns_subscriptions import make_notification_history as _mnh
            record = _mnh(workspace_id, resource, "all_subscribers", "FAILED")
            try:
                storage.save_sns_notification_history(record)
            except Exception:
                pass
            errors += 1

    logger.info("SNS dispatch complete workspace=%s dispatched=%d dedup=%d errors=%d",
                workspace_id, dispatched, skipped_dedup, errors)
    return {
        "dispatched":     dispatched,
        "skipped_dedup":  skipped_dedup,
        "skipped_no_subs": 0,
        "errors":         errors,
    }


def send_test_alert(workspace_id: str, workspace_name: str, topic_arn: str) -> dict:
    """Send a test email via SNS to confirm delivery is working."""
    import sns_service

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"[TEST] AWS EOL Monitor Alert — {workspace_name}"

    html_body = f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,sans-serif;color:#1e293b;padding:24px;margin:0;background:#f8fafc;">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:16px;border:1px solid #e2e8f0;overflow:hidden;">
  <div style="background:#0f172a;padding:24px 32px;">
    <p style="margin:0;font-size:18px;font-weight:800;color:#fff;">AWS EOL Monitor</p>
    <p style="margin:4px 0 0;font-size:12px;color:#94a3b8;">Test Notification</p>
  </div>
  <div style="padding:28px 32px;">
    <div style="background:#f0fdf4;border-radius:12px;padding:20px;margin-bottom:20px;">
      <p style="margin:0;color:#16a34a;font-weight:800;font-size:16px;">&#10003; Email notifications are working!</p>
      <p style="margin:8px 0 0;color:#15803d;font-size:13px;">
        Your workspace <strong>{workspace_name}</strong> is configured to receive EOL alerts via AWS SNS.
      </p>
    </div>
    <p style="color:#64748b;font-size:13px;">Sent at: {now}</p>
    <p style="color:#64748b;font-size:13px;">
      You will receive alerts whenever a HIGH or MEDIUM severity EOL event is detected in your AWS accounts.
    </p>
    <a href="{APP_URL}/alerts" style="display:inline-block;background:#6366f1;color:#fff;text-decoration:none;
       font-size:14px;font-weight:700;padding:12px 24px;border-radius:10px;margin-top:12px;">
      View Alerts Dashboard &rarr;
    </a>
  </div>
  <div style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:16px 32px;">
    <p style="margin:0;font-size:11px;color:#94a3b8;text-align:center;">
      Workspace: <strong>{workspace_name}</strong> &bull; AWS EOL Monitor
    </p>
  </div>
</div>
</body></html>"""

    text_body = (
        f"AWS EOL Monitor — Test Notification\n"
        f"Workspace: {workspace_name}\n"
        f"Sent at: {now}\n\n"
        f"Email notifications are working correctly.\n"
        f"You will receive alerts for HIGH and MEDIUM severity EOL events.\n\n"
        f"View Alerts: {APP_URL}/alerts\n"
    )

    msg_id = sns_service.publish_alert(topic_arn, subject, html_body, text_body)
    return {"success": True, "messageId": msg_id}
