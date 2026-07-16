#!/usr/bin/env python3
"""
Dry-run audit of stale inventory resources across all workspaces.

Stale = resource that would be excluded by _is_reportable():
  - scan_source is missing, NO_SOURCE, or a lifecycle-library value
    (VERIFIED_AWS_OFFICIAL, ENDOFLIFE_DATE, etc.)
  - AND account_id does not match any currently active connected account
    or active org member account

This script NEVER deletes anything.

Usage:
    # From the project root:
    python3 backend/scripts/audit_stale_resources.py

    # Override data directory (FileBackend):
    DATA_DIR=/home/ubuntu/eol-data python3 backend/scripts/audit_stale_resources.py

    # Verbose: show individual resource IDs:
    python3 backend/scripts/audit_stale_resources.py --verbose

    # Single workspace:
    python3 backend/scripts/audit_stale_resources.py --workspace ws_abc123
"""

import argparse
import os
import sys
from collections import defaultdict

# ── Allow importing the backend modules ──────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, BACKEND_DIR)

from storage import get_storage  # noqa: E402  (after sys.path fixup)

# scan_source values that indicate a live scan — resources with these are ACTIVE
_ACTIVE_SCAN_SOURCES = {"ACCOUNT_SCAN", "ORG_SCAN"}

# scan_source values that are explicitly stale (lifecycle-library ingestion)
_STALE_SCAN_SOURCES = {
    "VERIFIED_AWS_OFFICIAL",
    "ENDOFLIFE_DATE",
    "NO_SOURCE",
    "LIFECYCLE_ONLY",
    "GENERAL_EOL",
}


def _collect_active_ids(storage, workspace_id: str) -> tuple[set, set]:
    """Return (active_acct_ids, active_org_ids) for a workspace."""
    accounts = storage.get_accounts(workspace_id)
    active_acct_ids = {a.get("id") for a in accounts if a.get("id")}

    active_org_ids: set = set()
    for oc in storage.get_org_connections(workspace_id):
        if oc.get("status") == "CONNECTED":
            for oa in storage.get_org_accounts(workspace_id, oc["id"]):
                aid = oa.get("awsAccountId", "")
                if aid:
                    active_org_ids.add(aid)

    return active_acct_ids, active_org_ids


def _is_stale(r: dict, active_acct_ids: set, active_org_ids: set) -> tuple[bool, str]:
    """
    Return (is_stale, reason).
    A resource is stale if _is_reportable() would exclude it.
    """
    src = r.get("scan_source") or ""

    # Explicitly a stale lifecycle-library source
    if src in _STALE_SCAN_SOURCES:
        acct_id = r.get("account_id") or ""
        in_active = acct_id in active_acct_ids or acct_id in active_org_ids
        return True, f"scan_source={src!r} (lifecycle-library value)"

    # Known active source — always keep
    if src in _ACTIVE_SCAN_SOURCES:
        return False, ""

    # No scan_source at all — stale only if account is no longer active
    if not src:
        acct_id = r.get("account_id") or ""
        if acct_id in active_acct_ids or acct_id in active_org_ids:
            return False, ""
        return True, f"no scan_source, account_id={acct_id!r} not in active accounts"

    # Unknown scan_source value — flag for review
    return True, f"unknown scan_source={src!r}"


def audit_workspace(storage, workspace_id: str, verbose: bool) -> dict:
    ws = storage.get_workspace(workspace_id) or {}
    ws_name = ws.get("name", workspace_id)

    active_acct_ids, active_org_ids = _collect_active_ids(storage, workspace_id)
    resources = storage.get_resources({"workspace_id": workspace_id})

    stale: list[dict] = []
    active_count = 0

    for r in resources:
        is_s, reason = _is_stale(r, active_acct_ids, active_org_ids)
        if is_s:
            stale.append({
                "resource_id":  r.get("resource_id") or r.get("id") or "?",
                "resource_name": r.get("resource_name") or r.get("resourceName") or "?",
                "account_id":   r.get("account_id") or "",
                "scan_source":  r.get("scan_source") or "",
                "service":      r.get("service_type") or "",
                "reason":       reason,
            })
        else:
            active_count += 1

    # Group stale by reason
    by_reason: dict = defaultdict(list)
    for s in stale:
        by_reason[s["reason"]].append(s)

    return {
        "workspace_id":    workspace_id,
        "workspace_name":  ws_name,
        "total_resources": len(resources),
        "active_count":    active_count,
        "stale_count":     len(stale),
        "stale":           stale,
        "by_reason":       dict(by_reason),
        "active_acct_ids": sorted(active_acct_ids),
        "active_org_ids":  sorted(active_org_ids),
    }


def print_report(result: dict, verbose: bool) -> None:
    ws = result["workspace_name"]
    wid = result["workspace_id"]
    total = result["total_resources"]
    stale = result["stale_count"]
    active = result["active_count"]

    status = "CLEAN" if stale == 0 else "HAS STALE"
    print(f"\n{'='*70}")
    print(f"Workspace : {ws} ({wid})  [{status}]")
    print(f"Resources : {total} total  |  {active} active  |  {stale} stale")

    if result["active_acct_ids"]:
        print(f"  Active accounts  : {', '.join(result['active_acct_ids'])}")
    if result["active_org_ids"]:
        print(f"  Active org accts : {', '.join(result['active_org_ids'])}")

    if stale == 0:
        return

    print(f"\n  Stale breakdown by reason:")
    for reason, items in result["by_reason"].items():
        print(f"    [{len(items):3d}]  {reason}")
        if verbose:
            for item in items[:10]:
                print(f"           → {item['resource_id']:<36}  "
                      f"svc={item['service']:<12}  acct={item['account_id']}")
            if len(items) > 10:
                print(f"           … and {len(items) - 10} more")


def main():
    parser = argparse.ArgumentParser(
        description="Dry-run audit of stale inventory resources. Never deletes anything."
    )
    parser.add_argument("--workspace", help="Audit a single workspace ID only")
    parser.add_argument("--verbose",   action="store_true",
                        help="Show individual resource IDs for each stale group")
    args = parser.parse_args()

    storage = get_storage()

    if args.workspace:
        workspace_ids = [args.workspace]
    else:
        all_ws = storage.get_all_workspaces() if hasattr(storage, "get_all_workspaces") else []
        if not all_ws:
            # Fall back: read workspaces from file backend
            print("Note: get_all_workspaces() not available — listing via file backend fallback")
            data_dir = os.environ.get("DATA_DIR", "/var/lib/eol-data")
            ws_file = os.path.join(data_dir, "workspaces.json")
            if os.path.exists(ws_file):
                import json
                with open(ws_file) as f:
                    all_ws = json.load(f)
            else:
                print(f"ERROR: Could not enumerate workspaces. Pass --workspace <id> or set DATA_DIR.")
                sys.exit(1)
        workspace_ids = [w.get("id") or w for w in all_ws if w]

    grand_total = grand_stale = 0
    for wid in workspace_ids:
        try:
            result = audit_workspace(storage, wid, args.verbose)
            print_report(result, args.verbose)
            grand_total += result["total_resources"]
            grand_stale += result["stale_count"]
        except Exception as e:
            print(f"\nERROR auditing workspace {wid}: {e}")

    print(f"\n{'='*70}")
    print(f"SUMMARY: {len(workspace_ids)} workspace(s) | "
          f"{grand_total} total resources | {grand_stale} stale")
    if grand_stale > 0:
        print("ACTION: Review stale resources above. To clean up, run targeted")
        print("        DELETE via admin API or storage.delete_resource() after")
        print("        confirming each account is truly decommissioned.")
    else:
        print("All resources are from active account or org scans. No cleanup needed.")
    print()


if __name__ == "__main__":
    main()
