"""
Unified lifecycle status classifier.

Shared between general_eol.py and eol_collector.py so that the General EOL
library page and account/org scan results always produce identical status
classifications for the same product version and date.

Allowed status values (matches frontend ACTIONABLE_STATUSES set):
  EOL, EXPIRING_SOON, EXTENDED_SUPPORT, SUPPORTED, UNKNOWN, LIFECYCLE_NOT_TRACKED
"""
import os
from datetime import date
from typing import Optional

WARN_DAYS = int(os.environ.get("WARN_DAYS", "180"))


def parse_date(val) -> Optional[date]:
    """Parse ISO date string or False/None into a date object. Returns None on failure."""
    if not val or val is False:
        return None
    try:
        return date.fromisoformat(str(val))
    except ValueError:
        return None


def classify(
    eol_from: Optional[str],
    support_from: Optional[str],
    is_eoes: bool,
    warn_days: int = WARN_DAYS,
) -> tuple[str, Optional[str], Optional[int]]:
    """Return (status, primary_alert_date_str, days_to_primary).

    Primary alert date selection:
    - Extended-support services (is_eoes=True): eol_from is the cutoff.
    - Standard services: support_from drives the alert when it precedes eol_from
      (e.g. Lambda runtime deprecation fires before the final eol block date).
    - No dates available: ('SUPPORTED', None, None).
    """
    eol_dt     = parse_date(eol_from)
    support_dt = parse_date(support_from)

    if is_eoes and eol_dt:
        primary_dt = eol_dt
    elif support_dt and eol_dt and support_dt < eol_dt:
        primary_dt = support_dt
    elif eol_dt:
        primary_dt = eol_dt
    elif support_dt:
        primary_dt = support_dt
    else:
        return "SUPPORTED", None, None

    today = date.today()
    days  = (primary_dt - today).days

    if days < 0:
        status = "EOL"
    elif days <= warn_days:
        status = "EXPIRING_SOON"
    elif is_eoes:
        status = "EXTENDED_SUPPORT"
    else:
        status = "SUPPORTED"

    return status, str(primary_dt), days


def classify_from_eol_data(
    eol_data: Optional[dict],
    warn_days: int = WARN_DAYS,
) -> tuple[str, Optional[str], Optional[int]]:
    """Convenience wrapper: extract fields from an eol_data dict, then classify.

    Returns (status, primary_alert_date_str, days).
    Returns ('LIFECYCLE_NOT_TRACKED', None, None) when eol_data is None —
    meaning no lifecycle information was found from any source.
    """
    if eol_data is None:
        return "LIFECYCLE_NOT_TRACKED", None, None

    is_eoes  = bool(eol_data.get("isEoes") or eol_data.get("extendedSupport"))
    eol_raw  = eol_data.get("eolFrom") or eol_data.get("eol")
    sup_raw  = eol_data.get("support")
    eol_from    = str(eol_raw) if eol_raw  and eol_raw  is not False else None
    support_from = str(sup_raw) if sup_raw and sup_raw is not False else None

    return classify(eol_from, support_from, is_eoes, warn_days)
