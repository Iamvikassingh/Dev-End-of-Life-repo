import React, { useState, useMemo, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { LayoutGrid, List, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import { AppSelect } from "../components/AppSelect";
import axios from "axios";
import { useSummary, useInventory } from "../hooks/useInventory";
import { getStatusConfig, serviceLabel } from "../utils/classify";
import { loadAccounts } from "../utils/connectedAccounts";
import { API_BASE_URL } from "../utils/config";
import { getWorkspaceId, workspaceHeaders } from "../utils/workspace";

const STATUS_ORDER = ["EOL", "EXPIRING_SOON", "EXTENDED_SUPPORT", "SUPPORTED", "NEEDS_INSPECTION", "LIFECYCLE_NOT_TRACKED", "UNKNOWN"];

const STATUS_META = {
  EOL:                   { label: "EOL",          bg: "bg-red-50",     text: "text-red-700",    dot: "#ef4444" },
  EXPIRING_SOON:         { label: "Expiring",     bg: "bg-amber-50",   text: "text-amber-700",  dot: "#f59e0b" },
  EXTENDED_SUPPORT:      { label: "Ext. Support", bg: "bg-blue-50",    text: "text-blue-700",   dot: "#3b82f6" },
  SUPPORTED:             { label: "Supported",    bg: "bg-green-50",   text: "text-green-700",  dot: "#22c55e" },
  NEEDS_INSPECTION:      { label: "Inspect",      bg: "bg-purple-50",  text: "text-purple-700", dot: "#a855f7" },
  LIFECYCLE_NOT_TRACKED: { label: "Not Tracked",  bg: "bg-slate-50",   text: "text-slate-500",  dot: "#94a3b8" },
  UNKNOWN:               { label: "Unknown",      bg: "bg-gray-50",    text: "text-gray-500",   dot: "#9ca3af" },
};

// ── Shared components ─────────────────────────────────────────────────────────

function DistributionBar({ counts }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (total === 0) return null;
  return (
    <div className="flex h-2.5 rounded-full overflow-hidden gap-px w-full">
      {STATUS_ORDER.filter(s => counts[s] > 0).map(s => {
        const cfg = getStatusConfig(s);
        return (
          <div key={s} style={{ width: `${(counts[s] / total) * 100}%`, backgroundColor: cfg.hex }} />
        );
      })}
    </div>
  );
}

function RiskBadge({ counts, total }) {
  const t = total ?? Object.values(counts).reduce((a, b) => a + b, 0);
  if (t === 0)
    return <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-slate-100 text-slate-500 shrink-0">Not scored</span>;
  if ((counts.EOL ?? 0) > 0)
    return <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-red-100 text-red-700 shrink-0">Action Required</span>;
  if ((counts.EXPIRING_SOON ?? 0) > 0)
    return <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-100 text-amber-700 shrink-0">Review Soon</span>;
  return <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-green-100 text-green-700 shrink-0">Healthy</span>;
}

// ── KPI chips ─────────────────────────────────────────────────────────────────

function KpiChips({ totals, grand, onChipClick }) {
  return (
    <div className="flex flex-wrap gap-3 mb-4">
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm px-4 py-2.5 flex items-center gap-2">
        <span className="text-sm font-bold text-gray-900">{grand}</span>
        <span className="text-xs text-gray-400">Total</span>
      </div>
      {STATUS_ORDER.filter(s => totals[s] > 0).map(s => {
        const m = STATUS_META[s];
        return (
          <button key={s} onClick={() => onChipClick(s)}
            className={`rounded-xl border border-transparent px-4 py-2.5 flex items-center gap-2 hover:border-gray-200 transition-all ${m.bg}`}>
            <span className={`text-sm font-bold ${m.text}`}>{totals[s]}</span>
            <span className={`text-xs ${m.text} opacity-80`}>{m.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ── Card view ─────────────────────────────────────────────────────────────────

function ServiceCard({ rawName, counts, onCardClick, onStatusClick }) {
  const total       = Object.values(counts).reduce((a, b) => a + b, 0);
  const displayName = serviceLabel(rawName);
  const borderColor = total === 0 ? "border-l-slate-200"
    : (counts.EOL ?? 0) > 0 ? "border-l-red-500"
    : (counts.EXPIRING_SOON ?? 0) > 0 ? "border-l-amber-400"
    : "border-l-green-400";

  return (
    <div
      onClick={() => onCardClick(rawName)}
      className={`group bg-white rounded-2xl border border-gray-100 border-l-4 p-5 cursor-pointer flex flex-col
                  shadow-sm hover:shadow-md hover:border-gray-200 transition-all duration-150 ${borderColor}`}
    >
      <div className="flex items-start justify-between gap-2 mb-3" style={{ minHeight: "52px" }}>
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-bold text-gray-900 leading-tight line-clamp-2">{displayName}</h3>
        </div>
        <div className="shrink-0 mt-0.5">
          <RiskBadge counts={counts} total={total} />
        </div>
      </div>
      <DistributionBar counts={counts} />
      <div className="mt-3 flex flex-wrap gap-1.5" onClick={e => e.stopPropagation()}>
        {STATUS_ORDER.filter(s => counts[s] > 0).map(s => (
          <button key={s} onClick={() => onStatusClick(rawName, s)}
            className="flex items-center gap-1.5 rounded-lg px-2.5 py-1 hover:opacity-80 active:scale-95 transition-all"
            style={{ backgroundColor: getStatusConfig(s).bghex, color: getStatusConfig(s).hex }}>
            <span className="text-sm font-bold">{counts[s]}</span>
            <span className="text-xs">{getStatusConfig(s).label}</span>
          </button>
        ))}
      </div>
      <div className="mt-4 pt-3.5 border-t border-slate-100 flex items-center justify-between">
        <span className="text-xs font-semibold text-indigo-500 group-hover:text-indigo-700 transition-colors">
          View resources →
        </span>
        <span className="text-xs text-slate-400">
          {total === 0 ? "Inventory only" : `${total} resource${total !== 1 ? "s" : ""}`}
        </span>
      </div>
    </div>
  );
}

// ── Table view ────────────────────────────────────────────────────────────────

const TABLE_COLS = [
  { key: "name",                 label: "Service",        align: "left"   },
  { key: "total",                label: "Total",          align: "right"  },
  { key: "EOL",                  label: "EOL",            align: "right"  },
  { key: "EXPIRING_SOON",        label: "Expiring Soon",  align: "right"  },
  { key: "EXTENDED_SUPPORT",     label: "Ext. Support",   align: "right"  },
  { key: "SUPPORTED",            label: "Supported",      align: "right"  },
  { key: "LIFECYCLE_NOT_TRACKED",label: "Not Tracked",    align: "right"  },
  { key: "UNKNOWN",              label: "Unknown",        align: "right"  },
];

function SortIcon({ col, sortKey, dir }) {
  if (sortKey !== col) return <ArrowUpDown size={12} className="text-slate-300 ml-1 inline" strokeWidth={2} />;
  return dir === "asc"
    ? <ArrowUp   size={12} className="text-indigo-500 ml-1 inline" strokeWidth={2.5} />
    : <ArrowDown size={12} className="text-indigo-500 ml-1 inline" strokeWidth={2.5} />;
}

function CountCell({ value, onClick, tone }) {
  if (value == null) return <span className="text-slate-300 text-xs">—</span>;
  if (value === 0)   return <span className="text-slate-300 text-xs">0</span>;
  const cls = {
    red:    "text-red-600    hover:bg-red-50",
    amber:  "text-amber-600  hover:bg-amber-50",
    blue:   "text-blue-600   hover:bg-blue-50",
    green:  "text-green-600  hover:bg-green-50",
    purple: "text-purple-600 hover:bg-purple-50",
    slate:  "text-slate-500  hover:bg-slate-50",
  }[tone] ?? "text-slate-700 hover:bg-slate-50";
  return (
    <button onClick={onClick}
      className={`text-sm font-bold rounded-md px-1.5 py-0.5 transition-colors ${cls}`}
      title="Filter dashboard by this service + status">
      {value}
    </button>
  );
}

const STATUS_TONE = {
  EOL: "red", EXPIRING_SOON: "amber", EXTENDED_SUPPORT: "blue",
  SUPPORTED: "green", NEEDS_INSPECTION: "purple",
  LIFECYCLE_NOT_TRACKED: "slate", UNKNOWN: "slate",
};

function ServiceTable({ rows, sortKey, sortDir, onSort, onRowClick, onStatusClick }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="overflow-x-auto scrollbar-thin">
        <table className="min-w-[760px] w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50">
              {TABLE_COLS.map(col => (
                <th key={col.key}
                  onClick={() => onSort(col.key)}
                  className={`px-4 py-3 text-xs font-bold uppercase tracking-wide text-slate-500 cursor-pointer select-none whitespace-nowrap
                    ${col.align === "right" ? "text-right" : "text-left"} hover:bg-slate-100 transition-colors`}>
                  {col.label}
                  <SortIcon col={col.key} sortKey={sortKey} dir={sortDir} />
                </th>
              ))}
              <th className="px-4 py-3 text-right text-xs font-bold uppercase tracking-wide text-slate-500 whitespace-nowrap">
                Action
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ rawName, counts }) => {
              const total = Object.values(counts).reduce((a, b) => a + b, 0);
              const hasRisk = (counts.EOL ?? 0) > 0;
              const hasExpiring = (counts.EXPIRING_SOON ?? 0) > 0;
              return (
                <tr key={rawName}
                  className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70 group cursor-pointer"
                  onClick={() => onRowClick(rawName)}>
                  {/* Service name */}
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className={`w-2 h-2 rounded-full shrink-0 ${total === 0 ? "bg-slate-300" : hasRisk ? "bg-red-500" : hasExpiring ? "bg-amber-400" : "bg-green-400"}`} />
                      <span className="font-semibold text-slate-900 group-hover:text-indigo-700 transition-colors">
                        {serviceLabel(rawName)}
                      </span>
                    </div>
                  </td>
                  {/* Total */}
                  <td className="px-4 py-3 text-right">
                    <span className="text-sm font-bold text-slate-700">{total}</span>
                  </td>
                  {/* Status counts */}
                  {["EOL", "EXPIRING_SOON", "EXTENDED_SUPPORT", "SUPPORTED", "UNKNOWN"].map(s => (
                    <td key={s} className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                      <CountCell
                        value={counts[s]}
                        tone={STATUS_TONE[s]}
                        onClick={() => onStatusClick(rawName, s)}
                      />
                    </td>
                  ))}
                  {/* Action */}
                  <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                    <button
                      onClick={() => onRowClick(rawName)}
                      className="text-xs font-semibold text-indigo-500 hover:text-indigo-700 whitespace-nowrap transition-colors">
                      View All →
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const EMPTY_SVC_COUNTS = () => ({
  EOL: 0, EXPIRING_SOON: 0, EXTENDED_SUPPORT: 0, SUPPORTED: 0,
  NEEDS_INSPECTION: 0, LIFECYCLE_NOT_TRACKED: 0, UNKNOWN: 0,
});

function buildByService(items) {
  const map = {};
  for (const item of items) {
    const svc = item.service_type || "Unknown";
    if (!map[svc]) map[svc] = EMPTY_SVC_COUNTS();
    const s = item.eol_status || "UNKNOWN";
    if (s in map[svc]) map[svc][s]++;
    else map[svc].UNKNOWN++;
  }
  return map;
}

export default function ServicesPage() {
  const navigate = useNavigate();
  const [view,             setView]           = useState("table");
  const [sortKey,          setSortKey]        = useState("EOL");
  const [sortDir,          setSortDir]        = useState("desc");
  const [accountId,        setAccountId]      = useState("");
  const [sourceFilter,     setSourceFilter]   = useState(""); // "" | "ACCOUNT_SCAN" | "ORG_SCAN"
  const [orgMemberAccounts, setOrgMemberAccounts] = useState([]);

  const { data: summaryData, isLoading: summaryLoading, isError } = useSummary(
    sourceFilter ? { scan_source: sourceFilter } : {}
  );

  // Reset account selection when source changes
  useEffect(() => { setAccountId(""); }, [sourceFilter]);

  // Fetch org member accounts when Org Scan source is selected
  useEffect(() => {
    if (sourceFilter !== "ORG_SCAN") { setOrgMemberAccounts([]); return; }
    const wsId = getWorkspaceId();
    if (!wsId) return;
    let cancelled = false;
    (async () => {
      try {
        const r1 = await axios.get(`${API_BASE_URL}/workspaces/${wsId}/org-connections`,
          { headers: workspaceHeaders(), timeout: 6000 });
        const activeConn = (r1.data.connections || []).find(c => c.status === "CONNECTED");
        if (!activeConn || cancelled) return;
        const r2 = await axios.get(
          `${API_BASE_URL}/workspaces/${wsId}/org-connections/${activeConn.id}/accounts`,
          { headers: workspaceHeaders(), timeout: 6000 });
        if (!cancelled) setOrgMemberAccounts((r2.data.accounts || []).filter(a => a.status === "ACTIVE"));
      } catch { /* non-fatal */ }
    })();
    return () => { cancelled = true; };
  }, [sourceFilter]);

  const connectedAccounts = loadAccounts();
  const orgAccountsCount  = summaryData?.org_accounts ?? 0;
  const showSourceFilter  = orgAccountsCount > 0;

  // Account dropdown list depends on source
  const accountDropdownList = sourceFilter === "ORG_SCAN" ? orgMemberAccounts : connectedAccounts;
  const showAccountFilter   = sourceFilter === "ORG_SCAN"
    ? orgMemberAccounts.length > 1
    : connectedAccounts.length > 1;

  const sourceOptions = [
    { value: "",             label: "All Sources"   },
    { value: "ACCOUNT_SCAN", label: "Account Scan"  },
    { value: "ORG_SCAN",     label: "Org Scan"      },
  ];

  const accountSelectOptions = useMemo(() => [
    { value: "", label: sourceFilter === "ORG_SCAN" ? "All organization accounts" : "All Accounts" },
    ...(sourceFilter === "ORG_SCAN"
      ? orgMemberAccounts.map(a => ({ value: a.awsAccountId, label: a.name || a.awsAccountId }))
      : connectedAccounts.map(a => ({ value: a.id, label: a.accountName || a.name || a.id }))
    ),
  ], [sourceFilter, orgMemberAccounts, connectedAccounts]);

  // Total account count for subtitle
  const totalAccountCount = sourceFilter === "ORG_SCAN"
    ? orgAccountsCount
    : sourceFilter === "ACCOUNT_SCAN"
      ? (summaryData?.accounts_total ?? connectedAccounts.length)
      : (summaryData?.accounts_total ?? connectedAccounts.length) + orgAccountsCount;

  const { data: filteredInv, isLoading: invLoading } = useInventory(
    { account_id: accountId, ...(sourceFilter ? { scan_source: sourceFilter } : {}) },
    { enabled: !!accountId }
  );

  const baseByService = summaryData?.by_service ?? {};
  const baseTotals    = summaryData?.totals ?? { EOL: 0, EXPIRING_SOON: 0, EXTENDED_SUPPORT: 0, SUPPORTED: 0, UNKNOWN: 0, NEEDS_INSPECTION: 0, LIFECYCLE_NOT_TRACKED: 0 };

  const byService = useMemo(() => {
    if (!accountId || !filteredInv?.items) return baseByService;
    return buildByService(filteredInv.items);
  }, [accountId, filteredInv, baseByService]);

  const totals = useMemo(() => {
    if (!accountId || !filteredInv?.items) return baseTotals;
    return filteredInv.items.reduce((acc, item) => {
      const s = item.eol_status || "UNKNOWN";
      if (s in acc) acc[s]++;
      else acc.UNKNOWN++;
      return acc;
    }, { EOL: 0, EXPIRING_SOON: 0, EXTENDED_SUPPORT: 0, SUPPORTED: 0, UNKNOWN: 0, NEEDS_INSPECTION: 0, LIFECYCLE_NOT_TRACKED: 0 });
  }, [accountId, filteredInv, baseTotals]);

  const isLoading = summaryLoading || (!!accountId && invLoading && !filteredInv);
  const grand     = Object.values(totals).reduce((a, b) => a + b, 0);

  const sortedRows = useMemo(() => {
    const entries = Object.entries(byService).map(([rawName, counts]) => ({ rawName, counts }));
    entries.sort((a, b) => {
      let va, vb;
      if (sortKey === "name") {
        va = serviceLabel(a.rawName).toLowerCase();
        vb = serviceLabel(b.rawName).toLowerCase();
        return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
      }
      if (sortKey === "total") {
        va = Object.values(a.counts).reduce((x, y) => x + y, 0);
        vb = Object.values(b.counts).reduce((x, y) => x + y, 0);
      } else {
        va = a.counts[sortKey] ?? 0;
        vb = b.counts[sortKey] ?? 0;
      }
      return sortDir === "asc" ? va - vb : vb - va;
    });
    return entries;
  }, [byService, sortKey, sortDir]);

  function handleSort(col) {
    if (col === sortKey) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(col); setSortDir("desc"); }
  }

  function handleCardClick(rawService) {
    const p = new URLSearchParams({ service: rawService });
    if (accountId)    p.set("account_id", accountId);
    if (sourceFilter) p.set("source", sourceFilter);
    navigate(`/dashboard?${p.toString()}`);
  }
  function handleStatusClick(rawService, status) {
    const p = new URLSearchParams({ service: rawService, status });
    if (accountId)    p.set("account_id", accountId);
    if (sourceFilter) p.set("source", sourceFilter);
    navigate(`/dashboard?${p.toString()}`);
  }

  if (isLoading) {
    return (
      <div className="px-4 sm:px-6 py-6 sm:py-8 max-w-7xl mx-auto">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-indigo-500 mb-2">Service Risk</p>
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 mb-1.5">Services</h1>
        <p className="text-sm text-slate-500 mb-8">Loading service breakdown…</p>
        <div className="space-y-4 animate-pulse">
          <div className="h-20 rounded-2xl bg-white shadow-sm" />
          <div className="rounded-2xl border border-slate-200 overflow-hidden">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="flex gap-4 border-b border-slate-100 px-4 py-4 last:border-0">
                {[...Array(8)].map((__, j) => <div key={j} className="h-4 flex-1 animate-pulse rounded bg-slate-100" />)}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="px-4 sm:px-6 pt-6 sm:pt-8 pb-8 sm:pb-10 max-w-7xl mx-auto">

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-indigo-500 uppercase tracking-widest mb-2">Service Risk</p>
          <h1 className="text-3xl font-extrabold text-gray-900 mb-1">Services</h1>
          <p className="text-sm text-gray-500">
            EOL risk by AWS service type.
            {grand > 0 && (() => {
              const svcStr = `${sortedRows.length} service${sortedRows.length !== 1 ? "s" : ""}`;
              const resStr = `${grand} resource${grand !== 1 ? "s" : ""}`;
              const acctLabel = sourceFilter === "ORG_SCAN" ? "org account" : "connected account";
              const acctStr  = totalAccountCount > 1 ? ` and ${totalAccountCount} ${acctLabel}${totalAccountCount !== 1 ? "s" : ""}` : "";
              return ` ${resStr} across ${svcStr}${acctStr}.`;
            })()}
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {/* Source filter — only when org scan data exists */}
          {showSourceFilter && (
            <AppSelect
              value={sourceFilter}
              options={sourceOptions}
              onChange={setSourceFilter}
              size="md"
            />
          )}
          {/* Account filter — connected accounts or org member accounts depending on source */}
          {showAccountFilter && (
            <AppSelect
              value={accountId}
              options={accountSelectOptions}
              onChange={setAccountId}
              size="md"
            />
          )}
          {grand > 0 && (
            <div className="flex rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
              <button
                onClick={() => setView("table")}
                title="Table view"
                className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-bold transition-colors ${
                  view === "table" ? "bg-slate-950 text-white" : "text-slate-500 hover:bg-slate-50"
                }`}>
                <List size={13} strokeWidth={2} /> Table
              </button>
              <button
                onClick={() => setView("grid")}
                title="Grid view"
                className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-bold transition-colors ${
                  view === "grid" ? "bg-slate-950 text-white" : "text-slate-500 hover:bg-slate-50"
                }`}>
                <LayoutGrid size={13} strokeWidth={2} /> Grid
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Active account filter banner */}
      {accountId && (() => {
        const orgAcct = orgMemberAccounts.find(a => a.awsAccountId === accountId);
        const connAcct = connectedAccounts.find(a => a.id === accountId);
        const name  = orgAcct?.name || connAcct?.accountName || connAcct?.name || accountId;
        const rawId = orgAcct?.awsAccountId || connAcct?.accountId || "";
        const masked = rawId.length === 12 ? `${rawId.slice(0,4)}…${rawId.slice(-4)}` : rawId;
        return (
          <div className="mb-5 flex items-center gap-2 rounded-lg border border-indigo-100 bg-indigo-50 px-3 py-2 text-xs text-indigo-700">
            <span className="font-semibold">Filtered:</span>
            <span>{name}{masked ? ` · ${masked}` : ""}</span>
            <button onClick={() => setAccountId("")} className="ml-auto text-indigo-400 hover:text-indigo-700 font-bold text-sm leading-none">✕</button>
          </div>
        );
      })()}

      {/* Error state */}
      {isError && (
        <div className="text-center py-12 text-red-500 text-sm">Unable to load service data from backend.</div>
      )}

      {/* Empty state — source-aware */}
      {!isError && grand === 0 && (
        <div className="bg-white rounded-2xl border border-slate-100 shadow-sm px-6 py-16 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-slate-100">
            <LayoutGrid size={24} className="text-slate-400" strokeWidth={1.5} />
          </div>
          <h3 className="text-base font-bold text-slate-900 mb-1">
            {sourceFilter === "ORG_SCAN"    ? "No org scan inventory yet"
             : sourceFilter === "ACCOUNT_SCAN" ? "No account scan inventory yet"
             : "No service inventory yet"}
          </h3>
          <p className="text-sm text-slate-500 max-w-xs mx-auto mb-5 leading-relaxed">
            {sourceFilter === "ORG_SCAN"
              ? "Run an organization scan to see service breakdown by AWS service type."
              : "Run an account scan to see EOL risk grouped by AWS service."}
          </p>
          <button
            onClick={() => navigate(sourceFilter === "ORG_SCAN" ? "/org-scan" : "/account-scan")}
            className="inline-flex items-center rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-bold text-white hover:bg-slate-700 transition-colors">
            {sourceFilter === "ORG_SCAN" ? "Open Organization Scan" : "Connect Account"}
          </button>
        </div>
      )}

      {!isError && grand > 0 && (
        <>
          {/* Distribution summary */}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 mb-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">Overall Distribution</h2>
            <KpiChips totals={totals} grand={grand} onChipClick={s => navigate(`/dashboard?status=${s}`)} />
            <DistributionBar counts={totals} />
            <div className="flex flex-wrap gap-4 mt-3">
              {STATUS_ORDER.filter(s => totals[s] > 0).map(s => (
                <button key={s} onClick={() => navigate(`/dashboard?status=${s}`)}
                  className="flex items-center gap-1.5 hover:underline">
                  <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: getStatusConfig(s).hex }} />
                  <span className="text-xs text-gray-500">
                    {getStatusConfig(s).label}: <strong className="text-gray-700">{totals[s]}</strong>
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Table or Grid */}
          {view === "table" ? (
            <ServiceTable
              rows={sortedRows}
              sortKey={sortKey}
              sortDir={sortDir}
              onSort={handleSort}
              onRowClick={handleCardClick}
              onStatusClick={handleStatusClick}
            />
          ) : (
            <>
              <div className="mb-4">
                <p className="text-xs text-slate-500">Click a service to review affected resources.</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
                {sortedRows.map(({ rawName, counts }) => (
                  <ServiceCard
                    key={rawName}
                    rawName={rawName}
                    counts={counts}
                    onCardClick={handleCardClick}
                    onStatusClick={handleStatusClick}
                  />
                ))}
              </div>
            </>
          )}

          {view === "table" && (
            <p className="mt-3 text-xs text-slate-400">
              {sortedRows.length} service{sortedRows.length !== 1 ? "s" : ""} · click any count to filter Dashboard · click row to view all resources
            </p>
          )}
        </>
      )}
    </div>
  );
}
