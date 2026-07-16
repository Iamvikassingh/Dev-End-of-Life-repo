"""
AWS EOL Monitor — DynamoDB Streams Alert Notifier
Processes new/updated records and sends deduplicated SNS alerts.
"""
import json
import logging
import os
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SNS_TOPIC_ARN   = os.environ.get("SNS_TOPIC_ARN", "")
DEDUP_TABLE     = os.environ.get("DEDUP_TABLE", "aws-eol-alert-dedup")
DEDUP_HOURS     = int(os.environ.get("DEDUP_HOURS", "24"))

ALERT_STATUSES = {"EOL", "EXPIRING_SOON"}

TEMPLATES = {
    "EOL": (
        "[CRITICAL] AWS Resource Past End-of-Life",
        "🚨 CRITICAL — Resource is past End-of-Life and may no longer receive security patches.\n\n"
        "Resource:  {resource_id}\n"
        "Service:   {service_type}\n"
        "Region:    {region}\n"
        "Version:   {version}\n"
        "EOL Date:  {eol_date}\n"
        "Days Past: {days_past}\n\n"
        "ACTION REQUIRED: Upgrade immediately.\n"
    ),
    "EXPIRING_SOON": (
        "[WARNING] AWS Resource Approaching End-of-Life",
        "⚠️  WARNING — Resource will reach End-of-Life soon.\n\n"
        "Resource:  {resource_id}\n"
        "Service:   {service_type}\n"
        "Region:    {region}\n"
        "Version:   {version}\n"
        "EOL Date:  {eol_date}\n"
        "Days Left: {days_to_eol}\n\n"
        "ACTION REQUIRED: Plan upgrade within the next {days_to_eol} days.\n"
    ),
}


def is_duplicate(resource_id: str, status: str) -> bool:
    """Return True if an alert was already sent for this resource+status within DEDUP_HOURS."""
    if not DEDUP_TABLE:
        return False
    table = boto3.resource("dynamodb").Table(DEDUP_TABLE)
    key = f"{resource_id}#{status}"
    try:
        item = table.get_item(Key={"alert_key": key}).get("Item")
        if item:
            sent_at = item.get("sent_at", "")
            if sent_at:
                cutoff = datetime.utcnow() - timedelta(hours=DEDUP_HOURS)
                if datetime.fromisoformat(sent_at) > cutoff:
                    return True
    except ClientError as e:
        logger.warning("Dedup check failed — allowing alert through: %s", e)
    return False


def mark_sent(resource_id: str, status: str):
    if not DEDUP_TABLE:
        return
    table = boto3.resource("dynamodb").Table(DEDUP_TABLE)
    key = f"{resource_id}#{status}"
    ttl = int((datetime.utcnow() + timedelta(hours=DEDUP_HOURS * 2)).timestamp())
    try:
        table.put_item(Item={"alert_key": key, "sent_at": datetime.utcnow().isoformat(), "ttl": ttl})
    except ClientError as e:
        logger.warning("Could not mark alert sent: %s", e)


def send_sns(subject: str, message: str):
    if not SNS_TOPIC_ARN:
        logger.warning("SNS_TOPIC_ARN not set — skipping alert")
        return
    try:
        boto3.client("sns").publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject[:100],
            Message=message,
        )
    except ClientError as e:
        logger.error("SNS publish failed: %s", e)


def process_record(record: dict):
    if record.get("eventName") not in ("INSERT", "MODIFY"):
        return

    new_image = record.get("dynamodb", {}).get("NewImage", {})
    if not new_image:
        return

    def attr(key: str) -> str:
        v = new_image.get(key, {})
        return v.get("S") or str(v.get("N", "")) or ""

    resource_id  = attr("resource_id")
    service_type = attr("service_type")
    eol_status   = attr("eol_status")
    region       = attr("region")
    version      = attr("version")
    eol_date     = attr("eol_date")
    days_raw     = attr("days_to_eol")

    if eol_status not in ALERT_STATUSES:
        return

    if is_duplicate(resource_id, eol_status):
        logger.info("Duplicate alert suppressed for %s", resource_id)
        return

    days_to_eol = int(days_raw) if days_raw.lstrip("-").isdigit() else 0
    days_past   = abs(days_to_eol) if days_to_eol < 0 else 0

    subject_tpl, body_tpl = TEMPLATES[eol_status]
    message = body_tpl.format(
        resource_id=resource_id,
        service_type=service_type,
        region=region,
        version=version,
        eol_date=eol_date,
        days_to_eol=days_to_eol,
        days_past=days_past,
    )
    send_sns(subject_tpl, message)
    mark_sent(resource_id, eol_status)
    logger.info("Alert sent: %s %s", eol_status, resource_id)


def lambda_handler(event, context):
    records = event.get("Records", [])
    logger.info("Processing %d DynamoDB stream records", len(records))
    for record in records:
        try:
            process_record(record)
        except Exception as exc:
            logger.error("Failed to process record: %s", exc)
    return {"processed": len(records)}
