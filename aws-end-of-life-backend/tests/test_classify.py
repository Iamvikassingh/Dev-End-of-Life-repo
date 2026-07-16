"""Unit tests for EOL status classification."""
import sys
import os
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eol_collector import classify_status


def future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def past(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def test_eol_when_past():
    data = {"eolFrom": past(10), "isEoes": False}
    status, eol_date, days = classify_status(data)
    assert status == "EOL"
    assert days < 0


def test_expiring_soon_within_warn():
    data = {"eolFrom": future(30), "isEoes": False}
    status, _, days = classify_status(data)
    assert status == "EXPIRING_SOON"
    assert 0 <= days <= 180


def test_supported_beyond_warn():
    data = {"eolFrom": future(365), "isEoes": False}
    status, _, days = classify_status(data)
    assert status == "SUPPORTED"
    assert days > 180


def test_extended_support():
    data = {"eolFrom": future(400), "isEoes": True}
    status, _, _ = classify_status(data)
    assert status == "EXTENDED_SUPPORT"


def test_unknown_on_none():
    status, _, _ = classify_status(None)
    assert status == "UNKNOWN"


def test_no_eol_date_returns_supported():
    status, eol_date, days = classify_status({"isMaintained": True})
    assert status == "SUPPORTED"
    assert eol_date is None


def test_eol_date_preserved():
    eol = future(50)
    _, eol_date, _ = classify_status({"eolFrom": eol})
    assert eol_date == eol


def test_days_boundary_zero():
    data = {"eolFrom": date.today().isoformat(), "isEoes": False}
    status, _, days = classify_status(data)
    assert status == "EXPIRING_SOON"
    assert days == 0


def test_extended_support_with_past_standard_support():
    """Standard support ended (past) but extended support is still running (future).
    This is the real AWS Extended Support scenario: e.g. RDS MySQL 5.7.
    Must return EXTENDED_SUPPORT, NOT EOL.
    """
    data = {
        "support": past(300),    # standard support ended 300 days ago
        "eolFrom": future(400),  # extended support ends 400 days from now
        "isEoes":  True,
    }
    status, eol_date, days = classify_status(data)
    assert status == "EXTENDED_SUPPORT", f"Expected EXTENDED_SUPPORT, got {status}"
    assert days > 0
    assert eol_date == future(400)


def test_extended_support_ending_soon():
    """Extended support ends within WARN_DAYS → EXPIRING_SOON."""
    data = {
        "support": past(400),   # standard support long ended
        "eolFrom": future(60),  # extended support ending in 60 days
        "isEoes":  True,
    }
    status, _, days = classify_status(data)
    assert status == "EXPIRING_SOON"
    assert 0 < days <= 180


def test_extended_support_fully_ended():
    """Both standard and extended support are past → EOL."""
    data = {
        "support": past(600),
        "eolFrom": past(100),
        "isEoes":  True,
    }
    status, _, days = classify_status(data)
    assert status == "EOL"
    assert days < 0
