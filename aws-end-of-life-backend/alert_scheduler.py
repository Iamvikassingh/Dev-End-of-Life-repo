"""
AWS EOL Monitor — Background Alert Scheduler

Runs evaluate_and_dispatch for all workspaces on a configurable interval.
Launched as a daemon thread from run-local-backend.py at startup.

For production:
  Use an EventBridge rule: rate(12 hours) → Lambda or
  POST /admin/alerts/dispatch-all (with admin token)

Env vars:
  ALERT_SCHEDULE_HOURS   Interval between dispatch runs (default: 12)
  SNS_ALERTS_ENABLED     Set to "true" to activate (default: false for safety)
"""
import logging
import os
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SCHEDULE_HOURS   = float(os.environ.get("ALERT_SCHEDULE_HOURS", "12"))
ALERTS_ENABLED   = os.environ.get("SNS_ALERTS_ENABLED", "false").lower() in ("1", "true", "yes")
SCHEDULE_SECONDS = SCHEDULE_HOURS * 3600

_scheduler_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _run_dispatch_cycle():
    """Dispatch alerts for all active workspaces."""
    logger.info("SNS scheduler — starting dispatch cycle")
    try:
        from storage import get_storage
        import sns_alert_handler

        storage    = get_storage()
        workspaces = storage.get_workspaces()

        if not workspaces:
            logger.info("SNS scheduler — no workspaces found")
            return

        total_dispatched = 0
        for ws in workspaces:
            ws_id   = ws.get("id") or ws.get("workspaceId") or ""
            ws_name = ws.get("name") or ws_id
            if not ws_id:
                continue
            try:
                result = sns_alert_handler.evaluate_and_dispatch(ws_id, ws_name)
                total_dispatched += result.get("dispatched", 0)
                logger.info(
                    "SNS scheduler ws=%s dispatched=%d dedup=%d errors=%d",
                    ws_id, result.get("dispatched", 0),
                    result.get("skipped_dedup", 0), result.get("errors", 0)
                )
            except Exception as exc:
                logger.error("SNS scheduler error for workspace %s: %s", ws_id, exc)

        logger.info("SNS scheduler — cycle complete, total dispatched=%d", total_dispatched)

    except Exception as exc:
        logger.error("SNS scheduler dispatch cycle failed: %s", exc)


def _scheduler_loop():
    logger.info(
        "SNS alert scheduler started — interval=%.1f hours (%.0f seconds)",
        SCHEDULE_HOURS, SCHEDULE_SECONDS
    )
    while not _stop_event.is_set():
        _run_dispatch_cycle()
        # Wait for the interval OR until stop is requested
        _stop_event.wait(SCHEDULE_SECONDS)
    logger.info("SNS alert scheduler stopped")


def start_scheduler():
    """
    Start the background scheduler thread.
    Safe to call multiple times — only one thread will run.
    No-op if SNS_ALERTS_ENABLED is not 'true'.
    """
    global _scheduler_thread

    if not ALERTS_ENABLED:
        logger.info(
            "SNS alert scheduler disabled (SNS_ALERTS_ENABLED != true). "
            "Set SNS_ALERTS_ENABLED=true to enable automatic alert dispatch."
        )
        return

    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        logger.info("SNS alert scheduler already running")
        return

    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        name="sns-alert-scheduler",
        daemon=True,
    )
    _scheduler_thread.start()
    logger.info("SNS alert scheduler thread started (daemon)")


def stop_scheduler():
    """Signal the scheduler loop to stop gracefully."""
    _stop_event.set()
    logger.info("SNS alert scheduler stop requested")


def trigger_now():
    """Run a single dispatch cycle immediately (blocking, for manual triggers)."""
    _run_dispatch_cycle()
