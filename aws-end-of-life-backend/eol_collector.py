"""
AWS EOL Monitor — Main Collector Lambda
Scans all AWS service versions across all regions and checks EOL status.
"""
import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

import boto3
import requests
from botocore.config import Config
from botocore.exceptions import ClientError

from storage import get_storage
from service_config import SERVICE_REGISTRY, SERVICE_SLUG  # noqa: F401 — central registry

class OrgScanCancelled(Exception):
    """Raised by run_all_collectors when a cooperative cancel is detected mid-scan."""
    pass


# Short timeouts for every AWS API call made by collectors.
# Prevents a single hung AWS API from blocking a Stop Scan request for minutes.
_COLLECTOR_CLIENT_CONFIG = Config(
    connect_timeout=5,
    read_timeout=15,
    retries={"max_attempts": 2},
)


class _TimedSession:
    """Thin wrapper: injects _COLLECTOR_CLIENT_CONFIG into every session.client() call."""
    __slots__ = ("_s",)

    def __init__(self, session):
        self._s = session

    def client(self, service_name, **kwargs):
        kwargs.setdefault("config", _COLLECTOR_CLIENT_CONFIG)
        return self._s.client(service_name, **kwargs)


_STATUS_LABELS: dict[str, str] = {
    "EOL":                  "End of Life",
    "EXPIRING_SOON":        "Expiring Soon",
    "EXTENDED_SUPPORT":     "Extended Support",
    "SUPPORTED":            "Supported",
    "UNKNOWN":              "Unknown",
    "NEEDS_INSPECTION":     "Needs Inspection",
    "LIFECYCLE_NOT_TRACKED":"Lifecycle Not Tracked",
}

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SNS_TOPIC_ARN    = os.environ.get("SNS_TOPIC_ARN", "")
WARN_DAYS        = int(os.environ.get("WARN_DAYS", "180"))
EOL_API_BASE     = os.environ.get("EOL_API_BASE", "https://endoflife.date/api")
EOL_API_TIMEOUT  = int(os.environ.get("EOL_API_TIMEOUT_SECONDS", "10"))
EOL_API_RETRIES  = int(os.environ.get("EOL_API_RETRIES", "2"))
EOL_CACHE: dict  = {}
SCAN_WARNINGS: list[dict] = []

# Lifecycle discovery: ON by default. Set LIFECYCLE_DISCOVERY_ENABLED=false to disable.
_LIFECYCLE_DISCOVERY_ENABLED = os.environ.get(
    "LIFECYCLE_DISCOVERY_ENABLED", "true"
).lower() not in ("0", "false", "no")

# In-memory override cache — loaded once per process from storage.
_OVERRIDES:        dict = {}
_OVERRIDES_LOADED: bool = False


SERVICE_ACCESS_WARNINGS: dict[str, tuple[str, str]] = {
    "CodeBuild":            ("CODEBUILD_ACCESS_DENIED", "CodeBuild scan skipped because read permission is missing."),
    "ElasticBeanstalk":     ("ELASTIC_BEANSTALK_ACCESS_DENIED", "Elastic Beanstalk scan skipped because read permission is missing."),
    "EMR":                  ("EMR_ACCESS_DENIED", "EMR scan skipped because read permission is missing."),
    "Glue":                 ("GLUE_ACCESS_DENIED", "Glue scan skipped because read permission is missing."),
    "MSK":                  ("MSK_ACCESS_DENIED", "MSK scan skipped because read permission is missing."),
    "CloudFrontFunctions":  ("CLOUDFRONT_ACCESS_DENIED", "CloudFront Functions scan skipped because read permission is missing."),
    "ECR":                  ("ECR_ACCESS_DENIED", "ECR scan skipped because read permission is missing."),
    "OpenSearch":           ("OPENSEARCH_ACCESS_DENIED", "OpenSearch scan skipped because read permission is missing."),
    "AmazonMQ":             ("AMAZON_MQ_ACCESS_DENIED", "Amazon MQ scan skipped because read permission is missing."),
    "DMS":                  ("DMS_ACCESS_DENIED", "AWS DMS scan skipped because read permission is missing."),
    "MWAA":                 ("MWAA_ACCESS_DENIED", "Amazon MWAA scan skipped because read permission is missing."),
    "ECSFargate":           ("ECS_ACCESS_DENIED", "ECS Fargate scan skipped because read permission is missing."),
    "SageMakerNotebook":    ("SAGEMAKER_ACCESS_DENIED", "SageMaker Notebook scan skipped because read permission is missing."),
    "AWSBatch":             ("BATCH_ACCESS_DENIED", "AWS Batch scan skipped because read permission is missing."),
}


def _client_error_code(exc: ClientError) -> str:
    return ((exc.response or {}).get("Error") or {}).get("Code", "")


def _is_access_denied(exc: ClientError) -> bool:
    code = _client_error_code(exc).lower()
    return "accessdenied" in code or "unauthorized" in code or "notauthorized" in code


def _record_service_warning(service_key: str, exc: ClientError | None = None) -> None:
    code, message = SERVICE_ACCESS_WARNINGS.get(
        service_key,
        (f"{service_key.upper()}_ACCESS_DENIED", f"{service_key} scan skipped because read permission is missing."),
    )
    if exc and not _is_access_denied(exc):
        message = f"{service_key} scan skipped: {_client_error_code(exc) or str(exc)}"
    warning = {"code": code, "message": message}
    if warning not in SCAN_WARNINGS:
        SCAN_WARNINGS.append(warning)


def get_scan_warnings() -> list[dict]:
    return list(SCAN_WARNINGS)


def _unknown_lifecycle(reason: str) -> tuple[str, None, None, str]:
    return "UNKNOWN", None, None, reason


def _lifecycle_not_tracked(reason: str) -> tuple[str, None, None, str]:
    """Use for services where lifecycle tracking is not implemented (CodeBuild, EMR, EB)."""
    return "LIFECYCLE_NOT_TRACKED", None, None, reason


def _load_overrides_once() -> None:
    """Load all manual EOL overrides from storage into the module-level dict (once per process)."""
    global _OVERRIDES, _OVERRIDES_LOADED
    if _OVERRIDES_LOADED:
        return
    try:
        all_overrides = get_storage().list_eol_overrides()
        _OVERRIDES = {f"{r.get('product','')}/{r.get('version','')}": r for r in all_overrides}
        _OVERRIDES_LOADED = True
        logger.info("Loaded %d EOL overrides from storage", len(_OVERRIDES))
    except Exception as exc:
        logger.warning("Failed to load EOL overrides: %s — proceeding without overrides", exc)


def _get_eol_override(product: str, version: str) -> Optional[dict]:
    """Return an endoflife.date-compatible dict for a manual override, or None."""
    _load_overrides_once()
    record = _OVERRIDES.get(f"{product}/{version}")
    if not record:
        return None
    eol_date = record.get("eolDate")
    return {
        "eolFrom":         eol_date,
        "eol":             eol_date,
        "support":         record.get("supportEndDate"),
        "extendedSupport": record.get("finalEolDate"),
        "isEoes":          False,
        "__meta": {
            "lifecycle_source": "MANUAL_OVERRIDE",
            "source_url":       record.get("sourceUrl", ""),
            "confidence":       "VERIFIED",
            "fetched_at":       record.get("updatedAt", ""),
            "is_stale":         False,
            "override_by":      record.get("updatedBy", ""),
            "override_reason":  record.get("reason", ""),
        },
    }


def _get_verified_lifecycle(product: str, version: str) -> Optional[dict]:
    """Return admin-validated verified lifecycle record as eol_data dict, or None.

    Only returns records with validationStatus="verified".
    Does NOT call aws_mcp_validator — that is admin-only.
    Safe to call from account scan path (reads storage only).
    """
    try:
        record = get_storage().get_verified_lifecycle(product, version)
        if not record:
            return None
        if record.get("validationStatus") != "verified":
            return None
        eol_date = record.get("eolDate")
        return {
            "eolFrom":         eol_date,
            "eol":             eol_date,
            "support":         record.get("supportEndDate"),
            "extendedSupport": record.get("extendedSupportEndDate"),
            "isEoes":          bool(record.get("extendedSupportEndDate") and not record.get("eolDate")),
            "__meta": {
                "lifecycle_source":    record.get("lifecycle_source", "VERIFIED_AWS_OFFICIAL"),
                "source_url":          record.get("officialSourceUrl"),
                "officialSourceUrl":   record.get("officialSourceUrl"),
                "confidence":          record.get("confidence", "HIGH"),
                "validatedBy":         record.get("validatedBy", "aws_mcp"),
                "lastValidatedAt":     record.get("lastValidatedAt"),
                "fetched_at":          record.get("lastValidatedAt"),
                "is_stale":            record.get("is_stale", False),
                "validationStatus":    record.get("validationStatus"),
                "manual_override":     False,
                "conflict":            record.get("conflict", False),
                "requiresManualReview": record.get("requiresManualReview", False),
            },
        }
    except Exception as exc:
        logger.warning("Failed to fetch verified lifecycle for %s/%s: %s", product, version, exc)
        return None


def _review_recommendation(service_name: str = "service/runtime") -> str:
    return f"Review {service_name} lifecycle and update to a current supported version."


# ── EC2 OS lifecycle — inline table (authoritative, no API call needed) ──────
# Keyed by the OS label returned by _detect_ec2_os / SSM platform name+version.
EC2_OS_LIFECYCLE: dict = {
    "Amazon Linux 2":    "2026-06-30",
    "Amazon Linux 2023": "2028-03-15",
    "Ubuntu 18.04":      "2023-04-30",
    "Ubuntu 20.04":      "2025-05-31",
    "Ubuntu 22.04":      "2027-04-30",
    "Ubuntu 24.04":      "2029-05-31",
    "Ubuntu 26.04":      "2031-04-30",
    "CentOS 7":          "2024-06-30",
    "CentOS Stream 8":   "2024-05-31",
    "CentOS Stream 9":   "2027-05-31",
    "RHEL 7":            "2024-06-30",
    "RHEL 8":            "2029-05-31",
    "RHEL 9":            "2032-05-31",
    "Debian 10":         "2024-06-30",
    "Debian 11":         "2026-08-31",
    "Debian 12":         "2028-06-30",
    "Windows Server 2012": "2023-10-10",
    "Windows Server 2016": "2027-01-12",
    "Windows Server 2019": "2029-01-09",
    "Windows Server 2022": "2031-10-14",
    "Windows Server 2025": "2034-10-14",
}

# Ordered from most-specific to least-specific to avoid false matches.
# Each group also covers SSM PlatformName variants (e.g. "CentOS Linux 7",
# "Debian GNU/Linux 11") and official Ubuntu AMI codenames (focal/jammy/noble).
_EC2_OS_PATTERNS: list[tuple[list[str], str]] = [
    (["amzn2023", "amazon-linux-2023", "al2023"],              "Amazon Linux 2023"),
    (["amzn2", "amazon-linux-2", "al2-", "amazon linux 2"],   "Amazon Linux 2"),
    # Ubuntu — version numbers AND official codenames (for both AMI names and SSM data)
    (["ubuntu-resolute", "ubuntu/resolute", "ubuntu resolute",
      "resolute-26.04", "ubuntu-26.04",  "ubuntu/26.04",  "ubuntu 26.04"],  "Ubuntu 26.04"),
    (["ubuntu-noble",  "ubuntu/noble",  "ubuntu noble",
      "noble-24.04",   "ubuntu-24.04",  "ubuntu/24.04",  "ubuntu 24.04"],  "Ubuntu 24.04"),
    (["ubuntu-jammy",  "ubuntu/jammy",  "ubuntu jammy",
      "jammy-22.04",   "ubuntu-22.04",  "ubuntu/22.04",  "ubuntu 22.04"],  "Ubuntu 22.04"),
    (["ubuntu-focal",  "ubuntu/focal",  "ubuntu focal",
      "focal-20.04",   "ubuntu-20.04",  "ubuntu/20.04",  "ubuntu 20.04"],  "Ubuntu 20.04"),
    (["ubuntu-bionic", "ubuntu/bionic", "ubuntu bionic",
      "bionic-18.04",  "ubuntu-18.04",  "ubuntu/18.04",  "ubuntu 18.04"],  "Ubuntu 18.04"),
    # Windows Server — most-specific first (2025 before 2022 before 2019…)
    (["windows server 2025", "win2025", "windows_server-2025"], "Windows Server 2025"),
    (["windows server 2022", "win2022", "windows_server-2022"], "Windows Server 2022"),
    (["windows server 2019", "win2019", "windows_server-2019"], "Windows Server 2019"),
    (["windows server 2016", "win2016", "windows_server-2016"], "Windows Server 2016"),
    (["windows server 2012", "win2012", "windows_server-2012"], "Windows Server 2012"),
    # CentOS — "centos linux 7" covers SSM PlatformName="CentOS Linux", PlatformVersion="7"
    (["centos stream 9", "centos-stream-9"],                    "CentOS Stream 9"),
    (["centos stream 8", "centos-stream-8"],                    "CentOS Stream 8"),
    (["centos-7", "centos7", "centos 7", "/centos/7",
      "centos linux 7", "centos linux release 7"],              "CentOS 7"),
    (["rhel-9", "rhel9", "rhel 9", "red hat enterprise linux 9"], "RHEL 9"),
    (["rhel-8", "rhel8", "rhel 8", "red hat enterprise linux 8"], "RHEL 8"),
    (["rhel-7", "rhel7", "rhel 7", "red hat enterprise linux 7"], "RHEL 7"),
    # Debian — "debian gnu/linux N" covers SSM PlatformName format
    (["debian-12", "debian/12", "debian 12", "debian gnu/linux 12"], "Debian 12"),
    (["debian-11", "debian/11", "debian 11", "debian gnu/linux 11"], "Debian 11"),
    (["debian-10", "debian/10", "debian 10", "debian gnu/linux 10"], "Debian 10"),
]


# ECS Fargate Linux platform version lifecycle — inline authoritative table.
# AWS retired platform versions 1.0.0–1.3.0 in April 2022 (forced all services to 1.4.0).
# "LATEST" is a dynamic alias; the actual underlying version is not visible in the service API.
# Value = EOL/retirement date string, or None when no retirement date is announced.
FARGATE_PLATFORM_EOL: dict[str, Optional[str]] = {
    "1.0.0": "2022-04-01",
    "1.1.0": "2022-04-01",
    "1.2.0": "2022-04-01",
    "1.3.0": "2022-04-01",
    "1.4.0": None,  # current standard; no announced EOL
}

# SageMaker Notebook Instance platform identifier lifecycle — inline authoritative table.
# notebook-al1-v1:  Amazon Linux 1 retired December 2023; AWS removed AL1 notebook images.
# notebook-al2-v*:  Amazon Linux 2 standard support ends 2026-06-30; plan migration to AL2023.
# notebook-al2023-v1: Current recommended platform; no announced EOL.
# Value = retirement/EOL date string, or None when no retirement date is announced.
SAGEMAKER_NOTEBOOK_PLATFORM_EOL: dict[str, Optional[str]] = {
    "notebook-al1-v1":   "2023-12-31",  # AL1 retired; AWS deprecated these images
    "notebook-al2-v1":   "2026-06-30",  # AL2 standard support end
    "notebook-al2-v2":   "2026-06-30",
    "notebook-al2-v3":   "2026-06-30",
    "notebook-al2023-v1": None,          # current; no announced EOL
}

# AWS Batch managed compute environment AMI type lifecycle — inline authoritative table.
# Keyed by ec2Configuration.imageType values from describe_compute_environments.
# AL2 ECS/EKS-optimized AMIs follow Amazon Linux 2 standard support (ends 2026-06-30).
# AL2023 variants are current with no announced EOL.
# Value = retirement/EOL date string, or None when no retirement date is announced.
BATCH_COMPUTE_AMI_EOL: dict[str, Optional[str]] = {
    # ECS-backed compute environments
    "ECS_AL2":           "2026-06-30",   # Amazon Linux 2 ECS-optimized AMI
    "ECS_AL2_NVIDIA":    "2026-06-30",   # AL2 with NVIDIA GPU drivers
    "ECS_AL2_ARM64":     "2026-06-30",   # AL2 ARM64
    "ECS_AL2023":        None,           # Amazon Linux 2023 ECS-optimized (current)
    "ECS_AL2023_NVIDIA": None,
    "ECS_AL2023_ARM64":  None,
    # EKS-backed compute environments
    "EKS_AL2":           "2026-06-30",   # Amazon Linux 2 EKS-optimized AMI
    "EKS_AL2_NVIDIA":    "2026-06-30",
    "EKS_AL2023":        None,           # Amazon Linux 2023 EKS-optimized (current)
}

# Elastic Beanstalk OS-level fallback lifecycle table.
# Used when describe_platform_version is unavailable or the platform ARN is absent.
# Checked in order — "amazon linux 2023" MUST come before "amazon linux 2" because
# "amazon linux 2" is a substring of "amazon linux 2023".
_EB_OS_EOL_FALLBACK: list[tuple[str, Optional[str]]] = [
    ("amazon linux 2023", None),          # AL2023 — current; no announced EOL
    ("amazon linux 2",    "2026-06-30"),   # AL2 standard support end
    ("amazon linux",      "2023-12-31"),   # AL1 — retired December 2023
]


def _eb_os_fallback_classify(stack: str) -> tuple[str, Optional[str], Optional[int], str, str]:
    """Classify Elastic Beanstalk environment from SolutionStackName OS substring.
    Returns (status, eol_date, days, recommendation, classification_reason).
    """
    lower = stack.lower()
    for os_key, eol_date_str in _EB_OS_EOL_FALLBACK:
        if os_key in lower:
            if eol_date_str:
                status, eol_date, days = classify_status({"eol": eol_date_str})
                rec = (
                    "Elastic Beanstalk platform branch is approaching or past retirement. "
                    "Migrate to an AL2023 platform branch."
                ) if status in ("EOL", "EXPIRING_SOON") else ""
                reason = "Platform OS lifecycle inferred from solution stack name (describe_platform_version unavailable)."
            else:
                status, eol_date, days = "SUPPORTED", None, None
                rec    = ""
                reason = "Platform appears to be AL2023-based (no announced EOL)."
            return status, eol_date, days, rec, reason
    return (
        "UNKNOWN", None, None,
        "Elastic Beanstalk platform lifecycle should be verified from AWS official platform retirement schedule.",
        "Could not determine OS platform type from solution stack name.",
    )


def _detect_ec2_os(ami_name: str, ami_desc: str, platform_details: str) -> tuple:
    """Detect OS label from AMI name/description/platform_details.
    Returns (os_label, eol_date_str_or_None).
    """
    text = f"{ami_name} {ami_desc} {platform_details}".lower()
    for keywords, os_label in _EC2_OS_PATTERNS:
        if any(kw in text for kw in keywords):
            return os_label, EC2_OS_LIFECYCLE.get(os_label)
    return "", None


SSM_INVENTORY_WARNING = "SSM inventory unavailable. EC2 OS detection used AMI metadata fallback."


def _ssm_os_map(session, region: str) -> tuple[dict, bool]:
    """Return ({instance_id: SSM metadata}, unavailable) using SSM DescribeInstanceInformation.

    Normalization order:
    1. Exact match in EC2_OS_LIFECYCLE  (e.g. "Amazon Linux 2", "Ubuntu 22.04")
    2. Pattern detection via _detect_ec2_os  (handles "CentOS Linux 7",
       "Debian GNU/Linux 11", Ubuntu codename variants, etc.)
    3. Raw os_key as fallback (won't match lifecycle — will show UNKNOWN)
    """
    result = {}
    try:
        ssm = session.client("ssm", region_name=region)
        pager = ssm.get_paginator("describe_instance_information")
        for page in pager.paginate():
            for info in page["InstanceInformationList"]:
                iid  = info.get("InstanceId", "")
                name = info.get("PlatformName", "").strip()
                ver  = info.get("PlatformVersion", "").strip()
                if not iid:
                    continue
                os_key = f"{name} {ver}".strip()
                label = ""
                if os_key in EC2_OS_LIFECYCLE:
                    label = os_key
                else:
                    label, _ = _detect_ec2_os(os_key, os_key, "")
                result[iid] = {
                    "os_label":         label or os_key,
                    "platform_name":    name,
                    "platform_version": ver,
                    "platform_type":    info.get("PlatformType", ""),
                    "computer_name":    info.get("ComputerName", ""),
                    "agent_status":     info.get("PingStatus", "") or info.get("AssociationStatus", ""),
                }
    except ClientError as exc:
        logger.warning("SSM inventory unavailable in %s: %s", region, exc)
        return result, True
    return result, False


_EC2_RECS: dict[str, str] = {
    "Amazon Linux 2":    "Migrate to Amazon Linux 2023 before 2026-06-30.",
    "Ubuntu 18.04":      "Upgrade to Ubuntu 22.04 LTS or 24.04 LTS.",
    "Ubuntu 20.04":      "Upgrade to Ubuntu 22.04 LTS or 24.04 LTS.",
    "CentOS 7":          "Migrate to Amazon Linux 2023, RHEL 9, or Ubuntu 22.04.",
    "CentOS Stream 8":   "Upgrade to CentOS Stream 9 or migrate to RHEL 9.",
    "RHEL 7":            "Upgrade to RHEL 8 or RHEL 9.",
    "Debian 10":         "Upgrade to Debian 12.",
    "Debian 11":         "Plan upgrade to Debian 12 before August 2026.",
    "Windows Server 2012": "Upgrade to Windows Server 2022 (2012 is past EOL).",
    "Windows Server 2016": "Plan upgrade to Windows Server 2022 or 2025.",
    "Windows Server 2019": "Plan upgrade to Windows Server 2022 or 2025.",
    "Windows Server 2025": "Windows Server 2025 is currently supported (extended support until 2034-10-14).",
}

# Previous-generation EC2 instance families per AWS documentation.
# AWS has no published retirement dates for instance types, so these are
# classified as NEEDS_INSPECTION — still runnable but AWS recommends migration.
# Key = family prefix (e.g. "t2" matches "t2.micro", "t2.small", etc.)
_PREV_GEN_INSTANCE_FAMILIES: dict[str, str] = {
    # First generation (pre-2014) — hardware oldest, worst perf/$ ratio
    "t1":  "Upgrade to t3 or t4g (t1 is first-generation).",
    "m1":  "Upgrade to m6i or m7i (m1 is first-generation).",
    "m2":  "Upgrade to r6i for high-memory workloads (m2 is first-generation).",
    "m3":  "Upgrade to m6i or m7i (m3 is previous generation).",
    "c1":  "Upgrade to c6i or c7i (c1 is first-generation).",
    "c3":  "Upgrade to c6i or c7i (c3 is previous generation).",
    "cc2": "Upgrade to c5n or hpc6a (cc2 is previous generation).",
    "cr1": "Upgrade to r6i or r7i (cr1 is previous generation).",
    "hi1": "Upgrade to i3en or i4i (hi1 is previous generation).",
    "hs1": "Upgrade to d3 or d3en (hs1 is previous generation).",
    "i2":  "Upgrade to i3, i3en, or i4i (i2 is previous generation).",
    "r3":  "Upgrade to r6i or r7i (r3 is previous generation).",
    "g2":  "Upgrade to g4dn or g5 (g2 is previous generation).",
    # Second/third generation — common in production, AWS recommends migration
    "t2":  "Upgrade to t3 or t4g for better performance and lower cost.",
    "m4":  "Upgrade to m6i or m7i (m4 is previous generation).",
    "c4":  "Upgrade to c6i or c7i (c4 is previous generation).",
    "r4":  "Upgrade to r6i or r7i (r4 is previous generation).",
    "d2":  "Upgrade to d3 or d3en (d2 is previous generation).",
    "x1":  "Upgrade to x2idn or x2iedn (x1 is previous generation).",
    "p2":  "Upgrade to p3, p4d, or p5 (p2 is previous generation).",
    "p3":  "Plan upgrade to p4d or p5 (p3 is approaching end of generation cycle).",
    "f1":  "Consider migrating to f2 or newer FPGA instances.",
}


_RDS_UPGRADE_TARGETS: dict[str, str] = {
    "5.7": "8.4", "8.0": "8.4",               # MySQL
    "11":  "16",  "12": "16", "13": "16", "14": "16",  # PostgreSQL
}


def _eks_recommendation(version: str, status: str) -> str:
    """Return a human-readable recommendation for an EKS cluster lifecycle result."""
    if status not in ("EOL", "EXPIRING_SOON", "EXTENDED_SUPPORT"):
        return ""
    if status == "EXTENDED_SUPPORT":
        return (
            f"EKS {version} is in Extended Support. Review cost exposure and "
            "plan upgrade to a supported Kubernetes minor version."
        )
    if status == "EOL":
        return (
            f"Upgrade this EKS cluster from {version} immediately. "
            "This Kubernetes minor version is past standard support."
        )
    return (
        f"Plan an EKS control plane upgrade from {version} before support ends. "
        "Validate add-ons, node groups, and workloads in a staging cluster first."
    )


def _rds_recommendation(engine: str, major: str, status: str) -> str:
    """Return a human-readable recommendation for an RDS/Aurora lifecycle result."""
    if status not in ("EOL", "EXPIRING_SOON", "EXTENDED_SUPPORT"):
        return ""
    e   = engine.lower()
    tgt = _RDS_UPGRADE_TARGETS.get(major)
    ext = status == "EXTENDED_SUPPORT"
    suffix = " to avoid extended support charges." if ext else "."
    if "mysql" in e:
        return f"Upgrade MySQL {major} to {tgt or '8.4'}{suffix}"
    if "postgres" in e:
        return f"Upgrade PostgreSQL {major} to {tgt or '16'}{suffix}"
    if "mariadb" in e:
        return f"Upgrade MariaDB {major} to a supported version{suffix}"
    return f"Upgrade to a supported {engine} version."


def _ec2_recommendation(os_label: str, status: str) -> str:
    """Return a human-readable recommendation for an EC2 lifecycle result."""
    if not os_label or status == "UNKNOWN":
        return (
            "Enable SSM Inventory or use supported AMI naming conventions "
            "for accurate EC2 lifecycle detection."
        )
    if status in ("EOL", "EXPIRING_SOON"):
        return _EC2_RECS.get(os_label, "Upgrade to a supported OS version.")
    return ""


# ── EOL API ─────────────────────────────────────────────────────────────────

def fetch_eol(product: str, version: str) -> Optional[dict]:
    """Return EOL data for a product/version.

    Priority chain:
      0. In-memory cache
      1. Manual override           (highest priority, always wins)
      2. Verified lifecycle storage (admin-validated AWS official records)
      3. endoflife.date            (with configurable retry)
      4. Discovered cache (fresh)  ┐ only when
      5. Auto-discovery            ├ LIFECYCLE_DISCOVERY_ENABLED=true
      6. Discovered cache (stale)  ┘
      7. None → LIFECYCLE_NOT_TRACKED

    IMPORTANT: Steps 1-6 only READ from storage.
    aws_mcp_validator is NEVER called here — it is admin-only.
    Normal account scan path is safe.
    """
    key = f"{product}/{version}"
    if key in EOL_CACHE:
        return EOL_CACHE[key]

    # 1. Manual override — always highest priority
    override = _get_eol_override(product, version)
    if override is not None:
        EOL_CACHE[key] = override
        logger.info("EOL override applied: %s", key)
        return override

    # 2. Verified lifecycle storage — admin-validated AWS official records
    # This slot is populated only by POST /admin/eol/validate-mcp, never inline.
    verified = _get_verified_lifecycle(product, version)
    if verified is not None:
        EOL_CACHE[key] = verified
        logger.info("Verified lifecycle used: %s (source=%s)", key,
                    verified.get("__meta", {}).get("lifecycle_source"))
        return verified

    # 3. Primary: endoflife.date (with retry)
    fetched_at = datetime.now(timezone.utc).isoformat()
    for attempt in range(1, EOL_API_RETRIES + 2):
        try:
            r = requests.get(f"{EOL_API_BASE}/{product}/{version}.json", timeout=EOL_API_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                data["__meta"] = {
                    "lifecycle_source": "ENDOFLIFE_DATE",
                    "source_url": f"{EOL_API_BASE}/{product}/{version}.json",
                    "confidence": "MEDIUM",
                    "fetched_at": fetched_at,
                    "is_stale": False,
                }
                EOL_CACHE[key] = data
                logger.info("EOL API hit: %s", key)
                return data
            if r.status_code == 404:
                logger.info("EOL API %s → 404 (version not in endoflife.date)", key)
                break  # no point retrying a definitive not-found
            logger.warning("EOL API %s → HTTP %s (attempt %d/%d)", key, r.status_code, attempt, EOL_API_RETRIES + 1)
        except Exception as exc:
            logger.warning("EOL API error for %s (attempt %d/%d): %s", key, attempt, EOL_API_RETRIES + 1, exc)

    # 2-4. Fallback chain (only when feature flag is enabled)
    if _LIFECYCLE_DISCOVERY_ENABLED:
        result = _lifecycle_fallback(product, version)
        EOL_CACHE[key] = result
        return result

    EOL_CACHE[key] = None
    return None


def _lifecycle_fallback(product: str, version: str) -> Optional[dict]:
    """Discovered cache → auto-discovery → stale cache. Returns None if all fail."""
    try:
        from lifecycle.cache import (
            is_record_fresh,
            query_discovered_cache,
            upsert_discovered_record,
        )
        from lifecycle.auto_discovery import auto_discover_lifecycle
    except ImportError:
        logger.warning("lifecycle modules unavailable — skipping fallback for %s/%s", product, version)
        return None

    # Fresh cache hit
    cached = query_discovered_cache(product, version, allow_stale=True)
    if cached and is_record_fresh(cached):
        logger.info("Lifecycle cache hit (fresh): %s/%s", product, version)
        return cached.get("lifecycle_data")

    # Auto-discovery
    try:
        discovered = auto_discover_lifecycle(product, version)
        if discovered is not None:
            upsert_discovered_record({
                "product":        product,
                "version":        version,
                "lifecycle_data": discovered,
                "discovered_at":  datetime.now(timezone.utc).isoformat(),
            })
            logger.info("Lifecycle auto-discovered: %s/%s", product, version)
            return discovered
    except Exception as exc:
        logger.warning("Lifecycle auto-discovery error for %s/%s: %s", product, version, exc)

    # Stale cache (stale-if-error)
    if cached:
        logger.info("Lifecycle cache hit (stale): %s/%s", product, version)
        return cached.get("lifecycle_data")

    return None


def _lifecycle_fields(eol_data: Optional[dict]) -> dict:
    """Extract source/confidence metadata from eol_data.__meta for resource JSON enrichment.

    Always returns at least lifecycle_source and confidence so the frontend can
    display trust information even for plain endoflife.date responses.
    """
    meta = (eol_data or {}).get("__meta")
    if not meta:
        # No __meta means we either got None (no data) or a raw endoflife.date response
        # before the wrapping was added. Provide conservative defaults.
        if eol_data:
            meta = {"lifecycle_source": "ENDOFLIFE_DATE", "confidence": "MEDIUM", "is_stale": False}
        else:
            meta = {"lifecycle_source": "UNKNOWN", "confidence": "UNKNOWN", "is_stale": False}

    fields = {
        "lifecycle_source":     meta.get("lifecycle_source"),
        "source":               meta.get("lifecycle_source"),
        "source_url":           meta.get("source_url"),
        "officialSourceUrl":    meta.get("officialSourceUrl") or meta.get("source_url"),
        "confidence":           meta.get("confidence"),
        "validatedBy":          meta.get("validatedBy"),
        "lastValidatedAt":      meta.get("lastValidatedAt"),
        "fetchedAt":            meta.get("fetched_at"),
        "is_stale":             meta.get("is_stale", False),
        "validationStatus":     meta.get("validationStatus"),
        "manual_override":      meta.get("manual_override", False),
        "conflict":             meta.get("conflict", False),
        "requiresManualReview": meta.get("requiresManualReview", False),
        "discovery_method":     meta.get("discovery_method"),
    }
    if meta.get("data_source_error"):
        fields["data_source_error"] = meta["data_source_error"]
    if meta.get("confidence", "HIGH") not in ("HIGH", "VERIFIED"):
        fields["review_required"] = True
    return {k: v for k, v in fields.items() if v is not None}


def classify_status(eol_data: Optional[dict]) -> tuple[str, Optional[str], Optional[int]]:
    """Return (status, primary_alert_date_str, days_to_primary_date).

    Delegates to lifecycle.classifier for unified behavior with the general EOL
    library page. Returns 'UNKNOWN' when eol_data is None (version-level data
    not found in any source — distinct from LIFECYCLE_NOT_TRACKED which is set
    explicitly by collectors for services with no lifecycle tracking implemented).
    """
    if not eol_data:
        return "UNKNOWN", None, None

    from lifecycle.classifier import classify as _classify
    is_eoes  = bool(eol_data.get("isEoes") or eol_data.get("extendedSupport"))
    eol_raw  = eol_data.get("eolFrom") or eol_data.get("eol")
    sup_raw  = eol_data.get("support")
    eol_from    = str(eol_raw) if eol_raw and eol_raw is not False else None
    support_from = str(sup_raw) if sup_raw and sup_raw is not False else None
    return _classify(eol_from, support_from, is_eoes, WARN_DAYS)


# ── SNS Alerts ───────────────────────────────────────────────────────────────

def send_alert(resource: dict):
    if not SNS_TOPIC_ARN:
        return
    status = resource.get("eol_status", "")
    if status not in ("EOL", "EXPIRING_SOON"):
        return
    subject = f"[AWS EOL] {status}: {resource.get('resource_id', '')} ({resource.get('service_type', '')})"
    msg = (
        f"Resource: {resource.get('resource_id')}\n"
        f"Service:  {resource.get('service_type')}\n"
        f"Region:   {resource.get('region')}\n"
        f"Version:  {resource.get('version')}\n"
        f"Status:   {status}\n"
        f"EOL Date: {resource.get('eol_date', 'N/A')}\n"
        f"Days:     {resource.get('days_to_eol', 'N/A')}\n"
    )
    try:
        boto3.client("sns").publish(TopicArn=SNS_TOPIC_ARN, Subject=subject[:100], Message=msg)
    except Exception as exc:
        logger.warning("SNS publish failed: %s", exc)


# ── Region Discovery ──────────────────────────────────────────────────────────

def get_enabled_regions(session=None) -> list[str]:
    ec2 = (session or boto3).client("ec2", region_name="us-east-1")
    regions = ec2.describe_regions(Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}])
    return [r["RegionName"] for r in regions["Regions"]]


# ── Service Collectors ────────────────────────────────────────────────────────

def collect_lambda(session, region: str, account_id: str) -> list[dict]:
    client = session.client("lambda", region_name=region)
    resources = []
    paginator = client.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page["Functions"]:
            runtime = fn.get("Runtime", "")
            if not runtime or runtime.startswith("provided"):
                continue
            eol_data = fetch_eol(SERVICE_SLUG["Lambda"], runtime)
            status, eol_date, days = classify_status(eol_data)

            # For Lambda, include both the primary alert date (support end) and final EOL
            support_raw = (eol_data or {}).get("support")
            final_eol   = (eol_data or {}).get("eolFrom") or (eol_data or {}).get("eol")
            support_str = str(support_raw) if support_raw and support_raw is not False else None
            final_str   = str(final_eol)   if final_eol   and final_eol   is not False else None

            resources.append({
                "resource_id":      fn["FunctionArn"],
                "service_type":     "Lambda",
                "region":           region,
                "account_id":       account_id,
                "version":          runtime,
                "resource_name":    fn["FunctionName"],
                "eol_status":       status,
                "eol_date":         eol_date,                # None when no EOL announced
                "days_to_eol":      days,
                "support_end_date": support_str,             # runtime deprecation date
                "final_eol_date":   final_str,               # final block/removal date
                **_lifecycle_fields(eol_data),
            })
    return resources


def collect_eks(session, region: str, account_id: str) -> list[dict]:
    client = session.client("eks", region_name=region)
    resources = []
    try:
        pager    = client.get_paginator("list_clusters")
        clusters = []
        for page in pager.paginate():
            clusters.extend(page["clusters"])
    except ClientError:
        return resources
    for name in clusters:
        try:
            detail = client.describe_cluster(name=name)["cluster"]
        except ClientError:
            continue
        version  = detail.get("version", "")
        eol_data = fetch_eol(SERVICE_SLUG["EKS"], version)
        status, eol_date, days = classify_status(eol_data)

        support_raw = (eol_data or {}).get("support")
        final_raw   = (eol_data or {}).get("eolFrom") or (eol_data or {}).get("eol")
        support_str = str(support_raw) if support_raw and support_raw is not False else None
        final_str   = str(final_raw)   if final_raw   and final_raw   is not False else None

        res_net = detail.get("resourcesVpcConfig", {})
        resources.append({
            "resource_id":            detail["arn"],
            "service_type":           "EKS",
            "region":                 region,
            "account_id":             account_id,
            "version":                version,
            "resource_name":          name,
            "eol_status":             status,
            "eol_date":               eol_date,
            "days_to_eol":            days,
            "support_end_date":       support_str,
            "final_eol_date":         final_str,
            "recommendation":         _eks_recommendation(version, status),
            "platform_version":       detail.get("platformVersion", ""),
            "cluster_status":         detail.get("status", ""),
            "endpoint_public_access": res_net.get("endpointPublicAccess", True),
            "endpoint_private_access": res_net.get("endpointPrivateAccess", False),
            "created_at":             str(detail["createdAt"]) if detail.get("createdAt") else "",
            **_lifecycle_fields(eol_data),
        })
    return resources


def collect_rds(session, region: str, account_id: str) -> list[dict]:
    client = session.client("rds", region_name=region)
    resources = []

    def _rds_fields(eol_data, engine, major, status):
        """Extract support_end_date / final_eol_date / recommendation from eol_data."""
        support_raw = (eol_data or {}).get("support")
        final_raw   = (eol_data or {}).get("eolFrom") or (eol_data or {}).get("eol")
        support_str = str(support_raw) if support_raw and support_raw is not False else None
        final_str   = str(final_raw)   if final_raw   and final_raw   is not False else None
        return support_str, final_str, _rds_recommendation(engine, major, status)

    def _rds_major(engine: str, ver: str) -> str:
        """Return the lifecycle key for endoflife.date.
        PostgreSQL uses major-only ("14"), MySQL/MariaDB use major.minor ("8.0").
        Aurora MySQL version strings like "8.0.mysql_aurora.3.04.1" → "8.0".
        """
        parts = ver.split(".")
        if "postgres" in engine:
            return parts[0]          # "14.12" → "14"
        return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else parts[0]

    # DB Instances
    try:
        paginator = client.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page["DBInstances"]:
                engine     = db.get("Engine", "")
                engine_ver = db.get("EngineVersion", "")
                major      = _rds_major(engine, engine_ver)

                if "mysql" in engine:
                    slug = SERVICE_SLUG["RDS_mysql"]
                elif "postgres" in engine:
                    slug = SERVICE_SLUG["RDS_postgres"]
                elif "mariadb" in engine:
                    slug = SERVICE_SLUG["RDS_mariadb"]
                else:
                    continue

                eol_data = fetch_eol(slug, major)
                status, eol_date, days = classify_status(eol_data)
                support_str, final_str, rec = _rds_fields(eol_data, engine, major, status)
                resources.append({
                    "resource_id":        db["DBInstanceArn"],
                    "service_type":       f"RDS_{engine}",
                    "region":             region,
                    "account_id":         account_id,
                    "version":            engine_ver,
                    "resource_name":      db["DBInstanceIdentifier"],
                    "eol_status":         status,
                    "eol_date":           eol_date,
                    "days_to_eol":        days,
                    "engine":             engine,
                    "support_end_date":   support_str,
                    "final_eol_date":     final_str,
                    "recommendation":     rec,
                    "db_instance_class":  db.get("DBInstanceClass", ""),
                    "db_instance_status": db.get("DBInstanceStatus", ""),
                    "multi_az":           db.get("MultiAZ", False),
                    **_lifecycle_fields(eol_data),
                })
    except ClientError as e:
        logger.warning("RDS instances error in %s: %s", region, e)

    # DB Clusters (Aurora)
    try:
        paginator = client.get_paginator("describe_db_clusters")
        for page in paginator.paginate():
            for cluster in page["DBClusters"]:
                engine     = cluster.get("Engine", "")
                engine_ver = cluster.get("EngineVersion", "")
                major      = _rds_major(engine, engine_ver)

                if "aurora-postgresql" in engine:
                    slug = SERVICE_SLUG["Aurora_postgres"]
                    svc  = "Aurora_PostgreSQL"
                elif "aurora-mysql" in engine or "aurora" in engine:
                    slug = SERVICE_SLUG["Aurora_mysql"]
                    svc  = "Aurora_MySQL"
                else:
                    continue

                eol_data = fetch_eol(slug, major)
                status, eol_date, days = classify_status(eol_data)
                support_str, final_str, rec = _rds_fields(eol_data, engine, major, status)
                resources.append({
                    "resource_id":      cluster["DBClusterArn"],
                    "service_type":     svc,
                    "region":           region,
                    "account_id":       account_id,
                    "version":          engine_ver,
                    "resource_name":    cluster["DBClusterIdentifier"],
                    "eol_status":       status,
                    "eol_date":         eol_date,
                    "days_to_eol":      days,
                    "engine":           engine,
                    "support_end_date": support_str,
                    "final_eol_date":   final_str,
                    "recommendation":   rec,
                    "cluster_status":   cluster.get("Status", ""),
                    "engine_mode":      cluster.get("EngineMode", ""),
                    **_lifecycle_fields(eol_data),
                })
    except ClientError as e:
        logger.warning("RDS clusters error in %s: %s", region, e)

    return resources


def collect_elasticache(session, region: str, account_id: str) -> list[dict]:
    client = session.client("elasticache", region_name=region)
    resources = []
    try:
        paginator = client.get_paginator("describe_cache_clusters")
        for page in paginator.paginate():
            for cluster in page["CacheClusters"]:
                engine = cluster.get("Engine", "")
                if engine not in ("redis", "valkey"):
                    continue
                version = cluster.get("EngineVersion", "")
                _parts = version.split(".")
                major_minor = f"{_parts[0]}.{_parts[1]}" if len(_parts) >= 2 else _parts[0]
                # Valkey clusters (Engine="valkey") use a separate endoflife.date product.
                # Redis clusters keep the original amazon-elasticache-redis slug.
                slug = SERVICE_SLUG["Valkey"] if engine == "valkey" else SERVICE_SLUG["ElastiCache"]
                eol_data = fetch_eol(slug, major_minor)
                status, eol_date, days = classify_status(eol_data)
                support_raw = (eol_data or {}).get("support")
                final_raw   = (eol_data or {}).get("eolFrom") or (eol_data or {}).get("eol")
                support_str = str(support_raw) if support_raw and support_raw is not False else None
                final_str   = str(final_raw)   if final_raw   and final_raw   is not False else None
                resources.append({
                    "resource_id":      f"arn:aws:elasticache:{region}:{account_id}:cluster:{cluster['CacheClusterId']}",
                    "service_type":     "ElastiCache",
                    "region":           region,
                    "account_id":       account_id,
                    "version":          version,
                    "resource_name":    cluster["CacheClusterId"],
                    "eol_status":       status,
                    "eol_date":         eol_date,
                    "days_to_eol":      days,
                    "support_end_date": support_str,
                    "final_eol_date":   final_str,
                    "engine":           engine,
                    **_lifecycle_fields(eol_data),
                })
    except ClientError as e:
        logger.warning("ElastiCache error in %s: %s", region, e)
    return resources


def collect_ec2_amis(session, region: str, account_id: str) -> list[dict]:
    """Collect EC2 instances and classify by OS/AMI lifecycle risk.

    Detection priority:
    1. SSM DescribeInstanceInformation — OS name + version (most accurate)
    2. AMI name / description / PlatformDetails pattern matching
    3. AMI DeprecationTime (deprecated AMI = at least LEGACY risk)
    4. UNKNOWN when OS cannot be determined
    """
    ec2 = session.client("ec2", region_name=region)
    resources = []

    # SSM OS map: instance_id → inventory metadata (best-effort fallback on failure)
    ssm_map, ssm_unavailable = _ssm_os_map(session, region)

    try:
        pager = ec2.get_paginator("describe_instances")
        reservations = []
        for page in pager.paginate(
            Filters=[{"Name": "instance-state-name", "Values": ["running", "stopped"]}]
        ):
            reservations.extend(page["Reservations"])
    except ClientError as e:
        logger.warning("EC2 describe_instances error in %s: %s", region, e)
        return resources

    # Collect instances + batch-fetch AMI metadata
    instances = [inst for res in reservations for inst in res["Instances"]]
    if not instances:
        return resources

    image_ids = {inst.get("ImageId", "") for inst in instances} - {""}
    ami_info: dict = {}
    if image_ids:
        try:
            for img in ec2.describe_images(ImageIds=list(image_ids))["Images"]:
                ami_info[img["ImageId"]] = img
        except ClientError as e:
            logger.warning("EC2 describe_images error in %s: %s", region, e)

    for inst in instances:
        iid    = inst["InstanceId"]
        img_id = inst.get("ImageId", "")
        img    = ami_info.get(img_id, {})

        # Instance name from Name tag
        name_tag = next(
            (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
            iid,
        )

        # ── OS detection ────────────────────────────────────────────────────
        os_label             = ""
        eol_date_s           = None
        os_source            = "UNKNOWN"
        detection_confidence = "LOW"
        ssm_info             = ssm_map.get(iid)

        # 1. SSM (most accurate)
        if ssm_info:
            os_label   = ssm_info.get("os_label", "")
            eol_date_s = EC2_OS_LIFECYCLE.get(os_label)
            os_source  = "SSM_INVENTORY"
            detection_confidence = "HIGH"

        # 2. AMI metadata fallback
        if not os_label:
            os_label, eol_date_s = _detect_ec2_os(
                img.get("Name", ""),
                img.get("Description", ""),
                inst.get("PlatformDetails", ""),
            )
            if os_label:
                os_source = "AMI_METADATA"
                detection_confidence = "MEDIUM"

        # 3. Deprecated AMI — override eol_date if earlier
        dep_time = img.get("DeprecationTime", "")
        ami_deprecated = False
        if dep_time:
            try:
                dep_d = date.fromisoformat(dep_time[:10])
                if dep_d <= date.today():
                    ami_deprecated = True
                    # Use deprecation date if we have no OS-level EOL or it's later
                    dep_str = str(dep_d)
                    if not eol_date_s or dep_str < eol_date_s:
                        eol_date_s = dep_str
            except ValueError:
                pass

        # ── Classification ──────────────────────────────────────────────────
        if eol_date_s:
            status, eol_date, days = classify_status({"eol": eol_date_s})
        elif ami_deprecated:
            dep_d  = date.fromisoformat(dep_time[:10]) if dep_time else None
            status, eol_date, days = "EOL", str(dep_d) if dep_d else None, (dep_d - date.today()).days if dep_d else None
        elif os_label:
            # OS detected but no lifecycle mapping — tracked OS with no EOL date known
            status, eol_date, days = "LIFECYCLE_NOT_TRACKED", None, None
        else:
            # OS could not be detected at all
            status, eol_date, days = "UNKNOWN", None, None

        # ── Instance type generation check (advisory only — does NOT change lifecycle status) ──
        # Previous-gen instance type is a cost/performance advisory, not an EOL lifecycle risk.
        # Status must reflect only OS/AMI lifecycle so dashboard counts remain accurate.
        instance_type  = inst.get("InstanceType", "")
        itype_family   = instance_type.split(".")[0] if instance_type else ""
        itype_note     = _PREV_GEN_INSTANCE_FAMILIES.get(itype_family, "")
        itype_gen      = "Previous Generation" if itype_note else "Current Generation"

        recommendation = _ec2_recommendation(os_label, status)

        resources.append({
            "resource_id":        f"arn:aws:ec2:{region}:{account_id}:instance/{iid}",
            "service_type":       "EC2",
            "region":             region,
            "account_id":         account_id,
            "version":            os_label or "Unknown OS",
            "resource_name":      name_tag,
            "eol_status":         status,
            "eol_date":           eol_date,
            "days_to_eol":        days,
            "ami_id":             img_id,
            "image_name":         img.get("Name", ""),
            "image_description":  img.get("Description", ""),
            "instance_type":      instance_type,
            "instance_type_generation": itype_gen,
            "instance_type_note": itype_note,
            "has_advisory":       bool(itype_note),
            "advisory_type":      "INSTANCE_GENERATION" if itype_note else "",
            "platform_details":   inst.get("PlatformDetails", ""),
            "os_source":          os_source,
            "detection_source":    os_source,
            "confidence":          detection_confidence,
            "ssm_managed":         bool(ssm_info),
            "ssm_platform_name":   ssm_info.get("platform_name", "") if ssm_info else "",
            "ssm_platform_version": ssm_info.get("platform_version", "") if ssm_info else "",
            "ssm_platform_type":   ssm_info.get("platform_type", "") if ssm_info else "",
            "ssm_computer_name":   ssm_info.get("computer_name", "") if ssm_info else "",
            "ssm_agent_status":    ssm_info.get("agent_status", "") if ssm_info else "",
            "ssm_inventory_unavailable": ssm_unavailable,
            "scan_warning":        SSM_INVENTORY_WARNING if ssm_unavailable else "",
            "recommendation":      recommendation,
        })
        logger.info("  EC2 %s (%s) → %s [%s] %s", iid, name_tag, os_label or "UNKNOWN OS", os_source, status)

    return resources


def collect_codebuild(session, region: str, account_id: str) -> list[dict]:
    client = session.client("codebuild", region_name=region)
    resources = []
    try:
        project_names: list[str] = []
        paginator = client.get_paginator("list_projects")
        for page in paginator.paginate():
            project_names.extend(page.get("projects", []))

        for i in range(0, len(project_names), 100):
            for project in client.batch_get_projects(names=project_names[i:i + 100]).get("projects", []):
                env = project.get("environment") or {}
                image = env.get("image", "")
                status, eol_date, days, reason = _lifecycle_not_tracked(
                    "CodeBuild image lifecycle is not tracked. AWS does not publish a version EOL schedule for build images."
                )
                resources.append({
                    "resource_id":       project.get("arn") or f"arn:aws:codebuild:{region}:{account_id}:project/{project.get('name', '')}",
                    "service_type":      "CodeBuild",
                    "region":            region,
                    "account_id":        account_id,
                    "version":           image or "Unknown image",
                    "resource_name":     project.get("name", ""),
                    "eol_status":        status,
                    "eol_date":          eol_date,
                    "days_to_eol":       days,
                    "detection_source":  "CODEBUILD_PROJECT_ENVIRONMENT",
                    "confidence":        "HIGH" if image else "LOW",
                    "resource_type":     "CodeBuild Project",
                    "codebuild_image":   image,
                    "environment_type":  env.get("type", ""),
                    "compute_type":      env.get("computeType", ""),
                    "privileged_mode":   env.get("privilegedMode"),
                    "classification_reason": reason,
                    "recommendation":    _review_recommendation("CodeBuild build image"),
                })
    except ClientError as e:
        _record_service_warning("CodeBuild", e)
        logger.warning("CodeBuild error in %s: %s", region, e)
    return resources


def collect_elastic_beanstalk(session, region: str, account_id: str) -> list[dict]:
    """Collect Elastic Beanstalk environments and classify platform branch lifecycle.

    Required IAM permissions: elasticbeanstalk:DescribeEnvironments, elasticbeanstalk:DescribePlatformVersion
    Primary signal: PlatformLifecycleState from describe_platform_version (supported/deprecated/retired/beta).
    Fallback: OS inferred from SolutionStackName when ARN is absent or describe_platform_version fails.
    """
    client = session.client("elasticbeanstalk", region_name=region)
    resources = []
    _platform_cache: dict = {}  # ARN → PlatformDescription dict, or None on error
    try:
        paginator = client.get_paginator("describe_environments")
        for page in paginator.paginate(IncludeDeleted=False):
            for env in page.get("Environments", []):
                platform_arn    = env.get("PlatformArn", "")
                stack           = env.get("SolutionStackName", "")
                platform_state  = ""
                platform_branch = ""
                confidence      = "LOW"
                classification_reason = ""

                if platform_arn:
                    if platform_arn not in _platform_cache:
                        try:
                            resp = client.describe_platform_version(PlatformArn=platform_arn)
                            _platform_cache[platform_arn] = resp.get("PlatformDescription") or {}
                        except ClientError as exc:
                            _platform_cache[platform_arn] = None
                            logger.warning("EB describe_platform_version failed: region=%s err=%s",
                                           region, _client_error_code(exc))
                    pd = _platform_cache[platform_arn]
                    if pd is not None:
                        platform_state  = (pd.get("PlatformLifecycleState") or "").lower()
                        platform_branch = pd.get("PlatformBranchName") or ""
                        confidence      = "HIGH"

                # --- Classify ---
                if platform_state == "retired":
                    status, eol_date, days = "EOL", None, None
                    recommendation = (
                        "Elastic Beanstalk platform branch is retired. "
                        "Migrate to a supported AL2023 platform branch immediately."
                    )
                    classification_reason = "AWS API reports PlatformLifecycleState=retired."
                elif platform_state == "deprecated":
                    status, eol_date, days = "NEEDS_INSPECTION", None, None
                    recommendation = (
                        "Elastic Beanstalk platform branch is deprecated by AWS. "
                        "Plan migration to an AL2023 platform branch before it is retired."
                    )
                    classification_reason = "AWS API reports PlatformLifecycleState=deprecated."
                elif platform_state in ("supported", "beta"):
                    status, eol_date, days = "SUPPORTED", None, None
                    recommendation = ""
                elif platform_arn and _platform_cache.get(platform_arn) is None:
                    # describe_platform_version failed → OS fallback (medium confidence)
                    status, eol_date, days, recommendation, classification_reason = _eb_os_fallback_classify(stack)
                    confidence = "MEDIUM" if status != "UNKNOWN" else "LOW"
                elif not platform_arn:
                    # No ARN → OS fallback from stack name
                    status, eol_date, days, recommendation, classification_reason = _eb_os_fallback_classify(stack)
                    confidence = "MEDIUM" if status != "UNKNOWN" else "LOW"
                else:
                    # ARN present + describe returned data, but lifecycle state unrecognised
                    status, eol_date, days = "UNKNOWN", None, None
                    recommendation = (
                        "Elastic Beanstalk platform lifecycle should be verified from AWS official "
                        "platform retirement schedule."
                    )
                    classification_reason = f"Unrecognised PlatformLifecycleState='{platform_state}'."
                    # confidence stays HIGH — API responded, we just don't recognise the state

                resource = {
                    "resource_id":          env.get("EnvironmentArn") or f"arn:aws:elasticbeanstalk:{region}:{account_id}:environment/{env.get('ApplicationName', '')}/{env.get('EnvironmentName', '')}",
                    "service_type":         "ElasticBeanstalk",
                    "region":               region,
                    "account_id":           account_id,
                    "version":              platform_branch or stack or "Unknown platform",
                    "resource_name":        env.get("EnvironmentName", ""),
                    "eol_status":           status,
                    "eol_date":             eol_date,
                    "days_to_eol":          days,
                    "detection_source":     "ELASTIC_BEANSTALK_ENVIRONMENT",
                    "confidence":           confidence,
                    "resource_type":        "Elastic Beanstalk Environment",
                    "application_name":     env.get("ApplicationName", ""),
                    "environment_name":     env.get("EnvironmentName", ""),
                    "environment_id":       env.get("EnvironmentId", ""),
                    "platform_arn":         platform_arn,
                    "platform_branch_name": platform_branch,
                    "platform_lifecycle_state": platform_state,
                    "solution_stack_name":  stack,
                    "environment_status":   env.get("Status", ""),
                    "health":               env.get("Health", ""),
                    "tier":                 (env.get("Tier") or {}).get("Name", ""),
                    "version_label":        env.get("VersionLabel", ""),
                    "date_created":         str(env["DateCreated"]) if env.get("DateCreated") else None,
                    "date_updated":         str(env["DateUpdated"]) if env.get("DateUpdated") else None,
                    "recommendation":       recommendation,
                }
                if classification_reason:
                    resource["classification_reason"] = classification_reason
                resources.append(resource)
                logger.info("  ElasticBeanstalk env=%s platform_state=%s → %s",
                            env.get("EnvironmentName", ""), platform_state or "(stack fallback)", status)
    except ClientError as e:
        _record_service_warning("ElasticBeanstalk", e)
        logger.warning("Elastic Beanstalk error in %s: %s", region, e)
    return resources


def collect_emr(session, region: str, account_id: str) -> list[dict]:
    client = session.client("emr", region_name=region)
    resources = []
    try:
        paginator = client.get_paginator("list_clusters")
        for page in paginator.paginate():
            for item in page.get("Clusters", []):
                cluster = client.describe_cluster(ClusterId=item["Id"]).get("Cluster", {})
                release = cluster.get("ReleaseLabel", "")
                status, eol_date, days, reason = _lifecycle_not_tracked(
                    "EMR release lifecycle is not tracked. Refer to AWS EMR release documentation for support timelines."
                )
                apps = ", ".join(a.get("Name", "") for a in cluster.get("Applications", []) if a.get("Name"))
                resources.append({
                    "resource_id":       cluster.get("ClusterArn") or f"arn:aws:elasticmapreduce:{region}:{account_id}:cluster/{item['Id']}",
                    "service_type":      "EMR",
                    "region":            region,
                    "account_id":        account_id,
                    "version":           release or "Unknown release",
                    "resource_name":     cluster.get("Name") or item.get("Name", item["Id"]),
                    "eol_status":        status,
                    "eol_date":          eol_date,
                    "days_to_eol":       days,
                    "detection_source":  "EMR_CLUSTER",
                    "confidence":        "HIGH" if release else "LOW",
                    "resource_type":     "EMR Cluster",
                    "cluster_id":        item["Id"],
                    "release_label":     release,
                    "cluster_state":     (cluster.get("Status") or {}).get("State", item.get("Status", {}).get("State", "")),
                    "applications":      apps,
                    "classification_reason": reason,
                    "recommendation":    _review_recommendation("EMR release"),
                })
    except ClientError as e:
        _record_service_warning("EMR", e)
        logger.warning("EMR error in %s: %s", region, e)
    return resources


def collect_msk(session, region: str, account_id: str) -> list[dict]:
    client = session.client("kafka", region_name=region)
    resources = []
    try:
        paginator = client.get_paginator("list_clusters_v2")
        for page in paginator.paginate():
            for cluster in page["ClusterInfoList"]:
                version = cluster.get("CurrentVersion", "") or ""
                provisioned = cluster.get("Provisioned") or {}
                serverless = cluster.get("Serverless") or {}
                kafka_ver = (provisioned or serverless).get("CurrentBrokerSoftwareInfo", {}).get("KafkaVersion", version)
                major = ".".join(kafka_ver.split(".")[:2]) if kafka_ver else version
                eol_data = fetch_eol(SERVICE_SLUG["MSK"], major)
                status, eol_date, days = classify_status(eol_data)
                resources.append({
                    "resource_id":       cluster["ClusterArn"],
                    "service_type":      "MSK",
                    "region":            region,
                    "account_id":        account_id,
                    "version":           kafka_ver or version,
                    "resource_name":     cluster["ClusterName"],
                    "eol_status":        status,
                    "eol_date":          eol_date,
                    "days_to_eol":       days,
                    "detection_source":  "MSK_CLUSTER_INFO",
                    "confidence":        "HIGH" if kafka_ver else "LOW",
                    "resource_type":     "MSK Cluster",
                    "kafka_version":     kafka_ver,
                    "cluster_state":     cluster.get("State", ""),
                    "broker_node_count": provisioned.get("NumberOfBrokerNodes"),
                    "current_version":   version,
                    "recommendation":    "" if status not in ("EOL", "EXPIRING_SOON") else _review_recommendation("MSK Kafka version"),
                })
    except ClientError as e:
        _record_service_warning("MSK", e)
        logger.warning("MSK error in %s: %s", region, e)
    return resources


def collect_opensearch(session, region: str, account_id: str) -> list[dict]:
    client = session.client("opensearch", region_name=region)
    resources = []
    try:
        domain_names = [d["DomainName"] for d in client.list_domain_names()["DomainNames"]]
        if not domain_names:
            return resources
        # describe_domains accepts up to 5 domain names per call
        for i in range(0, len(domain_names), 5):
            batch = domain_names[i:i + 5]
            for detail in client.describe_domains(DomainNames=batch)["DomainStatusList"]:
                version_str = detail.get("EngineVersion", "")
                is_elasticsearch = version_str.startswith("Elasticsearch_")
                version = version_str.replace("OpenSearch_", "").replace("Elasticsearch_", "")
                # Legacy Elasticsearch-mode domains use amazon-elasticsearch on endoflife.date.
                # Modern OpenSearch domains use amazon-opensearch.
                # endoflife.date cycles use minor versions (e.g. "2.17", "7.10"), not just major.
                slug = "amazon-elasticsearch" if is_elasticsearch else SERVICE_SLUG["OpenSearch"]
                eol_data = fetch_eol(slug, version)
                status, eol_date, days = classify_status(eol_data)
                resources.append({
                    "resource_id":   detail["ARN"],
                    "service_type":  "OpenSearch",
                    "region":        region,
                    "account_id":    account_id,
                    "version":       version,
                    "resource_name": detail["DomainName"],
                    "eol_status":    status,
                    "eol_date":      eol_date,  # None when no EOL announced; frontend renders "—"
                    "days_to_eol":   days,
                    "engine_mode":   "Elasticsearch" if is_elasticsearch else "OpenSearch",
                })
    except ClientError as e:
        if _is_access_denied(e):
            _record_service_warning("OpenSearch", e)
        logger.warning("OpenSearch error in %s: %s", region, e)
    return resources


def collect_documentdb(session, region: str, account_id: str) -> list[dict]:
    client = session.client("docdb", region_name=region)
    resources = []
    try:
        paginator = client.get_paginator("describe_db_clusters")
        for page in paginator.paginate(Filters=[{"Name": "engine", "Values": ["docdb"]}]):
            for cluster in page["DBClusters"]:
                version = cluster.get("EngineVersion", "")
                # endoflife.date cycles use major.minor ("4.0", "5.0") — not major-only
                minor = ".".join(version.split(".")[:2]) if version else ""
                eol_data = fetch_eol(SERVICE_SLUG["DocumentDB"], minor)
                status, eol_date, days = classify_status(eol_data)
                resources.append({
                    "resource_id":   cluster["DBClusterArn"],
                    "service_type":  "DocumentDB",
                    "region":        region,
                    "account_id":    account_id,
                    "version":       version,
                    "resource_name": cluster["DBClusterIdentifier"],
                    "eol_status":    status,
                    "eol_date":      eol_date,
                    "days_to_eol":   days,
                })
    except ClientError as e:
        logger.warning("DocumentDB error in %s: %s", region, e)
    return resources


def collect_neptune(session, region: str, account_id: str) -> list[dict]:
    client = session.client("neptune", region_name=region)
    resources = []
    try:
        paginator = client.get_paginator("describe_db_clusters")
        for page in paginator.paginate(Filters=[{"Name": "engine", "Values": ["neptune"]}]):
            for cluster in page["DBClusters"]:
                version = cluster.get("EngineVersion", "")
                # endoflife.date cycles use full 4-part patch versions (e.g. "1.4.7.0")
                eol_data = fetch_eol(SERVICE_SLUG["Neptune"], version)
                status, eol_date, days = classify_status(eol_data)
                resources.append({
                    "resource_id":   cluster["DBClusterArn"],
                    "service_type":  "Neptune",
                    "region":        region,
                    "account_id":    account_id,
                    "version":       version,
                    "resource_name": cluster["DBClusterIdentifier"],
                    "eol_status":    status,
                    "eol_date":      eol_date,
                    "days_to_eol":   days,
                })
    except ClientError as e:
        logger.warning("Neptune error in %s: %s", region, e)
    return resources


def collect_glue(session, region: str, account_id: str) -> list[dict]:
    client = session.client("glue", region_name=region)
    resources = []
    try:
        paginator = client.get_paginator("get_jobs")
        for page in paginator.paginate():
            for job in page.get("Jobs", []):
                job_name = job.get("Name", "")
                glue_version = job.get("GlueVersion", "")
                command = job.get("Command") or {}
                python_version = command.get("PythonVersion", "")
                version = f"Glue {glue_version}" + (f" / Python {python_version}" if python_version else "")
                eol_data = fetch_eol(SERVICE_SLUG["Glue"], glue_version) if glue_version else None
                status, eol_date, days = classify_status(eol_data)
                resources.append({
                    "resource_id":       f"arn:aws:glue:{region}:{account_id}:job/{job_name}",
                    "service_type":      "Glue",
                    "region":            region,
                    "account_id":        account_id,
                    "version":           version or "Unknown Glue version",
                    "resource_name":     job_name,
                    "eol_status":        status,
                    "eol_date":          eol_date,
                    "days_to_eol":       days,
                    "detection_source":  "GLUE_JOB_CONFIG",
                    "confidence":        "HIGH" if glue_version else "LOW",
                    "resource_type":     "Glue Job",
                    "glue_version":      glue_version,
                    "python_version":    python_version,
                    "spark_version":     (job.get("DefaultArguments") or {}).get("--spark-version", ""),
                    "worker_type":       job.get("WorkerType", ""),
                    "command_name":      command.get("Name", ""),
                    "command_script_location": command.get("ScriptLocation", ""),
                    "recommendation":    "" if status not in ("EOL", "EXPIRING_SOON") else _review_recommendation("AWS Glue version"),
                })
    except ClientError as e:
        _record_service_warning("Glue", e)
        logger.warning("Glue error in %s: %s", region, e)
    return resources


def collect_cloudfront_functions(session, region: str, account_id: str) -> list[dict]:
    if region != "us-east-1":
        return []
    client = session.client("cloudfront", region_name="us-east-1")
    resources = []
    try:
        cf_resp = client.list_functions()
        function_list = cf_resp.get("FunctionList", {})
        for item in function_list.get("Items", []):
            meta = item.get("FunctionMetadata") or {}
            cfg = item.get("FunctionConfig") or {}
            runtime = cfg.get("Runtime", "")
            resources.append({
                "resource_id":       meta.get("FunctionARN") or f"arn:aws:cloudfront::{account_id}:function/{item.get('Name', '')}",
                "service_type":      "CloudFrontFunctions",
                "region":            "global",
                "account_id":        account_id,
                "version":           runtime or "Unknown runtime",
                "resource_name":     item.get("Name", ""),
                "eol_status":        "LIFECYCLE_NOT_TRACKED",
                "eol_date":          None,
                "days_to_eol":       None,
                "detection_source":  "CLOUDFRONT_FUNCTION",
                "confidence":        "HIGH" if runtime else "LOW",
                "resource_type":     "CloudFront Function",
                "function_runtime":  runtime,
                "function_stage":    meta.get("Stage", ""),
                "function_status":   item.get("Status", ""),
                "classification_reason": "No published EOL lifecycle is currently tracked for CloudFront Functions runtimes.",
                "recommendation":    "No published EOL lifecycle is currently tracked for this runtime.",
            })
    except ClientError as e:
        _record_service_warning("CloudFrontFunctions", e)
        logger.warning("CloudFront Functions error: %s", e)
    return resources


def collect_ecr(session, region: str, account_id: str) -> list[dict]:
    client = session.client("ecr", region_name=region)
    resources = []
    try:
        repo_paginator = client.get_paginator("describe_repositories")
        for repo_page in repo_paginator.paginate():
            for repo in repo_page.get("repositories", []):
                repo_name = repo.get("repositoryName", "")
                images = []
                try:
                    img_paginator = client.get_paginator("describe_images")
                    for img_page in img_paginator.paginate(repositoryName=repo_name):
                        images.extend(img_page.get("imageDetails", []))
                except ClientError as img_exc:
                    logger.warning("ECR describe_images error for %s in %s: %s", repo_name, region, img_exc)
                    continue

                def _pushed_sort_key(img: dict) -> float:
                    pushed_at = img.get("imagePushedAt")
                    return pushed_at.timestamp() if hasattr(pushed_at, "timestamp") else 0.0

                images.sort(key=_pushed_sort_key, reverse=True)
                for img in images[:10]:
                    digest = img.get("imageDigest", "")
                    short_digest = digest.replace("sha256:", "")[:12]
                    tags = img.get("imageTags") or []
                    tag = tags[0] if tags else None
                    display_tag = tag if tag else f"<untagged>@{short_digest}"
                    pushed = img.get("imagePushedAt")
                    # ECR itself has no published EOL lifecycle. Container lifecycle risk
                    # lives inside the image (base OS, runtime, packages). Without SBOM /
                    # Trivy / base-image inspection this record is inventory-only.
                    # TODO: Reintroduce as a proper lifecycle module once container image
                    #       inspection (base-image mapping, Trivy/Grype, SBOM) is implemented.
                    reason = (
                        "ECR repository/image metadata does not provide direct EOL lifecycle "
                        "information. Container lifecycle risk requires base image, package, "
                        "runtime, or SBOM analysis."
                    )
                    resources.append({
                        "resource_id":       f"arn:aws:ecr:{region}:{account_id}:repository/{repo_name}@{digest}",
                        "service_type":      "ECR",
                        "region":            region,
                        "account_id":        account_id,
                        "version":           display_tag,
                        "resource_name":     f"{repo_name}:{display_tag}",
                        "eol_status":        "LIFECYCLE_NOT_TRACKED",
                        "eol_date":          None,
                        "days_to_eol":       None,
                        "detection_source":  "ECR_IMAGE_METADATA",
                        "confidence":        "LOW",
                        "resource_type":     "ECR Image",
                        "repository_name":   repo_name,
                        "image_tag":         display_tag,
                        "image_digest":      digest,
                        "short_digest":      short_digest,
                        "image_pushed_at":   pushed.isoformat() if hasattr(pushed, "isoformat") else pushed,
                        "image_size_in_bytes": img.get("imageSizeInBytes"),
                        "base_image_status": "LIFECYCLE_NOT_TRACKED",
                        "status_label":      "Lifecycle Not Tracked",
                        "classification_reason": reason,
                        "recommendation":    "Enable container image scanning (Trivy/Grype/SBOM) to detect base OS, runtime, and package EOL status inside the image.",
                    })
                    logger.info(
                        "  ECR repo=%s tag=%s digest=%.16s status=LIFECYCLE_NOT_TRACKED (inventory-only)",
                        repo_name, display_tag, digest,
                    )
    except ClientError as e:
        _record_service_warning("ECR", e)
        logger.warning("ECR error in %s: %s", region, e)
    return resources


def collect_amazon_mq(session, region: str, account_id: str) -> list[dict]:
    """Collect Amazon MQ brokers and classify ActiveMQ/RabbitMQ engine version lifecycle.

    Required IAM permissions: mq:ListBrokers, mq:DescribeBroker
    """
    client = session.client("mq", region_name=region)
    resources = []
    try:
        brokers = []
        resp = client.list_brokers(MaxResults=100)
        brokers.extend(resp.get("BrokerSummaries", []))
        while resp.get("NextToken"):
            resp = client.list_brokers(MaxResults=100, NextToken=resp["NextToken"])
            brokers.extend(resp.get("BrokerSummaries", []))

        for summary in brokers:
            broker_id = summary.get("BrokerId", "")
            if not broker_id:
                continue
            try:
                detail = client.describe_broker(BrokerId=broker_id)
            except ClientError as exc:
                logger.warning("Amazon MQ describe_broker failed: broker=%s region=%s err=%s",
                               broker_id, region, _client_error_code(exc))
                continue

            engine_type    = detail.get("EngineType", "").upper()   # ACTIVEMQ or RABBITMQ
            engine_version = detail.get("EngineVersion", "")
            broker_name    = detail.get("BrokerName", "")
            broker_arn     = detail.get("BrokerArn", "")
            broker_state   = detail.get("BrokerState", "")
            deployment_mode = detail.get("DeploymentMode", "")
            auto_minor     = detail.get("AutoMinorVersionUpgrade", False)

            # Select slug by engine type; fall back to UNKNOWN if unrecognised.
            if engine_type == "ACTIVEMQ":
                slug = SERVICE_SLUG["AmazonMQ_ActiveMQ"]
            elif engine_type == "RABBITMQ":
                slug = SERVICE_SLUG["AmazonMQ_RabbitMQ"]
            else:
                slug = None

            if slug and engine_version:
                # Use major.minor for lookup (e.g. "5.17.6" → "5.17", "3.11.28" → "3.11")
                parts = engine_version.split(".")
                lookup_ver = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else engine_version
                eol_data = fetch_eol(slug, lookup_ver)
            else:
                eol_data = None

            status, eol_date, days = classify_status(eol_data)
            support_raw = (eol_data or {}).get("support")
            final_raw   = (eol_data or {}).get("eolFrom") or (eol_data or {}).get("eol")
            support_str = str(support_raw) if support_raw and support_raw is not False else None
            final_str   = str(final_raw)   if final_raw   and final_raw   is not False else None

            if status in ("EOL", "EXPIRING_SOON"):
                recommendation = _review_recommendation(f"Amazon MQ {engine_type.title()} {engine_version}")
            elif status == "UNKNOWN":
                recommendation = (
                    "Amazon MQ engine version lifecycle should be verified from AWS official "
                    "Amazon MQ version support documentation."
                )
            else:
                recommendation = ""

            resources.append({
                "resource_id":              broker_arn or f"arn:aws:mq:{region}:{account_id}:broker:{broker_id}",
                "service_type":             "AmazonMQ",
                "region":                   region,
                "account_id":               account_id,
                "version":                  engine_version or "Unknown version",
                "resource_name":            broker_name,
                "eol_status":               status,
                "eol_date":                 eol_date,
                "days_to_eol":              days,
                "support_end_date":         support_str,
                "final_eol_date":           final_str,
                "detection_source":         "AMAZON_MQ_BROKER_DETAIL",
                "resource_type":            "Amazon MQ Broker",
                "engine_type":              engine_type,
                "broker_id":                broker_id,
                "broker_state":             broker_state,
                "deployment_mode":          deployment_mode,
                "auto_minor_version_upgrade": auto_minor,
                "recommendation":           recommendation,
                **_lifecycle_fields(eol_data),
            })
            logger.info("  AmazonMQ broker=%s engine=%s version=%s → %s",
                        broker_name, engine_type, engine_version, status)

    except ClientError as e:
        _record_service_warning("AmazonMQ", e)
        logger.warning("Amazon MQ error in %s: %s", region, e)
    return resources


def collect_dms(session, region: str, account_id: str) -> list[dict]:
    """Collect AWS DMS replication instances and classify engine version lifecycle.

    Required IAM permissions: dms:DescribeReplicationInstances
    """
    client = session.client("dms", region_name=region)
    resources = []
    try:
        paginator = client.get_paginator("describe_replication_instances")
        for page in paginator.paginate():
            for inst in page.get("ReplicationInstances", []):
                engine_version = inst.get("EngineVersion", "")
                identifier     = inst.get("ReplicationInstanceIdentifier", "")
                arn            = inst.get("ReplicationInstanceArn", "")
                inst_class     = inst.get("ReplicationInstanceClass", "")
                inst_status    = inst.get("ReplicationInstanceStatus", "")
                auto_minor     = inst.get("AutoMinorVersionUpgrade", False)
                allocated_gb   = inst.get("AllocatedStorage")
                publicly       = inst.get("PubliclyAccessible", False)
                multi_az       = inst.get("MultiAZ", False)

                if engine_version:
                    parts = engine_version.split(".")
                    lookup_ver = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else engine_version
                    eol_data = fetch_eol(SERVICE_SLUG["DMS"], lookup_ver)
                else:
                    eol_data = None

                status, eol_date, days = classify_status(eol_data)
                support_raw = (eol_data or {}).get("support")
                final_raw   = (eol_data or {}).get("eolFrom") or (eol_data or {}).get("eol")
                support_str = str(support_raw) if support_raw and support_raw is not False else None
                final_str   = str(final_raw)   if final_raw   and final_raw   is not False else None

                if status in ("EOL", "EXPIRING_SOON"):
                    recommendation = _review_recommendation(f"AWS DMS engine version {engine_version}")
                elif status == "UNKNOWN":
                    recommendation = (
                        "AWS DMS engine version lifecycle should be verified from AWS official "
                        "DMS release notes or engine version metadata."
                    )
                else:
                    recommendation = ""

                resources.append({
                    "resource_id":                  arn or f"arn:aws:dms:{region}:{account_id}:ri:{identifier}",
                    "service_type":                 "DMS",
                    "region":                       region,
                    "account_id":                   account_id,
                    "version":                      engine_version or "Unknown version",
                    "resource_name":                identifier,
                    "eol_status":                   status,
                    "eol_date":                     eol_date,
                    "days_to_eol":                  days,
                    "support_end_date":             support_str,
                    "final_eol_date":               final_str,
                    "detection_source":             "DMS_REPLICATION_INSTANCE",
                    "resource_type":                "DMS Replication Instance",
                    "replication_instance_class":   inst_class,
                    "replication_instance_status":  inst_status,
                    "auto_minor_version_upgrade":   auto_minor,
                    "allocated_storage":            allocated_gb,
                    "publicly_accessible":          publicly,
                    "multi_az":                     multi_az,
                    "recommendation":               recommendation,
                    **_lifecycle_fields(eol_data),
                })
                logger.info("  DMS instance=%s version=%s → %s", identifier, engine_version, status)

    except ClientError as e:
        _record_service_warning("DMS", e)
        logger.warning("DMS error in %s: %s", region, e)
    return resources


def collect_sagemaker_notebooks(session, region: str, account_id: str) -> list[dict]:
    """Collect SageMaker Notebook Instances and classify platform version lifecycle.

    Required IAM permissions: sagemaker:ListNotebookInstances, sagemaker:DescribeNotebookInstance
    Platform identifiers (notebook-al1-v1, notebook-al2-v*, notebook-al2023-v1) are classified
    via an inline AWS retirement table. AL1 retired December 2023; AL2 support ends June 2026.
    """
    client = session.client("sagemaker", region_name=region)
    resources = []
    try:
        nb_names = []
        for page in client.get_paginator("list_notebook_instances").paginate():
            for summary in page.get("NotebookInstances", []):
                nb_names.append(summary["NotebookInstanceName"])

        for name in nb_names:
            try:
                detail = client.describe_notebook_instance(NotebookInstanceName=name)
            except ClientError as exc:
                logger.warning("SageMaker describe_notebook_instance failed: name=%s region=%s err=%s",
                               name, region, _client_error_code(exc))
                continue

            platform_id  = detail.get("PlatformIdentifier", "")
            nb_arn       = detail.get("NotebookInstanceArn", "")
            nb_status    = detail.get("NotebookInstanceStatus", "")
            instance_type = detail.get("InstanceType", "")
            volume_gb    = detail.get("VolumeSizeInGB")
            creation_time = detail.get("CreationTime")
            last_modified = detail.get("LastModifiedTime")
            direct_inet  = detail.get("DirectInternetAccess", "")
            root_access  = detail.get("RootAccess", "")
            role_arn     = detail.get("RoleArn", "")

            classification_reason = ""
            if not platform_id:
                status, eol_date, days = "UNKNOWN", None, None
                recommendation = (
                    "SageMaker Notebook Instance platform identifier is not set. "
                    "Update to notebook-al2023-v1 for the current supported platform."
                )
                classification_reason = "PlatformIdentifier is not set on this notebook instance."
            elif platform_id in SAGEMAKER_NOTEBOOK_PLATFORM_EOL:
                eol_date_str = SAGEMAKER_NOTEBOOK_PLATFORM_EOL[platform_id]
                if eol_date_str:
                    status, eol_date, days = classify_status({"eol": eol_date_str})
                    recommendation = (
                        f"SageMaker Notebook platform {platform_id} is end-of-life or expiring soon. "
                        "Migrate to notebook-al2023-v1."
                    )
                else:
                    status, eol_date, days = "SUPPORTED", None, None
                    recommendation = ""
            else:
                status, eol_date, days = "UNKNOWN", None, None
                recommendation = (
                    "Verify SageMaker Notebook platform lifecycle from AWS official "
                    "SageMaker platform support documentation."
                )
                classification_reason = (
                    f"SageMaker Notebook platform '{platform_id}' is not in the known "
                    "lifecycle table. Check AWS SageMaker Notebook release notes."
                )

            resource = {
                "resource_id":              nb_arn or f"arn:aws:sagemaker:{region}:{account_id}:notebook-instance/{name}",
                "service_type":             "SageMakerNotebook",
                "region":                   region,
                "account_id":               account_id,
                "version":                  platform_id or "Unknown platform",
                "resource_name":            name,
                "eol_status":               status,
                "eol_date":                 eol_date,
                "days_to_eol":              days,
                "detection_source":         "SAGEMAKER_NOTEBOOK_INSTANCE",
                "resource_type":            "SageMaker Notebook Instance",
                "platform_identifier":      platform_id,
                "notebook_instance_status": nb_status,
                "instance_type":            instance_type,
                "volume_size_in_gb":        volume_gb,
                "direct_internet_access":   direct_inet,
                "root_access":              root_access,
                "role_arn":                 role_arn,
                "creation_time":            creation_time.isoformat() if hasattr(creation_time, "isoformat") else creation_time,
                "last_modified_time":       last_modified.isoformat() if hasattr(last_modified, "isoformat") else last_modified,
                "recommendation":           recommendation,
            }
            if classification_reason:
                resource["classification_reason"] = classification_reason
            resources.append(resource)
            logger.info("  SageMakerNotebook nb=%s platform=%s → %s", name, platform_id, status)

    except ClientError as e:
        _record_service_warning("SageMakerNotebook", e)
        logger.warning("SageMaker Notebook error in %s: %s", region, e)
    return resources


def collect_ecs_fargate(session, region: str, account_id: str) -> list[dict]:
    """Collect ECS Fargate services and classify platform version lifecycle.

    Required IAM permissions: ecs:ListClusters, ecs:ListServices, ecs:DescribeServices
    Platform versions 1.0.0–1.3.0 were retired by AWS in April 2022.
    Services pinned to 'LATEST' cannot be version-classified (dynamic alias).
    """
    client = session.client("ecs", region_name=region)
    resources = []
    try:
        cluster_arns = []
        for page in client.get_paginator("list_clusters").paginate():
            cluster_arns.extend(page.get("clusterArns", []))

        for cluster_arn in cluster_arns:
            cluster_name = cluster_arn.split("/")[-1]
            try:
                svc_arns = []
                for page in client.get_paginator("list_services").paginate(cluster=cluster_arn):
                    svc_arns.extend(page.get("serviceArns", []))
            except ClientError as exc:
                logger.warning("ECS list_services failed: cluster=%s region=%s err=%s",
                               cluster_name, region, _client_error_code(exc))
                continue

            # describe_services accepts at most 10 ARNs per call
            for i in range(0, len(svc_arns), 10):
                try:
                    svcs = client.describe_services(
                        cluster=cluster_arn, services=svc_arns[i:i + 10]
                    ).get("services", [])
                except ClientError as exc:
                    logger.warning("ECS describe_services failed: cluster=%s region=%s err=%s",
                                   cluster_name, region, _client_error_code(exc))
                    continue

                for svc in svcs:
                    launch_type   = svc.get("launchType", "")
                    cap_strategy  = svc.get("capacityProviderStrategy") or []
                    is_fargate = (
                        launch_type == "FARGATE" or
                        any("FARGATE" in (c.get("capacityProvider", "")).upper() for c in cap_strategy)
                    )
                    if not is_fargate:
                        continue

                    platform_version = svc.get("platformVersion") or "LATEST"
                    platform_family  = svc.get("platformFamily", "LINUX")
                    svc_name         = svc.get("serviceName", "")
                    svc_arn          = svc.get("serviceArn", "")

                    classification_reason = ""
                    if platform_version == "LATEST":
                        status         = "LIFECYCLE_NOT_TRACKED"
                        eol_date       = None
                        days           = None
                        recommendation = (
                            "Service uses LATEST platform version alias. Pin to '1.4.0' to "
                            "ensure predictable behavior and enable version lifecycle tracking."
                        )
                        classification_reason = (
                            "Fargate LATEST is a dynamic alias. The underlying platform version "
                            "cannot be determined from the service configuration alone."
                        )
                    elif platform_version in FARGATE_PLATFORM_EOL:
                        eol_date_str = FARGATE_PLATFORM_EOL[platform_version]
                        if eol_date_str:
                            status, eol_date, days = classify_status({"eol": eol_date_str})
                            recommendation = (
                                f"ECS Fargate platform version {platform_version} was retired by AWS. "
                                "Migrate services to platform version 1.4.0."
                            )
                        else:
                            status, eol_date, days = "SUPPORTED", None, None
                            recommendation = ""
                    else:
                        status, eol_date, days = "UNKNOWN", None, None
                        recommendation = (
                            "Verify ECS Fargate platform version lifecycle from AWS official "
                            "ECS platform version release notes."
                        )
                        classification_reason = (
                            f"Fargate platform version '{platform_version}' is not in the known "
                            "lifecycle table. Check AWS ECS platform version release notes."
                        )

                    resource = {
                        "resource_id":      svc_arn,
                        "service_type":     "ECSFargate",
                        "region":           region,
                        "account_id":       account_id,
                        "version":          platform_version,
                        "resource_name":    svc_name,
                        "eol_status":       status,
                        "eol_date":         eol_date,
                        "days_to_eol":      days,
                        "detection_source": "ECS_SERVICE",
                        "resource_type":    "ECS Fargate Service",
                        "platform_version": platform_version,
                        "platform_family":  platform_family,
                        "cluster_name":     cluster_name,
                        "cluster_arn":      cluster_arn,
                        "service_status":   svc.get("status", ""),
                        "running_count":    svc.get("runningCount", 0),
                        "desired_count":    svc.get("desiredCount", 0),
                        "launch_type":      launch_type or "FARGATE",
                        "recommendation":   recommendation,
                    }
                    if classification_reason:
                        resource["classification_reason"] = classification_reason
                    resources.append(resource)
                    logger.info("  ECSFargate svc=%s platform=%s → %s",
                                svc_name, platform_version, status)

    except ClientError as e:
        _record_service_warning("ECSFargate", e)
        logger.warning("ECS Fargate error in %s: %s", region, e)
    return resources


def collect_mwaa(session, region: str, account_id: str) -> list[dict]:
    """Collect Amazon MWAA environments and classify Apache Airflow version lifecycle.

    Required IAM permissions: mwaa:ListEnvironments, mwaa:GetEnvironment
    Lifecycle source: apache-airflow (endoflife.date major.minor lookup).
    AWS MWAA official support dates should be added via the verified_lifecycle table.
    """
    client = session.client("mwaa", region_name=region)
    resources = []
    try:
        env_names = []
        resp = client.list_environments()
        env_names.extend(resp.get("Environments", []))
        while resp.get("NextToken"):
            resp = client.list_environments(NextToken=resp["NextToken"])
            env_names.extend(resp.get("Environments", []))

        for name in env_names:
            try:
                env = client.get_environment(Name=name).get("Environment", {})
            except ClientError as exc:
                logger.warning("MWAA get_environment failed: name=%s region=%s err=%s",
                               name, region, _client_error_code(exc))
                continue

            airflow_version = env.get("AirflowVersion", "")
            env_arn         = env.get("Arn", "")
            env_status      = env.get("Status", "")
            env_class       = env.get("EnvironmentClass", "")
            webserver_mode  = env.get("WebserverAccessMode", "")
            max_workers     = env.get("MaxWorkers")
            min_workers     = env.get("MinWorkers")
            schedulers      = env.get("Schedulers")
            created_at      = env.get("CreatedAt")

            if airflow_version:
                parts = airflow_version.split(".")
                lookup_ver = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else airflow_version
                eol_data = fetch_eol(SERVICE_SLUG["MWAA"], lookup_ver)
            else:
                eol_data = None

            status, eol_date, days = classify_status(eol_data)
            support_raw = (eol_data or {}).get("support")
            final_raw   = (eol_data or {}).get("eolFrom") or (eol_data or {}).get("eol")
            support_str = str(support_raw) if support_raw and support_raw is not False else None
            final_str   = str(final_raw)   if final_raw   and final_raw   is not False else None

            if status in ("EOL", "EXPIRING_SOON"):
                recommendation = _review_recommendation(f"Amazon MWAA Airflow {airflow_version}")
            elif status == "UNKNOWN":
                recommendation = (
                    "Amazon MWAA Airflow version lifecycle should be verified from AWS official "
                    "MWAA version support documentation."
                )
            else:
                recommendation = ""

            resources.append({
                "resource_id":          env_arn or f"arn:aws:airflow:{region}:{account_id}:environment/{name}",
                "service_type":         "MWAA",
                "region":               region,
                "account_id":           account_id,
                "version":              airflow_version or "Unknown version",
                "resource_name":        name,
                "eol_status":           status,
                "eol_date":             eol_date,
                "days_to_eol":          days,
                "support_end_date":     support_str,
                "final_eol_date":       final_str,
                "detection_source":     "MWAA_ENVIRONMENT",
                "resource_type":        "MWAA Environment",
                "airflow_version":      airflow_version,
                "environment_class":    env_class,
                "environment_status":   env_status,
                "webserver_access_mode": webserver_mode,
                "max_workers":          max_workers,
                "min_workers":          min_workers,
                "schedulers":           schedulers,
                "created_at":           created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
                "recommendation":       recommendation,
                **_lifecycle_fields(eol_data),
            })
            logger.info("  MWAA env=%s airflow=%s → %s", name, airflow_version, status)

    except ClientError as e:
        _record_service_warning("MWAA", e)
        logger.warning("MWAA error in %s: %s", region, e)
    return resources


def collect_batch(session, region: str, account_id: str) -> list[dict]:
    """Collect AWS Batch managed compute environments and classify AMI lifecycle.

    Required IAM permissions: batch:DescribeComputeEnvironments
    Classification source: ec2Configuration.imageType from describe_compute_environments.
    AL2 ECS/EKS-optimized AMIs follow Amazon Linux 2 standard support (ends 2026-06-30).
    AL2023 variants are current. Custom imageId without imageType → NEEDS_INSPECTION.
    """
    client = session.client("batch", region_name=region)
    resources = []
    try:
        paginator = client.get_paginator("describe_compute_environments")
        for page in paginator.paginate():
            for ce in page.get("computeEnvironments", []):
                ce_name      = ce.get("computeEnvironmentName", "")
                ce_arn       = ce.get("computeEnvironmentArn", "")
                ce_type      = ce.get("type", "")
                ce_state     = ce.get("state", "")
                ce_status    = ce.get("status", "")
                status_reason = ce.get("statusReason", "")
                service_role = ce.get("serviceRole", "")

                compute_resources = ce.get("computeResources") or {}
                cr_type        = compute_resources.get("type", "")
                alloc_strategy = compute_resources.get("allocationStrategy", "")
                min_vcpus      = compute_resources.get("minvCpus")
                max_vcpus      = compute_resources.get("maxvCpus")
                desired_vcpus  = compute_resources.get("desiredvCpus")
                instance_types = compute_resources.get("instanceTypes", [])
                image_id       = compute_resources.get("imageId", "")
                ec2_config     = compute_resources.get("ec2Configuration") or []
                eks_config     = ce.get("eksConfiguration") or {}

                # Extract imageType from the first ec2Configuration entry (usually only one)
                image_type = ec2_config[0].get("imageType", "") if ec2_config else ""

                classification_reason = ""
                if image_type in BATCH_COMPUTE_AMI_EOL:
                    eol_date_str = BATCH_COMPUTE_AMI_EOL[image_type]
                    if eol_date_str:
                        eol_status, eol_date, days = classify_status({"eol": eol_date_str})
                        recommendation = (
                            f"AWS Batch compute environment uses {image_type} (Amazon Linux 2). "
                            "Migrate to an AL2023 imageType before 2026-06-30."
                        ) if eol_status in ("EOL", "EXPIRING_SOON") else ""
                    else:
                        eol_status, eol_date, days = "SUPPORTED", None, None
                        recommendation = ""
                    confidence = "HIGH"
                    classification_reason = f"AMI lifecycle classified from ec2Configuration imageType={image_type}."
                elif image_type:
                    # imageType is set but not in our table — unrecognised
                    eol_status, eol_date, days = "UNKNOWN", None, None
                    recommendation = (
                        "Verify AWS Batch compute environment AMI lifecycle from AWS official documentation."
                    )
                    confidence = "LOW"
                    classification_reason = (
                        f"ec2Configuration imageType='{image_type}' is not in the known lifecycle table."
                    )
                elif image_id:
                    # Custom AMI ID set but no imageType — OS cannot be determined safely
                    eol_status, eol_date, days = "NEEDS_INSPECTION", None, None
                    recommendation = (
                        "Custom AMI specified without ec2Configuration imageType. "
                        "Verify AMI OS and support status manually."
                    )
                    confidence = "LOW"
                    classification_reason = (
                        "Custom imageId without ec2Configuration.imageType — OS cannot be determined safely."
                    )
                elif cr_type in ("FARGATE", "FARGATE_SPOT"):
                    eol_status, eol_date, days = "LIFECYCLE_NOT_TRACKED", None, None
                    recommendation = ""
                    confidence = "HIGH"
                    classification_reason = (
                        "Fargate-backed Batch compute environment has no AMI lifecycle to track."
                    )
                else:
                    eol_status, eol_date, days = "UNKNOWN", None, None
                    recommendation = "Verify AWS Batch compute environment AMI configuration."
                    confidence = "LOW"
                    classification_reason = (
                        "No ec2Configuration imageType or imageId found — cannot determine AMI lifecycle."
                    )

                version = image_type or image_id or cr_type or "Unknown AMI type"

                resource = {
                    "resource_id":             ce_arn or f"arn:aws:batch:{region}:{account_id}:compute-environment/{ce_name}",
                    "service_type":            "AWSBatch",
                    "region":                  region,
                    "account_id":              account_id,
                    "version":                 version,
                    "resource_name":           ce_name,
                    "eol_status":              eol_status,
                    "eol_date":                eol_date,
                    "days_to_eol":             days,
                    "detection_source":        "BATCH_COMPUTE_ENVIRONMENT",
                    "resource_type":           "AWS Batch Compute Environment",
                    "confidence":              confidence,
                    "recommendation":          recommendation,
                    "classification_reason":   classification_reason,
                    "compute_environment_name": ce_name,
                    "compute_environment_arn": ce_arn,
                    "type":                    ce_type,
                    "state":                   ce_state,
                    "status":                  ce_status,
                    "status_reason":           status_reason,
                    "compute_resources_type":  cr_type,
                    "allocation_strategy":     alloc_strategy,
                    "min_vcpus":               min_vcpus,
                    "max_vcpus":               max_vcpus,
                    "desired_vcpus":           desired_vcpus,
                    "instance_types":          instance_types,
                    "image_id":                image_id,
                    "image_type":              image_type,
                    "ec2_configuration":       ec2_config,
                    "eks_configuration":       eks_config or None,
                    "service_role":            service_role,
                }
                resources.append(resource)
                logger.info("  Batch ce=%s image_type=%s → %s",
                            ce_name, image_type or "(none)", eol_status)

    except ClientError as e:
        _record_service_warning("AWSBatch", e)
        logger.warning("AWS Batch error in %s: %s", region, e)
    return resources


COLLECTORS = [
    collect_lambda,
    collect_eks,
    collect_ecs_fargate,
    collect_rds,
    collect_elasticache,
    collect_ec2_amis,
    collect_codebuild,
    collect_elastic_beanstalk,
    collect_emr,
    collect_msk,
    collect_amazon_mq,
    collect_dms,
    collect_mwaa,
    collect_batch,
    collect_sagemaker_notebooks,
    collect_opensearch,
    collect_documentdb,
    collect_neptune,
    collect_glue,
    collect_cloudfront_functions,
    collect_ecr,
]


def run_all_collectors(
    session,
    account_id: str,
    regions: list | None = None,
    cancel_check=None,
) -> list[dict]:
    SCAN_WARNINGS.clear()
    if regions is None:
        regions = get_enabled_regions(session)
        logger.info("Resolved scan regions (all enabled): %s", ", ".join(regions))
    timed = _TimedSession(session)
    all_resources: list[dict] = []
    for region in regions:
        if cancel_check and cancel_check():
            logger.info("Org scan cancel observed before region=%s account=%s", region, account_id)
            raise OrgScanCancelled(f"cancel before region {region}")
        logger.info("Scanning region %s", region)
        for collector in COLLECTORS:
            if cancel_check and cancel_check():
                logger.info("Org scan cancel observed before collector=%s region=%s account=%s",
                            collector.__name__, region, account_id)
                raise OrgScanCancelled(f"cancel before {collector.__name__} in {region}")
            try:
                results = collector(timed, region, account_id)
                all_resources.extend(results)
                logger.info("  %s → %d resources", collector.__name__, len(results))
            except OrgScanCancelled:
                raise
            except Exception as exc:
                logger.warning("  %s failed in %s: %s", collector.__name__, region, exc)

    # Inject lifecycle classification fields from service registry into every resource.
    # Using setdefault so any collector that already sets these fields keeps its value.
    for resource in all_resources:
        svc   = resource.get("service_type", "")
        entry = SERVICE_REGISTRY.get(svc, {})
        resource.setdefault("lifecycle_applicable",  entry.get("lifecycle_applicable",  True))
        resource.setdefault("classification_type",   entry.get("classification_type",   "EOL_TRACKED"))
        status = resource.get("eol_status", "UNKNOWN")
        resource.setdefault("status_label", _STATUS_LABELS.get(status, status.replace("_", " ").title()))

    return all_resources


# ── Lambda Handler ────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    sts = boto3.client("sts")
    account_id = sts.get_caller_identity()["Account"]
    session = boto3.Session()

    # Read scan scope from UI config (storage backend); event payload overrides if present
    storage = get_storage()
    ui_config = storage.get_config()
    org_scan = event.get("scan_org", ui_config.get("scan_org", False))
    sessions = [(session, account_id)]
    if org_scan:
        try:
            org = boto3.client("organizations")
            accounts = org.list_accounts()["Accounts"]
            for acct in accounts:
                if acct["Status"] != "ACTIVE" or acct["Id"] == account_id:
                    continue
                try:
                    creds = sts.assume_role(
                        RoleArn=f"arn:aws:iam::{acct['Id']}:role/EOLReadOnlyRole",
                        RoleSessionName="eol-scan"
                    )["Credentials"]
                    s = boto3.Session(
                        aws_access_key_id=creds["AccessKeyId"],
                        aws_secret_access_key=creds["SecretAccessKey"],
                        aws_session_token=creds["SessionToken"],
                    )
                    sessions.append((s, acct["Id"]))
                except ClientError as e:
                    logger.warning("Cannot assume role for %s: %s", acct["Id"], e)
        except ClientError as e:
            logger.warning("Organizations listing failed: %s", e)

    total_written = 0
    alerts_sent = 0

    for sess, acct in sessions:
        resources = run_all_collectors(sess, acct)
        try:
            total_written += storage.save_resources(resources)
        except Exception as exc:
            logger.error("Storage write failed: %s", exc)
        for resource in resources:
            if resource.get("eol_status") in ("EOL", "EXPIRING_SOON"):
                send_alert(resource)
                alerts_sent += 1

    summary = {
        "statusCode": 200,
        "accounts_scanned": len(sessions),
        "resources_written": total_written,
        "alerts_sent": alerts_sent,
        "scanned_at": datetime.utcnow().isoformat(),
    }
    logger.info("Scan complete: %s", summary)
    return summary


if __name__ == "__main__":
    # Local test run
    logging.basicConfig(level=logging.INFO)
    result = lambda_handler({}, None)
    print(json.dumps(result, indent=2))
