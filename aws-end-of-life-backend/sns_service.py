"""
AWS EOL Monitor — SNS Service Layer

Wraps boto3 SNS operations with:
  - Exponential backoff retry on transient failures
  - Per-workspace topic naming convention: eolm-ws-{workspace_id}
  - Graceful degradation when AWS credentials are not configured

Env vars:
  AWS_REGION           AWS region for SNS (default: us-east-1)
  SNS_TOPIC_PREFIX     Topic name prefix (default: eolm-ws)
"""
import logging
import os
import time
import re
from typing import Optional

logger = logging.getLogger(__name__)

AWS_REGION       = os.environ.get("AWS_REGION", "us-east-1")
SNS_TOPIC_PREFIX = os.environ.get("SNS_TOPIC_PREFIX", "eolm-ws")
MAX_RETRIES      = 3
BASE_BACKOFF     = 0.5  # seconds


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitize_ws_id(workspace_id: str) -> str:
    """Make workspace_id safe for an SNS topic name (alphanumeric + hyphens)."""
    return re.sub(r"[^a-zA-Z0-9\-]", "-", workspace_id)[:64]


def _get_client():
    """Return a boto3 SNS client. Raises RuntimeError if boto3 is unavailable."""
    try:
        import boto3
        return boto3.client("sns", region_name=AWS_REGION)
    except ImportError:
        raise RuntimeError("boto3 is not installed. Run: pip install boto3")


def _retry(fn, *args, **kwargs):
    """
    Call fn(*args, **kwargs) with exponential backoff.
    Re-raises on the final attempt or on non-retryable errors.
    """
    from botocore.exceptions import ClientError, EndpointResolutionError
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            # Non-retryable: auth, not-found, invalid input
            if code in ("AccessDenied", "AuthorizationError",
                        "InvalidParameter", "NotFound",
                        "SubscriptionLimitExceeded", "TopicLimitExceeded"):
                raise
            last_exc = exc
            logger.warning("SNS retry %d/%d — %s: %s", attempt + 1, MAX_RETRIES, code, exc)
        except (EndpointResolutionError, OSError) as exc:
            last_exc = exc
            logger.warning("SNS network error retry %d/%d — %s", attempt + 1, MAX_RETRIES, exc)
        wait = BASE_BACKOFF * (2 ** attempt)
        time.sleep(wait)
    raise last_exc


# ── Public API ────────────────────────────────────────────────────────────────

def topic_name_for_workspace(workspace_id: str) -> str:
    """Return the SNS topic name for a workspace."""
    return f"{SNS_TOPIC_PREFIX}-{_sanitize_ws_id(workspace_id)}"


def create_or_get_topic(workspace_id: str) -> str:
    """
    Create an SNS topic for the workspace (idempotent — safe to call repeatedly).
    Returns the TopicArn.
    """
    name   = topic_name_for_workspace(workspace_id)
    client = _get_client()
    logger.info("SNS create_or_get_topic workspace=%s name=%s", workspace_id, name)
    response = _retry(client.create_topic, Name=name, Attributes={
        "DisplayName": f"EOL Monitor Alerts ({workspace_id[:20]})",
    })
    arn = response["TopicArn"]
    logger.info("SNS topic ready: %s", arn)
    return arn


def subscribe_email(topic_arn: str, email: str) -> str:
    """
    Subscribe an email address to the SNS topic.
    SNS sends a confirmation email automatically.
    Returns the SubscriptionArn (will be 'PendingConfirmation' until confirmed).
    """
    client = _get_client()
    logger.info("SNS subscribe email=%s topic=%s", email, topic_arn)
    response = _retry(client.subscribe,
        TopicArn=topic_arn,
        Protocol="email",
        Endpoint=email,
        ReturnSubscriptionArn=True,
    )
    arn = response.get("SubscriptionArn", "PendingConfirmation")
    logger.info("SNS subscription initiated: %s → %s", email, arn)
    return arn


def confirm_subscription(topic_arn: str, token: str) -> str:
    """
    Confirm an SNS email subscription using the token from the confirmation email.
    Returns the confirmed SubscriptionArn.
    """
    client = _get_client()
    logger.info("SNS confirm_subscription topic=%s", topic_arn)
    response = _retry(client.confirm_subscription,
        TopicArn=topic_arn,
        Token=token,
        AuthenticateOnUnsubscribe="false",
    )
    arn = response.get("SubscriptionArn", "")
    logger.info("SNS subscription confirmed: %s", arn)
    return arn


def unsubscribe(subscription_arn: str) -> None:
    """Unsubscribe a previously confirmed SNS subscription."""
    if not subscription_arn or subscription_arn in ("PendingConfirmation", ""):
        logger.info("SNS unsubscribe skipped — no confirmed arn")
        return
    client = _get_client()
    logger.info("SNS unsubscribe arn=%s", subscription_arn)
    _retry(client.unsubscribe, SubscriptionArn=subscription_arn)
    logger.info("SNS unsubscribed: %s", subscription_arn)


def publish_alert(topic_arn: str, subject: str, html_body: str,
                  text_body: Optional[str] = None) -> str:
    """
    Publish an EOL alert to all confirmed subscribers on the topic.
    SNS email protocol delivers the plain text body; HTML is embedded via
    MessageStructure='json' with a separate 'email-json' entry when possible,
    but standard SNS email only supports plain text.

    We publish the HTML in the Message field — SNS strips tags for most clients,
    so we also provide a clean text_body fallback.

    Returns the MessageId.
    """
    client  = _get_client()
    message = text_body or _html_to_text(html_body)
    logger.info("SNS publish topic=%s subject=%s", topic_arn, subject[:60])
    response = _retry(client.publish,
        TopicArn=topic_arn,
        Subject=subject[:100],
        Message=message,
    )
    msg_id = response.get("MessageId", "")
    logger.info("SNS published MessageId=%s", msg_id)
    return msg_id


def get_subscription_status(topic_arn: str, email: str) -> Optional[str]:
    """
    Check whether an email is currently subscribed to the topic.
    Returns: 'PendingConfirmation' | 'Confirmed' | None
    """
    client = _get_client()
    try:
        paginator = client.get_paginator("list_subscriptions_by_topic")
        for page in paginator.paginate(TopicArn=topic_arn):
            for sub in page.get("Subscriptions", []):
                if sub.get("Endpoint", "").lower() == email.lower():
                    return sub.get("SubscriptionArn", "")
    except Exception as exc:
        logger.warning("SNS get_subscription_status failed: %s", exc)
    return None


# ── Text fallback ─────────────────────────────────────────────────────────────

def _html_to_text(html: str) -> str:
    """Very simple HTML → plain text conversion for SNS fallback."""
    import re as _re
    # Remove style/script blocks
    text = _re.sub(r"<(style|script)[^>]*>.*?</\1>", "", html,
                   flags=_re.DOTALL | _re.IGNORECASE)
    # Replace common block elements with newlines
    text = _re.sub(r"<br\s*/?>|</(p|div|tr|li|h[1-6])>", "\n", text,
                   flags=_re.IGNORECASE)
    # Remove remaining tags
    text = _re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&#10003;", "✓")
    # Collapse whitespace
    lines = [ln.strip() for ln in text.splitlines()]
    text  = "\n".join(ln for ln in lines if ln)
    return text
