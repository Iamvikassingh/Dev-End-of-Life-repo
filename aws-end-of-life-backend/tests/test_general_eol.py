"""Unit tests for general_eol module."""
import sys
import os
import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import general_eol


# ── Helpers ───────────────────────────────────────────────────────────────────

def future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()

def past(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


# ── _classify ─────────────────────────────────────────────────────────────────

def test_classify_eol():
    status, days = general_eol._classify(past(10), False)
    assert status == "EOL"
    assert days < 0


def test_classify_expiring_soon():
    status, days = general_eol._classify(future(30), False)
    assert status == "EXPIRING_SOON"
    assert 0 <= days <= 180


def test_classify_supported():
    status, days = general_eol._classify(future(365), False)
    assert status == "SUPPORTED"
    assert days > 180


def test_classify_extended_support():
    status, days = general_eol._classify(future(400), True)
    assert status == "EXTENDED_SUPPORT"


def test_classify_no_eol_date():
    status, days = general_eol._classify(None, False)
    assert status == "SUPPORTED"
    assert days is None


def test_classify_invalid_date():
    # Unparseable date strings are treated as "no date" by the unified classifier,
    # which returns SUPPORTED (no deadline found) rather than UNKNOWN.
    status, days = general_eol._classify("not-a-date", False)
    assert status == "SUPPORTED"
    assert days is None


# ── _normalize ────────────────────────────────────────────────────────────────

def test_normalize_basic_eks():
    raw = {"cycle": "1.29", "eolFrom": future(150), "isEoes": False}
    rec = general_eol._normalize("amazon-eks", raw)
    assert rec is not None
    assert rec["service"] == "EKS"
    assert rec["version"] == "1.29"
    assert rec["status"] == "EXPIRING_SOON"
    assert rec["source"] == "endoflife.date"
    assert rec["product_slug"] == "amazon-eks"


def test_normalize_eol_false_means_no_eol():
    # endoflife.date uses False for "no EOL date set"
    raw = {"cycle": "3.12", "eolFrom": False, "isEoes": False}
    rec = general_eol._normalize("aws-lambda", raw)
    assert rec is not None
    assert rec["eolDate"] is None
    assert rec["status"] == "SUPPORTED"


def test_normalize_known_upgrade():
    raw = {"cycle": "python3.8", "eolFrom": past(100), "isEoes": False}
    rec = general_eol._normalize("aws-lambda", raw)
    assert rec is not None
    assert rec["recommendedUpgrade"] == "python3.12"


def test_normalize_missing_cycle_returns_none():
    raw = {"eolFrom": future(100)}   # no cycle field
    rec = general_eol._normalize("amazon-eks", raw)
    assert rec is None


def test_normalize_id_is_slugified():
    raw = {"cycle": "1.29", "eolFrom": future(200), "isEoes": False}
    rec = general_eol._normalize("amazon-eks", raw)
    assert "." not in rec["id"]


# ── compute_summary ───────────────────────────────────────────────────────────

def test_compute_summary_counts():
    records = [
        {"status": "EOL"},
        {"status": "EOL"},
        {"status": "EXPIRING_SOON"},
        {"status": "SUPPORTED"},
        {"status": "EXTENDED_SUPPORT"},
    ]
    summary = general_eol.compute_summary(records)
    assert summary["EOL"] == 2
    assert summary["EXPIRING_SOON"] == 1
    assert summary["SUPPORTED"] == 1
    assert summary["EXTENDED_SUPPORT"] == 1


def test_compute_summary_empty():
    summary = general_eol.compute_summary([])
    assert summary["EOL"] == 0
    assert sum(summary.values()) == 0


# ── filter_records ────────────────────────────────────────────────────────────

def _old_eol(years_ago: int) -> str:
    from datetime import date
    return date.today().replace(year=date.today().year - years_ago).isoformat()

RECORDS = [
    {"service": "Lambda",  "version": "python3.8",   "status": "EOL",           "family": "Python",  "eolDate": _old_eol(4)},   # legacy
    {"service": "Lambda",  "version": "python3.9",   "status": "EOL",           "family": "Python",  "eolDate": _old_eol(1)},   # recent EOL
    {"service": "Lambda",  "version": "nodejs18.x",  "status": "EXPIRING_SOON", "family": "Node.js", "eolDate": future(30)},
    {"service": "EKS",     "version": "1.29",        "status": "EXPIRING_SOON", "family": "EKS",     "eolDate": future(60)},
    {"service": "EKS",     "version": "1.33",        "status": "SUPPORTED",     "family": "EKS",     "eolDate": future(400)},
]

def test_filter_by_service():
    result = general_eol.filter_records(RECORDS, service="EKS", include_legacy=True)
    assert all(r["service"] == "EKS" for r in result)
    assert len(result) == 2


def test_filter_by_status():
    # include_legacy=True to count all EOL records
    result = general_eol.filter_records(RECORDS, status="EOL", include_legacy=True)
    assert all(r["status"] == "EOL" for r in result)
    assert len(result) == 2


def test_filter_by_search():
    result = general_eol.filter_records(RECORDS, search="python", include_legacy=True)
    assert len(result) == 2


def test_filter_combined():
    result = general_eol.filter_records(RECORDS, service="Lambda", status="EXPIRING_SOON", include_legacy=True)
    assert len(result) == 1
    assert result[0]["version"] == "nodejs18.x"


def test_filter_no_match():
    result = general_eol.filter_records(RECORDS, service="DocumentDB")
    assert result == []


def test_filter_empty_returns_non_legacy_by_default():
    # Default (include_legacy=False) should hide the 4-years-ago EOL record
    result = general_eol.filter_records(RECORDS)
    versions = [r["version"] for r in result]
    assert "python3.8" not in versions      # 4 years ago = legacy, hidden
    assert "python3.9" in versions          # 1 year ago = recent, shown
    assert "nodejs18.x" in versions
    assert "1.33" in versions


def test_filter_include_legacy_true_shows_all():
    result = general_eol.filter_records(RECORDS, include_legacy=True)
    versions = [r["version"] for r in result]
    assert "python3.8" in versions          # legacy, now shown
    assert len(result) == len(RECORDS)


def test_is_legacy_old_eol():
    record = {"status": "EOL", "eolDate": _old_eol(4)}
    assert general_eol._is_legacy(record) is True


def test_is_legacy_recent_eol():
    record = {"status": "EOL", "eolDate": _old_eol(1)}
    assert general_eol._is_legacy(record) is False


def test_is_legacy_expiring_soon_never_legacy():
    record = {"status": "EXPIRING_SOON", "eolDate": _old_eol(4)}
    assert general_eol._is_legacy(record) is False


def test_is_legacy_no_eol_date():
    record = {"status": "EOL", "eolDate": None}
    assert general_eol._is_legacy(record) is False


def test_filter_empty_excludes_legacy_by_default():
    # Default (include_legacy=False) hides old retired versions
    result = general_eol.filter_records(RECORDS)
    assert len(result) < len(RECORDS)

def test_filter_include_legacy_returns_all():
    result = general_eol.filter_records(RECORDS, include_legacy=True)
    assert len(result) == len(RECORDS)


# ── get_cached_only ───────────────────────────────────────────────────────────

def test_cached_only_fresh_cache_no_external_call():
    """GET endpoint must never call external API — returns from cache instantly."""
    from datetime import datetime, timedelta
    storage = MagicMock()
    storage.get_general_eol_cache.return_value = {
        "records":      [{"id": "cached"}],
        "refreshed_at": "2026-05-30T00:00:00",
        "expires_at":   (datetime.utcnow() + timedelta(hours=1)).isoformat(),
    }
    result = general_eol.get_cached_only(storage)
    assert result.records == [{"id": "cached"}]
    assert result.is_stale  is False
    assert result.is_empty  is False


def test_cached_only_expired_cache_returns_stale_without_fetch():
    """Expired cache still returns data immediately — marks it as stale."""
    from datetime import datetime, timedelta
    storage = MagicMock()
    storage.get_general_eol_cache.return_value = {
        "records":      [{"id": "old"}],
        "refreshed_at": "2026-05-01T00:00:00",
        "expires_at":   (datetime.utcnow() - timedelta(hours=1)).isoformat(),
    }
    result = general_eol.get_cached_only(storage)
    assert result.records == [{"id": "old"}]
    assert result.is_stale is True
    assert result.is_empty is False
    # No external call made
    storage.save_general_eol_cache.assert_not_called()


def test_cached_only_empty_cache_returns_is_empty():
    """Empty cache returns is_empty=True — frontend shows the Refresh prompt."""
    storage = MagicMock()
    storage.get_general_eol_cache.return_value = None
    result = general_eol.get_cached_only(storage)
    assert result.is_empty  is True
    assert result.records   == []
    storage.save_general_eol_cache.assert_not_called()


def test_cached_only_cache_with_empty_records_is_empty():
    storage = MagicMock()
    storage.get_general_eol_cache.return_value = {
        "records": [], "refreshed_at": "", "expires_at": ""
    }
    result = general_eol.get_cached_only(storage)
    assert result.is_empty is True


# ── refresh() — POST endpoint, may call external API ─────────────────────────

@patch("general_eol.fetch_all", return_value=[{"id": "fresh"}])
def test_refresh_fetches_and_saves(mock_fetch):
    storage = MagicMock()
    records, _ = general_eol.refresh(storage)
    assert records == [{"id": "fresh"}]
    storage.save_general_eol_cache.assert_called_once()
    mock_fetch.assert_called_once()


@patch("general_eol.fetch_all", return_value=[])
def test_refresh_does_not_cache_empty_result(mock_fetch):
    storage = MagicMock()
    records, _ = general_eol.refresh(storage)
    assert records == []
    storage.save_general_eol_cache.assert_not_called()


@patch("general_eol.fetch_all", return_value=[{"id": "new"}])
def test_get_or_refresh_fetches_when_no_cache(mock_fetch):
    """Backward-compat wrapper still works."""
    storage = MagicMock()
    storage.get_general_eol_cache.return_value = None
    records, _ = general_eol.get_or_refresh(storage)
    assert records == [{"id": "new"}]
    storage.save_general_eol_cache.assert_called_once()


# ── fetch_all (network mock) ──────────────────────────────────────────────────

@patch("general_eol.requests.get")
def test_fetch_all_normalizes_products(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"cycle": "1.33", "eolFrom": future(600), "isEoes": False, "latest": "1.33.1"},
    ]
    mock_get.return_value = mock_resp

    records = general_eol.fetch_all()
    # One record per product (all products return the same mock response)
    assert len(records) == len(general_eol.PRODUCTS)
    assert all("service" in r for r in records)
    assert all("status" in r for r in records)


@patch("general_eol.requests.get")
def test_fetch_all_handles_api_failure_gracefully(mock_get):
    mock_get.side_effect = Exception("Network error")
    records = general_eol.fetch_all()
    # Should return empty list, not raise
    assert records == []


# ── File backend cache round-trip ─────────────────────────────────────────────

def test_file_backend_general_eol_cache_roundtrip(tmp_path):
    import importlib
    os.environ["STORAGE_BACKEND"] = "file"
    os.environ["EOL_DATA_DIR"]    = str(tmp_path)

    import storage as stor
    importlib.reload(stor)
    backend = stor.FileBackend()

    sample = [{"id": "eks-1_33", "service": "EKS", "version": "1.33", "status": "SUPPORTED"}]
    backend.save_general_eol_cache(sample, "2026-05-30T00:00:00", "2026-05-31T00:00:00")

    cached = backend.get_general_eol_cache()
    assert cached is not None
    assert cached["records"] == sample
    assert cached["refreshed_at"] == "2026-05-30T00:00:00"
    assert cached["expires_at"] == "2026-05-31T00:00:00"

    os.environ.pop("STORAGE_BACKEND", None)
    os.environ.pop("EOL_DATA_DIR", None)
