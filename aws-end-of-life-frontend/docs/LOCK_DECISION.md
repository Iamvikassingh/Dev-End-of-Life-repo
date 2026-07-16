# Phase 1 Lock Decision

**Status:** LOCKED  
**Lock date:** June 2026  
**Git tag:** `v0.1-demo-freeze`  
**Decision maker:** Neetesh

---

## Decision

Phase 1 of AWS EOL Monitor is declared complete and locked. No new features will be added to the Phase 1 codebase without reopening the phase.

---

## What Was Delivered

Phase 1 delivered a demo-ready SaaS dashboard that:

1. Connects to real customer AWS accounts via read-only cross-account IAM roles.
2. Scans 16+ AWS service types for end-of-life lifecycle risk.
3. Classifies every resource into 7 lifecycle statuses.
4. Displays results in a multi-account dashboard with per-resource EOL timeline.
5. Enforces workspace isolation — multi-tenant data is isolated at every layer.
6. Provides workspace-scoped RBAC (ADMIN / EDITOR / VIEWER).
7. Runs on EC2 with PM2; deployable with a single script.

All P0 security findings pass (see `docs/SECURITY_AUDIT.md`).

---

## Bugs Fixed Before Lock

| Bug | File | Fix |
|---|---|---|
| OpenSearch 3.x showing UNKNOWN | `eol_collector.py` | Pass full minor version `"3.5"` to endoflife.date |
| DocumentDB always UNKNOWN | `eol_collector.py` | Use `major.minor` format `"4.0"` |
| Neptune always UNKNOWN | `eol_collector.py` | Use full patch version `"1.4.7.0"` |
| `extendedSupport` field ignored | `eol_collector.py`, `general_eol.py` | Check both `isEoes` and `extendedSupport` |
| `"unknown"` string stored in eol_date | `eol_collector.py` (all collectors) | Remove all `or "unknown"` fallbacks; store `None` |
| EC2 deprecated AMI days=None | `eol_collector.py` | Calculate days from deprecation date |
| Status badge wrapping | `StatusBadge.jsx` | Add `whitespace-nowrap`, increase column width |
| NEEDS_INSPECTION missing from summary | `AccountResultsPage.jsx` | Add non-lifecycle summary cards row |
| Post-scan stale inventory | `AccountResultsPage.jsx` | 1.5s delay before re-fetching after scan completes |
| `"unknown"` in EOLTimeline | `EOLTimeline.jsx` | Defensive check for `eolDate !== "unknown"` |

---

## Allowed After Lock

These changes may be made without reopening Phase 1:

1. **P0/P1 security fixes** — Any newly discovered authentication or data isolation vulnerability.
2. **EOL classification correctness** — If a new endoflife.date API change breaks classification for a supported service.
3. **Broken UI** — A UI feature that is visibly broken (crash, blank screen, wrong data).
4. **Deploy fixes** — Fixes required to deploy and run the app on EC2 with PM2.
5. **Documentation corrections** — Fixing factual errors in docs.

---

## Not Allowed After Lock

These changes require a new phase designation:

- New service scanners (new AWS services)
- New UI pages or major layout changes
- Scheduled scans
- Email / Slack alerts delivery
- Per-account RBAC
- AWS Organizations integration
- SBOM / ECR image scanning
- Billing / subscriptions
- Data storage migration (file → DynamoDB / PostgreSQL)
- CSV / PDF export
- Any feature listed in `docs/NEXT_PHASE_ROADMAP.md`

---

## Why This Line

The lock is drawn here because:

- The product is demo-ready and all known bugs are fixed.
- Security audit passed at P0 level.
- Scope creep at this stage would delay the demo without adding customer value.
- Phase 2 features require architectural decisions (scheduler, database, SBOM integration) that should be planned independently.

---

## Git Tag Recommendation

```bash
git tag -a v0.1-demo-freeze -m "Phase 1 demo-ready freeze — June 2026"
git push origin v0.1-demo-freeze
```

This creates an immutable reference point. Any post-freeze fix commits should be made on a `phase-1-hotfix/*` branch off this tag.

---

## Hotfix Branch Protocol

For allowed post-lock fixes:

```bash
git checkout v0.1-demo-freeze
git checkout -b phase-1-hotfix/opensearch-version-fix
# make fix
git commit -m "fix: <description>"
git tag v0.1.1-hotfix
git push origin phase-1-hotfix/opensearch-version-fix
```

Hotfixes are versioned as `v0.1.x`. Phase 2 starts at `v0.2.0`.
