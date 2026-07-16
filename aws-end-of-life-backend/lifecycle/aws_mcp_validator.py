"""AWS MCP Lifecycle Validator — provider abstraction.

Current status: STUB (not_configured)
MCP client dependency is not yet installed. This module provides the full
interface so that all call sites are written correctly today. When the MCP
client is added, only this file changes.

To enable real MCP validation:
  1. Add to requirements.txt:   mcp>=1.0.0
  2. Implement _call_aws_mcp_client() below using the MCP SDK.
  3. Set env var: AWS_MCP_ENABLED=true

Hard constraints (never violate):
  - Never access customer AWS accounts.
  - Never mutate AWS resources.
  - Never call MCP from the normal account scan path.
  - Never return fake verified dates.
  - Return not_configured clearly when MCP is not available.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_MCP_ENABLED = os.environ.get("AWS_MCP_ENABLED", "false").lower() in ("1", "true", "yes")

# Services supported for MCP lifecycle validation
SUPPORTED_PRODUCTS = {
    "aws-lambda",
    "amazon-eks",
    "amazon-rds-postgresql",
    "amazon-rds-mysql",
    "amazon-rds-mariadb",
    "amazon-aurora-postgresql",
    "amazon-aurora-mysql",
    "amazon-opensearch",
    "amazon-elasticache-redis",
    "amazon-elasticache-memcached",
}


def _not_configured_response(product: str, version: str, reason: str = "") -> dict:
    return {
        "product":             product,
        "version":             version,
        "validationStatus":    "not_configured",
        "confidence":          "LOW",
        "source":              "aws_official_docs",
        "lifecycle_source":    "AWS_MCP",
        "validatedBy":         "aws_mcp",
        "eolDate":             None,
        "supportEndDate":      None,
        "extendedSupportEndDate": None,
        "officialSourceUrl":   None,
        "lastValidatedAt":     datetime.now(timezone.utc).isoformat(),
        "conflict":            False,
        "requiresManualReview": True,
        "is_stale":            False,
        "manual_override":     False,
        "notes": (
            reason or
            "AWS MCP validator interface is present, but MCP client is not configured. "
            "Add mcp>=1.0.0 to requirements.txt and set AWS_MCP_ENABLED=true to enable."
        ),
    }


def _call_aws_mcp_client(product: str, version: str) -> Optional[dict]:
    """Placeholder for real MCP client call.

    Replace this function body when mcp SDK is installed.
    Must return a dict with at minimum:
      eolDate, supportEndDate, officialSourceUrl, confidence
    or None on failure.

    IMPORTANT: must NOT access customer AWS accounts.
    IMPORTANT: must NOT be called from account scan path.
    """
    # Real implementation example (do not enable without mcp installed):
    #
    # import asyncio
    # from mcp import ClientSession, StdioServerParameters
    # from mcp.client.stdio import stdio_client
    #
    # async def _query():
    #     server_params = StdioServerParameters(
    #         command="uvx",
    #         args=["awslabs.aws-documentation-mcp-server@latest"],
    #     )
    #     async with stdio_client(server_params) as (read, write):
    #         async with ClientSession(read, write) as session:
    #             await session.initialize()
    #             result = await session.call_tool(
    #                 "search_documentation",
    #                 arguments={"search_phrase": f"{product} {version} end of life support dates"},
    #             )
    #             return _parse_mcp_result(result, product, version)
    #
    # return asyncio.run(_query())
    return None


def _detect_conflict(aws_eol_date: Optional[str], endoflife_eol_date: Optional[str]) -> dict:
    """Compare AWS official date against endoflife.date value.

    Returns conflict metadata dict. Both dates must be YYYY-MM-DD strings.
    """
    if not aws_eol_date or not endoflife_eol_date:
        return {"conflict": False, "requiresManualReview": False}
    if aws_eol_date.strip() != endoflife_eol_date.strip():
        return {
            "conflict":            True,
            "awsOfficialValue":    aws_eol_date,
            "endoflifeDateValue":  endoflife_eol_date,
            "requiresManualReview": True,
        }
    return {"conflict": False, "requiresManualReview": False}


def validate_lifecycle_with_aws_mcp(
    product: str,
    version: str,
    endoflife_eol_date: Optional[str] = None,
) -> dict:
    """Validate lifecycle dates for product/version using AWS MCP documentation.

    Parameters
    ----------
    product : str
        Product slug, e.g. "aws-lambda", "amazon-eks"
    version : str
        Version string, e.g. "python3.9", "1.30"
    endoflife_eol_date : str, optional
        Current endoflife.date EOL value for conflict detection.
        If provided and AWS MCP returns a different date, conflict=true is set.

    Returns
    -------
    dict
        validationStatus: "verified" | "needs_review" | "not_found" | "not_configured"
        confidence: "HIGH" | "MEDIUM" | "LOW"
        All other lifecycle metadata fields populated where available.

    Safety guarantees
    -----------------
    - Never calls customer AWS accounts.
    - Never mutates resources.
    - Returns not_configured safely when MCP is unavailable.
    - Never returns fake verified dates.
    """
    if product not in SUPPORTED_PRODUCTS:
        return {
            **_not_configured_response(product, version),
            "validationStatus": "not_found",
            "notes": f"Product '{product}' is not in the supported MCP validation list.",
        }

    if not _MCP_ENABLED:
        return _not_configured_response(product, version)

    # Real MCP path (only reached when AWS_MCP_ENABLED=true and mcp is installed)
    try:
        raw = _call_aws_mcp_client(product, version)
    except Exception as exc:
        logger.warning("MCP client call failed for %s/%s: %s", product, version, exc)
        return {
            **_not_configured_response(product, version),
            "validationStatus": "not_configured",
            "notes": f"MCP client error: {exc}",
        }

    if raw is None:
        return {
            **_not_configured_response(product, version),
            "validationStatus": "not_found",
            "notes": f"AWS MCP returned no lifecycle data for {product}/{version}.",
        }

    # Validate result has minimum required fields before marking as verified
    eol_date = raw.get("eolDate")
    if not eol_date:
        return {
            **_not_configured_response(product, version),
            "validationStatus": "needs_review",
            "confidence": "LOW",
            "notes": "MCP result missing eolDate — cannot mark as verified.",
        }

    conflict_meta = _detect_conflict(eol_date, endoflife_eol_date)
    now = datetime.now(timezone.utc).isoformat()

    return {
        "product":                product,
        "version":                version,
        "validationStatus":       "verified",
        "confidence":             raw.get("confidence", "HIGH"),
        "source":                 "aws_official_docs",
        "lifecycle_source":       "VERIFIED_AWS_OFFICIAL",
        "validatedBy":            "aws_mcp",
        "eolDate":                eol_date,
        "supportEndDate":         raw.get("supportEndDate"),
        "extendedSupportEndDate": raw.get("extendedSupportEndDate"),
        "officialSourceUrl":      raw.get("officialSourceUrl"),
        "lastValidatedAt":        now,
        "is_stale":               False,
        "manual_override":        False,
        "notes":                  raw.get("notes", "Validated from AWS official documentation."),
        **conflict_meta,
    }
