"""
Notification delivery for AWS EOL Monitor.

Supports:
  - AWS SES (default email provider)
  - SMTP (fallback email provider)
  - Slack incoming webhooks

Env vars:
  NOTIFICATIONS_EMAIL_PROVIDER  ses | smtp  (default: ses)
  NOTIFICATIONS_FROM_EMAIL      Sender address (required for email)
  AWS_REGION                    Used for SES client
  SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL
  APP_URL                       Dashboard link included in notifications
"""
import json
import logging
import os
import secrets
import urllib.request
import urllib.error
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

EMAIL_PROVIDER = os.environ.get("NOTIFICATIONS_EMAIL_PROVIDER", "ses").lower()
FROM_EMAIL     = os.environ.get("NOTIFICATIONS_FROM_EMAIL", "")
SMTP_HOST      = os.environ.get("SMTP_HOST", "")
SMTP_PORT      = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME  = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD  = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM      = os.environ.get("SMTP_FROM_EMAIL", "")
APP_URL        = os.environ.get("APP_URL", "").rstrip("/")


def is_email_configured() -> bool:
    if EMAIL_PROVIDER == "ses":
        return bool(FROM_EMAIL)
    if EMAIL_PROVIDER == "smtp":
        return bool(SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD and (SMTP_FROM or FROM_EMAIL))
    return False


def is_slack_configured(webhook_url: str) -> bool:
    return bool(webhook_url and webhook_url.startswith("https://hooks.slack.com/"))


# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(recipients: list, subject: str, html_body: str, text_body: str) -> dict:
    """Returns {"success": True} or {"success": False, "error": "..."}"""
    if not recipients:
        return {"success": False, "error": "No recipients"}
    if EMAIL_PROVIDER == "smtp":
        return _send_smtp(recipients, subject, html_body, text_body)
    return _send_ses(recipients, subject, html_body, text_body)


def _send_ses(recipients: list, subject: str, html_body: str, text_body: str) -> dict:
    if not FROM_EMAIL:
        return {"success": False, "error": "NOTIFICATIONS_FROM_EMAIL not configured"}
    try:
        import boto3
        aws_region = os.environ.get("AWS_REGION", "us-east-1")
        ses = boto3.client("ses", region_name=aws_region)
        ses.send_email(
            Source=FROM_EMAIL,
            Destination={"ToAddresses": recipients},
            Message={
                "Subject": {"Data": subject},
                "Body": {
                    "Html": {"Data": html_body},
                    "Text": {"Data": text_body},
                },
            },
        )
        return {"success": True}
    except Exception as exc:
        logger.error("SES send failed: %s", exc)
        return {"success": False, "error": "Email delivery failed"}


def _send_smtp(recipients: list, subject: str, html_body: str, text_body: str) -> dict:
    from_addr = SMTP_FROM or FROM_EMAIL
    if not (SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD and from_addr):
        return {"success": False, "error": "SMTP not fully configured"}
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = from_addr
        msg["To"]      = ", ".join(recipients)
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(from_addr, recipients, msg.as_string())
        return {"success": True}
    except Exception as exc:
        logger.error("SMTP send failed: %s", exc)
        return {"success": False, "error": "Email delivery failed"}


# ── Slack ─────────────────────────────────────────────────────────────────────

def send_slack(webhook_url: str, payload: dict) -> dict:
    """POST JSON payload to a Slack incoming webhook."""
    if not webhook_url or not webhook_url.startswith("https://hooks.slack.com/"):
        return {"success": False, "error": "Invalid Slack webhook URL"}
    try:
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode()
            if body.strip().lower() != "ok":
                return {"success": False, "error": f"Slack returned: {body[:200]}"}
        return {"success": True}
    except urllib.error.HTTPError as exc:
        logger.error("Slack webhook HTTP error %s", exc.code)
        return {"success": False, "error": f"Slack HTTP {exc.code}"}
    except Exception as exc:
        logger.error("Slack send failed: %s", exc)
        return {"success": False, "error": "Slack delivery failed"}


# ── Payload builders ──────────────────────────────────────────────────────────

def _top_alerts(alerts: list, n: int = 5) -> list:
    priority = {"EOL": 0, "EXPIRING_SOON": 1, "EXTENDED_SUPPORT": 2}
    return sorted(alerts, key=lambda a: priority.get(a.get("severity", ""), 9))[:n]


def build_slack_scan_summary(ws_name: str, scan_id: str, account_name: str,
                              summary: dict, alerts: list) -> dict:
    eol      = summary.get("eol", 0)
    expiring = summary.get("expiringSoon", 0)
    total    = summary.get("total", 0)

    resource_lines = []
    for a in _top_alerts(alerts):
        emoji = ":red_circle:" if a.get("severity") == "EOL" else ":large_yellow_circle:"
        resource_lines.append(
            f"{emoji} *{a.get('resourceName', a.get('resourceId', '?'))}* "
            f"— {a.get('service', '?')} {a.get('version', '?')}"
        )

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "AWS EOL Monitor — EOL Risk Summary", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Workspace*\n{ws_name}"},
                {"type": "mrkdwn", "text": f"*Account*\n{account_name}"},
                {"type": "mrkdwn", "text": f"*EOL*\n:red_circle: {eol}"},
                {"type": "mrkdwn", "text": f"*Expiring Soon*\n:large_yellow_circle: {expiring}"},
                {"type": "mrkdwn", "text": f"*Total Scanned*\n{total}"},
                {"type": "mrkdwn", "text": f"*Scan ID*\n`{scan_id}`"},
            ],
        },
    ]
    if resource_lines:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Top affected resources:*\n" + "\n".join(resource_lines)},
        })
    if APP_URL:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"<{APP_URL}/alerts|View full alert list →>"},
        })
    return {"blocks": blocks}


def build_slack_test(ws_name: str) -> dict:
    return {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        ":white_check_mark: *AWS EOL Monitor — Test Notification*\n"
                        f"Workspace: *{ws_name}*\n"
                        "Slack notifications are configured and working correctly."
                    ),
                },
            }
        ]
    }


def build_slack_weekly_digest(ws_name: str, alerts: list) -> dict:
    eol      = sum(1 for a in alerts if a.get("severity") == "EOL")
    expiring = sum(1 for a in alerts if a.get("severity") == "EXPIRING_SOON")
    summary  = {"eol": eol, "expiringSoon": expiring, "total": len(alerts)}
    payload  = build_slack_scan_summary(ws_name, "weekly-digest", "All Accounts", summary, alerts)
    payload["blocks"][0]["text"]["text"] = "AWS EOL Monitor — Weekly Digest"
    return payload


def build_email_scan_summary(ws_name: str, scan_id: str, account_name: str,
                              summary: dict, alerts: list) -> tuple:
    """Returns (subject, html_body, text_body)."""
    eol      = summary.get("eol", 0)
    expiring = summary.get("expiringSoon", 0)
    total    = summary.get("total", 0)
    top      = _top_alerts(alerts)

    noun     = "resource" if eol == 1 else "resources"
    subject  = f"AWS EOL Monitor: {eol} EOL {noun} detected in {ws_name}"

    rows_html = ""
    rows_text = ""
    for a in top:
        status = a.get("severity", "?")
        color  = "#dc2626" if status == "EOL" else "#d97706"
        rows_html += (
            f"<tr>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #f1f5f9'>"
            f"{a.get('resourceName', a.get('resourceId', '?'))}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #f1f5f9'>"
            f"{a.get('service', '?')}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #f1f5f9;font-family:monospace'>"
            f"{a.get('version', '?')}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #f1f5f9;"
            f"color:{color};font-weight:600'>{status}</td>"
            f"</tr>"
        )
        rows_text += (
            f"  - {a.get('resourceName', '?')} "
            f"({a.get('service', '?')} {a.get('version', '?')}) — {status}\n"
        )

    table_html = ""
    if rows_html:
        table_html = (
            "<h2 style='font-size:14px;font-weight:700;margin:20px 0 8px'>"
            "Top affected resources</h2>"
            "<table style='width:100%;border-collapse:collapse;background:white;"
            "border-radius:12px;overflow:hidden'>"
            "<thead><tr style='background:#f8fafc'>"
            "<th style='padding:8px 12px;text-align:left;font-size:11px;color:#94a3b8;"
            "text-transform:uppercase'>Resource</th>"
            "<th style='padding:8px 12px;text-align:left;font-size:11px;color:#94a3b8;"
            "text-transform:uppercase'>Service</th>"
            "<th style='padding:8px 12px;text-align:left;font-size:11px;color:#94a3b8;"
            "text-transform:uppercase'>Version</th>"
            "<th style='padding:8px 12px;text-align:left;font-size:11px;color:#94a3b8;"
            "text-transform:uppercase'>Status</th>"
            "</tr></thead>"
            f"<tbody>{rows_html}</tbody></table>"
        )

    dashboard_link = (
        f'<p style="margin:24px 0 8px">'
        f'<a href="{APP_URL}/alerts" style="color:#6366f1;font-weight:600">'
        f'Open Alerts →</a></p>'
    ) if APP_URL else ""

    html_body = f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
color:#1e293b;background:#f8fafc;padding:24px;margin:0">
<div style="max-width:600px;margin:0 auto">
  <h1 style="font-size:20px;font-weight:800;margin:0 0 4px">AWS EOL Monitor</h1>
  <p style="color:#64748b;margin:0 0 20px">
    EOL Risk Summary for <strong>{ws_name}</strong>
  </p>
  <div style="display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap">
    <div style="flex:1;min-width:100px;background:#fef2f2;border-radius:12px;padding:16px">
      <p style="font-size:28px;font-weight:800;color:#dc2626;margin:0">{eol}</p>
      <p style="font-size:11px;color:#dc2626;text-transform:uppercase;font-weight:600;
         margin:4px 0 0">EOL</p>
    </div>
    <div style="flex:1;min-width:100px;background:#fffbeb;border-radius:12px;padding:16px">
      <p style="font-size:28px;font-weight:800;color:#d97706;margin:0">{expiring}</p>
      <p style="font-size:11px;color:#d97706;text-transform:uppercase;font-weight:600;
         margin:4px 0 0">Expiring Soon</p>
    </div>
    <div style="flex:1;min-width:100px;background:#f0fdf4;border-radius:12px;padding:16px">
      <p style="font-size:28px;font-weight:800;color:#16a34a;margin:0">{total}</p>
      <p style="font-size:11px;color:#16a34a;text-transform:uppercase;font-weight:600;
         margin:4px 0 0">Total Scanned</p>
    </div>
  </div>
  {table_html}
  {dashboard_link}
  <p style="font-size:11px;color:#94a3b8;border-top:1px solid #e2e8f0;
     padding-top:16px;margin-top:24px">
    You are receiving this because scan notifications are enabled for workspace
    <strong>{ws_name}</strong>.
    Account: {account_name} · Scan ID: <code>{scan_id}</code>
  </p>
</div></body></html>"""

    text_body = (
        f"AWS EOL Monitor — EOL Risk Summary\n"
        f"Workspace: {ws_name} | Account: {account_name} | Scan ID: {scan_id}\n\n"
        f"EOL: {eol}  |  Expiring Soon: {expiring}  |  Total Scanned: {total}\n\n"
        f"Top affected resources:\n{rows_text or '  None'}\n"
        + (f"Open Alerts: {APP_URL}/alerts\n" if APP_URL else "")
        + f"\n---\nNotifications enabled for workspace {ws_name}."
    )
    return subject, html_body, text_body


def build_email_test(ws_name: str) -> tuple:
    subject = f"AWS EOL Monitor — Test Notification for {ws_name}"
    html_body = f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,sans-serif;color:#1e293b;padding:24px;margin:0">
<div style="max-width:600px;margin:0 auto">
  <h1 style="font-size:20px;font-weight:800">AWS EOL Monitor — Test Notification</h1>
  <p style="color:#64748b">This is a test notification for workspace
    <strong>{ws_name}</strong>.</p>
  <div style="background:#f0fdf4;border-radius:12px;padding:16px;margin-top:16px">
    <p style="color:#16a34a;font-weight:700;margin:0">
      &#10003; Email notifications are configured and working.
    </p>
  </div>
</div></body></html>"""
    text_body = (
        f"AWS EOL Monitor — Test Notification\n"
        f"Workspace: {ws_name}\n"
        f"Email notifications are configured and working correctly."
    )
    return subject, html_body, text_body


def build_email_weekly_digest(ws_name: str, alerts: list) -> tuple:
    eol      = sum(1 for a in alerts if a.get("severity") == "EOL")
    expiring = sum(1 for a in alerts if a.get("severity") == "EXPIRING_SOON")
    summary  = {"eol": eol, "expiringSoon": expiring, "total": len(alerts)}
    _, html_body, text_body = build_email_scan_summary(
        ws_name, "weekly-digest", "All Accounts", summary, alerts
    )
    noun    = "resource" if eol == 1 else "resources"
    subject = f"AWS EOL Weekly Digest: {ws_name} — {eol} EOL {noun}, {expiring} expiring"
    return subject, html_body, text_body


# ── Delivery log helper ───────────────────────────────────────────────────────

def make_delivery_log(ws_id: str, notif_type: str, channel: str,
                      status: str, recipient: str = "", scan_id: str = None,
                      alert_count: int = 0, error: str = None) -> dict:
    """
    notif_type: SCAN_COMPLETE | WEEKLY_DIGEST | TEST
    channel:    EMAIL | SLACK
    status:     SUCCESS | FAILED | SKIPPED
    """
    return {
        "id":           f"notif_{secrets.token_hex(8)}",
        "workspaceId":  ws_id,
        "type":         notif_type,
        "channel":      channel,
        "status":       status,
        "recipient":    recipient,
        "scanId":       scan_id,
        "alertCount":   alert_count,
        "errorCode":    "NOTIFICATION_SEND_FAILED" if status == "FAILED" else None,
        "errorMessage": error,
        "createdAt":    datetime.now(timezone.utc).isoformat(),
    }
