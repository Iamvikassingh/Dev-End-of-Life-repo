"""
AWS EOL Monitor — General EOL Library
Fetches public lifecycle data from endoflife.date and caches it.
No AWS account access required.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Stable JSON API — returns a plain list of cycle objects per product.
# The v1 API (/api/v1/products/{slug}/) returns a dict, not a list.
EOL_API_BASE     = os.environ.get("EOL_API_BASE", "https://endoflife.date/api")
WARN_DAYS        = int(os.environ.get("WARN_DAYS", "180"))
CACHE_TTL_HOURS  = int(os.environ.get("GENERAL_EOL_CACHE_TTL_HOURS", "24"))

# Module-level lock: prevents concurrent requests from all triggering a full
# fetch simultaneously (React Query fires multiple parallel requests on load).
_fetch_lock   = threading.Lock()
_fetch_in_progress = False

# ── Product registry ──────────────────────────────────────────────────────────
# Each entry maps an endoflife.date product slug → display metadata + known
# recommended upgrades per version prefix.

PRODUCTS: list[dict] = [
    {
        "slug": "aws-lambda",
        "service": "Lambda",
        "family": None,
        "upgrades": {
            "python3.7":  "python3.12",
            "python3.8":  "python3.12",
            "python3.9":  "python3.12",
            "nodejs14.x": "nodejs22.x",
            "nodejs16.x": "nodejs22.x",
            "nodejs18.x": "nodejs22.x",
            "java11":     "java21",
            "ruby2.7":    "ruby3.4",
            "ruby3.2":    "ruby3.4",
        },
    },
    {
        "slug": "amazon-eks",
        "service": "EKS",
        "family": "EKS",
        "upgrades": {},
    },
    {
        "slug": "amazon-rds-mysql",
        "service": "RDS MySQL",
        "family": "MySQL",
        "upgrades": {"5.7": "8.4", "8.0": "8.4"},
    },
    {
        "slug": "amazon-rds-postgresql",
        "service": "RDS PostgreSQL",
        "family": "PostgreSQL",
        "upgrades": {"11": "16", "12": "16", "13": "16"},
    },
    {
        "slug": "amazon-rds-mariadb",
        "service": "RDS MariaDB",
        "family": "MariaDB",
        "upgrades": {},
    },
    {
        "slug": "amazon-aurora-postgresql",
        "service": "Aurora PostgreSQL",
        "family": "Aurora",
        "upgrades": {"13": "16", "14": "16"},
    },
    {
        "slug": "amazon-aurora-mysql",
        "service": "Aurora MySQL",
        "family": "Aurora",
        "upgrades": {"2": "3"},
    },
    {
        "slug": "amazon-elasticache-redis",
        "service": "ElastiCache Redis",
        "family": "Redis",
        "upgrades": {"5.0": "7.x", "6.0": "7.x", "6.2": "7.x"},
    },
    {
        "slug": "amazon-linux",
        "service": "Amazon Linux",
        "family": "Amazon Linux",
        "upgrades": {"1": "2023", "2": "2023"},
    },
    {
        "slug": "amazon-msk",
        "service": "MSK Kafka",
        "family": "Kafka",
        "upgrades": {"3.4": "3.7", "3.5": "3.7"},
    },
    {
        "slug": "amazon-opensearch",
        "service": "OpenSearch",
        "family": "OpenSearch",
        "upgrades": {"1.3": "2.x"},
    },
    {
        "slug": "amazon-documentdb",
        "service": "DocumentDB",
        "family": "DocumentDB",
        "upgrades": {},
    },
    {
        "slug": "amazon-neptune",
        "service": "Neptune",
        "family": "Neptune",
        "upgrades": {},
    },
    {
        "slug": "amazon-glue",
        "service": "AWS Glue",
        "family": "Glue",
        "upgrades": {"2.0": "4.0", "3.0": "4.0"},
    },
]

_PRODUCT_BY_SLUG: dict[str, dict] = {p["slug"]: p for p in PRODUCTS}


# ── Official discovery integration ───────────────────────────────────────────
# Maps source_registry IDs → frontend-facing lifecycle_source constants
_DISCOVERY_SOURCE_MAP: dict[str, str] = {
    "aws_lambda_docs": "AWS_DOCS",
    "aws_eks_docs":    "AWS_DOCS",
    "aws_eks_api":     "AWS_API",
}


def _make_cached_http_get(cache: dict):
    """Returns an http_get that fetches each URL at most once per fetch_all() run.

    Prevents 49 separate requests for the Lambda docs page — one fetch, all versions share it.
    """
    from lifecycle.auto_discovery import _default_http_get
    def _get(url: str, timeout: int = 5) -> Optional[str]:
        if url not in cache:
            cache[url] = _default_http_get(url, timeout=timeout)
        return cache[url]
    return _get


def _try_official_discovery(slug: str, version: str, http_get) -> Optional[dict]:
    """Return classifier-shape dict from official AWS source, or None.

    Tries sources in priority order per source_registry.json:
      Lambda: AWS docs page (public, no credentials needed)
      EKS:    AWS EKS API (needs IAM role) → falls back to EKS docs page
    All failures are swallowed — never crashes the refresh.
    """
    try:
        from lifecycle.auto_discovery import auto_discover_lifecycle
        return auto_discover_lifecycle(slug, version, http_get=http_get)
    except Exception as exc:
        logger.debug("Official discovery failed for %s/%s: %s", slug, version, exc)
        return None


# ── Classification ─────────────────────────────────────────────────────────────

def _parse_date(val) -> Optional[date]:
    if not val or val is False:
        return None
    try:
        return date.fromisoformat(str(val))
    except ValueError:
        return None


def _classify(eol_from: Optional[str], is_eoes: bool,
              support_from: Optional[str] = None,
              include_primary: bool = False):
    """Return lifecycle status and days to the primary risk date.

    Delegates to lifecycle.classifier for consistency with eol_collector.classify_status.
    When include_primary=True, also returns the selected primary date string.
    """
    try:
        from lifecycle.classifier import classify as _unified_classify
        status, primary_date, days = _unified_classify(eol_from, support_from, is_eoes, WARN_DAYS)
    except ImportError:
        # Fallback to inline logic if classifier module is unavailable
        eol_dt     = _parse_date(eol_from)
        support_dt = _parse_date(support_from)
        if support_dt and eol_dt and support_dt < eol_dt:
            primary_dt = support_dt
        elif eol_dt:
            primary_dt = eol_dt
        elif support_dt:
            primary_dt = support_dt
        else:
            return ("SUPPORTED", None, None) if include_primary else ("SUPPORTED", None)
        days = (primary_dt - date.today()).days
        if days < 0:
            status, primary_date = "EOL", str(primary_dt)
        elif days <= WARN_DAYS:
            status, primary_date = "EXPIRING_SOON", str(primary_dt)
        elif is_eoes:
            status, primary_date = "EXTENDED_SUPPORT", str(primary_dt)
        else:
            status, primary_date = "SUPPORTED", str(primary_dt)

    if include_primary:
        return status, days, primary_date
    return status, days


# ── endoflife.date fetch ───────────────────────────────────────────────────────

def _fetch_product_versions(slug: str) -> list[dict]:
    """Fetch all version cycles for a product slug from the stable JSON API."""
    url = f"{EOL_API_BASE}/{slug}.json"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
            logger.warning("endoflife.date %s → unexpected format: %s", slug, type(data).__name__)
        else:
            logger.warning("endoflife.date %s → HTTP %s", slug, r.status_code)
    except Exception as exc:
        logger.warning("endoflife.date fetch failed for %s: %s", slug, exc)
    return []


# ── Normalization ─────────────────────────────────────────────────────────────

def _normalize(slug: str, raw: dict, fetched_at: Optional[str] = None,
               discovery: Optional[dict] = None) -> Optional[dict]:
    """Convert a raw endoflife.date cycle record to the frontend-ready shape.

    When discovery is provided (AWS docs/API result), its dates take precedence
    over endoflife.date and the source metadata reflects the official AWS source.
    """
    meta    = _PRODUCT_BY_SLUG.get(slug, {})
    version = str(raw.get("cycle") or raw.get("version") or "").strip()
    if not version:
        return None

    # Start with endoflife.date values as baseline
    eol_raw     = raw.get("eolFrom") or raw.get("eol")
    support_raw = raw.get("support")
    eol_from    = str(eol_raw)     if eol_raw     and eol_raw     is not False else None
    support_str = str(support_raw) if support_raw and support_raw is not False else None
    is_eoes     = bool(raw.get("isEoes") or raw.get("extendedSupport"))

    # Source metadata defaults (endoflife.date)
    lifecycle_source = "ENDOFLIFE_DATE"
    confidence       = "MEDIUM"
    source_url       = f"https://endoflife.date/{slug}"
    recommended_latest = raw.get("latest") or None

    # Official AWS discovery overrides dates and source attribution
    if discovery:
        disc_meta   = discovery.get("__meta", {})
        raw_src_id  = disc_meta.get("lifecycle_source", "")
        lifecycle_source = _DISCOVERY_SOURCE_MAP.get(raw_src_id, "AWS_OFFICIAL")
        confidence       = disc_meta.get("confidence") or "HIGH"
        source_url       = disc_meta.get("source_url") or source_url

        disc_eol = discovery.get("eolFrom")
        disc_sup = discovery.get("support")
        if disc_eol and disc_eol is not False:
            eol_from = str(disc_eol)
        if disc_sup and disc_sup is not False:
            support_str = str(disc_sup)
        # Always take discovery's isEoes — overrides endoflife.date value in both directions
        is_eoes = bool(discovery.get("isEoes", False))
        if discovery.get("latest"):
            recommended_latest = discovery["latest"]

    status, days, primary_date = _classify(
        eol_from, is_eoes, support_from=support_str, include_primary=True
    )

    # Separate final EOL date when support is used as primary alert date
    final_eol = eol_from if (support_str and eol_from and support_str != eol_from) else None

    upgrades: dict      = meta.get("upgrades", {})
    recommended: Optional[str] = upgrades.get(version)
    if not recommended and status in ("EOL", "EXPIRING_SOON"):
        recommended = recommended_latest

    return {
        "id":                 f"{slug}-{version}".replace(".", "_").replace("/", "-"),
        "service":            meta.get("service", slug),
        "version":            version,
        "eolDate":            primary_date,
        "daysToEol":          days,
        "status":             status,
        "family":             meta.get("family"),
        "recommendedUpgrade": recommended,
        "source":             "endoflife.date",
        "lifecycle_source":   lifecycle_source,
        "confidence":         confidence,
        "is_stale":           False,
        "fetched_at":         fetched_at,
        "source_url":         source_url,
        "product_slug":       slug,
        "supportEndDate":     support_str,
        "finalEolDate":       final_eol,
    }


# ── Verified lifecycle overlay ────────────────────────────────────────────────

def merge_verified_lifecycle(records: list[dict], storage) -> tuple[list[dict], int]:
    """Overlay verified_lifecycle DB records on top of the endoflife.date cache.

    Only records with validationStatus=verified and at least one date are applied.
    No external network calls — reads from storage only.
    Returns (merged_records, overlay_count).
    """
    try:
        verified = storage.list_verified_lifecycle()
    except Exception as exc:
        logger.warning("merge_verified_lifecycle: could not load records: %s", exc)
        return records, 0

    verified_map: dict[tuple[str, str], dict] = {}
    for v in verified:
        if v.get("validationStatus") != "verified":
            continue
        product = v.get("product", "")
        version = v.get("version", "")
        if product and version and (v.get("eolDate") or v.get("supportEndDate")):
            verified_map[(product, version)] = v

    if not verified_map:
        return records, 0

    existing_idx: dict[tuple[str, str], int] = {
        (r.get("product_slug", ""), r.get("version", "")): i
        for i, r in enumerate(records)
    }

    result = list(records)
    overlay_count = 0

    for (product, version), vr in verified_map.items():
        eol_date    = vr.get("eolDate")
        support_end = vr.get("supportEndDate")
        # is_eoes: extended support phase exists (support ends before hard EOL)
        is_eoes     = bool(eol_date and support_end)
        status, days, primary_date = _classify(
            eol_date, is_eoes, support_from=support_end, include_primary=True
        )
        final_eol = eol_date if (support_end and eol_date and support_end != eol_date) else None

        meta  = _PRODUCT_BY_SLUG.get(product, {})
        patch = {
            "eolDate":            primary_date,
            "supportEndDate":     support_end,
            "finalEolDate":       final_eol,
            "daysToEol":          days,
            "status":             status,
            "lifecycle_source":   "VERIFIED_AWS_OFFICIAL",
            "confidence":         vr.get("confidence", "HIGH"),
            "source":             "verified_lifecycle",
            "source_url":         vr.get("officialSourceUrl") or f"https://endoflife.date/{product}",
            "officialSourceUrl":  vr.get("officialSourceUrl"),
            "lastValidatedAt":    vr.get("lastValidatedAt"),
            "validatedBy":        vr.get("validatedBy"),
            "validationStatus":   "verified",
        }

        key = (product, version)
        if key in existing_idx:
            result[existing_idx[key]] = {**result[existing_idx[key]], **patch}
        else:
            # Record not in endoflife.date cache — append as verified-only entry
            new_rec = {
                "id":                 f"{product}-{version}".replace(".", "_").replace("/", "-"),
                "service":            meta.get("service", product),
                "version":            version,
                "family":             meta.get("family"),
                "recommendedUpgrade": meta.get("upgrades", {}).get(version),
                "is_stale":           False,
                "product_slug":       product,
                **patch,
            }
            result.append(new_rec)
            existing_idx[key] = len(result) - 1

        overlay_count += 1

    return result, overlay_count


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_all() -> list[dict]:
    """Fetch and normalize all configured products from endoflife.date.

    For products with official AWS discovery (Lambda, EKS), enriches source
    metadata and dates from AWS docs/API. A shared page cache ensures each
    docs URL is fetched only once per refresh run regardless of version count.
    """
    records: list[dict] = []
    fetched_at = datetime.utcnow().isoformat() + "Z"
    _page_cache: dict = {}
    _http_get = _make_cached_http_get(_page_cache)

    for product in PRODUCTS:
        slug     = product["slug"]
        versions = _fetch_product_versions(slug)
        logger.info("endoflife.date: %d cycles for %s", len(versions), slug)
        for raw in versions:
            version_str = str(raw.get("cycle") or raw.get("version") or "").strip()
            discovery = _try_official_discovery(slug, version_str, _http_get) if version_str else None
            rec = _normalize(slug, raw, fetched_at=fetched_at, discovery=discovery)
            if rec:
                records.append(rec)

    logger.info("General EOL: %d total normalized records", len(records))
    return records


def compute_summary(records: list[dict]) -> dict:
    """Return status-count summary for a list of records."""
    counts: dict[str, int] = {
        "EOL": 0, "EXPIRING_SOON": 0, "EXTENDED_SUPPORT": 0, "SUPPORTED": 0, "UNKNOWN": 0,
    }
    for r in records:
        s = r.get("status", "UNKNOWN")
        counts[s] = counts.get(s, 0) + 1
    return counts


LEGACY_CUTOFF_YEARS = 3


def _is_legacy(record: dict) -> bool:
    """True when a record is EOL and its EOL date is older than LEGACY_CUTOFF_YEARS."""
    if record.get("status") != "EOL":
        return False
    eol_date = record.get("eolDate")
    if not eol_date:
        return False
    try:
        cutoff = date.today().replace(year=date.today().year - LEGACY_CUTOFF_YEARS)
        return date.fromisoformat(eol_date) < cutoff
    except ValueError:
        return False


def filter_records(
    records: list[dict],
    service:         str  = "",
    status:          str  = "",
    search:          str  = "",
    include_legacy:  bool = False,
) -> list[dict]:
    """Apply optional filters server-side. All filters are case-insensitive.

    include_legacy=False (default): hides EOL versions whose EOL date is older
    than LEGACY_CUTOFF_YEARS years — keeps the table focused on current risk.
    include_legacy=True: shows the full history including ancient retired cycles.
    """
    result = records

    if not include_legacy:
        result = [r for r in result if not _is_legacy(r)]

    if service:
        q = service.lower()
        result = [r for r in result if q in r.get("service", "").lower()]
    if status:
        result = [r for r in result if r.get("status", "").upper() == status.upper()]
    if search:
        q = search.lower()
        result = [
            r for r in result
            if q in r.get("service", "").lower()
            or q in r.get("version", "").lower()
            or q in (r.get("family") or "").lower()
        ]
    return result


class CacheResult:
    """Holds the result of a cache read so callers can inspect freshness."""
    __slots__ = ("records", "refreshed_at", "is_stale", "is_empty")

    def __init__(self, records, refreshed_at, is_stale, is_empty):
        self.records      = records
        self.refreshed_at = refreshed_at
        self.is_stale     = is_stale
        self.is_empty     = is_empty


def get_cached_only(storage) -> CacheResult:
    """
    Read from cache and return immediately — NO external network call.

    Use this for GET endpoints so page load is always fast.
    CacheResult.is_empty=True means the cache has never been populated.
    CacheResult.is_stale=True means the data exists but the TTL has expired.

    Call `refresh(storage)` (or POST /eol/general/refresh) to populate/update.
    """
    t0 = datetime.utcnow()
    cached = storage.get_general_eol_cache()

    if not cached or not cached.get("records"):
        logger.info("GET /eol/general cache_hit=false cache_empty=true duration_ms=%d",
                    int((datetime.utcnow() - t0).total_seconds() * 1000))
        return CacheResult(records=[], refreshed_at="", is_stale=False, is_empty=True)

    records      = cached["records"]
    refreshed_at = cached.get("refreshed_at", "")
    expires_at   = cached.get("expires_at", "")
    is_stale     = bool(expires_at and datetime.utcnow().isoformat() >= expires_at)

    logger.info("GET /eol/general cache_hit=true cache_records=%d stale=%s duration_ms=%d",
                len(records), is_stale,
                int((datetime.utcnow() - t0).total_seconds() * 1000))
    return CacheResult(records=records, refreshed_at=refreshed_at, is_stale=is_stale, is_empty=False)


def refresh(storage) -> tuple[list[dict], str]:
    """
    Fetch fresh data from endoflife.date and update cache.

    This is the ONLY function that makes external network calls.
    Use for POST /eol/general/refresh — may take 15–30s.
    Thread-safe via module-level lock (prevents concurrent stampedes).
    """
    with _fetch_lock:
        logger.info("Refresh: fetching all products from endoflife.date")
        records      = fetch_all()
        refreshed_at = datetime.utcnow().isoformat()

        if records:
            expires_at = (datetime.utcnow() + timedelta(hours=CACHE_TTL_HOURS)).isoformat()
            storage.save_general_eol_cache(records, refreshed_at, expires_at)
            logger.info("Refresh complete: cached %d records (TTL %sh)", len(records), CACHE_TTL_HOURS)
        else:
            logger.warning("Refresh: endoflife.date returned 0 records — cache not updated")

        return records, refreshed_at


def warm_cache_background(storage) -> None:
    """
    Non-blocking background cache warm. Call once at server startup when cache is empty.
    Runs in a daemon thread so it never blocks the server from starting.
    """
    import threading

    def _warm():
        logger.info("General EOL cache warm: starting background fetch")
        try:
            records, _ = refresh(storage)
            logger.info("General EOL cache warm: complete — %d records", len(records))
        except Exception as exc:
            logger.error("General EOL cache warm: failed — %s", exc)

    threading.Thread(target=_warm, daemon=True, name="eol-cache-warm").start()


# Keep for backward compatibility (used by tests that test the old behaviour)
def get_or_refresh(storage) -> tuple[list[dict], str]:
    """Deprecated: use get_cached_only() for GET and refresh() for POST."""
    result = get_cached_only(storage)
    if result.is_empty:
        return refresh(storage)
    return result.records, result.refreshed_at
