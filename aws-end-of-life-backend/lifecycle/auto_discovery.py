"""Auto-discovery handlers — fetch lifecycle data from trusted AWS sources.

Safety contract:
  - Every handler catches all exceptions and returns None on failure.
  - No handler makes random internet requests — only documented AWS URLs.
  - Ubuntu handler always returns None (month-level precision only for MVP).
  - No dates are invented or synthesised from imprecise data.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_LAMBDA_RUNTIMES_URL = "https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html"
_EKS_DOCS_URL        = "https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html"


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _default_http_get(url: str, timeout: int = 5) -> Optional[str]:
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "aws-eol-monitor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("HTTP GET %s failed: %s", url, exc)
        return None


# ── Date parsing ──────────────────────────────────────────────────────────────

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%b %d, %Y",    # Nov 14, 2024
    "%B %d, %Y",    # November 14, 2024
    "%d %b %Y",     # 14 Nov 2024
    "%d %B %Y",     # 14 November 2024
]


def _parse_date_exact(text: str) -> Optional[str]:
    """Return YYYY-MM-DD only if text is an exact date (not month/year only). None otherwise."""
    text = text.strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _to_utc_date(val) -> Optional[str]:
    """Convert datetime / ISO string → YYYY-MM-DD UTC."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return _parse_date_exact(str(val))


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def _table_rows(html: str) -> list:
    return re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)


def _row_cells(row: str) -> list:
    raw = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
    return [_strip_tags(c).strip() for c in raw]


# ── Lambda docs handler ───────────────────────────────────────────────────────

def discover_lambda_from_docs(version: str, http_get=None) -> Optional[dict]:
    """Parse AWS Lambda runtimes page. Returns lifecycle dict or None.

    Returns None if:
    - HTTP fails
    - version identifier not found in page
    - fewer than 1 parseable exact date found in that row
    """
    _get = http_get or _default_http_get
    html = _get(_LAMBDA_RUNTIMES_URL, timeout=5)
    if not html:
        return None

    target = version.lower().replace(" ", "")

    for row in _table_rows(html):
        cells = _row_cells(row)
        if not cells:
            continue
        cells_norm = [c.lower().replace(" ", "") for c in cells]
        if target not in cells_norm:
            continue

        date_vals = [d for c in cells if (d := _parse_date_exact(c))]
        if not date_vals:
            logger.debug("Lambda docs: no exact dates for %s in row %s", version, cells)
            return None

        # Column convention on AWS docs: deprecation date first, block date second
        support_date = date_vals[0]
        eol_date     = date_vals[1] if len(date_vals) >= 2 else None

        logger.debug("Lambda docs: %s → support=%s eol=%s", version, support_date, eol_date)
        return {
            "eol":        eol_date,
            "support":    support_date,
            "is_eoes":    False,
            "confidence": "HIGH",
            "link":       _LAMBDA_RUNTIMES_URL,
        }

    logger.debug("Lambda docs: runtime %s not found", version)
    return None


# ── EKS API handler ───────────────────────────────────────────────────────────

def discover_eks_from_api(version: str, boto3_session=None) -> Optional[dict]:
    """Call EKS DescribeClusterVersions. Returns lifecycle dict or None."""
    try:
        import boto3
        session = boto3_session or boto3.session.Session()
        client  = session.client("eks")
        resp    = client.describe_cluster_versions(
            clusterVersions=[version.lstrip("v")],
            includeAll=True,
        )
        versions = resp.get("clusterVersions", [])
        if not versions:
            logger.debug("EKS API: version %s not found", version)
            return None

        v = versions[0]
        eol_std = _to_utc_date(v.get("endOfStandardSupportDate"))
        eol_ext = _to_utc_date(v.get("endOfExtendedSupportDate"))
        release = _to_utc_date(v.get("releaseDate"))
        status  = v.get("versionStatus", "")
        is_eoes = status in ("EXTENDED_SUPPORT", "EXTENDED_SUPPORT_ENDING")

        # Primary EOL date depends on current support status
        eol_primary = eol_ext if is_eoes and eol_ext else eol_std
        if not eol_primary:
            return None

        return {
            "eol":             eol_primary,
            "support":         eol_std if is_eoes else None,  # show std-end as support milestone
            "is_eoes":         is_eoes,
            "latest":          v.get("kubernetesPatchVersion"),
            "confidence":      "HIGH",
            "link":            _EKS_DOCS_URL,
            "_version_status": status,
            "_release_date":   release,
        }
    except Exception as exc:
        logger.debug("EKS API discovery failed for %s: %s", version, exc)
        return None


# ── EKS docs handler ─────────────────────────────────────────────────────────

def discover_eks_from_docs(version: str, http_get=None) -> Optional[dict]:
    """Parse EKS Kubernetes versions docs page. Returns lifecycle dict or None.

    AWS docs table column order (by date position in row):
      index 0 — release date          ← NEVER use as EOL, it is always in the past
      index 1 — end of standard support
      index 2 — end of extended support  (optional, present for 1.23+)

    is_eoes is True when standard support has already ended but extended support
    is still active today.
    """
    _get = http_get or _default_http_get
    html = _get(_EKS_DOCS_URL, timeout=5)
    if not html:
        return None

    target = version.lstrip("v").strip()
    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for row in _table_rows(html):
        cells = _row_cells(row)
        if not cells:
            continue
        cells_norm = [c.lower().replace(" ", "").lstrip("v") for c in cells]
        if target not in cells_norm:
            continue

        date_vals = [d for c in cells if (d := _parse_date_exact(c))]

        # Need at least [release_date, std_support_end] to classify correctly.
        # With only 1 date we cannot distinguish release from support-end — skip.
        if len(date_vals) < 2:
            logger.debug("EKS docs: %s — only %d date(s) found (%s), skipping",
                         version, len(date_vals), date_vals)
            return None

        # date_vals[0] = release date — intentionally ignored
        std_support_end = date_vals[1]
        ext_support_end = date_vals[2] if len(date_vals) >= 3 else None

        # True when standard support ended but extended support is still active
        is_eoes = (std_support_end < today
                   and ext_support_end is not None
                   and ext_support_end >= today)

        # Primary EOL = extended support end (if available), else standard support end
        eol     = ext_support_end if ext_support_end else std_support_end
        # Report std_support_end as "support" milestone only when ext support exists
        support = std_support_end if ext_support_end else None

        logger.info(
            "EKS docs parsed: version=%s release=%s std_support=%s ext_support=%s "
            "is_eoes=%s → eol=%s support=%s",
            version, date_vals[0], std_support_end, ext_support_end,
            is_eoes, eol, support,
        )
        return {
            "eol":        eol,
            "support":    support,
            "is_eoes":    is_eoes,
            "confidence": "HIGH",
            "link":       _EKS_DOCS_URL,
        }

    logger.debug("EKS docs: version %s not found in page", version)
    return None


# ── Ubuntu handler (disabled for MVP) ────────────────────────────────────────

def discover_ubuntu_from_vendor_docs(version: str, http_get=None) -> Optional[dict]:
    """Ubuntu lifecycle — always returns None for MVP.

    Ubuntu release cycle page shows month-level precision only (e.g. 'May 2025').
    Synthesising an exact date from partial data violates the no-fake-dates rule.
    endoflife.date remains the only Ubuntu source until a structured data API exists.
    """
    logger.debug("Ubuntu vendor docs discovery disabled for MVP")
    return None


# ── Handler dispatch ──────────────────────────────────────────────────────────

_HANDLERS = {
    "discover_lambda_from_docs":        discover_lambda_from_docs,
    "discover_eks_from_api":            discover_eks_from_api,
    "discover_eks_from_docs":           discover_eks_from_docs,
    "discover_ubuntu_from_vendor_docs": discover_ubuntu_from_vendor_docs,
}


def auto_discover_lifecycle(
    product: str,
    version: str,
    now=None,             # unused; accepted for test injection
    http_get=None,
    boto3_session=None,
) -> Optional[dict]:
    """Attempt discovery via sources in priority order. Returns classifier-compatible dict or None.

    All network/parser errors are caught — scan never crashes.
    """
    from lifecycle.sources import get_sources_for_product
    from lifecycle.normalizer import to_classifier_shape

    sources = get_sources_for_product(product)
    if not sources:
        return None

    for src in sources:
        handler_name = src.get("handler")
        fn = _HANDLERS.get(handler_name)
        if fn is None:
            logger.warning("Unknown discovery handler: %s", handler_name)
            continue
        try:
            raw = fn(version, **_handler_kwargs(src, http_get, boto3_session))
            if raw is None:
                continue
            record = to_classifier_shape(
                product=product,
                version=version,
                source_payload=raw,
                source_cfg=src,
            )
            logger.info("Lifecycle discovered: %s/%s via %s", product, version, handler_name)
            return record
        except Exception as exc:
            logger.warning("Handler %s failed for %s/%s: %s", handler_name, product, version, exc)
            continue

    return None


def _handler_kwargs(src: dict, http_get, boto3_session) -> dict:
    """Return kwargs appropriate to the handler type."""
    t = src.get("source_type", "")
    if t == "aws_api":
        return {"boto3_session": boto3_session}
    return {"http_get": http_get}
