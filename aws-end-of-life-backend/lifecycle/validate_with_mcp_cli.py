#!/usr/bin/env python3
"""MCP validation CLI — standalone admin tool for AWS Documentation MCP server.

IMPORTANT — safety constraints:
  - Never import this module from account scan path.
  - Never call from fetch_eol() or any scan-time code.
  - This is an admin/batch CLI only.
  - Does NOT access customer AWS accounts.
  - Does NOT mutate AWS resources.

Validation flow per product:
  1. MCP search_documentation → find canonical AWS docs URL
  2. MCP read_documentation   → full page content
  3. MCP read_sections        → targeted section content (if step 2 thin)
  4. Direct HTML fallback     → requests.get + BeautifulSoup table parse
     (used when MCP content does not expose full lifecycle table)

Usage:
  python -m lifecycle.validate_with_mcp_cli --list-tools
  python -m lifecycle.validate_with_mcp_cli --product aws-lambda --version python3.9 --json --verbose
  python -m lifecycle.validate_with_mcp_cli --product aws-lambda --version python3.9 --save --json

Setup:
  python3 -m venv venv-mcp
  source venv-mcp/bin/activate
  pip install -r requirements-mcp.txt
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── MCP server config ─────────────────────────────────────────────────────────

MCP_SERVER_CMD  = os.environ.get("MCP_SERVER_CMD", "uvx")
MCP_SERVER_ARGS = os.environ.get(
    "MCP_SERVER_ARGS",
    "awslabs.aws-documentation-mcp-server@latest",
).split()

MCP_SERVER_ENV = {
    **os.environ,
    "FASTMCP_LOG_LEVEL": "ERROR",
    "LOG_LEVEL":         "ERROR",
}

# ── Product config ────────────────────────────────────────────────────────────

PRODUCT_CONFIG: dict[str, dict] = {
    "aws-lambda": {
        "search_query": "AWS Lambda runtimes end of life deprecation date supported",
        "url_hints":    ["lambda-runtimes", "lambda/latest/dg/lambda-runtimes"],
        "extra_urls":   [
            "https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html",
            "https://docs.aws.amazon.com/lambda/latest/dg/runtimes-list-deprecated.html",
        ],
        "sections": [
            "Supported runtimes",
            "Deprecated runtimes",
            "Runtime deprecation policy",
            "Runtime use after deprecation",
        ],
    },
    "amazon-eks": {
        "search_query": "Amazon EKS Kubernetes version end of standard support extended support lifecycle dates",
        "url_hints":    ["kubernetes-versions"],
        "extra_urls":   [
            # Extended support page lists ALL past versions with both support-end dates
            "https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions-extended.html",
            # Standard support page — current + recently-expired versions
            "https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions-standard.html",
            # Main versions overview page as fallback
            "https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html",
        ],
        "sections": [
            "Kubernetes version support",
            "End of standard support",
            "End of extended support",
            "Amazon EKS Kubernetes versions",
        ],
    },
    "amazon-rds-postgresql": {
        "search_query": "Amazon RDS PostgreSQL major version end of standard support extended support lifecycle",
        "url_hints":    ["postgresql-release-calendar", "PostgreSQLReleaseNotes"],
        "extra_urls":   [
            # Release calendar — has Table 1 with all major version lifecycle dates
            "https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-release-calendar.html",
        ],
        "sections": [
            "PostgreSQL major version",
            "RDS end of standard support date",
            "RDS end of Extended Support date",
            "Major versions",
        ],
    },
    "amazon-rds-mysql": {
        "search_query": "Amazon RDS MySQL major version end of standard support extended support lifecycle",
        "url_hints":    ["MySQL.Concepts.VersionMgmt", "mysql-release-calendar"],
        "extra_urls":   [
            # Table 4 (MySQL major version) has the lifecycle dates
            "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/MySQL.Concepts.VersionMgmt.html",
        ],
        "sections": [
            "MySQL major version",
            "RDS end of standard support date",
            "RDS end of Extended Support date",
            "Major versions",
        ],
    },
    "amazon-rds-mariadb": {
        "search_query": "Amazon RDS MariaDB major version end of standard support lifecycle deprecation",
        "url_hints":    ["MariaDB.Concepts", "mariadb-release-calendar"],
        "extra_urls":   [
            "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/MariaDB.Concepts.VersionMgmt.html",
        ],
        "sections": [
            "Major version lifecycle",
            "End of life",
            "Extended Support",
        ],
    },
    "amazon-aurora-postgresql": {
        "search_query": "Amazon Aurora PostgreSQL major version end of standard support lifecycle release calendar",
        "url_hints":    ["aurorapostgresql-release-calendar", "AuroraPostgreSQLReleaseNotes"],
        "extra_urls":   [
            # Aurora PostgreSQL major version release calendar
            "https://docs.aws.amazon.com/AmazonRDS/latest/AuroraPostgreSQLReleaseNotes/aurorapostgresql-release-calendar.html",
        ],
        "sections": [
            "PostgreSQL major version",
            "Aurora end of standard support date",
            "End of RDS Extended Support date",
            "Major versions",
        ],
    },
    "amazon-aurora-mysql": {
        "search_query": "Amazon Aurora MySQL major version end of standard support lifecycle release calendar",
        "url_hints":    ["AuroraMySQL.release-calendars", "AuroraMySQLReleaseNotes"],
        "extra_urls":   [
            # Aurora MySQL major version release calendar
            "https://docs.aws.amazon.com/AmazonRDS/latest/AuroraMySQLReleaseNotes/AuroraMySQL.release-calendars.html",
        ],
        "sections": [
            "Community major version",
            "Aurora end of standard support date",
            "RDS end of Extended Support date",
            "Major versions",
        ],
    },
    "amazon-opensearch": {
        "search_query": "Amazon OpenSearch Service version end of life support date lifecycle",
        "url_hints":    ["supported-opensearch-version", "version-lifecycle", "opensearch"],
        "extra_urls":   [
            "https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-opensearch-version.html",
            "https://docs.aws.amazon.com/opensearch-service/latest/developerguide/what-is.html",
        ],
        "sections": ["Supported versions", "End of life", "Version lifecycle", "Version support"],
    },
    "amazon-elasticache-redis": {
        "search_query": "Amazon ElastiCache Redis engine version end of standard support extended support EOL lifecycle",
        "url_hints":    ["engine-versions", "extended-support"],
        "extra_urls":   [
            # AWS docs reorganized from /red-ug/ to /dg/ — use new paths
            "https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/engine-versions.html",
            "https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/extended-support.html",
        ],
        "sections": [
            "Redis OSS versions end of life schedule",
            "Extended Support",
            "Engine version lifecycle",
            "End of standard support",
            "End of extended support",
        ],
    },
    "amazon-elasticache-memcached": {
        "search_query": "Amazon ElastiCache Memcached engine version end of support lifecycle deprecation",
        "url_hints":    ["supported-engine-versions", "elasticache-memcached"],
        "extra_urls":   [
            "https://docs.aws.amazon.com/AmazonElastiCache/latest/mem-ug/supported-engine-versions.html",
        ],
        "sections": ["Supported versions", "End of life", "Deprecation", "Engine versions"],
    },
}

# ── Lambda-specific direct HTML parser ───────────────────────────────────────

# Column header keywords → canonical field name
_LAMBDA_COL_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"runtime\s*(identifier|id)?$", re.I), "runtime_id"),
    (re.compile(r"^(runtime|name)$", re.I),            "runtime_name"),
    (re.compile(r"deprecation\s*date", re.I),           "deprecation_date"),
    (re.compile(r"block\s*function\s*creat", re.I),     "block_create"),
    (re.compile(r"block\s*function\s*updat", re.I),     "block_update"),
    (re.compile(r"(support|eol|end.of.life)", re.I),    "support_end"),
]


def _classify_lambda_header(text: str) -> Optional[str]:
    for pattern, field in _LAMBDA_COL_MAP:
        if pattern.search(text.strip()):
            return field
    return None


def _parse_lambda_html_tables(html: str, version: str, variants: list[str]) -> Optional[dict]:
    """Parse all tables in a Lambda docs HTML page for a runtime row.

    Returns a dict with extracted date fields, or None if not found.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.debug("beautifulsoup4 not installed — skipping HTML table parse")
        return None

    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    logger.debug("HTML parse: %d tables found in page", len(tables))

    for table_idx, table in enumerate(tables):
        # Extract headers
        header_cells = table.find_all("th")
        if not header_cells:
            # Some tables use first <tr> as header row
            first_row = table.find("tr")
            header_cells = first_row.find_all("td") if first_row else []

        headers: list[str] = [c.get_text(strip=True) for c in header_cells]
        col_map: dict[int, str] = {}
        for idx, hdr in enumerate(headers):
            field = _classify_lambda_header(hdr)
            if field:
                col_map[idx] = field

        logger.debug("Table %d: headers=%s col_map=%s", table_idx, headers, col_map)

        if not col_map:
            continue  # not a lifecycle table

        # Scan data rows
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            cell_texts = [c.get_text(separator=" ", strip=True) for c in cells]
            row_text   = " | ".join(cell_texts)

            # Check if any variant matches anywhere in this row
            matched_variant = None
            for variant in variants:
                if re.search(r"(?<![a-zA-Z0-9_])" + re.escape(variant) + r"(?![a-zA-Z0-9_])",
                             row_text, re.I):
                    matched_variant = variant
                    break

            if not matched_variant:
                continue

            logger.debug("Matched variant %r in row: %r", matched_variant, row_text[:200])

            # Extract date fields from mapped columns
            found: dict[str, str] = {}
            for col_idx, field in col_map.items():
                if col_idx < len(cell_texts):
                    raw = cell_texts[col_idx].strip()
                    d   = _normalize_date_str(raw)
                    if d:
                        found[field] = d
                    elif raw and field not in ("runtime_id", "runtime_name"):
                        logger.debug("  col %d (%s): %r — not a date", col_idx, field, raw)

            logger.debug("Extracted fields from row: %s", found)
            return {
                "matched_variant": matched_variant,
                "row_text":        row_text,
                "deprecation_date": found.get("deprecation_date"),
                "block_create":     found.get("block_create"),
                "block_update":     found.get("block_update"),
                "support_end":      found.get("support_end"),
                "table_headers":    headers,
            }

    return None  # version not found in any table


def _lambda_html_to_result(
    parsed: dict,
    product: str,
    version: str,
    source_url: str,
    now: str,
) -> dict:
    """Convert parsed Lambda HTML table row into a validation result dict."""
    # EOL date priority: block_update → deprecation_date → support_end
    eol_date     = (parsed.get("block_update")
                    or parsed.get("deprecation_date")
                    or parsed.get("support_end"))
    support_end  = parsed.get("deprecation_date") or parsed.get("support_end")
    block_create = parsed.get("block_create")
    block_update = parsed.get("block_update")

    date_count   = sum(1 for v in [eol_date, support_end, block_create] if v)
    confidence   = "HIGH" if date_count >= 2 else "MEDIUM" if eol_date else "LOW"
    v_status     = "verified" if confidence in ("HIGH", "MEDIUM") else "needs_review"

    note_parts   = []
    if parsed.get("deprecation_date"):
        note_parts.append(f"deprecation={parsed['deprecation_date']}")
    if block_create:
        note_parts.append(f"block_create={block_create}")
    if block_update:
        note_parts.append(f"block_update={block_update}")

    if not eol_date:
        return {
            "product": product, "version": version,
            "validationStatus": "needs_review", "confidence": "LOW",
            "source": "aws_official_docs",
            "officialSourceUrl": source_url,
            "matchedVariant": parsed["matched_variant"],
            "fetchMethod": "direct_html",
            "matchedSection": parsed["row_text"][:300],
            "notes": "Runtime row found but no lifecycle dates extracted",
        }

    return {
        "product":                product,
        "version":                version,
        "validationStatus":       v_status,
        "confidence":             confidence,
        "source":                 "aws_official_docs",
        "lifecycle_source":       "VERIFIED_AWS_OFFICIAL",
        "validatedBy":            "aws_mcp+direct_aws_docs",
        "eolDate":                eol_date,
        "supportEndDate":         support_end,
        "blockCreateDate":        block_create,
        "blockUpdateDate":        block_update,
        "extendedSupportEndDate": None,
        "officialSourceUrl":      source_url,
        "matchedVariant":         parsed["matched_variant"],
        "fetchMethod":            "direct_html",
        "lastValidatedAt":        now,
        "is_stale":               False,
        "manual_override":        False,
        "conflict":               False,
        "requiresManualReview":   v_status != "verified",
        "notes":                  "Direct AWS docs HTML parse. " + ", ".join(note_parts),
        "matchedSection":         parsed["row_text"][:300],
    }


# ── Generic HTML table parser (EKS, RDS, Aurora, OpenSearch, ElastiCache) ─────

# Per-product column header → canonical field name mappings.
# Keys use product slug patterns. Each list is tried in order; first match wins.
_GENERIC_COL_MAPS: dict[str, list[tuple[re.Pattern, str]]] = {
    "amazon-eks": [
        (re.compile(r"end\s*of\s*extended\s*support",  re.I), "eolDate"),
        (re.compile(r"end\s*of\s*standard\s*support",  re.I), "supportEndDate"),
        (re.compile(r"(kubernetes\s*)?version$",        re.I), "version_col"),
        (re.compile(r"release\s*date",                 re.I), "release_date"),    # skip
    ],
    # RDS PostgreSQL / RDS MySQL / Aurora PostgreSQL / Aurora MySQL
    # Actual columns from AWS release calendar pages:
    #   "RDS end of Extended Support date"   → eolDate
    #   "RDS end of standard support date"   → supportEndDate
    #   "Aurora end of standard support date"→ supportEndDate
    #   "End of RDS Extended Support date"   → eolDate  (Aurora PG)
    #   "Community end of life date"         → upstreamEol (skip)
    #   "PostgreSQL major version"           → version_col
    #   "MySQL major version"                → version_col
    #   "Aurora major version"               → version_col
    #   "Community major version"            → version_col (Aurora MySQL table 1)
    "_rds_aurora": [
        # eolDate — RDS/Aurora extended support end (must match before "standard support")
        (re.compile(
            r"rds\s+end\s+of\s+extended\s+support|"
            r"end\s+of\s+rds\s+extended\s+support|"
            r"rds\s+end\s+of\s+extended|"
            r"extended\s+support\s+date|"
            r"deprecation\s+date|eol\s+date|end\s+of\s+life(?!\s+date)",
            re.I,
        ), "eolDate"),
        # supportEndDate — RDS/Aurora standard support end
        (re.compile(
            r"rds\s+end\s+of\s+standard\s+support|"
            r"aurora\s+end\s+of\s+standard\s+support|"
            r"end\s+of\s+standard\s+support|"
            r"(general\s*)?support\s+end(?!\s+of\s+extended)",
            re.I,
        ), "supportEndDate"),
        # upstreamEol — community EOL, skip for date extraction
        (re.compile(r"community\s+(end\s+of\s+life|eol)|upstream\s+eol", re.I), "upstreamEol"),
        # version_col — major version identifier
        (re.compile(
            r"^(?:postgresql|mysql|aurora|community)\s+major\s+version$|"
            r"^(?:postgresql|mysql|aurora|mariadb)\s+version$|"
            r"^major\s+version$",
            re.I,
        ), "version_col"),
        (re.compile(r"release\s+date", re.I), "release_date"),
    ],
    "amazon-opensearch": [
        (re.compile(r"end\s*of\s*life|eol|end\s*of\s*support",           re.I), "eolDate"),
        (re.compile(r"support\s*end|end\s*of\s*standard",                re.I), "supportEndDate"),
        (re.compile(r"(opensearch\s*)?version$",                         re.I), "version_col"),
        (re.compile(r"release\s*date",                                   re.I), "release_date"),
    ],
    "_elasticache": [
        # "End of Extended Support and version EOL" → eolDate
        # Must check extended BEFORE standard to avoid standard stealing the match
        (re.compile(r"end\s*of\s*extended\s*support|extended.+eol|eol\s*date|deprecation\s*date", re.I), "eolDate"),
        # "End of Standard Support" → supportEndDate
        (re.compile(r"end\s*of\s*standard\s*support|end\s*of\s*support(?!\s*and)|standard\s*support\s*end", re.I), "supportEndDate"),
        # "Major Engine Version" / "Engine Version" / "Redis Version" / "Source Major Version" → version_col
        (re.compile(r"(source\s+)?(major\s*)?(engine\s*|redis\s*|valkey\s*)?version$", re.I), "version_col"),
        (re.compile(r"release\s*date",                                    re.I), "release_date"),
    ],
}

# Skip-fields — dates in these columns are informational, not lifecycle dates
_SKIP_DATE_FIELDS = {"release_date", "version_col", "upstreamEol"}


def _get_col_map(product: str) -> list[tuple[re.Pattern, str]]:
    """Return the column map for a product slug."""
    if product == "amazon-eks":
        return _GENERIC_COL_MAPS["amazon-eks"]
    if product in ("amazon-rds-postgresql", "amazon-rds-mysql", "amazon-rds-mariadb",
                   "amazon-aurora-postgresql", "amazon-aurora-mysql"):
        return _GENERIC_COL_MAPS["_rds_aurora"]
    if product == "amazon-opensearch":
        return _GENERIC_COL_MAPS["amazon-opensearch"]
    if product in ("amazon-elasticache-redis", "amazon-elasticache-memcached"):
        return _GENERIC_COL_MAPS["_elasticache"]
    return _GENERIC_COL_MAPS["_rds_aurora"]  # reasonable fallback


def _classify_generic_header(text: str, col_map: list[tuple[re.Pattern, str]]) -> Optional[str]:
    for pattern, field in col_map:
        if pattern.search(text.strip()):
            return field
    return None


def _parse_generic_html_tables(
    html: str, product: str, version: str, variants: list[str]
) -> Optional[dict]:
    """Parse all tables in an AWS docs HTML page for a version lifecycle row.

    Handles EKS, RDS, Aurora, OpenSearch, ElastiCache pages generically.
    Returns a result dict or None if version not found.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.debug("beautifulsoup4 not installed — skipping generic HTML table parse")
        return None

    col_map = _get_col_map(product)
    soup    = BeautifulSoup(html, "lxml")
    tables  = soup.find_all("table")
    logger.debug("Generic HTML parse: %d tables in page (product=%s)", len(tables), product)

    all_headers_seen: list[list[str]] = []

    for table_idx, table in enumerate(tables):
        # ── Detect and normalize headers ──────────────────────────────────
        header_cells = table.find_all("th")
        if not header_cells:
            first_row = table.find("tr")
            header_cells = first_row.find_all("td") if first_row else []

        # Normalize internal whitespace so multi-line headers classify correctly
        headers = [" ".join(c.get_text().split()) for c in header_cells]
        all_headers_seen.append(headers)

        mapped: dict[int, str] = {}
        for idx, hdr in enumerate(headers):
            field = _classify_generic_header(hdr, col_map)
            if field:
                mapped[idx] = field

        logger.debug("Table %d: headers=%s  mapped=%s", table_idx, headers, mapped)

        has_lifecycle_col = any(f not in _SKIP_DATE_FIELDS for f in mapped.values())
        if not has_lifecycle_col:
            logger.debug("Table %d: no lifecycle columns — skipping", table_idx)
            continue

        # Identify the version column index (if any)
        version_col_idx: Optional[int] = next(
            (idx for idx, f in mapped.items() if f == "version_col"), None
        )
        logger.debug("Table %d: version_col_idx=%s", table_idx, version_col_idx)

        # ── Scan data rows ────────────────────────────────────────────────
        data_rows: list[str] = []  # collect for debug/diagnostic output

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            cell_texts = [" ".join(c.get_text(separator=" ", strip=True).split()) for c in cells]
            row_text   = " | ".join(cell_texts)
            data_rows.append(row_text)

            # ── Version matching: check version column ONLY ───────────────
            # Rationale: checking full row_text causes false matches — "14"
            # matches inside date strings like "2024-05-14".
            matched_variant: Optional[str] = None

            if version_col_idx is not None and version_col_idx < len(cell_texts):
                version_cell = cell_texts[version_col_idx]
                for variant in variants:
                    escaped = re.escape(variant)
                    if re.search(r"(?:^|\s|,)" + escaped + r"(?:\s|,|$)", version_cell, re.I):
                        matched_variant = variant
                        break
                if not matched_variant and logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "  Table %d row: version_cell=%r  variants=%s  → no match",
                        table_idx, version_cell, variants
                    )
            else:
                for variant in variants:
                    escaped = re.escape(variant)
                    if re.search(r"(?:^|\|\s*)" + escaped + r"\s*(?:\||$)", row_text, re.I):
                        matched_variant = variant
                        break

            if not matched_variant:
                continue

            logger.debug("Matched variant %r in row (table %d): %r",
                         matched_variant, table_idx, row_text[:200])

            # ── Extract dates from lifecycle columns ──────────────────────
            found:        dict[str, str] = {}
            placeholders: dict[str, str] = {}

            for col_idx, field in mapped.items():
                if field in _SKIP_DATE_FIELDS:
                    continue
                if col_idx >= len(cell_texts):
                    continue
                raw = cell_texts[col_idx]
                if not raw:
                    continue
                if _is_placeholder_date(raw):
                    placeholders[field] = raw
                    logger.debug("  col %d (%s): placeholder %r", col_idx, field, raw)
                    continue
                d = _normalize_date_str(raw)
                if d:
                    found[field] = d
                    logger.debug("  col %d (%s): parsed %r → %s", col_idx, field, raw, d)
                else:
                    logger.debug("  col %d (%s): %r — unparseable", col_idx, field, raw)

            logger.debug("Extracted: %s  placeholders: %s", found, placeholders)
            return {
                "matched_variant":    matched_variant,
                "row_text":           row_text,
                "eolDate":            found.get("eolDate"),
                "supportEndDate":     found.get("supportEndDate"),
                "upstreamEol":        found.get("upstreamEol"),
                "table_headers":      headers,
                "placeholders":       placeholders,
                "matchedLifecycleTable": True,
                "table_idx":          table_idx,
            }

    if not all_headers_seen:
        return None  # no tables at all in page

    # Lifecycle tables existed but version row was not found.
    # Return diagnostic dict so the caller can decide whether to try next URL
    # or return a meaningful needs_review response.
    lifecycle_tables = [h for h in all_headers_seen if h]  # non-empty header lists
    last_data_rows   = data_rows[:20] if "data_rows" in dir() else []  # rows from last lifecycle table

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "No version row found. Requested variants: %s\n"
            "  Lifecycle table headers seen: %s\n"
            "  Sample rows (first 20):\n    %s",
            variants,
            lifecycle_tables,
            "\n    ".join(last_data_rows[:20]) or "(none)",
        )

    return {
        "matched_variant":         None,
        "matchedLifecycleTable":   bool(lifecycle_tables),
        "allHeadersSeen":          lifecycle_tables,
        "sampleRows":              last_data_rows[:20],
        "requestedVersionVariants": variants,
        "reason":                  (
            f"Lifecycle table(s) found but version row for {variants!r} not present. "
            "Check sampleRows to see what versions are listed."
        ),
    }


def _generic_html_to_result(
    parsed: dict, product: str, version: str, source_url: str, now: str
) -> dict:
    """Convert generic parsed HTML table row into a validation result dict."""
    eol_date    = parsed.get("eolDate")
    support_end = parsed.get("supportEndDate")
    # At least one lifecycle date must be present to be useful
    any_date    = eol_date or support_end
    date_count  = sum(1 for v in [eol_date, support_end] if v)
    confidence  = "HIGH" if date_count >= 2 else "MEDIUM" if any_date else "LOW"
    v_status    = "verified" if confidence in ("HIGH", "MEDIUM") else "needs_review"

    note_parts = []
    for field, label in [("eolDate", "eol"), ("supportEndDate", "support_end"), ("upstreamEol", "upstream_eol")]:
        if parsed.get(field):
            note_parts.append(f"{label}={parsed[field]}")

    placeholders = parsed.get("placeholders", {})

    if not any_date:
        # Special case: version row found but official dates say "Not announced"
        if placeholders:
            placeholder_summary = "; ".join(f"{f}={v!r}" for f, v in placeholders.items())
            return {
                "product": product, "version": version,
                "validationStatus": "needs_review", "confidence": "MEDIUM",
                "source": "aws_official_docs", "officialSourceUrl": source_url,
                "matchedVariant": parsed["matched_variant"], "fetchMethod": "direct_html",
                "matchedSection": parsed["row_text"][:300],
                "notes": f"Official AWS page lists lifecycle date as not yet announced: {placeholder_summary}",
            }
        return {
            "product": product, "version": version,
            "validationStatus": "needs_review", "confidence": "LOW",
            "source": "aws_official_docs", "officialSourceUrl": source_url,
            "matchedVariant": parsed["matched_variant"], "fetchMethod": "direct_html",
            "matchedSection": parsed["row_text"][:300],
            "notes": "Version row found but no lifecycle dates extracted",
        }

    return {
        "product":                product,
        "version":                version,
        "validationStatus":       v_status,
        "confidence":             confidence,
        "source":                 "aws_official_docs",
        "lifecycle_source":       "VERIFIED_AWS_OFFICIAL",
        "validatedBy":            "aws_mcp+direct_aws_docs",
        "eolDate":                eol_date,
        "supportEndDate":         support_end,
        "extendedSupportEndDate": None,
        "officialSourceUrl":      source_url,
        "matchedVariant":         parsed["matched_variant"],
        "fetchMethod":            "direct_html",
        "lastValidatedAt":        now,
        "is_stale":               False,
        "manual_override":        False,
        "conflict":               False,
        "requiresManualReview":   v_status != "verified",
        "notes":                  "Direct AWS docs HTML parse. " + ", ".join(note_parts),
        "matchedSection":         parsed["row_text"][:300],
    }


def _fetch_direct_html(url: str) -> Optional[str]:
    """Fetch an official AWS docs page directly via requests.

    Only accepts docs.aws.amazon.com URLs. Returns HTML string or None.
    """
    if not url.startswith("https://docs.aws.amazon.com/"):
        logger.warning("Refused direct fetch of non-AWS-docs URL: %s", url)
        return None
    try:
        import requests
        resp = requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; aws-eol-monitor/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        if resp.status_code == 200:
            logger.debug("Direct fetch %s → %d chars", url, len(resp.text))
            return resp.text
        logger.debug("Direct fetch %s → HTTP %d", url, resp.status_code)
        return None
    except Exception as exc:
        logger.debug("Direct fetch %s failed: %s", url, exc)
        return None


# ── EKS plain-text section parser ────────────────────────────────────────────
# kubernetes-versions-extended.html and similar EKS pages do not use <table>
# elements — they use definition lists, cards, or prose sections. This parser
# scans the extracted plain text for version headings and nearby support dates.

_EKS_DATE_KEYWORDS = [
    ("end of standard support",  "supportEndDate"),
    ("end of extended support",  "eolDate"),
    ("extended support",         "eolDate"),       # fallback keyword
    ("standard support",         "supportEndDate"), # fallback keyword
]


def _parse_eks_plain_text(plain: str, version: str, variants: list[str]) -> Optional[dict]:
    """Parse EKS lifecycle dates from extracted plain text.

    Searches for a wide context window around the version mention, then
    looks for date keywords within that window.

    Returns None if version not found. Returns a result dict with dates or
    a diagnostic dict if version found but no dates.
    """
    # Find the version in plain text
    matched_variant: Optional[str] = None
    match_start = match_end = -1

    for variant in variants:
        pattern = r"(?<![a-zA-Z0-9\.])" + re.escape(variant) + r"(?![a-zA-Z0-9\.])"
        m = re.search(pattern, plain, re.I)
        if m:
            matched_variant = variant
            match_start, match_end = m.start(), m.end()
            break

    if not matched_variant:
        return None

    # Use a wide context window: ±2000 chars
    ctx_start = max(0, match_start - 400)
    ctx_end   = min(len(plain), match_end + 2000)
    section   = plain[ctx_start:ctx_end]
    logger.debug("EKS plain text: matched variant %r, context window %d chars", matched_variant, len(section))

    found: dict[str, str] = {}
    for keyword, field in _EKS_DATE_KEYWORDS:
        if field in found:
            continue  # already found a better match for this field
        # Find all dates near the keyword
        pattern = re.compile(
            re.escape(keyword) + r".{0,120}?(\d{4}-\d{2}-\d{2})"
            r"|(\d{4}-\d{2}-\d{2}).{0,120}?" + re.escape(keyword),
            re.I | re.S,
        )
        m = pattern.search(section)
        if m:
            date_str = m.group(1) or m.group(2)
            d = _normalize_date_str(date_str)
            if d:
                found[field] = d
                logger.debug("  EKS: keyword=%r → %s=%s", keyword, field, d)

    if not found:
        # Last resort: collect all ISO dates in section, skip the earliest (likely release date)
        all_dates = sorted(set(re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", section)))
        logger.debug("  EKS: no keyword dates found. All ISO dates in section: %s", all_dates)
        if len(all_dates) >= 2:
            # Skip first (release date), use remaining as support end candidates
            found["supportEndDate"] = all_dates[1]
            if len(all_dates) >= 3:
                found["eolDate"] = all_dates[2]
            # Mark as low confidence since no keyword anchoring
            return {
                "matched_variant": matched_variant,
                "section":         section[:400],
                "eolDate":         found.get("eolDate"),
                "supportEndDate":  found.get("supportEndDate"),
                "confidence":      "LOW",
                "note":            "Dates inferred by position, not keyword anchoring",
            }
        return {
            "matched_variant": matched_variant,
            "section":         section[:400],
            "eolDate":         None,
            "supportEndDate":  None,
            "confidence":      "LOW",
            "note":            "Version found in EKS plain text but no lifecycle dates near it",
        }

    confidence = "HIGH" if ("eolDate" in found and "supportEndDate" in found) else "MEDIUM"
    return {
        "matched_variant": matched_variant,
        "section":         section[:400],
        "eolDate":         found.get("eolDate"),
        "supportEndDate":  found.get("supportEndDate"),
        "confidence":      confidence,
        "note":            "EKS plain-text keyword extraction",
    }


# ── Date normalization ────────────────────────────────────────────────────────

_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


# Cell values that mean "no date available" — never treat as lifecycle date
_PLACEHOLDER_DATE_RE = re.compile(
    r"^\s*(not\s+announced|not\s+available|n/?a|tbd|tba|—|–|-|\.{2,}|none|pending|unknown)\s*$",
    re.I,
)


def _is_placeholder_date(raw: str) -> bool:
    return bool(_PLACEHOLDER_DATE_RE.match(raw))


def _normalize_date_str(raw: str) -> Optional[str]:
    """Parse a date string into YYYY-MM-DD.

    Handles:
      2025-01-15          ISO format
      January 15, 2025    Long month name with day
      Jan 15, 2025        Short month name with day
      15 January 2025     Day-first
      January 2025        Month-year only (day defaults to 01)
    Returns None for unparseable or placeholder strings.
    """
    raw = " ".join(raw.split())  # normalize internal whitespace
    raw = raw.strip()

    if _is_placeholder_date(raw):
        return None

    # YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw

    # "January 15, 2025" / "Jan 15, 2025" / "January 15 2025"
    m = re.match(r"^([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})$", raw)
    if m:
        month = _MONTH_MAP.get(m.group(1).lower())
        if month:
            return f"{m.group(3)}-{month}-{m.group(2).zfill(2)}"

    # "15 January 2025"
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})$", raw)
    if m:
        month = _MONTH_MAP.get(m.group(2).lower())
        if month:
            return f"{m.group(3)}-{month}-{m.group(1).zfill(2)}"

    # "January 2025" / "Jan 2025" (no day — use 01)
    m = re.match(r"^([A-Za-z]{3,9})\s+(\d{4})$", raw)
    if m:
        month = _MONTH_MAP.get(m.group(1).lower())
        if month:
            return f"{m.group(2)}-{month}-01"

    # "1/31/2027" / "01/31/2027" (M/DD/YYYY or MM/DD/YYYY)
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw)
    if m:
        try:
            month_n = int(m.group(1))
            day_n   = int(m.group(2))
            year    = m.group(3)
            if 1 <= month_n <= 12 and 1 <= day_n <= 31:
                return f"{year}-{month_n:02d}-{day_n:02d}"
        except ValueError:
            pass

    # "2025/01/31" (YYYY/MM/DD)
    m = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})$", raw)
    if m:
        try:
            month_n = int(m.group(2))
            day_n   = int(m.group(3))
            year    = m.group(1)
            if 1 <= month_n <= 12 and 1 <= day_n <= 31:
                return f"{year}-{month_n:02d}-{day_n:02d}"
        except ValueError:
            pass

    # "Q1 2025" — skip; too ambiguous
    return None


# ── Version variants ──────────────────────────────────────────────────────────

def _version_variants(product: str, version: str) -> list[str]:
    """Return all text strings to search for in page content.

    Product-aware: generates service-specific aliases so table cells match even
    when the docs use "Redis OSS 7" for version "7.0", etc.
    """
    variants = [version]

    # Versions like "python3.9" → also "Python 3.9", "3.9"
    m = re.match(r"([a-zA-Z]+)(\d+\.\d+.*)", version)
    if m:
        lang, ver = m.group(1), m.group(2)
        variants.append(f"{lang.capitalize()} {ver}")
        variants.append(ver)

    # ElastiCache: lifecycle table uses "Redis OSS v6" (major-only, v-prefix)
    # as well as "Redis OSS 7" / "Redis OSS 7.0" in other pages.
    if "elasticache" in product:
        mj = re.match(r"^(\d+)(?:\.\d+)?$", version)
        if mj:
            major = mj.group(1)
            variants += [
                major,
                f"Redis OSS v{major}",      # actual EOL table format: "Redis OSS v6"
                f"Redis OSS {major}",
                f"Redis OSS {version}",
                f"Valkey v{major}",
                f"Valkey {major}",
                f"Valkey {version}",
                f"Redis v{major}",
                f"Redis {major}",
                f"Redis {version}",
            ]

    # RDS PostgreSQL: table uses "PostgreSQL 15", "PostgreSQL 16" (major only)
    # User may query "15.4" or "15" — generate "PostgreSQL 15" variant
    if "rds-postgresql" in product:
        mj = re.match(r"^(\d+)(?:\.\d+.*)?$", version)
        if mj:
            major = mj.group(1)
            variants += [f"PostgreSQL {major}", major]

    # RDS MySQL: table uses "MySQL 8.4", "MySQL 8.0", "MySQL 5.7*"
    # User may query "8.0" or "8.0.35" — generate "MySQL 8.0" variant
    if "rds-mysql" in product:
        mj = re.match(r"^(\d+\.\d+)(?:\.\d+.*)?$", version)
        if mj:
            major_minor = mj.group(1)
            major = major_minor.split(".")[0]
            variants += [f"MySQL {major_minor}", f"MySQL {major_minor}*", major_minor]
        else:
            mj2 = re.match(r"^(\d+)$", version)
            if mj2:
                variants.append(f"MySQL {version}")

    # Aurora PostgreSQL: table uses "PostgreSQL 14", "PostgreSQL 15" as the key column
    # Aurora major version column has "Aurora PostgreSQL 3." etc — but we key on PostgreSQL version
    if "aurora-postgresql" in product:
        mj = re.match(r"^(\d+)(?:\.\d+.*)?$", version)
        if mj:
            major = mj.group(1)
            variants += [f"PostgreSQL {major}", major]

    # Aurora MySQL: table has two version columns:
    #   "Community major version" = "MySQL 8.0", "MySQL 5.7"
    #   "Aurora major version"    = "Aurora MySQL version 3", "Aurora MySQL version 2"
    # User may query "3" (Aurora major), "3.04.2" (Aurora minor), or "8.0" (community)
    if "aurora-mysql" in product:
        mj = re.match(r"^(\d+)(?:\.\d+.*)?$", version)
        if mj:
            aurora_major = mj.group(1)
            # Map Aurora major → community MySQL major.minor
            _aurora_to_mysql = {"1": "5.6", "2": "5.7", "3": "8.0", "8": "8.4"}
            community = _aurora_to_mysql.get(aurora_major)
            variants += [f"Aurora MySQL version {aurora_major}", aurora_major]
            if community:
                variants += [f"MySQL {community}", community]

    return list(dict.fromkeys(variants))


# ── MCP text / URL helpers ────────────────────────────────────────────────────

def _text_from_result(result) -> str:
    text = ""
    if hasattr(result, "content"):
        for block in result.content:
            if hasattr(block, "text"):
                text += block.text + "\n"
            elif hasattr(block, "data"):
                text += str(block.data) + "\n"
    else:
        text = str(result)
    return text


def _extract_urls(text: str) -> list[str]:
    urls = re.findall(r'https://docs\.aws\.amazon\.com[^\s\)\]"\'>,]+', text)
    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        u = u.rstrip(".,)")
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


# URL path segments that indicate the page is NOT a lifecycle/EOL reference
_REJECT_URL_RE = re.compile(
    r"CacheNodes|SupportedTypes|SupportedType|"
    r"instance.type|node.type|"
    r"pricing|charges|billing|cost|"
    r"migration.guide|upgrade.guide|"
    r"/cdk/|/api/|/sdk/|/cli/|/cdk-guide/|"
    r"bedrock|sagemaker|rekognition|"
    r"create-cluster|getting-started|what-is-aws$",
    re.I,
)

# Substrings in URL path that strongly suggest it IS a lifecycle/version page
_PREFER_URL_KEYWORDS = [
    "lifecycle", "deprecation", "end-of-support", "end-of-standard",
    "extended-support", "engine-versions", "version-management",
    "kubernetes-versions", "version-support", "supported-versions",
    "supported-engine-versions", "runtimes-list-deprecated",
]


def _url_score(url: str) -> int:
    """Score a URL — higher is better. Returns -999 for rejected pages."""
    if _REJECT_URL_RE.search(url):
        return -999
    score = 0
    url_lower = url.lower()
    for kw in _PREFER_URL_KEYWORDS:
        if kw in url_lower:
            score += 2
    return score


def _rank_candidate_urls(
    search_urls: list[str], url_hints: list[str], extra_urls: list[str]
) -> tuple[list[str], list[str]]:
    """Return (accepted_urls, rejected_urls) in priority order.

    Priority: extra_urls (pinned) → hint-matched search URLs → other search URLs.
    URLs scoring -999 are moved to rejected_urls and never tried.
    """
    # Extra URLs are always tried first (pinned canonical pages)
    pinned   = [u for u in extra_urls if _url_score(u) >= 0]
    rejected = [u for u in extra_urls if _url_score(u) < 0]

    hinted: list[str]   = []
    fallback: list[str] = []
    for u in search_urls:
        if u in pinned:
            continue
        score = _url_score(u)
        if score < 0:
            rejected.append(u)
            logger.debug("URL rejected (score=%d): %s", score, u)
            continue
        bucket = hinted if any(h.lower() in u.lower() for h in url_hints) else fallback
        bucket.append(u)

    # Sort hint-matched and fallback by score descending
    hinted.sort(key=_url_score, reverse=True)
    fallback.sort(key=_url_score, reverse=True)

    ordered: list[str] = []
    seen: set[str]     = set()
    for u in pinned + hinted + fallback:
        if u not in seen:
            seen.add(u)
            ordered.append(u)

    return ordered, rejected


# ── MCP plain-text version search ────────────────────────────────────────────

def _find_version_in_content(content: str, variants: list[str]) -> Optional[tuple[str, str]]:
    for variant in variants:
        pattern = r"(?<![a-zA-Z0-9_])" + re.escape(variant) + r"(?![a-zA-Z0-9_])"
        m = re.search(pattern, content, re.I)
        if m:
            start = max(0, m.start() - 600)
            end   = min(len(content), m.end() + 600)
            return variant, content[start:end]
    return None


def _extract_dates_from_section(section: str, product: str) -> dict:
    found: dict[str, str] = {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if "lambda" in product:
        patterns = [
            (r"(?:deprecat\w*|end.of.support|end.of.life|EOL)[^\d]{0,100}(\d{4}-\d{2}-\d{2})", "eolDate"),
            (r"(\d{4}-\d{2}-\d{2})[^\d]{0,100}(?:deprecat\w*|end.of.support|end.of.life)", "eolDate"),
            (r"(?:block[^\d]{0,30}(?:function.)?creat\w*)[^\d]{0,100}(\d{4}-\d{2}-\d{2})", "supportEndDate"),
            (r"(\d{4}-\d{2}-\d{2})[^\d]{0,100}(?:block[^\d]{0,30}(?:function.)?creat\w*)", "supportEndDate"),
            (r"(?:block[^\d]{0,30}(?:function.)?updat\w*)[^\d]{0,100}(\d{4}-\d{2}-\d{2})", "blockUpdateDate"),
            (r"(\d{4}-\d{2}-\d{2})[^\d]{0,100}(?:block[^\d]{0,30}(?:function.)?updat\w*)", "blockUpdateDate"),
        ]
    elif "eks" in product:
        patterns = [
            (r"(?:end.of.standard.support)[^\d]{0,100}(\d{4}-\d{2}-\d{2})", "supportEndDate"),
            (r"(\d{4}-\d{2}-\d{2})[^\d]{0,100}(?:end.of.standard.support)", "supportEndDate"),
            (r"(?:end.of.extended.support)[^\d]{0,100}(\d{4}-\d{2}-\d{2})", "eolDate"),
            (r"(\d{4}-\d{2}-\d{2})[^\d]{0,100}(?:end.of.extended.support)", "eolDate"),
        ]
    else:
        patterns = [
            (r"(?:end.of.(?:standard.)?support|deprecat\w+|end.of.life|EOL)[^\d]{0,100}(\d{4}-\d{2}-\d{2})", "eolDate"),
            (r"(\d{4}-\d{2}-\d{2})[^\d]{0,100}(?:end.of.(?:standard.)?support|deprecat\w+|end.of.life)", "eolDate"),
        ]

    for pattern, field in patterns:
        m = re.search(pattern, section, re.I | re.S)
        if m and field not in found:
            d = _normalize_date_str(m.group(1))
            if d:
                found[field] = d

    if not found:
        all_dates = sorted(set(re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", section)))
        past   = [d for d in all_dates if d < today]
        future = [d for d in all_dates if d >= today]
        if past:
            return {"eolDate": past[-1], "supportEndDate": None, "confidence": "LOW",
                    "extractionNote": f"Fallback: most recent past date ({past[-1]}). Manual review recommended.",
                    "matchedSection": section[:400]}
        if future:
            return {"eolDate": future[0], "supportEndDate": None, "confidence": "LOW",
                    "extractionNote": f"Fallback: first future date ({future[0]}). Manual review recommended.",
                    "matchedSection": section[:400]}
        return {"eolDate": None, "supportEndDate": None, "confidence": "LOW",
                "extractionNote": "No lifecycle dates found in version section",
                "matchedSection": section[:400]}

    eol = found.get("eolDate") or found.get("blockUpdateDate")
    return {
        "eolDate":        eol,
        "supportEndDate": found.get("supportEndDate"),
        "blockUpdateDate": found.get("blockUpdateDate"),
        "confidence":     "HIGH" if len(found) >= 2 else "MEDIUM",
        "extractionNote": f"Extracted {len(found)} date field(s) via regex",
        "matchedSection": section[:400],
    }


def _build_result(
    product: str, version: str, extracted: dict,
    source_url: str, matched_variant: str, fetch_method: str, now: str,
) -> dict:
    eol_date   = extracted.get("eolDate")
    confidence = extracted.get("confidence", "LOW")
    if not eol_date:
        return {
            "product": product, "version": version,
            "validationStatus": "needs_review", "confidence": confidence,
            "source": "aws_official_docs", "officialSourceUrl": source_url,
            "matchedVariant": matched_variant, "fetchMethod": fetch_method,
            "notes": extracted.get("extractionNote", "Version found but no dates extracted"),
            "matchedSection": extracted.get("matchedSection", ""),
        }
    v_status = "verified" if confidence in ("HIGH", "MEDIUM") else "needs_review"
    return {
        "product": product, "version": version,
        "validationStatus": v_status, "confidence": confidence,
        "source": "aws_official_docs", "lifecycle_source": "VERIFIED_AWS_OFFICIAL",
        "validatedBy": "aws_mcp",
        "eolDate": eol_date, "supportEndDate": extracted.get("supportEndDate"),
        "blockUpdateDate": extracted.get("blockUpdateDate"),
        "extendedSupportEndDate": None,
        "officialSourceUrl": source_url, "matchedVariant": matched_variant,
        "fetchMethod": fetch_method, "lastValidatedAt": now,
        "is_stale": False, "manual_override": False, "conflict": False,
        "requiresManualReview": v_status != "verified",
        "notes": extracted.get("extractionNote", ""),
        "matchedSection": extracted.get("matchedSection", ""),
    }


# ── MCP session helpers ───────────────────────────────────────────────────────

async def _read_url(session, read_tool: str, url: str) -> str:
    try:
        return _text_from_result(await session.call_tool(read_tool, arguments={"url": url}))
    except Exception as exc:
        logger.debug("read_documentation(%s) failed: %s", url, exc)
        return ""


async def _read_section(session, sections_tool: str, url: str, section: str) -> str:
    try:
        return _text_from_result(await session.call_tool(
            sections_tool, arguments={"url": url, "sections": [section]}
        ))
    except Exception as exc:
        logger.debug("read_sections(%s, %r) failed: %s", url, section, exc)
        return ""


# ── Main validator ────────────────────────────────────────────────────────────

async def _mcp_list_tools() -> dict:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return {"connected": False,
                "error": "mcp package not installed. Run: pip install -r requirements-mcp.txt"}
    params = StdioServerParameters(command=MCP_SERVER_CMD, args=MCP_SERVER_ARGS, env=MCP_SERVER_ENV)
    try:
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                tr = await session.list_tools()
                tools = [t.name for t in tr.tools]
                return {"connected": True, "server": "awslabs.aws-documentation-mcp-server",
                        "tools": tools, "tool_count": len(tools)}
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


async def _direct_html_loop(
    product: str, version: str, variants: list[str], is_lambda: bool,
    candidate_urls: list[str], rejected_urls: list[str], tested_urls: list[str], now: str,
) -> dict:
    """Inner URL iteration loop for direct-HTTP validation (shared between MCP and --direct-html paths)."""
    for url in candidate_urls[:4]:
        tested_urls.append(url)
        logger.debug("Direct HTML: %s", url)
        html = _fetch_direct_html(url)
        if not html:
            continue
        logger.debug("  HTML: %d chars", len(html))

        if is_lambda:
            parsed = _parse_lambda_html_tables(html, version, variants)
            if parsed:
                return _lambda_html_to_result(parsed, product, version, url, now)
        else:
            parsed = _parse_generic_html_tables(html, product, version, variants)
            if parsed is not None:
                if parsed.get("matched_variant"):
                    return _generic_html_to_result(parsed, product, version, url, now)
                else:
                    logger.debug(
                        "  Generic table: version not in lifecycle table.\n"
                        "  Headers: %s\n  Reason: %s\n  Sample rows:\n    %s",
                        parsed.get("allHeadersSeen"), parsed.get("reason"),
                        "\n    ".join(parsed.get("sampleRows", [])[:10]),
                    )
                    if "eks" not in product:
                        continue
                    # EKS: fall through to plain-text

        # Plain-text fallback (all products with 0 HTML tables, or EKS after table miss)
        try:
            from bs4 import BeautifulSoup
            plain = BeautifulSoup(html, "lxml").get_text(separator="\n")
        except ImportError:
            plain = re.sub(r"<[^>]+>", " ", html)

        logger.debug("  Plain text: %d chars", len(plain))

        if "eks" in product:
            eks_parsed = _parse_eks_plain_text(plain, version, variants)
            if eks_parsed:
                logger.debug(
                    "  EKS plain-text: matched=%r eolDate=%s supportEndDate=%s confidence=%s",
                    eks_parsed.get("matched_variant"), eks_parsed.get("eolDate"),
                    eks_parsed.get("supportEndDate"), eks_parsed.get("confidence"),
                )
                if eks_parsed.get("eolDate") and eks_parsed.get("confidence") in ("HIGH", "MEDIUM"):
                    extracted = {
                        "eolDate":        eks_parsed["eolDate"],
                        "supportEndDate": eks_parsed.get("supportEndDate"),
                        "confidence":     eks_parsed["confidence"],
                        "matchedSection": eks_parsed.get("section", ""),
                    }
                    return _build_result(
                        product, version, extracted, url,
                        eks_parsed["matched_variant"], "direct_html_text_eks", now,
                    )
                logger.debug("  EKS: confidence=%s or no eolDate — try next URL",
                             eks_parsed.get("confidence"))
            continue

        match = _find_version_in_content(plain, variants)
        if match:
            matched_variant, section_text = match
            extracted = _extract_dates_from_section(section_text, product)
            return _build_result(product, version, extracted, url, matched_variant, "direct_html_text", now)

    return {
        "product": product, "version": version,
        "validationStatus": "needs_review", "confidence": "LOW",
        "source": "aws_official_docs",
        "notes": (f"Version '{version}' (variants: {variants}) not found in direct HTML on "
                  f"{len(tested_urls)} URL(s)"),
        "testedUrls":   tested_urls,
        "rejectedUrls": rejected_urls,
        "recommendation": (
            "Run --verbose to see table headers found per URL. "
            "If the lifecycle table exists but version row is missing, "
            "the version may have been removed from docs. "
            "Otherwise add the correct lifecycle page URL to PRODUCT_CONFIG extra_urls."
        ),
    }


async def _mcp_validate_lifecycle(product: str, version: str, skip_mcp: bool = False) -> dict:
    """Three-tier validation: MCP read_documentation → MCP read_sections → direct HTML.

    Never raises. Always returns a dict with validationStatus.
    When skip_mcp=True, jumps directly to the direct-HTTP fetch path.
    """
    cfg = PRODUCT_CONFIG.get(product)
    if not cfg:
        return {"product": product, "version": version,
                "validationStatus": "not_found", "confidence": "LOW",
                "notes": f"Product '{product}' not in PRODUCT_CONFIG."}

    variants      = _version_variants(product, version)
    url_hints     = cfg["url_hints"]
    extra_urls    = cfg["extra_urls"]
    now           = datetime.now(timezone.utc).isoformat()
    is_lambda     = "lambda" in product
    rejected_urls: list[str] = []
    tested_urls:   list[str] = []

    if skip_mcp:
        # Direct-HTTP-only path: skip MCP entirely, go straight to direct HTML fetch
        try:
            candidate_urls, rejected_urls = _rank_candidate_urls([], url_hints, extra_urls)
            logger.debug("Direct-HTML mode. Candidate URLs (%d): %s", len(candidate_urls), candidate_urls)
            return await _direct_html_loop(
                product, version, variants, is_lambda, candidate_urls,
                rejected_urls, tested_urls, now,
            )
        except Exception as exc:
            logger.error("Direct HTML validation failed for %s/%s: %s", product, version, exc, exc_info=True)
            return {"product": product, "version": version,
                    "validationStatus": "needs_review", "confidence": "LOW",
                    "notes": f"Direct HTML error: {exc}"}

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return {"product": product, "version": version,
                "validationStatus": "not_configured", "confidence": "LOW",
                "notes": "mcp not installed. Run: pip install -r requirements-mcp.txt"}

    search_query  = cfg["search_query"]
    section_names = cfg["sections"]

    params = StdioServerParameters(command=MCP_SERVER_CMD, args=MCP_SERVER_ARGS, env=MCP_SERVER_ENV)

    try:
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()

                tr        = await session.list_tools()
                available = {t.name for t in tr.tools}
                logger.debug("Available MCP tools: %s", sorted(available))

                search_tool   = next((t for t in ("search_documentation", "search") if t in available), None)
                read_tool     = next((t for t in ("read_documentation", "read", "get_documentation") if t in available), None)
                sections_tool = next((t for t in ("read_sections", "get_sections") if t in available), None)

                if not search_tool:
                    return {"product": product, "version": version,
                            "validationStatus": "needs_review", "confidence": "LOW",
                            "notes": f"No search tool. Available: {sorted(available)}"}
                if not read_tool:
                    return {"product": product, "version": version,
                            "validationStatus": "needs_review", "confidence": "LOW",
                            "notes": f"No read_documentation tool. Available: {sorted(available)}"}

                # ── Step 1: search ────────────────────────────────────────
                logger.debug("search_documentation: %r", search_query)
                search_result  = await session.call_tool(search_tool, arguments={"search_phrase": search_query})
                search_text    = _text_from_result(search_result)
                search_urls    = _extract_urls(search_text)
                candidate_urls, rejected_urls = _rank_candidate_urls(search_urls, url_hints, extra_urls)
                logger.debug("Candidate URLs (%d): %s", len(candidate_urls), candidate_urls)
                if rejected_urls:
                    logger.debug("Rejected URLs (%d): %s", len(rejected_urls), rejected_urls)

                if not candidate_urls:
                    return {"product": product, "version": version,
                            "validationStatus": "needs_review", "confidence": "LOW",
                            "notes": "No usable AWS docs URLs in search results (all rejected by URL filter)",
                            "rejectedUrls": rejected_urls}

                # ── Step 2: per-URL: MCP read → MCP sections → direct HTML ──
                tested_urls: list[str] = []

                for url in candidate_urls[:4]:
                    tested_urls.append(url)

                    # ── 2a. MCP read_documentation ────────────────────────
                    logger.debug("read_documentation(%s)", url)
                    page_text = await _read_url(session, read_tool, url)
                    logger.debug("  → %d chars", len(page_text))

                    mcp_version_found = False  # version found in MCP text, but maybe no dates

                    match = _find_version_in_content(page_text, variants)
                    if match:
                        matched_variant, section_text = match
                        logger.debug("  Version matched (MCP read): %r", matched_variant)
                        extracted = _extract_dates_from_section(section_text, product)
                        logger.debug("  Extracted: %s", {k: v for k, v in extracted.items() if k != "matchedSection"})
                        if extracted.get("eolDate") and extracted.get("confidence") in ("HIGH", "MEDIUM"):
                            # Good enough — return from MCP text
                            return _build_result(product, version, extracted, url, matched_variant,
                                                 "mcp_read_documentation", now)
                        # Version found but MCP content is truncated / dates missing.
                        # Skip read_sections for this URL and go straight to direct HTML
                        # (HTML has the complete table; read_sections will also be thin).
                        mcp_version_found = True
                        logger.debug(
                            "  MCP text: version found but confidence=%s eolDate=%s "
                            "→ skipping read_sections, trying direct HTML for same URL",
                            extracted.get("confidence"), extracted.get("eolDate"),
                        )

                    # ── 2b. MCP read_sections (skip if 2a already found version) ──
                    if not mcp_version_found and sections_tool:
                        for sname in section_names:
                            logger.debug("  read_sections(%s, %r)", url, sname)
                            sec_text = await _read_section(session, sections_tool, url, sname)
                            logger.debug("    → %d chars", len(sec_text))
                            if not sec_text:
                                continue
                            match = _find_version_in_content(sec_text, variants)
                            if match:
                                matched_variant, section_text = match
                                logger.debug("    Version matched in section %r: %r", sname, matched_variant)
                                extracted = _extract_dates_from_section(section_text, product)
                                logger.debug("    Extracted: %s", {k: v for k, v in extracted.items() if k != "matchedSection"})
                                if extracted.get("eolDate") and extracted.get("confidence") in ("HIGH", "MEDIUM"):
                                    return _build_result(product, version, extracted, url, matched_variant,
                                                         f"mcp_read_sections/{sname}", now)
                                mcp_version_found = True
                                logger.debug(
                                    "    Section %r: version found but confidence=%s → trying direct HTML",
                                    sname, extracted.get("confidence"),
                                )
                                break  # skip remaining sections, go to direct HTML

                    # 2c. Direct HTML fallback (official AWS docs only)
                    logger.debug("  MCP content insufficient — direct HTML fallback: %s", url)
                    html = _fetch_direct_html(url)
                    if html:
                        logger.debug("  Direct HTML: %d chars", len(html))

                        if is_lambda:
                            # Lambda: structured table parse with Lambda-specific col map
                            parsed = _parse_lambda_html_tables(html, version, variants)
                            if parsed:
                                logger.debug(
                                    "  Lambda table match: variant=%r deprecation=%s block_create=%s block_update=%s",
                                    parsed["matched_variant"], parsed.get("deprecation_date"),
                                    parsed.get("block_create"), parsed.get("block_update"),
                                )
                                return _lambda_html_to_result(parsed, product, version, url, now)
                        else:
                            # EKS, RDS, Aurora, OpenSearch, ElastiCache: generic col-map table parse
                            parsed = _parse_generic_html_tables(html, product, version, variants)
                            if parsed is not None:
                                if parsed.get("matched_variant"):
                                    # Version row found in a lifecycle table
                                    logger.debug(
                                        "  Generic table match: variant=%r eolDate=%s supportEndDate=%s lifecycle_table=%s",
                                        parsed["matched_variant"], parsed.get("eolDate"),
                                        parsed.get("supportEndDate"), parsed.get("matchedLifecycleTable"),
                                    )
                                    return _generic_html_to_result(parsed, product, version, url, now)
                                else:
                                    # Lifecycle tables present but version row not found
                                    logger.debug(
                                        "  Generic table: version not in lifecycle table.\n"
                                        "  Headers: %s\n"
                                        "  Reason: %s\n"
                                        "  Sample rows:\n    %s",
                                        parsed.get("allHeadersSeen"),
                                        parsed.get("reason"),
                                        "\n    ".join(parsed.get("sampleRows", [])[:10]),
                                    )
                                    # For EKS, also try plain-text — EKS pages may mix
                                    # prose sections with zero <table> elements even when
                                    # a lifecycle table-like structure was detected.
                                    if "eks" not in product:
                                        # For other products: lifecycle table is authoritative.
                                        continue
                                    # EKS: fall through to plain-text parser below

                        # Plain-text fallback: only when no lifecycle tables found at all
                        # (or for EKS, when lifecycle table found but version row absent)
                        try:
                            from bs4 import BeautifulSoup
                            plain = BeautifulSoup(html, "lxml").get_text(separator="\n")
                        except ImportError:
                            plain = re.sub(r"<[^>]+>", " ", html)

                        logger.debug("  Plain text from HTML: %d chars", len(plain))

                        # EKS-specific: use wide-window keyword parser
                        if "eks" in product:
                            eks_parsed = _parse_eks_plain_text(plain, version, variants)
                            if eks_parsed:
                                logger.debug(
                                    "  EKS plain-text: matched=%r eolDate=%s supportEndDate=%s confidence=%s",
                                    eks_parsed.get("matched_variant"),
                                    eks_parsed.get("eolDate"),
                                    eks_parsed.get("supportEndDate"),
                                    eks_parsed.get("confidence"),
                                )
                                if eks_parsed.get("eolDate") and eks_parsed.get("confidence") in ("HIGH", "MEDIUM"):
                                    extracted = {
                                        "eolDate":        eks_parsed["eolDate"],
                                        "supportEndDate": eks_parsed.get("supportEndDate"),
                                        "confidence":     eks_parsed["confidence"],
                                        "matchedSection": eks_parsed.get("section", ""),
                                    }
                                    return _build_result(
                                        product, version, extracted, url,
                                        eks_parsed["matched_variant"], "direct_html_text_eks", now,
                                    )
                                # Found version but confidence too low or no dates
                                logger.debug("  EKS: version found but confidence=%s or no eolDate — skip",
                                             eks_parsed.get("confidence"))
                            continue  # try next URL for EKS too

                        match = _find_version_in_content(plain, variants)
                        if match:
                            matched_variant, section_text = match
                            logger.debug("  Version matched in plain text: %r", matched_variant)
                            extracted = _extract_dates_from_section(section_text, product)
                            logger.debug("  Extracted: %s", {k: v for k, v in extracted.items() if k != "matchedSection"})
                            return _build_result(product, version, extracted, url, matched_variant, "direct_html_text", now)

                # ── All strategies exhausted ─────────────────────────────
                logger.debug("Version not found after all strategies. Tested: %s", tested_urls)
                return {
                    "product": product, "version": version,
                    "validationStatus": "needs_review", "confidence": "LOW",
                    "source": "aws_official_docs",
                    "notes": (f"Version '{version}' (variants: {variants}) not found after "
                              f"MCP read + sections + direct HTML on {len(tested_urls)} URL(s)"),
                    "testedUrls":            tested_urls,
                    "rejectedUrls":          rejected_urls,
                    "recommendation": (
                        "Run --verbose to see table headers found per URL. "
                        "If the lifecycle table exists but version row is missing, "
                        "the version may have been removed from docs (try a different URL). "
                        "Otherwise add the correct lifecycle page URL to PRODUCT_CONFIG extra_urls."
                    ),
                }

    except Exception as exc:
        logger.error("MCP validation failed for %s/%s: %s", product, version, exc, exc_info=True)
        return {"product": product, "version": version,
                "validationStatus": "needs_review", "confidence": "LOW",
                "notes": f"MCP error: {exc}"}


# ── Env / storage helpers ─────────────────────────────────────────────────────

def _find_project_root() -> Optional[str]:
    """Walk upward from this file until we find the directory with backend/storage.py."""
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(6):
        candidate = os.path.join(here, "backend", "storage.py")
        if os.path.isfile(candidate):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return None


def _load_env(env_file: Optional[str] = None) -> str:
    """Load environment variables from .env file.

    Priority:
      1. Explicit --env-file path
      2. <project_root>/.env
      3. Current working directory .env
    Returns a string describing what was loaded (for verbose output).
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return "python-dotenv not installed — skipping .env load"

    if env_file:
        if os.path.isfile(env_file):
            load_dotenv(env_file, override=False)
            return f"Loaded env from: {env_file}"
        return f"WARNING: --env-file {env_file!r} not found — no .env loaded"

    # Auto-detect: project root first, then cwd
    root = _find_project_root()
    for candidate in [
        os.path.join(root, ".env") if root else None,
        os.path.join(os.getcwd(), ".env"),
    ]:
        if candidate and os.path.isfile(candidate):
            load_dotenv(candidate, override=False)
            return f"Loaded env from: {candidate}"

    return "No .env file found (searched project root and cwd)"


_PLACEHOLDER_PATTERNS = re.compile(
    r"^\s*(postgresql|postgres|mysql|sqlite)://\s*\.\.\.|"
    r"<[^>]+>|"               # <your-db-url>
    r"YOUR_|your_|REPLACE_",  # YOUR_DB_URL, REPLACE_ME
    re.I,
)


def _is_placeholder(value: str) -> bool:
    """Return True if the value looks like an unfilled placeholder."""
    return bool(_PLACEHOLDER_PATTERNS.search(value)) or value.strip() in ("...", "placeholder", "xxx")


def _diagnose_storage() -> dict:
    """Return a dict showing detected storage env vars — for --verbose output."""
    backend  = os.environ.get("STORAGE_BACKEND", "")
    db_url   = os.environ.get("DATABASE_URL", "")
    data_dir = os.environ.get("EOL_DATA_DIR", "")
    root     = _find_project_root()

    db_display = "(not set)"
    if db_url:
        if _is_placeholder(db_url):
            db_display = f"PLACEHOLDER DETECTED: {db_url[:40]!r} — unset and use .env"
        else:
            db_display = db_url[:20] + "..."

    return {
        "STORAGE_BACKEND": backend or "(not set — will use default 'file')",
        "DATABASE_URL":    db_display,
        "EOL_DATA_DIR":    data_dir or "(not set)",
        "project_root":    root or "(not found)",
        "backend_storage_path": (
            os.path.join(root, "backend", "storage.py") if root else "(unknown)"
        ),
    }


def _save_to_storage(result: dict) -> bool:
    """Save a verified lifecycle result to the configured storage backend.

    Tries two sys.path inserts (project root and backend dir) to locate
    the storage module. Logs actionable diagnostics on failure.
    """
    # Early guard: catch placeholder DATABASE_URL before attempting connection
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url and _is_placeholder(db_url):
        logger.error(
            "DATABASE_URL looks like a placeholder: %r\n"
            "  Run: unset DATABASE_URL  then use --env-file or let .env auto-load.",
            db_url[:60],
        )
        return False

    root = _find_project_root()
    search_paths = []
    if root:
        search_paths.append(root)                        # enables `from backend.storage import ...`
        search_paths.append(os.path.join(root, "backend"))  # enables `from storage import ...`
    # Fallback: relative paths from this file
    search_paths += [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    ]

    last_exc: Optional[Exception] = None
    for path_insert in search_paths:
        if path_insert not in sys.path:
            sys.path.insert(0, path_insert)
        try:
            try:
                from backend.storage import get_storage  # type: ignore
            except ImportError:
                from storage import get_storage  # type: ignore
            get_storage().save_verified_lifecycle(result["product"], result["version"], result)
            logger.debug("Saved via storage path: %s", path_insert)
            return True
        except Exception as exc:
            last_exc = exc
            logger.debug("Storage attempt failed (path=%s): %s", path_insert, exc)

    diag = _diagnose_storage()
    logger.error(
        "Save failed for %s/%s.\n"
        "  Last error:       %s\n"
        "  STORAGE_BACKEND:  %s\n"
        "  DATABASE_URL:     %s\n"
        "  EOL_DATA_DIR:     %s\n"
        "  project_root:     %s\n"
        "  Fix: export these vars or use --env-file /path/to/.env",
        result["product"], result["version"],
        last_exc,
        diag["STORAGE_BACKEND"], diag["DATABASE_URL"],
        diag["EOL_DATA_DIR"],    diag["project_root"],
    )
    return False


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="AWS Documentation MCP lifecycle validator (admin CLI only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m lifecycle.validate_with_mcp_cli --list-tools
  python -m lifecycle.validate_with_mcp_cli --product aws-lambda --version python3.9 --json --verbose
  python -m lifecycle.validate_with_mcp_cli --product aws-lambda --version python3.9 --save --json
  python -m lifecycle.validate_with_mcp_cli --product amazon-eks --version 1.30 --json
        """,
    )
    p.add_argument("--list-tools", action="store_true",
                   help="Proof-of-connect: list available MCP tools then exit")
    p.add_argument("--product", help="Product slug, e.g. aws-lambda")
    p.add_argument("--version", help="Version string, e.g. python3.9")
    p.add_argument("--save",    action="store_true",
                   help="Save to verified_lifecycle storage (only when validationStatus=verified)")
    p.add_argument("--env-file", dest="env_file", metavar="PATH",
                   help="Path to .env file to load (auto-detected from project root if omitted)")
    p.add_argument("--check-storage", action="store_true",
                   help="Show detected storage config and exit")
    p.add_argument("--json",    dest="json_out", action="store_true",
                   help="Output JSON (machine-readable)")
    p.add_argument("--verbose", "-v", action="store_true", help="Enable DEBUG logging")
    p.add_argument("--direct-html", dest="direct_html", action="store_true",
                   help="Skip MCP; fetch lifecycle pages directly via HTTP (faster, no uvx needed)")
    return p


def main() -> int:
    parser = _build_parser()
    args   = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Load .env early so storage env vars are available for --save
    env_msg = _load_env(getattr(args, "env_file", None))
    logger.debug("Env load: %s", env_msg)

    # --check-storage: show detected storage config and exit
    if getattr(args, "check_storage", False):
        diag = _diagnose_storage()
        diag["env_load"] = env_msg
        if args.json_out:
            print(json.dumps(diag, indent=2))
        else:
            print("Storage config diagnostic:")
            for k, v in diag.items():
                print(f"  {k:<25} {v}")
        return 0

    if args.list_tools:
        result = asyncio.run(_mcp_list_tools())
        if args.json_out:
            print(json.dumps(result, indent=2))
        else:
            if result.get("connected"):
                print(f"Connected to: {result['server']}")
                print(f"Tools ({result['tool_count']}):")
                for t in result["tools"]:
                    print(f"  - {t}")
            else:
                print(f"Connection FAILED: {result.get('error')}", file=sys.stderr)
                return 1
        return 0

    if not args.product or not args.version:
        parser.error("--product and --version are required unless using --list-tools")

    skip_mcp = getattr(args, "direct_html", False)
    result = asyncio.run(_mcp_validate_lifecycle(args.product, args.version, skip_mcp=skip_mcp))

    saved = False
    if args.save:
        if result.get("validationStatus") == "verified":
            saved = _save_to_storage(result)
            result["saved"] = saved
            if saved:
                print(f"Saved: {args.product}/{args.version}", file=sys.stderr)
            else:
                diag = _diagnose_storage()
                print(
                    f"WARNING: save failed\n"
                    f"  Run with --verbose to see the full error.\n"
                    f"  STORAGE_BACKEND: {diag['STORAGE_BACKEND']}\n"
                    f"  DATABASE_URL:    {diag['DATABASE_URL']}\n"
                    f"  EOL_DATA_DIR:    {diag['EOL_DATA_DIR']}\n"
                    f"  project_root:    {diag['project_root']}\n"
                    f"  Fix: export env vars or pass --env-file /path/to/.env",
                    file=sys.stderr,
                )
        else:
            print(
                f"Not saved (validationStatus={result.get('validationStatus')!r}"
                f" — only 'verified' results are persisted)",
                file=sys.stderr,
            )

    if args.json_out:
        print(json.dumps(result, indent=2, default=str))
    else:
        status = result.get("validationStatus", "unknown")
        conf   = result.get("confidence", "")
        print(f"Product:    {args.product}/{args.version}")
        print(f"Status:     {status}  (confidence: {conf})")
        print(f"EOL date:   {result.get('eolDate') or '—'}")
        print(f"Support:    {result.get('supportEndDate') or '—'}")
        print(f"BlockCreate:{result.get('blockCreateDate') or '—'}")
        print(f"BlockUpdate:{result.get('blockUpdateDate') or '—'}")
        print(f"Source:     {result.get('officialSourceUrl') or '—'}")
        print(f"Method:     {result.get('fetchMethod') or '—'}")
        if result.get("matchedVariant"):
            print(f"Matched:    {result['matchedVariant']!r}")
        if result.get("notes"):
            print(f"Notes:      {result['notes']}")
        if result.get("testedUrls"):
            print(f"Tested:     {result['testedUrls']}")
        if result.get("rejectedUrls"):
            print(f"Rejected:   {result['rejectedUrls']}")
        if result.get("recommendation"):
            print(f"Tip:        {result['recommendation']}")
        if saved:
            print("Saved:      yes")

    return 0 if result.get("validationStatus") in ("verified", "not_found") else 1


if __name__ == "__main__":
    sys.exit(main())
