import React, { useState, useMemo, useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, X, LayoutDashboard, Server, PlayCircle } from "lucide-react";
import axios from "axios";
import { API_BASE_URL, isDemoEnabled } from "../utils/config";
import OnboardingChecklist from "../components/OnboardingChecklist";
import { MetricCard }   from "../components/MetricCard";
import { ResourceTable } from "../components/ResourceTable";
import { FilterBar }    from "../components/FilterBar";
import { DetailPanel }  from "../components/DetailPanel";
import { useInventory, useSummary } from "../hooks/useInventory";
import { loadAccounts, fetchAccountsFromServer, saveAccounts } from "../utils/connectedAccounts";
import { getWorkspaceId, workspaceHeaders } from "../utils/workspace";

// ── CSV Export ────────────────────────────────────────────────────────────────
function exportCSV(items) {
  const COLS = [
    "account_id","region","service_type","resource_name","resource_id",
    "version","eol_status","eol_date","support_end_date","final_eol_date",
    "days_to_eol","recommendation","engine","db_instance_class","platform_version",
    "cluster_status","engine_mode","instance_type","ami_id","image_name","os_source",
  ];
  const HEADERS = [
    "Account ID","Region","Service","Resource","Resource ID",
    "Version","Status","EOL Date","Support End","Final EOL",
    "Days to EOL","Recommendation","Engine","Instance Class","Platform Version",
    "Cluster Status","Engine Mode","EC2 Instance Type","AMI ID","AMI Name","OS Source",
  ];
  const header = HEADERS.join(",");
  const rows   = items.map(item =>
    COLS.map(c => `"${(item[c] ?? "").toString().replace(/"/g, '""')}"`).join(",")
  );
  const csv  = [header, ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url; a.download = `aws-eol-${new Date().toISOString().slice(0,10)}.csv`;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a); URL.revokeObjectURL(url);
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function Toast({ message, type, onClose }) {
  if (!message) return null;
  const colors = {
    success: "bg-green-50 border-green-200 text-green-800",
    error:   "bg-red-50 border-red-200 text-red-800",
    info:    "bg-blue-50 border-blue-200 text-blue-800",
  };
  return (
    <div className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl border shadow-lg text-sm font-medium ${colors[type] ?? colors.info}`}>
      <span>{message}</span>
      <button onClick={onClose} className="opacity-60 hover:opacity-100 ml-1 text-base leading-none">✕</button>
    </div>
  );
}

const STATUS_LABELS = {
  EOL: "End of Life", EXPIRING_SOON: "Expiring Soon",
  EXTENDED_SUPPORT: "Ext. Support", SUPPORTED: "Supported",
  UNKNOWN: "Unknown", NEEDS_INSPECTION: "Needs Inspection",
  LIFECYCLE_NOT_TRACKED: "Lifecycle Not Tracked",
};

// ── Active filter banner ──────────────────────────────────────────────────────
function ActiveFilterBanner({ filters, onClear, onRemove, accountMap = {} }) {
  const chips = [
    filters.account_id && { key: "account_id", label: `Account: ${accountMap[filters.account_id]?.name ?? filters.account_id}` },
    filters.service    && { key: "service",    label: `Service: ${filters.service}` },
    filters.status     && { key: "status",     label: `Status: ${STATUS_LABELS[filters.status] ?? filters.status}` },
    filters.region     && { key: "region",     label: `Region: ${filters.region}` },
    filters.search     && { key: "search",     label: `Search: "${filters.search}"` },
  ].filter(Boolean);
  if (chips.length === 0) return null;
  return (
    <div className="flex items-center gap-2 flex-wrap mb-3 px-1">
      <span className="text-xs text-gray-400 shrink-0">Active filters:</span>
      {chips.map(c => (
        <span key={c.key}
          className="flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-100">
          {c.label}
          <button onClick={() => onRemove(c.key)} className="ml-0.5 hover:text-indigo-900 leading-none">
            <X size={11} strokeWidth={2.5} />
          </button>
        </span>
      ))}
      <button onClick={onClear}
        className="text-xs font-semibold px-3 py-1 rounded-lg border border-gray-200 text-gray-600 bg-white hover:bg-gray-50 transition-all">
        Clear filters
      </button>
    </div>
  );
}

// ── Error banner ──────────────────────────────────────────────────────────────
function ErrorBanner({ message }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 mb-4 flex items-center gap-2 text-sm text-red-700">
      <AlertTriangle size={16} className="shrink-0" strokeWidth={1.75} />
      <span>{message}</span>
    </div>
  );
}

// ── Contextual empty states ────────────────────────────────────────────────────
function EmptyState({ reason, sourceFilter = "", hasOrgAccounts = false }) {
  const navigate = useNavigate();

  // For no_resources, the content and CTA depend on which source is active.
  function NoResourcesContent() {
    if (sourceFilter === "ORG_SCAN") {
      return (
        <>
          <h3 className="text-base font-bold text-slate-900 mb-1">No organization scan resources found</h3>
          <p className="text-sm text-slate-500 max-w-sm mx-auto mb-2 leading-relaxed">
            Run an organization scan or adjust the organization region scope to populate this view.
          </p>
          <p className="text-xs text-slate-400 max-w-xs mx-auto mb-6">
            Resources outside the selected organization regions will not appear here.
          </p>
          <button
            onClick={() => navigate("/org-scan")}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-bold text-white hover:bg-slate-700 transition-colors">
            Open Organization Scan
          </button>
        </>
      );
    }

    if (sourceFilter === "ACCOUNT_SCAN") {
      return (
        <>
          <h3 className="text-base font-bold text-slate-900 mb-1">No account scan resources found</h3>
          <p className="text-sm text-slate-500 max-w-sm mx-auto mb-6 leading-relaxed">
            Run a scan from your connected accounts to populate this view.
          </p>
          <button
            onClick={() => navigate("/connected-accounts")}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-bold text-white hover:bg-slate-700 transition-colors">
            Manage connected accounts
          </button>
        </>
      );
    }

    // All Sources — offer both paths when org accounts exist
    return (
      <>
        <h3 className="text-base font-bold text-slate-900 mb-1">No resources found</h3>
        <p className="text-sm text-slate-500 max-w-sm mx-auto mb-6 leading-relaxed">
          {hasOrgAccounts
            ? "Run an account scan or organization scan to populate the dashboard."
            : "Scan completed but no supported resources were found in the selected regions."}
        </p>
        <div className="flex items-center justify-center gap-3 flex-wrap">
          <button
            onClick={() => navigate("/connected-accounts")}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-bold text-white hover:bg-slate-700 transition-colors">
            Manage connected accounts
          </button>
          {hasOrgAccounts && (
            <button
              onClick={() => navigate("/org-scan")}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-bold text-slate-700 hover:bg-slate-50 transition-colors">
              Open Organization Scan
            </button>
          )}
        </div>
      </>
    );
  }

  const SETUP_STATES = {
    no_account: {
      Icon: Server,
      title: "No AWS account connected",
      body: "Connect your first AWS account to start scanning for EOL risks.",
      cta: "Connect AWS Account",
      to: "/account-scan",
    },
    no_scan: {
      Icon: PlayCircle,
      title: "No scan run yet",
      body: "Your account is connected. Run your first scan to populate the dashboard.",
      cta: "Run First Scan",
      to: "/connected-accounts",
    },
  };

  const setup = SETUP_STATES[reason];

  if (setup) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center shadow-sm">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-slate-100">
          <setup.Icon size={24} className="text-slate-400" strokeWidth={1.5} />
        </div>
        <h3 className="text-base font-bold text-slate-900 mb-1">{setup.title}</h3>
        <p className="text-sm text-slate-500 max-w-sm mx-auto mb-6 leading-relaxed">{setup.body}</p>
        <button
          onClick={() => navigate(setup.to)}
          className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-bold text-white hover:bg-slate-700 transition-colors">
          {setup.cta}
        </button>
      </div>
    );
  }

  // no_resources — source-aware content
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center shadow-sm">
      <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-slate-100">
        <LayoutDashboard size={24} className="text-slate-400" strokeWidth={1.5} />
      </div>
      <NoResourcesContent />
    </div>
  );
}

// ── Lifecycle Not Tracked card ────────────────────────────────────────────────
function LifecycleNotTrackedCard({ total, loading, onClick, active }) {
  const base = "cursor-pointer rounded-2xl border bg-white shadow-sm px-5 py-4 transition-all";
  const ring = active
    ? "border-slate-400 ring-1 ring-slate-200 bg-slate-50/40"
    : "border-slate-200 hover:border-slate-300";
  return (
    <div onClick={onClick} className={`${base} ${ring}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-1.5">
        Lifecycle Not Tracked
      </p>
      {loading ? (
        <div className="h-7 w-16 animate-pulse rounded bg-slate-100 mb-2" />
      ) : (
        <p className="text-2xl font-extrabold text-slate-500 mb-1">{total ?? 0}</p>
      )}
      <p className="text-xs text-slate-400">No published EOL schedule</p>
    </div>
  );
}

// ── Container Images card ─────────────────────────────────────────────────────
function ContainerImagesCard({ total, untagged, loading, onClick, active }) {
  const base = "cursor-pointer rounded-2xl border bg-white shadow-sm px-5 py-4 transition-all";
  const ring = active
    ? "border-violet-300 ring-1 ring-violet-200 bg-violet-50/30"
    : "border-slate-200 hover:border-violet-200";
  return (
    <div onClick={onClick} className={`${base} ${ring}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-1.5">
        Container Images
      </p>
      {loading ? (
        <div className="h-7 w-16 animate-pulse rounded bg-slate-100 mb-2" />
      ) : (
        <p className="text-2xl font-extrabold text-violet-700 mb-1">{total ?? 0}</p>
      )}
      <div className="space-y-0.5">
        {loading ? (
          <div className="h-3 w-24 animate-pulse rounded bg-slate-100" />
        ) : (
          <p className="text-xs text-slate-500">
            {untagged > 0 ? `${untagged} untagged` : "No untagged images"}
          </p>
        )}
        <p className="text-xs text-slate-400">Runtime detection pending</p>
      </div>
    </div>
  );
}

// ── Workspace loading skeleton (phase 1 — no table, no metric cards) ──────────
function WorkspaceContextSkeleton() {
  return (
    <div className="rounded-2xl border border-slate-100 bg-white px-6 py-12 flex flex-col items-center gap-3">
      <div className="flex gap-1.5 items-center">
        <span className="h-2 w-2 rounded-full bg-slate-300 animate-pulse" style={{ animationDelay: "0ms" }} />
        <span className="h-2 w-2 rounded-full bg-slate-300 animate-pulse" style={{ animationDelay: "150ms" }} />
        <span className="h-2 w-2 rounded-full bg-slate-300 animate-pulse" style={{ animationDelay: "300ms" }} />
      </div>
      <p className="text-sm text-slate-400">Loading workspace context…</p>
    </div>
  );
}

// ── Dynamic table section title ───────────────────────────────────────────────
function getTableTitle(filters, items = []) {
  // When filtering by service, use that service's display name
  if (filters.service) {
    const SVC_LABELS = {
      EC2: "EC2 Instances", Lambda: "Lambda Functions", RDS: "RDS Databases",
      EKS: "EKS Clusters", ElastiCache: "ElastiCache Clusters",
      OpenSearch: "OpenSearch Domains", ECR: "Container Images",
      MSK: "MSK Clusters", EMR: "EMR Clusters", Glue: "Glue Jobs",
      Neptune: "Neptune Databases", DocumentDB: "DocumentDB Clusters",
      ElasticBeanstalk: "Elastic Beanstalk Environments",
      CloudFrontFunctions: "CloudFront Functions", CodeBuild: "CodeBuild Projects",
    };
    return SVC_LABELS[filters.service] ?? `${filters.service} Resources`;
  }
  // When filtering by status only, derive title from what's actually shown
  if (filters.status) {
    const STATUS_TITLES = {
      EOL:                   "End of Life Resources",
      EXPIRING_SOON:         "Expiring Soon Resources",
      EXTENDED_SUPPORT:      "Extended Support Resources",
      SUPPORTED:             "Supported Resources",
      UNKNOWN:               "Unclassified Resources",
      NEEDS_INSPECTION:      "Needs Inspection",
      LIFECYCLE_NOT_TRACKED: "Lifecycle Not Tracked",
    };
    // If all visible items are the same service, use that service label
    const services = [...new Set(items.map(i => i.service_type).filter(Boolean))];
    if (services.length === 1) {
      const SVC_LABELS = { EC2: "EC2 Instances", ECR: "Container Images", Lambda: "Lambda Functions" };
      return SVC_LABELS[services[0]] ?? STATUS_TITLES[filters.status] ?? "Filtered Resources";
    }
    return STATUS_TITLES[filters.status] ?? "Filtered Resources";
  }
  if (filters.search || filters.region || filters.account_id) return "Filtered Resources";
  return "Actionable Lifecycle Risks";
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [filters, setFilters] = useState(() => ({
    service:    searchParams.get("service")    || "",
    status:     searchParams.get("status")     || "",
    region:     "",
    search:     "",
    account_id: searchParams.get("account_id") || "",
  }));
  const [sourceFilter, setSourceFilter] = useState(() => searchParams.get("source") || ""); // "" | "ACCOUNT_SCAN" | "ORG_SCAN"
  const [selected, setSelected] = useState(null);
  const [toast, setToast]       = useState(null);
  const sourceFilterMounted = useRef(false);

  useEffect(() => {
    const p = {};
    if (filters.status)     p.status     = filters.status;
    if (filters.service)    p.service    = filters.service;
    if (filters.account_id) p.account_id = filters.account_id;
    if (sourceFilter)       p.source     = sourceFilter;
    setSearchParams(p, { replace: true });
  }, [filters.status, filters.service, filters.account_id, sourceFilter]); // eslint-disable-line

  // ── Phase 1: load workspace summary/accounts ─────────────────────────────
  // Must resolve before we decide whether to show inventory at all.
  const { data: summaryData, isLoading: summaryLoading } = useSummary(
    sourceFilter ? { scan_source: sourceFilter } : {}
  );
  const globalTotals   = summaryData?.totals ?? { EOL: 0, EXPIRING_SOON: 0, EXTENDED_SUPPORT: 0, SUPPORTED: 0, UNKNOWN: 0, NEEDS_INSPECTION: 0, LIFECYCLE_NOT_TRACKED: 0 };
  const resourcesCount = summaryData?.resources_count ?? 0;
  const lastScanned    = summaryData?.last_scanned ?? null;
  // null = still loading; 0 = server confirmed zero accounts
  const accountsTotal  = summaryData?.accounts_total ?? null;
  const orgAccounts    = summaryData?.org_accounts    ?? 0;
  const isSummaryMock  = !!summaryData?.isMock;

  // Start empty — server fetch populates this. Avoids flashing stale localStorage
  // accounts from a previous session/workspace before the server responds.
  const [connectedAccounts, setConnectedAccounts] = useState([]);
  const [orgMemberAccounts, setOrgMemberAccounts] = useState([]);

  // Sync connected accounts from server on mount.
  useEffect(() => {
    fetchAccountsFromServer().then(serverList => {
      if (!serverList) return;
      saveAccounts(serverList);
      setConnectedAccounts(serverList);
    });
  }, []);

  // Fetch org member accounts when Org Scan source is active.
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

  // Reset account filter and selected item when source changes.
  // Skip initial mount so URL-seeded account_id is preserved on first load.
  useEffect(() => {
    if (!sourceFilterMounted.current) { sourceFilterMounted.current = true; return; }
    setFilters(f => ({ ...f, account_id: "" }));
    setSelected(null);
  }, [sourceFilter]);

  // Normalize dropdown list: unified { id, accountName } shape for FilterBar.
  const accountDropdownList = useMemo(() => {
    if (sourceFilter === "ORG_SCAN") {
      return orgMemberAccounts.map(a => ({ id: a.awsAccountId, accountName: a.name || a.awsAccountId }));
    }
    return connectedAccounts;
  }, [sourceFilter, connectedAccounts, orgMemberAccounts]);

  const accountLabel = sourceFilter === "ORG_SCAN" ? "All organization accounts" : "All Accounts";

  // Combined account map for the Active Filter Banner (resolves account name by ID).
  const accountMap = useMemo(() => {
    const map = {};
    for (const a of connectedAccounts) {
      map[a.id] = { name: a.accountName || a.name || a.id, awsId: a.accountId || "" };
    }
    for (const a of orgMemberAccounts) {
      map[a.awsAccountId] = { name: a.name || a.awsAccountId, awsId: a.awsAccountId };
    }
    return map;
  }, [connectedAccounts, orgMemberAccounts]);
  // Server-authoritative once loaded; localStorage fallback only while loading.
  const hasNoAccounts = !isSummaryMock && !summaryLoading && (
    accountsTotal !== null ? accountsTotal === 0 && orgAccounts === 0 : connectedAccounts.length === 0
  );
  const hasAccountsNoScan = connectedAccounts.length > 0 && connectedAccounts.every(a => !a.lastScanAt);
  const emptyReason = hasNoAccounts ? "no_account" : hasAccountsNoScan ? "no_scan" : "no_resources";

  // ── Phase 2: load inventory — only when accounts confirmed > 0 ────────────
  // Prevents unnecessary API call and eliminates table skeleton flash on empty workspaces.
  const inventoryEnabled = isSummaryMock || (!summaryLoading && (
    (accountsTotal !== null && accountsTotal > 0) || orgAccounts > 0
  ));
  const { data: inventoryData, isLoading, isError } = useInventory(
    {
      service: filters.service, status: filters.status,
      region: filters.region, account_id: filters.account_id,
      ...(sourceFilter ? { scan_source: sourceFilter } : {}),
    },
    { enabled: inventoryEnabled }
  );

  const allItems = inventoryData?.items ?? [];
  const isMock   = inventoryData?.isMock ?? false;

  const items = useMemo(() => {
    let result = allItems;
    // account_id is filtered by backend but also enforced client-side to guard
    // against stale cache or DynamoDB attribute-name mismatches.
    if (filters.account_id) {
      result = result.filter(i => i.account_id === filters.account_id);
    }
    if (filters.search) {
      const q = filters.search.toLowerCase();
      result = result.filter(i =>
        (i.resource_name || "").toLowerCase().includes(q) ||
        (i.service_type  || "").toLowerCase().includes(q) ||
        (i.version       || "").toLowerCase().includes(q)
      );
    }
    return result;
  }, [allItems, filters.account_id, filters.search]);

  // Default view: show only actionable lifecycle statuses.
  // SUPPORTED, LIFECYCLE_NOT_TRACKED, UNKNOWN are hidden in the zero-filter default view
  // because they are not EOL risks. But when the user has applied any explicit filter
  // (account, service, source, region, search) they expect ALL matching resources to be
  // visible — including LIFECYCLE_NOT_TRACKED / inventory-only items.
  const ACTIONABLE_STATUSES = new Set(["EOL", "EXPIRING_SOON", "EXTENDED_SUPPORT", "NEEDS_INSPECTION"]);

  const displayItems = useMemo(() => {
    if (filters.status) return items; // explicit status selection — show exactly that
    // Any other filter active → show every matching resource (no silent hiding)
    if (filters.account_id || filters.service || filters.region || filters.search || sourceFilter) return items;
    // Pure default view — show actionable statuses only
    return items.filter(i => ACTIONABLE_STATUSES.has(i.eol_status));
  }, [items, filters.status, filters.account_id, filters.service, filters.region, filters.search, sourceFilter]); // eslint-disable-line

  // Hidden counts only make sense in the pure default view (no filters applied at all)
  const isDefaultView = !filters.status && !filters.account_id && !filters.service && !filters.region && !filters.search && !sourceFilter;
  const hiddenSupportedCount = isDefaultView ? items.filter(i => i.eol_status === "SUPPORTED").length : 0;
  const hiddenInventoryCount = isDefaultView ? items.filter(i => i.eol_status === "LIFECYCLE_NOT_TRACKED").length : 0;

  const hasActiveFilters = Object.values(filters).some(Boolean);

  const totals = useMemo(() => {
    if (!hasActiveFilters) return globalTotals;
    return items.reduce((acc, item) => {
      const s = item.eol_status ?? "UNKNOWN";
      acc[s] = (acc[s] ?? 0) + 1;
      return acc;
    }, { EOL: 0, EXPIRING_SOON: 0, EXTENDED_SUPPORT: 0, SUPPORTED: 0, UNKNOWN: 0, NEEDS_INSPECTION: 0, LIFECYCLE_NOT_TRACKED: 0 });
  }, [hasActiveFilters, items, globalTotals]);

  const containerStats = useMemo(() => {
    const ecrItems = allItems.filter(i => i.service_type === "ECR");
    const untagged = ecrItems.filter(i => (i.version || "").startsWith("<untagged>")).length;
    return { total: ecrItems.length, untagged };
  }, [allItems]);

  const lifecycleNotTrackedCount = totals.LIFECYCLE_NOT_TRACKED ?? 0;

  const hasNoData = !isLoading && resourcesCount === 0 && !isMock && !isError;

  function handleExport() {
    exportCSV(items);
    setToast({ message: `Exported ${items.length} resources to CSV.`, type: "success" });
  }

  function toggleStatusFilter(s) {
    setFilters(f => ({ ...f, status: f.status === s ? "" : s }));
  }

  function removeFilter(key) {
    setFilters(f => ({ ...f, [key]: "" }));
  }

  // ── Shared page wrapper ───────────────────────────────────────────────────
  function PageHeader({ subtitle }) {
    return (
      <div className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold text-indigo-500 uppercase tracking-widest mb-1.5">
            Resource Inventory
          </p>
          <h1 className="text-3xl font-extrabold text-gray-900">EOL Risk Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>
          {lastScanned && !summaryLoading && (
            <p className="text-xs text-gray-400 mt-1">
              Last scan: {new Date(lastScanned).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })} UTC
            </p>
          )}
        </div>
        {items.length > 0 && (
          <button onClick={handleExport}
            className="inline-flex h-10 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-600 transition-all hover:bg-slate-50">
            ↓ Export CSV
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-0 py-0">
      <OnboardingChecklist
        hasAccounts={summaryLoading ? null : (accountsTotal ?? connectedAccounts.length) > 0}
        hasScanned={summaryLoading ? null : resourcesCount > 0 || !!lastScanned}
        hasAlerts={(globalTotals.EOL ?? 0) + (globalTotals.EXPIRING_SOON ?? 0) > 0}
      />
      <div className="px-4 sm:px-6 py-6 sm:py-8">

        {/* ── Phase 1: workspace summary not yet resolved ── */}
        {summaryLoading && !isDemoEnabled() ? (
          <>
            <PageHeader subtitle="Loading workspace…" />
            <WorkspaceContextSkeleton />
          </>
        ) : (
          <>
            <PageHeader subtitle={
              isLoading
                ? "Loading scanned resources…"
                : resourcesCount > 0
                  ? (() => {
                      if (sourceFilter === "ORG_SCAN") {
                        return `${resourcesCount} org scan resource${resourcesCount !== 1 ? "s" : ""} across ${orgAccounts} organization account${orgAccounts !== 1 ? "s" : ""}`;
                      }
                      const n = accountsTotal ?? connectedAccounts.length;
                      if (sourceFilter === "ACCOUNT_SCAN") {
                        return `${resourcesCount} account scan resource${resourcesCount !== 1 ? "s" : ""} across ${n} connected account${n !== 1 ? "s" : ""}`;
                      }
                      const orgSuffix = orgAccounts > 0 ? ` and ${orgAccounts} org account${orgAccounts !== 1 ? "s" : ""}` : "";
                      return `${resourcesCount} scanned resource${resourcesCount !== 1 ? "s" : ""} across ${n} connected account${n !== 1 ? "s" : ""}${orgSuffix}`;
                    })()
                  : "Scanned AWS resources from your connected accounts"
            } />

            {/* Error banner */}
            {isError && API_BASE_URL && (
              <ErrorBanner message="Unable to load inventory from backend. Please check your connection or retry." />
            )}

            {/* Demo banner */}
            {isMock && (
              <div className="bg-amber-50 ring-1 ring-amber-100 rounded-xl px-4 py-2.5 mb-4 flex items-center gap-2 text-sm text-amber-700">
                <AlertTriangle size={15} className="shrink-0" strokeWidth={1.75} />
                <span>Demo mode — showing sample scanned inventory.</span>
              </div>
            )}

            {/* Source filter pills — only shown when org scan data exists */}
            {!hasNoAccounts && orgAccounts > 0 && (
              <div className="flex items-center gap-2 mb-5 flex-wrap">
                {[
                  { value: "",             label: "All Sources" },
                  { value: "ACCOUNT_SCAN", label: "Account Scan" },
                  { value: "ORG_SCAN",     label: "Org Scan" },
                ].map(({ value, label }) => (
                  <button key={value}
                    onClick={() => setSourceFilter(value)}
                    className={`text-xs font-semibold px-3 py-1.5 rounded-full border transition-all ${
                      sourceFilter === value
                        ? "bg-indigo-600 text-white border-indigo-600"
                        : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                    }`}>
                    {label}
                  </button>
                ))}
                <span className="text-xs text-slate-400 ml-1">
                  {orgAccounts} org account{orgAccounts !== 1 ? "s" : ""}
                </span>
              </div>
            )}

            {/* ── Phase 2: accounts = 0 OR no data ── */}
            {hasNoAccounts || (hasNoData && !hasActiveFilters) ? (
              <EmptyState
                reason={emptyReason}
                sourceFilter={sourceFilter}
                hasOrgAccounts={orgAccounts > 0}
              />
            ) : (
              <>
                {/* Metric cards */}
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {hasActiveFilters ? "Filtered summary" : "Global summary"}
                  </span>
                  {hasActiveFilters && (
                    <span className="text-xs font-medium text-slate-500">
                      {items.length} resource{items.length !== 1 ? "s" : ""} match filters
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 mb-3">
                  {[
                    { key: "EOL",              label: "End of Life"      },
                    { key: "EXPIRING_SOON",    label: "Expiring Soon"    },
                    { key: "EXTENDED_SUPPORT", label: "Extended Support" },
                    { key: "SUPPORTED",        label: "Supported"        },
                    { key: "UNKNOWN",          label: "Unknown"          },
                  ].map(({ key, label }) => (
                    <MetricCard
                      key={key}
                      label={label}
                      value={!isLoading ? (totals[key] ?? 0) : undefined}
                      status={key}
                      loading={isLoading}
                      onClick={() => toggleStatusFilter(key)}
                      active={filters.status === key}
                    />
                  ))}
                </div>

                {(isLoading || containerStats.total > 0 || lifecycleNotTrackedCount > 0) && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-5">
                    {(isLoading || containerStats.total > 0) && (
                      <ContainerImagesCard
                        total={!isLoading ? containerStats.total : undefined}
                        untagged={containerStats.untagged}
                        loading={isLoading}
                        onClick={() => toggleStatusFilter("NEEDS_INSPECTION")}
                        active={filters.status === "NEEDS_INSPECTION"}
                      />
                    )}
                    {(isLoading || lifecycleNotTrackedCount > 0) && (
                      <LifecycleNotTrackedCard
                        total={!isLoading ? lifecycleNotTrackedCount : undefined}
                        loading={isLoading}
                        onClick={() => toggleStatusFilter("LIFECYCLE_NOT_TRACKED")}
                        active={filters.status === "LIFECYCLE_NOT_TRACKED"}
                      />
                    )}
                  </div>
                )}

                <ActiveFilterBanner
                  filters={filters}
                  onClear={() => setFilters({ service: "", status: "", region: "", search: "", account_id: "" })}
                  onRemove={removeFilter}
                  accountMap={accountMap}
                />

                <FilterBar
                  filters={filters}
                  onChange={setFilters}
                  totalFiltered={hasActiveFilters ? items.length : undefined}
                  accounts={accountDropdownList}
                  accountLabel={accountLabel}
                />

                {!isLoading && (
                  <div className="flex items-center justify-between mb-2 px-0.5 gap-3 flex-wrap">
                    <div className="flex items-center gap-3 flex-wrap">
                      <p className="text-xs font-bold uppercase tracking-widest text-slate-400">
                        {getTableTitle(filters, items)}
                      </p>
                      {hiddenSupportedCount > 0 && (
                        <button
                          onClick={() => toggleStatusFilter("SUPPORTED")}
                          className="text-xs text-green-600 hover:text-green-800 hover:underline transition-colors"
                        >
                          + {hiddenSupportedCount} supported hidden
                        </button>
                      )}
                      {hiddenInventoryCount > 0 && (
                        <button
                          onClick={() => toggleStatusFilter("LIFECYCLE_NOT_TRACKED")}
                          className="text-xs text-slate-400 hover:text-slate-600 hover:underline transition-colors"
                        >
                          + {hiddenInventoryCount} inventory-only hidden
                        </button>
                      )}
                    </div>
                    <span className="text-xs text-slate-400">
                      {hasActiveFilters
                        ? `${displayItems.length} filtered · ${resourcesCount} total`
                        : (hiddenSupportedCount + hiddenInventoryCount) > 0
                          ? `${displayItems.length} actionable · ${resourcesCount} total`
                          : `${resourcesCount} total`}
                    </span>
                  </div>
                )}

                <ResourceTable
                  items={displayItems}
                  filters={filters}
                  onRowClick={setSelected}
                  onActionClick={setSelected}
                  actionLabel="Details →"
                  loading={isLoading}
                  hasActiveFilters={hasActiveFilters}
                  onClearFilters={() => setFilters({ service: "", status: "", region: "", search: "", account_id: "" })}
                  accountMap={accountMap}
                />
              </>
            )}
          </>
        )}

        {selected && <DetailPanel item={selected} accountMap={accountMap} onClose={() => setSelected(null)} />}
        <Toast message={toast?.message} type={toast?.type} onClose={() => setToast(null)} />
      </div>
    </div>
  );
}
