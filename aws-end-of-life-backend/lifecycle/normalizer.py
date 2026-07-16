"""Convert raw discovery payloads to endoflife.date-compatible classifier shape.

The output must be accepted by eol_collector.classify_status() unchanged.
Discovery metadata goes under __meta and is ignored by the classifier.
"""
from datetime import datetime, timezone
from typing import Optional


def to_utc_date_str(val) -> Optional[str]:
    """Convert ISO timestamp / date string / datetime → YYYY-MM-DD (UTC). None on failure."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val.astimezone(timezone.utc).strftime("%Y-%m-%d")
    text = str(val).strip().replace("Z", "+00:00")
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def to_classifier_shape(
    product: str,
    version: str,
    source_payload: dict,
    source_cfg: dict,
    extra_meta: Optional[dict] = None,
) -> dict:
    """Return an endoflife.date-like dict that classify_status() can consume.

    source_payload keys (all optional):
      eol       — EOL / end-of-standard-support date
      support   — vendor/community support end date (earlier milestone)
      is_eoes   — bool, True if currently under paid extended support
      latest    — latest patch version string
      lts       — bool, is LTS release
      confidence — HIGH | MEDIUM | LOW
      link      — canonical source URL
    """
    eol_str     = to_utc_date_str(source_payload.get("eol"))
    support_str = to_utc_date_str(source_payload.get("support"))
    is_eoes     = bool(source_payload.get("is_eoes", False))

    record: dict = {}
    if eol_str:
        record["eolFrom"] = eol_str
    if support_str:
        record["support"] = support_str
    record["isEoes"] = is_eoes
    if source_payload.get("latest"):
        record["latest"] = source_payload["latest"]
    if source_payload.get("lts"):
        record["lts"] = source_payload["lts"]

    # Build __meta — consumed by collectors for field enrichment, NOT by classify_status()
    meta: dict = {
        "lifecycle_source": source_cfg.get("id"),
        "source_type":      source_cfg.get("source_type"),
        "source_url":       source_cfg.get("url") or source_payload.get("link"),
        "confidence":       source_payload.get("confidence") or source_cfg.get("confidence_base", "HIGH"),
        "discovery_method": source_cfg.get("handler"),
        "discovered_at":    datetime.now(timezone.utc).isoformat(),
        "product":          product,
        "version":          version,
    }
    # Attach any extra metadata from the source payload itself
    for k in ("_version_status", "_release_date"):
        if source_payload.get(k) is not None:
            meta[k] = source_payload[k]
    if extra_meta:
        meta.update(extra_meta)

    record["__meta"] = meta
    return record
