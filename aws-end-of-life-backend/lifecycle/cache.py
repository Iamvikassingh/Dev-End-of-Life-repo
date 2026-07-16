"""Persistent discovered lifecycle cache — JSON file backed, atomic writes.

Uses stale-if-error semantics:
  - Fresh records (< FRESH_TTL_DAYS) returned directly.
  - Stale records (< MAX_STALE_DAYS) returned only as fallback when discovery fails.
  - Expired records (>= MAX_STALE_DAYS) treated as absent.
"""
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

FRESH_TTL_DAYS = int(os.environ.get("LIFECYCLE_FRESH_TTL_DAYS", "7"))
MAX_STALE_DAYS = int(os.environ.get("LIFECYCLE_MAX_STALE_DAYS", "90"))

_EOL_DATA_DIR = os.environ.get("EOL_DATA_DIR", "/var/lib/eol-data")
_REPO_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "lifecycle_data")


def _cache_path() -> str:
    explicit = os.environ.get("LIFECYCLE_CACHE_PATH")
    if explicit:
        return explicit
    # Co-locate with other EOL data files for consistent storage
    return os.path.join(_EOL_DATA_DIR, "lifecycle_cache.json")


def load_discovered_cache() -> dict:
    """Return cache dict; never raises. Returns empty structure on error."""
    path = _cache_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "records" not in data:
            logger.warning("Lifecycle cache malformed at %s — resetting", path)
            return {"version": 1, "records": []}
        return data
    except FileNotFoundError:
        return {"version": 1, "records": []}
    except Exception as exc:
        logger.warning("Lifecycle cache load error: %s", exc)
        return {"version": 1, "records": []}


def save_discovered_cache(cache: dict) -> None:
    """Atomic write via temp file + os.replace; never raises."""
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        dir_ = os.path.dirname(path)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2, default=str)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as exc:
        logger.warning("Lifecycle cache save error: %s", exc)


def _age_days(record: dict) -> float:
    raw = record.get("discovered_at")
    if not raw:
        return float("inf")
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        dt_aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt_aware).total_seconds() / 86400
    except (ValueError, TypeError):
        return float("inf")


def is_record_fresh(record: dict) -> bool:
    return _age_days(record) < FRESH_TTL_DAYS


def is_record_usable(record: dict) -> bool:
    """True if within the stale-if-error window (< MAX_STALE_DAYS)."""
    return _age_days(record) < MAX_STALE_DAYS


def _make_key(product: str, version: str) -> str:
    return f"{product.lower().strip()}/{version.lower().strip()}"


def query_discovered_cache(
    product: str, version: str, allow_stale: bool = True
) -> Optional[dict]:
    """Return matching record or None.

    Fresh records always returned. Stale records returned only if allow_stale
    AND within MAX_STALE_DAYS. Expired records treated as absent.
    """
    key = _make_key(product, version)
    for record in load_discovered_cache().get("records", []):
        if _make_key(record.get("product", ""), record.get("version", "")) == key:
            if is_record_fresh(record):
                return record
            if allow_stale and is_record_usable(record):
                return record
            return None  # too old
    return None


def upsert_discovered_record(record: dict) -> None:
    """Insert or replace record by product+version. Atomic save."""
    key = _make_key(record.get("product", ""), record.get("version", ""))
    cache = load_discovered_cache()
    records = cache.get("records", [])
    for i, existing in enumerate(records):
        if _make_key(existing.get("product", ""), existing.get("version", "")) == key:
            records[i] = record
            cache["records"] = records
            save_discovered_cache(cache)
            return
    records.append(record)
    cache["records"] = records
    save_discovered_cache(cache)
