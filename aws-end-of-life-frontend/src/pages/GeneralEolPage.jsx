import React, { useMemo, useState, useEffect, useRef } from "react";
import { LockOpen, Lightbulb, Search, X, AlertCircle, RefreshCw, DatabaseZap, ExternalLink } from "lucide-react";
import { AppSelect } from "../components/AppSelect";
import { HAS_API } from "../utils/config";
import { StatusBadge } from "../components/StatusBadge";
import { useGeneralEol, useGeneralEolSummary } from "../hooks/useGeneralEol";

const PER_PAGE = 15;
const STATUS_PRIORITY = { EOL: 0, EXPIRING_SOON: 1, EXTENDED_SUPPORT: 2, SUPPORTED: 3 };
const STATUSES = ["", "EOL", "EXPIRING_SOON", "EXTENDED_SUPPORT", "SUPPORTED"];
const STATUS_LABELS = {
  "":               "All statuses",
  EOL:              "EOL",
  EXPIRING_SOON:    "Expiring Soon",
  EXTENDED_SUPPORT: "Ext. Support",
  SUPPORTED:        "Supported",
};

const SUMMARY_META = {
  EOL:              { label: "End of Life",   hint: "Already unsupported",    bg: "bg-red-50",   text: "text-red-800",   ring: "ring-red-400"   },
  EXPIRING_SOON:    { label: "Expiring Soon", hint: "Needs upgrade planning", bg: "bg-amber-50", text: "text-amber-800", ring: "ring-amber-400" },
  EXTENDED_SUPPORT: { label: "Ext. Support",  hint: "Review paid support",    bg: "bg-blue-50",  text: "text-blue-800",  ring: "ring-blue-400"  },
  SUPPORTED:        { label: "Supported",     hint: "No action needed",       bg: "bg-green-50", text: "text-green-800", ring: "ring-green-400" },
};

const TABLE_COLS = [
  { key: "service",            label: "AWS Service"       },
  { key: "version",            label: "Version / Runtime" },
  { key: "status",             label: "Status"            },
  { key: "daysToEol",          label: "Days to EOL"       },
  { key: "eolDate",            label: "Support Ends"      },
  { key: "finalEolDate",       label: "Final EOL"         },
  { key: "recommendedUpgrade", label: "Upgrade To"        },
  { key: "lifecycle_source",   label: "Source"            },
];

function formatSourceFreshness(meta) {
  const refreshedAt = meta?.refreshed_at || meta?.refreshedAt;
  const verifiedCount = meta?.verified_overlay_count;
  const sourceLabel = (meta?.source === "mixed" && verifiedCount > 0)
    ? `endoflife.date + ${verifiedCount} AWS verified`
    : "endoflife.date";
  if (!refreshedAt) return `Source: ${sourceLabel}`;
  const parsed = new Date(refreshedAt);
  if (Number.isNaN(parsed.getTime())) return `Source: ${sourceLabel} · refreshed ${refreshedAt}`;
  return `Source: ${sourceLabel} · refreshed ${parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SummaryCard({ statusKey, count, active, onClick }) {
  const m = SUMMARY_META[statusKey];
  return (
    <button
      onClick={onClick}
      className={`rounded-xl px-4 py-3.5 text-left transition-all w-full ${m.bg} ${m.text}
        ${active ? `ring-2 ${m.ring} ring-offset-1` : "opacity-80 hover:opacity-100"}`}
    >
      <p className="text-2xl font-extrabold">{count}</p>
      <p className="text-xs font-semibold uppercase tracking-wide mt-0.5">{m.label}</p>
      <p className="text-xs mt-0.5 opacity-60">{m.hint}</p>
      {active && <p className="text-xs mt-1.5 opacity-70 font-medium">Filtering ✓</p>}
    </button>
  );
}

function DaysCell({ days }) {
  if (days === null || days === undefined) return <span className="text-gray-400 text-xs">—</span>;
  if (days < 0)   return <span className="text-red-600 font-medium text-xs">{Math.abs(days)} days past EOL</span>;
  if (days === 0) return <span className="text-red-600 font-bold text-xs">EOL today</span>;
  if (days <= 30) return <span className="font-medium text-xs" style={{ color: "#B7770D" }}>{days} days remaining</span>;
  return <span className="text-gray-500 text-xs">{days} days remaining</span>;
}

const SOURCE_META = {
  MANUAL_OVERRIDE:       { label: "Override",       bg: "bg-purple-50",  text: "text-purple-700",  border: "border-purple-200",  title: "Manually set by admin" },
  VERIFIED_AWS_OFFICIAL: { label: "AWS Verified",   bg: "bg-emerald-50", text: "text-emerald-800", border: "border-emerald-300", title: "Admin-validated from AWS official documentation" },
  AWS_MCP:               { label: "AWS MCP",        bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", title: "Validated via AWS Documentation MCP" },
  ENDOFLIFE_DATE:        { label: "endoflife.date", bg: "bg-blue-50",    text: "text-blue-700",    border: "border-blue-200",    title: "From endoflife.date public API" },
  AWS_DOCS:              { label: "AWS Docs",       bg: "bg-orange-50",  text: "text-orange-700",  border: "border-orange-200",  title: "From AWS official documentation" },
  AWS_OFFICIAL:          { label: "AWS Official",   bg: "bg-orange-50",  text: "text-orange-700",  border: "border-orange-200",  title: "From AWS official documentation" },
  AWS_API:               { label: "AWS API",        bg: "bg-green-50",   text: "text-green-700",   border: "border-green-200",   title: "From AWS EKS API (live data)" },
};

const CONFIDENCE_META = {
  VERIFIED: { label: "Verified", bg: "bg-green-50",  text: "text-green-700",  border: "border-green-200"  },
  HIGH:     { label: "High",     bg: "bg-green-50",  text: "text-green-700",  border: "border-green-200"  },
  MEDIUM:   { label: "Medium",   bg: "bg-yellow-50", text: "text-yellow-700", border: "border-yellow-200" },
  LOW:      { label: "Low",      bg: "bg-red-50",    text: "text-red-600",    border: "border-red-200"    },
};

function SourceBadge({ row }) {
  const src        = row.lifecycle_source;
  const conf       = row.confidence;
  const isStale    = row.is_stale;
  const officialUrl = row.officialSourceUrl || (src === "VERIFIED_AWS_OFFICIAL" ? row.source_url : null);
  const validatedAt = row.lastValidatedAt;
  const srcMeta    = SOURCE_META[src] || { label: src || "—", bg: "bg-gray-50", text: "text-gray-500", border: "border-gray-200", title: "" };
  const confMeta   = conf ? CONFIDENCE_META[conf] : null;

  const badgeTitle = [
    srcMeta.title,
    validatedAt ? `Validated: ${new Date(validatedAt).toLocaleDateString()}` : null,
  ].filter(Boolean).join(" · ");

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1">
        <span
          className={`inline-block text-xs font-medium px-1.5 py-0.5 rounded border ${srcMeta.bg} ${srcMeta.text} ${srcMeta.border} whitespace-nowrap`}
          title={badgeTitle}
        >
          {srcMeta.label}
        </span>
        {officialUrl && (
          <a
            href={officialUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-gray-400 hover:text-blue-500 transition-colors"
            title="View official AWS documentation"
            onClick={e => e.stopPropagation()}
          >
            <ExternalLink size={11} />
          </a>
        )}
      </div>
      {confMeta && (
        <span className={`inline-block text-xs px-1.5 py-0.5 rounded border ${confMeta.bg} ${confMeta.text} ${confMeta.border} whitespace-nowrap`}>
          {confMeta.label}
        </span>
      )}
      {isStale && (
        <span className="inline-block text-xs px-1.5 py-0.5 rounded border bg-amber-50 text-amber-700 border-amber-200 whitespace-nowrap" title="Cached data — may be outdated">
          Stale
        </span>
      )}
    </div>
  );
}

function Pagination({ page, totalPages, total, onPage }) {
  if (totalPages <= 1) return null;
  const start = (page - 1) * PER_PAGE + 1;
  const end   = Math.min(page * PER_PAGE, total);
  return (
    <div className="flex items-center gap-1">
      <button onClick={() => onPage(page - 1)} disabled={page === 1}
        className="px-2 py-1 rounded text-xs border border-gray-200 disabled:opacity-40 hover:bg-gray-50">‹</button>
      {[...Array(totalPages)].map((_, i) => {
        const p = i + 1;
        if (p !== 1 && p !== totalPages && Math.abs(p - page) > 1) {
          if (p === 2 || p === totalPages - 1) return <span key={p} className="px-1 text-xs text-gray-400">…</span>;
          return null;
        }
        return (
          <button key={p} onClick={() => onPage(p)}
            className={`px-2.5 py-1 rounded text-xs border transition-colors ${
              p === page ? "bg-gray-900 text-white border-gray-900" : "border-gray-200 hover:bg-gray-50 text-gray-600"
            }`}>{p}</button>
        );
      })}
      <button onClick={() => onPage(page + 1)} disabled={page === totalPages}
        className="px-2 py-1 rounded text-xs border border-gray-200 disabled:opacity-40 hover:bg-gray-50">›</button>
      <span className="ml-2 text-xs text-gray-400">{start}–{end} of {total}</span>
    </div>
  );
}


// ── Page ──────────────────────────────────────────────────────────────────────

export default function GeneralEolPage() {
  const [search,        setSearch]        = useState("");
  const [service,       setService]       = useState("");
  const [status,        setStatus]        = useState("");
  const [sortKey,       setSortKey]       = useState("_urgency");
  const [sortDir,       setSortDir]       = useState("asc");
  const [page,          setPage]          = useState(1);
  const [includeLegacy, setIncludeLegacy] = useState(false);

  // Derive service list from real data (populated when no service filter is active)
  const serviceListRef = useRef([]);

  const {
    data: rawData, meta, loading, isError, isCacheEmpty,
    isMock, isRefreshing, triggerRefresh, refetch,
  } = useGeneralEol({ service, status, search, includeLegacy });
  const { summary } = useGeneralEolSummary(includeLegacy);

  // Update service list from full unfiltered data
  useEffect(() => {
    if (!service && rawData.length > 0) {
      const unique = [...new Set(rawData.map(r => r.service))].sort();
      serviceListRef.current = unique;
    }
  }, [rawData, service]);

  const serviceOptions = serviceListRef.current;

  const serviceSelectOptions = useMemo(() => [
    { value: "", label: "All Services" },
    ...serviceOptions.map(s => ({ value: s, label: s })),
  ], [serviceOptions]);

  const statusSelectOptions = useMemo(() =>
    STATUSES.map(s => ({ value: s, label: STATUS_LABELS[s] }))
  , []);

  const filtered = useMemo(() => {
    const rows = rawData;
    return sortKey === "_urgency"
      ? [...rows].sort((a, b) => {
          const d = STATUS_PRIORITY[a.status] - STATUS_PRIORITY[b.status];
          return d !== 0 ? d : (a.daysToEol ?? 0) - (b.daysToEol ?? 0);
        })
      : [...rows].sort((a, b) => {
          const av = a[sortKey] ?? "";
          const bv = b[sortKey] ?? "";
          if (av < bv) return sortDir === "asc" ? -1 : 1;
          if (av > bv) return sortDir === "asc" ? 1 : -1;
          return 0;
        });
  }, [rawData, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PER_PAGE));
  const paginated  = useMemo(() => filtered.slice((page - 1) * PER_PAGE, page * PER_PAGE), [filtered, page]);

  function handleFilter(setter) {
    return (val) => { setter(val); setPage(1); }; // reset to page 1 on any filter change
  }

  function clearFilters() {
    setSearch(""); setService(""); setStatus(""); setPage(1);
    // includeLegacy is intentionally NOT reset by Clear filters
  }

  function toggleSort(key) {
    setPage(1);
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("asc"); }
  }

  function SortIcon({ k }) {
    if (sortKey !== k) return <span className="text-gray-300 ml-1">↕</span>;
    return <span className="ml-1" style={{ color: "#2A85D8" }}>{sortDir === "asc" ? "↑" : "↓"}</span>;
  }

  const hasFilter = search || service || status;

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-7">
        <p className="text-xs font-semibold text-indigo-500 uppercase tracking-widest mb-2">Public Lifecycle Library</p>
        <h1 className="text-3xl font-extrabold text-gray-900 mb-2">Explore AWS service lifecycle timelines</h1>
        <p className="text-gray-500 text-sm max-w-2xl leading-relaxed">
          Understand which AWS runtimes, engines, and service versions are already EOL or approaching end-of-life.
          No AWS account connection required.
        </p>
      </div>

      {/* No-access strip */}
      <div className="flex items-center gap-2 text-sm text-slate-500 bg-slate-50 rounded-xl px-4 py-2.5 mb-4 ring-1 ring-slate-100">
        <LockOpen size={15} className="shrink-0 text-slate-400" strokeWidth={1.75} />
        <span>No AWS credentials used on this page. Public lifecycle information only.</span>
        <span className="ml-auto text-xs text-slate-400 shrink-0">{formatSourceFreshness(meta)}</span>
      </div>

      {/* Demo banner */}
      {isMock && (
        <div className="mb-5 px-4 py-3 bg-amber-50 border border-amber-200 rounded-xl text-amber-700 text-sm flex items-center gap-2">
          <span className="font-semibold">Demo mode:</span>
          <span>Showing sample lifecycle data. Set <code className="font-mono text-xs bg-amber-100 px-1 py-0.5 rounded">REACT_APP_API_URL</code> to connect to the live API.</span>
        </div>
      )}

      {/* Cache empty — prompt user to refresh */}
      {isCacheEmpty && (
        <div className="mb-5 px-5 py-4 bg-slate-50 border border-slate-200 rounded-xl text-slate-700 text-sm flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <DatabaseZap size={16} className="shrink-0 text-slate-400" />
            <span>Lifecycle cache is empty. Click to load data from endoflife.date (~15s).</span>
          </div>
          <button
            onClick={triggerRefresh}
            disabled={isRefreshing}
            className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg
                       bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60 transition-colors"
          >
            {isRefreshing
              ? <><span className="animate-spin inline-block w-3 h-3 border-2 border-white/40 border-t-white rounded-full" /> Loading…</>
              : <><RefreshCw size={13} /> Refresh lifecycle data</>}
          </button>
        </div>
      )}

      {/* Generic API error */}
      {isError && HAS_API && (
        <div className="mb-5 px-5 py-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <AlertCircle size={16} className="shrink-0" />
            <span>Unable to load lifecycle data from backend.</span>
          </div>
          <button onClick={refetch} className="flex items-center gap-1.5 text-xs font-medium text-red-600 hover:text-red-800">
            <RefreshCw size={13} /> Retry
          </button>
        </div>
      )}

      {/* Summary cards — counts always reflect current includeLegacy state */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        {["EOL", "EXPIRING_SOON", "EXTENDED_SUPPORT", "SUPPORTED"].map(key => (
          <SummaryCard
            key={key}
            statusKey={key}
            count={summary[key] ?? 0}
            active={status === key}
            onClick={() => { setStatus(s => s === key ? "" : key); setPage(1); }}
          />
        ))}
      </div>

      {/* Filter row */}
      <div className="flex flex-wrap items-center gap-3 mb-4">

        {/* Search input */}
        <div className="relative w-full sm:w-56">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          <input
            type="text"
            placeholder="Search service or version…"
            value={search}
            onChange={e => handleFilter(setSearch)(e.target.value)}
            className="pl-8 pr-3 py-2 text-sm border border-gray-200 rounded-lg bg-white
                       focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-300 w-full"
          />
        </div>

        {/* Service dropdown */}
        <AppSelect
          value={service}
          options={serviceSelectOptions}
          onChange={val => handleFilter(setService)(val)}
          size="md"
        />

        {/* Status dropdown */}
        <AppSelect
          value={status}
          options={statusSelectOptions}
          onChange={val => handleFilter(setStatus)(val)}
          size="md"
        />

        {/* Clear filters — only when search/service/status is active; does NOT reset includeLegacy */}
        {hasFilter && (
          <button
            onClick={clearFilters}
            className="text-sm text-gray-400 hover:text-gray-600 flex items-center gap-1"
          >
            <X size={12} /> Clear filters
          </button>
        )}

        {/* Entry count */}
        <span className="text-xs text-gray-400 shrink-0">
          {hasFilter ? `Showing ${filtered.length} filtered` : `${filtered.length} entries`}
        </span>

        {/* Legacy toggle — right-aligned */}
        <div className="ml-auto flex items-center gap-2 shrink-0">
          <button
            role="switch"
            aria-checked={includeLegacy}
            onClick={() => { setIncludeLegacy(v => !v); setPage(1); }}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none
              ${includeLegacy ? "bg-gray-500" : "bg-gray-200"}`}
          >
            <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform
              ${includeLegacy ? "translate-x-4" : "translate-x-1"}`}
            />
          </button>
          <span className="text-xs text-gray-400 whitespace-nowrap">
            {includeLegacy ? "Showing all history" : "Show older retired versions"}
          </span>
        </div>
      </div>

      {/* Loading skeleton */}
      {loading && (
        <div className="bg-white rounded-xl shadow-sm p-8 text-center text-gray-400 text-sm animate-pulse">
          Loading lifecycle data from endoflife.date…
        </div>
      )}

      {/* Table */}
      {!loading && (
        <div className="bg-white rounded-xl shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10">
                <tr className="bg-gray-50 border-b border-gray-200">
                  {TABLE_COLS.map(col => (
                    <th
                      key={col.key}
                      onClick={() => toggleSort(col.key)}
                      className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap cursor-pointer hover:text-gray-800 select-none"
                    >
                      {col.label}<SortIcon k={col.key} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paginated.length === 0 ? (
                  <tr>
                    <td colSpan={TABLE_COLS.length} className="text-center py-12 text-gray-400">
                      No entries match the selected filters.
                    </td>
                  </tr>
                ) : paginated.map(row => (
                  <tr key={row.id} className="border-b border-gray-100 hover:bg-gray-50/60 transition-colors">
                    <td className="px-4 py-3 font-medium text-gray-900 whitespace-nowrap">{row.service}</td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-700 whitespace-nowrap">{row.version}</td>
                    <td className="px-4 py-3"><StatusBadge status={row.status} /></td>
                    <td className="px-4 py-3 whitespace-nowrap"><DaysCell days={row.daysToEol} /></td>
                    <td className="px-4 py-3 text-xs whitespace-nowrap">
                      {row.eolDate
                        ? <span className={row.status === "EOL" || row.status === "EXPIRING_SOON" ? "text-red-600 font-semibold" : "text-gray-500"}>
                            {row.eolDate}
                          </span>
                        : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400 whitespace-nowrap">
                      {typeof row.finalEolDate === "string" && row.finalEolDate
                        ? row.finalEolDate
                        : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      {row.recommendedUpgrade
                        ? <span className="text-xs font-mono bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-full border border-emerald-100">{row.recommendedUpgrade}</span>
                        : <span className="text-gray-300 text-xs">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      <SourceBadge row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Footer */}
          <div className="px-4 py-3 border-t border-gray-100 flex items-center justify-between">
            <span className="text-xs text-gray-400">
              Data sourced from{" "}
              <a href="https://endoflife.date" target="_blank" rel="noopener noreferrer"
                className="text-blue-400 hover:underline">endoflife.date</a>
            </span>
            <Pagination page={page} totalPages={totalPages} total={filtered.length} onPage={setPage} />
          </div>
        </div>
      )}

      {/* Planning tip */}
      <div className="mt-6 bg-white rounded-2xl ring-1 ring-gray-100 shadow-sm px-6 py-5 flex items-start gap-4">
        <Lightbulb size={20} className="text-amber-500 shrink-0 mt-0.5" strokeWidth={1.75} />
        <div>
          <p className="text-sm font-semibold text-gray-800 mb-1">Planning tip</p>
          <p className="text-sm text-gray-500 leading-relaxed">
            Use this library to identify versions that need upgrade planning.
            Account and organization scans will show exactly where these versions are running in your AWS environment.
          </p>
        </div>
      </div>
    </div>
  );
}
