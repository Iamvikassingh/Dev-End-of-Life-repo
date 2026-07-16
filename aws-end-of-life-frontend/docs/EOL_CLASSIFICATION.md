# EOL Classification Guide

---

## Overview

AWS EOL Monitor classifies every discovered resource into one of 7 lifecycle statuses. Classification uses the `endoflife.date` API as the primary data source, with fallback rules for services without public lifecycle data.

---

## The 7 Statuses

| Status | Code | Meaning |
|---|---|---|
| End of Life | `EOL` | Past support end date, no further security patches |
| Expiring Soon | `EXPIRING_SOON` | Within 90 days of EOL |
| Extended Support | `EXTENDED_SUPPORT` | In paid/extended support period after standard EOL |
| Supported | `SUPPORTED` | Active, within lifecycle |
| Unknown | `UNKNOWN` | Version found but lifecycle could not be determined |
| Needs Inspection | `NEEDS_INSPECTION` | Resource discovered but requires manual inspection to classify (ECR) |
| Lifecycle Not Tracked | `LIFECYCLE_NOT_TRACKED` | Service has no public lifecycle dates to track (CloudFront Functions) |

### Important: Non-Lifecycle Statuses

`NEEDS_INSPECTION` and `LIFECYCLE_NOT_TRACKED` are **not lifecycle statuses** — they are discovery statuses. They are:
- Excluded from main EOL/EXPIRING_SOON/EXTENDED_SUPPORT/SUPPORTED/UNKNOWN counts
- Shown in a separate summary row in the UI
- Not included in risk calculations

---

## Classification Logic

```python
def classify_status(version, eol_data, days_threshold=90):
    if eol_data is None:
        return "UNKNOWN", None, None, "no lifecycle data found"

    eol_date_str = eol_data.get("eol")
    support_end  = eol_data.get("support")
    is_eoes = bool(eol_data.get("isEoes") or eol_data.get("extendedSupport"))

    # Primary risk date: support end (if available) else eol
    primary = support_end or eol_date_str

    if primary is None or primary is True:
        if is_eoes:
            return "EXTENDED_SUPPORT", None, None, "in extended support"
        return "SUPPORTED", None, None, "no EOL date announced"

    today = date.today()
    eol_d = date.fromisoformat(str(primary))
    days  = (eol_d - today).days

    if is_eoes:
        return "EXTENDED_SUPPORT", str(eol_d), days, "in extended support"
    if days < 0:
        return "EOL", str(eol_d), days, "past EOL"
    if days <= days_threshold:
        return "EXPIRING_SOON", str(eol_d), days, f"within {days_threshold}d of EOL"
    return "SUPPORTED", str(eol_d), days, "within lifecycle"
```

Key behaviors:
- `support` end date (standard support cutoff) takes priority over `eol` date.
- `extendedSupport: true` from endoflife.date is treated as extended support.
- `eol: true` (boolean `True`, not a date) means no EOL announced → `SUPPORTED`.
- `eol: null` means endoflife.date has no data → `UNKNOWN`.

---

## Version Format by Service

Each service requires a specific version key format to match endoflife.date cycles.

| Service | Cycle Key Format | Example | Notes |
|---|---|---|---|
| Lambda | runtime name | `python3.12` | e.g. `python3.12`, `nodejs20.x`, `java21` |
| EKS | `major.minor` | `1.29` | |
| RDS MySQL | `major.minor` | `8.0` | |
| RDS PostgreSQL | `major` | `16` | |
| RDS MariaDB | `major.minor` | `10.6` | |
| Aurora MySQL | `major.minor` | `3.4` (= MySQL 8.0) | Maps to Aurora-specific cycle |
| Aurora PostgreSQL | `major` | `15` | |
| ElastiCache Redis | `major` | `7` | NOT `7.0` — major-only |
| MSK (Kafka) | `major.minor` | `3.5` | |
| OpenSearch | `major.minor` | `3.5` | NOT major-only; full minor required |
| DocumentDB | `major.minor` | `4.0` | NOT major-only |
| Neptune | full patch | `1.4.7.0` | endoflife.date uses 4-part versions |
| EC2 AMI OS | OS name + major | `ubuntu:22.04` | Inline OS tables, not endoflife.date |
| CodeBuild | runtime name | `python/3.12` | |
| Glue | version string | `4.0` | |
| EMR | `major.minor` | `7.1` | |

### Service slugs used for endoflife.date

```python
SERVICE_SLUG = {
    "Lambda":           "aws-lambda",
    "EKS":              "amazon-eks",
    "RDS/MySQL":        "mysql",
    "RDS/PostgreSQL":   "postgresql",
    "RDS/MariaDB":      "mariadb",
    "Aurora/MySQL":     "amazon-aurora-mysql",
    "Aurora/PostgreSQL":"amazon-aurora-postgresql",
    "ElastiCache":      "amazon-elasticache-redis",
    "MSK":              "apache-kafka",
    "OpenSearch":       "amazon-opensearch",
    "DocumentDB":       "amazon-documentdb",
    "Neptune":          "amazon-neptune",
    "CodeBuild":        "aws-codebuild",
    "Glue":             "aws-glue",
    "EMR":              "amazon-emr",
}
```

---

## Date Fields

| Field | Type | When set |
|---|---|---|
| `eol_date` | `string \| null` | Date string `"YYYY-MM-DD"` if EOL announced; `null` if not |
| `support_end_date` | `string \| null` | Date string if standard support ends before EOL; `null` otherwise |
| `days_to_eol` | `int \| null` | Days from today to primary risk date; negative when past EOL; `null` if no date |

**Critical rule:** Never store the string `"unknown"` as an `eol_date` value. If no date is available, store `null` (Python `None`). The frontend checks for `null` and renders `"—"` in the UI.

---

## Recent Bug Fixes (Phase 1)

### 1. OpenSearch UNKNOWN (fixed)

**Root cause:** Collector extracted `version.split(".")[0]` = `"3"` and queried `amazon-opensearch/3.json` → HTTP 404.

**Fix:** Pass full minor version directly: `fetch_eol("amazon-opensearch", "3.5")`.

endoflife.date OpenSearch cycles: `3.5`, `3.3`, `2.17`, `2.15`, `2.13`, `2.11`, `1.3`, etc.

### 2. DocumentDB UNKNOWN (fixed)

**Root cause:** Same issue — major-only key `"4"` returned HTTP 404.

**Fix:** `minor = ".".join(version.split(".")[:2])` → `"4.0"`.

endoflife.date DocumentDB cycles: `5.0`, `4.0`, `3.6`.

### 3. Neptune UNKNOWN (fixed)

**Root cause:** Collector sent `"1.4"` but endoflife.date uses full patch: `"1.4.7.0"`.

**Fix:** Pass full version string from AWS API. endoflife.date Neptune cycles: `1.4.7.0`, `1.4.5.0`, etc.

### 4. ExtendedSupport field mismatch (fixed)

**Root cause:** Code checked `eol_data.get("isEoes")` but endoflife.date returns `"extendedSupport": true`.

**Fix:**
```python
is_eoes = bool(eol_data.get("isEoes") or eol_data.get("extendedSupport"))
```

Both `eol_collector.py` and `general_eol.py` updated.

### 5. `"unknown"` string in eol_date (fixed)

**Root cause:** All collectors used `eol_date or "unknown"` as a fallback when `eol_date=None`.

**Fix:** Removed all `or "unknown"` patterns globally. `eol_date` is stored as `None` when unknown.

**Root cause 2:** `_unknown_lifecycle()` returned `"unknown"` as the second element of its tuple.

**Fix:**
```python
def _unknown_lifecycle(reason: str) -> tuple[str, None, None, str]:
    return "UNKNOWN", None, None, reason
```

### 6. EC2 deprecated AMI days=None (fixed)

**Root cause:** When AMI was deprecated, `days` was set to `None` causing "Unknown" in EOL timeline despite `status="EOL"`.

**Fix:**
```python
dep_d  = date.fromisoformat(dep_time[:10]) if dep_time else None
status = "EOL"
eol_date = str(dep_d) if dep_d else None
days   = (dep_d - date.today()).days if dep_d else None
```

---

## Non-Lifecycle Services

### ECR (`NEEDS_INSPECTION`)

ECR images are discovered and listed but cannot be lifecycle-classified without inspecting the container OS and installed packages. This requires SBOM scanning (e.g. Trivy), which is out of scope for Phase 1.

All ECR images return:
```python
"eol_status": "NEEDS_INSPECTION",
"eol_date": None,
"days_to_eol": None,
"classification_reason": "ECR image OS/runtime inspection required"
```

### CloudFront Functions (`LIFECYCLE_NOT_TRACKED`)

CloudFront Functions use JavaScript runtime (`cloudfront-js-2.0`) but AWS does not publish an EOL lifecycle for this runtime. No endoflife.date entry exists.

All CloudFront Functions return:
```python
"eol_status": "LIFECYCLE_NOT_TRACKED",
"eol_date": None,
"days_to_eol": None,
"classification_reason": "CloudFront Functions runtime has no published lifecycle"
```

---

## EOL Timeline UI Behavior

The EOLTimeline component uses:

| Condition | Bar color | Label |
|---|---|---|
| `days < 0` | Red | "X days overdue" |
| `days <= 90` | Orange | "X days left" |
| `days <= 180` | Yellow | "X days left" |
| `days > 180` | Green | "X days left" |
| `days = null` + `status = UNKNOWN` | Gray | "Unknown" |
| `status = NEEDS_INSPECTION` | Gray | "Needs Inspection" |
| `status = LIFECYCLE_NOT_TRACKED` | Gray | "Not tracked" |

Date display rule: `eolDate && eolDate !== "unknown"` — this defensive check prevents old data with `"unknown"` strings from appearing in the UI.

---

## Adding a New Service

1. Add a slug to `SERVICE_SLUG` dict in `eol_collector.py`.
2. Verify the cycle key format at `https://endoflife.date/api/<slug>.json`.
3. Extract the correct version string from the AWS API response.
4. Call `fetch_eol(slug, version_key)` and pass result to `classify_status()`.
5. Return a resource dict with `eol_status`, `eol_date`, `days_to_eol`, `version`.
6. If no lifecycle exists for the service, return `LIFECYCLE_NOT_TRACKED` status with `None` dates.
7. If version is available but lookup fails, return result of `_unknown_lifecycle(reason)`.
