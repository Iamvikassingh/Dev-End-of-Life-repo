"""Admin batch validation job — validates known service/version pairs against AWS official docs.

Run manually or via cron/scheduler (NOT in the account scan path).

Usage:
  python backend/lifecycle/validate_batch.py --dry-run          # validate, do not save
  python backend/lifecycle/validate_batch.py --save             # validate and save verified
  python backend/lifecycle/validate_batch.py --save --direct-html  # skip MCP, use HTTP only
  python backend/lifecycle/validate_batch.py --check-changes    # compare with stored records, exit 1 if any date changed

Security rules (must not be violated):
  - This script is admin-only and NEVER called from account scan path.
  - It writes only to verified_lifecycle storage, never to scan results.
  - It does NOT use MCP for customer AWS account data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Catalogue of service/version pairs to validate ───────────────────────────
# Add new entries here when AWS announces lifecycle dates for a service.
# Format: (product_slug, version_string)
# product_slug must be a key in PRODUCT_CONFIG in validate_with_mcp_cli.py.

BATCH_TARGETS: list[tuple[str, str]] = [
    # Lambda runtimes
    ("aws-lambda",               "python3.9"),
    ("aws-lambda",               "python3.10"),
    ("aws-lambda",               "python3.11"),
    ("aws-lambda",               "python3.12"),
    ("aws-lambda",               "nodejs18.x"),
    ("aws-lambda",               "nodejs20.x"),
    # EKS Kubernetes versions
    ("amazon-eks",               "1.28"),
    ("amazon-eks",               "1.29"),
    ("amazon-eks",               "1.30"),
    ("amazon-eks",               "1.31"),
    ("amazon-eks",               "1.32"),
    ("amazon-eks",               "1.33"),
    ("amazon-eks",               "1.34"),
    # ElastiCache Redis
    ("amazon-elasticache-redis", "6.2"),
    ("amazon-elasticache-redis", "7.0"),
    ("amazon-elasticache-redis", "7.1"),
    # RDS PostgreSQL
    ("amazon-rds-postgresql",    "13"),
    ("amazon-rds-postgresql",    "14"),
    ("amazon-rds-postgresql",    "15"),
    ("amazon-rds-postgresql",    "16"),
    ("amazon-rds-postgresql",    "17"),
    # RDS MySQL
    ("amazon-rds-mysql",         "5.7"),
    ("amazon-rds-mysql",         "8.0"),
    ("amazon-rds-mysql",         "8.4"),
    # Aurora PostgreSQL
    ("amazon-aurora-postgresql", "13"),
    ("amazon-aurora-postgresql", "14"),
    ("amazon-aurora-postgresql", "15"),
    ("amazon-aurora-postgresql", "16"),
    # Aurora MySQL
    ("amazon-aurora-mysql",      "2"),
    ("amazon-aurora-mysql",      "3"),
    ("amazon-aurora-mysql",      "8"),
    # OpenSearch
    ("amazon-opensearch",        "1.3"),
    ("amazon-opensearch",        "2.3"),
    ("amazon-opensearch",        "2.11"),
    ("amazon-opensearch",        "2.15"),
]

logger = logging.getLogger("batch_validate")

# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_date(d: Optional[str]) -> str:
    return d or "—"

def _status_icon(status: str) -> str:
    return "✅" if status == "verified" else "⚠️ "


# ── Change detection ─────────────────────────────────────────────────────────

def _detect_changes(old: dict, new: dict) -> list[str]:
    """Return list of human-readable change descriptions between two lifecycle records."""
    changes = []
    for field in ("eolDate", "supportEndDate", "extendedSupportEndDate", "validationStatus"):
        old_val = old.get(field)
        new_val = new.get(field)
        if old_val != new_val:
            changes.append(f"{field}: {old_val!r} → {new_val!r}")
    return changes


# ── Load existing stored records ──────────────────────────────────────────────

def _load_existing(product: str, version: str) -> Optional[dict]:
    """Fetch the current stored record for a product/version pair."""
    try:
        root = Path(__file__).resolve()
        for _ in range(6):
            if (root / "backend" / "storage.py").exists():
                break
            root = root.parent
        for path_insert in [str(root), str(root / "backend")]:
            if path_insert not in sys.path:
                sys.path.insert(0, path_insert)
        try:
            from backend.storage import get_storage  # type: ignore
        except ImportError:
            from storage import get_storage  # type: ignore
        return get_storage().get_verified_lifecycle(product, version)
    except Exception as exc:
        logger.debug("Could not load existing record for %s/%s: %s", product, version, exc)
        return None


# ── Main batch loop ───────────────────────────────────────────────────────────

async def run_batch(
    targets: list[tuple[str, str]],
    *,
    save: bool,
    skip_mcp: bool,
    check_changes: bool,
    json_out: bool,
) -> int:
    """Run validation for all targets. Returns exit code (0 = ok, 1 = changes detected)."""
    # Import lazily — this file must survive being imported without mcp installed
    from validate_with_mcp_cli import _mcp_validate_lifecycle, _save_to_storage  # type: ignore

    results = []
    changed: list[dict] = []
    verified_count = needs_review_count = save_count = 0

    total = len(targets)
    for idx, (product, version) in enumerate(targets, 1):
        prefix = f"[{idx:>2}/{total}]  {product}/{version}"
        logger.info("%s → validating …", prefix)

        result = await _mcp_validate_lifecycle(product, version, skip_mcp=skip_mcp)
        status = result.get("validationStatus", "unknown")
        eol    = result.get("eolDate")
        sup    = result.get("supportEndDate")

        if status == "verified":
            verified_count += 1

            # Change detection: compare with previously stored record
            if check_changes:
                existing = _load_existing(product, version)
                if existing:
                    diffs = _detect_changes(existing, result)
                    if diffs:
                        change_entry = {
                            "product": product, "version": version,
                            "changes": diffs,
                            "old_eolDate": existing.get("eolDate"),
                            "new_eolDate": eol,
                            "old_supportEndDate": existing.get("supportEndDate"),
                            "new_supportEndDate": sup,
                        }
                        changed.append(change_entry)
                        logger.warning(
                            "DATE CHANGED  %s/%s  %s",
                            product, version,
                            "  |  ".join(diffs),
                        )

            if save:
                saved = _save_to_storage(result)
                if saved:
                    save_count += 1
                result["_saved"] = saved if save else False
        else:
            needs_review_count += 1

        result["_prefix"] = prefix
        results.append(result)

        if not json_out:
            icon = _status_icon(status)
            print(f"  {icon}  {prefix:<50}  status={status:<12}  eol={_fmt_date(eol):<12}  support={_fmt_date(sup)}")

    # ── Summary ───────────────────────────────────────────────────────────────
    if json_out:
        output = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "total": total,
            "verified": verified_count,
            "needs_review": needs_review_count,
            "saved": save_count if save else None,
            "changed": changed,
            "results": results,
        }
        print(json.dumps(output, indent=2))
    else:
        print()
        print("─" * 70)
        print(f"  Total:        {total}")
        print(f"  Verified:     {verified_count}")
        print(f"  Needs review: {needs_review_count}")
        if save:
            print(f"  Saved:        {save_count}")
        print(f"  Run at:       {datetime.now(timezone.utc).isoformat()}")

        if changed:
            print()
            print(f"  ⚠️   DATE CHANGES DETECTED ({len(changed)}):")
            for ch in changed:
                print(f"    {ch['product']}/{ch['version']}:")
                for diff in ch["changes"]:
                    print(f"      {diff}")

        if needs_review_count > 0:
            print()
            needs_review_items = [
                f"  {r['product']}/{r['version']}"
                for r in results if r.get("validationStatus") != "verified"
            ]
            print(f"  needs_review ({needs_review_count}):")
            for item in needs_review_items:
                print(item)

    # Return non-zero if date changes detected (useful for CI/alerting)
    return 1 if (check_changes and changed) else 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Batch lifecycle validator — admin use only, never call from account scan",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run: validate all, print table, do not save
  python backend/lifecycle/validate_batch.py

  # Validate + save verified records to DB
  python backend/lifecycle/validate_batch.py --save

  # Skip MCP (HTTP only), faster, no uvx needed
  python backend/lifecycle/validate_batch.py --save --direct-html

  # Only run specific services
  python backend/lifecycle/validate_batch.py --filter amazon-rds

  # Detect date changes vs stored records (exit 1 if any changed)
  python backend/lifecycle/validate_batch.py --check-changes --direct-html

  # JSON output for CI/alerting pipeline
  python backend/lifecycle/validate_batch.py --check-changes --json
        """,
    )
    p.add_argument("--save",          action="store_true",
                   help="Save verified records to storage (default: dry-run, do not save)")
    p.add_argument("--direct-html",   dest="direct_html", action="store_true",
                   help="Skip MCP, use direct HTTP fetch only (no uvx needed)")
    p.add_argument("--check-changes", dest="check_changes", action="store_true",
                   help="Compare new results with stored records; exit 1 if any date changed")
    p.add_argument("--filter",        metavar="SUBSTR",
                   help="Only validate targets whose product slug contains this substring")
    p.add_argument("--env-file",      dest="env_file", metavar="PATH",
                   help="Path to .env file (auto-detected from project root if omitted)")
    p.add_argument("--json",          dest="json_out", action="store_true",
                   help="JSON output (machine-readable)")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Enable DEBUG logging")
    p.add_argument("--list",          action="store_true",
                   help="List all configured targets and exit")
    return p


def main() -> int:
    parser = _build_parser()
    args   = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Load .env
    try:
        from dotenv import load_dotenv
        env_file = getattr(args, "env_file", None)
        if env_file and os.path.isfile(env_file):
            load_dotenv(env_file, override=False)
            logger.debug("Loaded env from: %s", env_file)
        else:
            # Auto-detect project root .env
            here = Path(__file__).resolve()
            for _ in range(6):
                candidate = here.parent / ".env"
                if candidate.is_file():
                    load_dotenv(str(candidate), override=False)
                    logger.debug("Loaded env from: %s", candidate)
                    break
                here = here.parent
    except ImportError:
        logger.debug("python-dotenv not installed; skipping .env load")

    # Wire up sys.path so validate_with_mcp_cli is importable
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))

    targets = BATCH_TARGETS

    if args.list:
        print(f"Configured targets ({len(targets)}):")
        for product, version in targets:
            print(f"  {product}/{version}")
        return 0

    if args.filter:
        targets = [(p, v) for p, v in targets if args.filter.lower() in p.lower()]
        if not targets:
            print(f"No targets match filter {args.filter!r}", file=sys.stderr)
            return 1
        logger.info("Filter %r → %d targets", args.filter, len(targets))

    if not args.json_out:
        print(f"Batch lifecycle validation — {len(targets)} targets")
        print(f"  Mode:       {'direct-HTML' if args.direct_html else 'MCP + direct-HTML'}")
        print(f"  Save:       {args.save}")
        print(f"  Check diffs:{args.check_changes}")
        print()

    return asyncio.run(
        run_batch(
            targets,
            save=args.save,
            skip_mcp=args.direct_html,
            check_changes=args.check_changes,
            json_out=args.json_out,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
