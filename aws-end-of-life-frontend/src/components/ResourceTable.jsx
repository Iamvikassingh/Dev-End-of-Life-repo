import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { StatusBadge } from "./StatusBadge";
import { EOLTimeline } from "./EOLTimeline";
import { serviceLabel } from "../utils/classify";

const PER_PAGE = 10;
const STATUS_PRIORITY = {
  EOL: 0, EXPIRING_SOON: 1, EXTENDED_SUPPORT: 2, SUPPORTED: 3,
  UNKNOWN: 4, NEEDS_INSPECTION: 5, LIFECYCLE_NOT_TRACKED: 6,
};

const NON_LIFECYCLE = new Set(["NEEDS_INSPECTION", "LIFECYCLE_NOT_TRACKED"]);

const COLS = [
  { key: "resource_name", label: "Resource",  sortable: true,  width: "w-[175px]", sticky: "left",  stickyOffset: "left-0"       },
  { key: "account_id",    label: "Account",   sortable: false, width: "w-[155px]", sticky: "left",  stickyOffset: "left-[175px]", stickyEdge: true },
  { key: "service_type",  label: "Service",   sortable: true,  width: "w-[175px]" },
  { key: "region",        label: "Region",    sortable: true,  width: "w-[115px]" },
  { key: "version",       label: "Version",   sortable: false, width: "w-[135px]" },
  { key: "eol_status",    label: "Status",    sortable: true,  width: "w-[195px]" },
  { key: "days_to_eol",   label: "Risk Info", sortable: true,  width: "w-[225px]" },
  { key: "eol_date",      label: "EOL Date",  sortable: true,  width: "w-[115px]" },
  { key: "_action",       label: "Action",    sortable: false, width: "w-[100px]", sticky: "right", stickyOffset: "right-0"      },
];

function AccountCell({ accountId, accountMap }) {
  if (!accountId) return <span className="text-slate-400 text-xs">—</span>;
  const info = accountMap?.[accountId];
  if (!info) return <span className="text-slate-500 text-xs font-mono truncate block">{accountId}</span>;
  const raw = info.awsId ?? "";
  const masked = raw.length === 12 ? `${raw.slice(0, 4)}…${raw.slice(-4)}` : raw;
  return (
    <div className="min-w-0">
      <p className="text-sm text-slate-700 font-medium truncate">{info.name}</p>
      {masked && <p className="text-xs text-slate-400 font-mono">{masked}</p>}
    </div>
  );
}

function applyFilters(items, filters) {
  let out = items;
  if (filters.search) {
    const q = filters.search.toLowerCase();
    out = out.filter(i =>
      (i.resource_name ?? "").toLowerCase().includes(q) ||
      (i.resource_id   ?? "").toLowerCase().includes(q) ||
      (i.service_type  ?? "").toLowerCase().includes(q)
    );
  }
  if (filters.service) out = out.filter(i => (i.service_type ?? "").toLowerCase().includes(filters.service.toLowerCase()));
  if (filters.status)  out = out.filter(i => i.eol_status === filters.status);
  if (filters.region)  out = out.filter(i => (i.region ?? "").includes(filters.region));
  return out;
}

function urgencySort(a, b) {
  const pa = STATUS_PRIORITY[a.eol_status] ?? 4;
  const pb = STATUS_PRIORITY[b.eol_status] ?? 4;
  if (pa !== pb) return pa - pb;
  const da = a.days_to_eol === null ? 99999 : Number(a.days_to_eol);
  const db = b.days_to_eol === null ? 99999 : Number(b.days_to_eol);
  return da - db;
}

function SkeletonTable() {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="overflow-x-auto scrollbar-thin">
        <table className="min-w-[1390px] w-full table-fixed text-sm border-collapse">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50">
              {COLS.map(col => (
                <th key={col.key}
                  className={`${col.width} px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500
                    ${col.sticky === "left"  ? `sticky ${col.stickyOffset ?? "left-0"} z-20 bg-slate-50` : ""}
                    ${col.sticky === "right" ? `sticky ${col.stickyOffset ?? "right-0"} z-20 bg-slate-50` : ""}
                    ${col.stickyEdge ? "border-r border-slate-200" : ""}`}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...Array(8)].map((_, row) => (
              <tr key={row} className="border-b border-slate-100">
                {COLS.map((col, cell) => (
                  <td key={col.key}
                    className={`${col.width} px-4 py-4
                      ${col.sticky === "left"  ? `sticky ${col.stickyOffset ?? "left-0"} z-10 bg-white` : ""}
                      ${col.sticky === "right" ? `sticky ${col.stickyOffset ?? "right-0"} z-10 bg-white` : ""}
                      ${col.stickyEdge ? "border-r border-slate-100" : ""}`}>
                    <div className={`h-4 animate-pulse rounded bg-slate-100 ${cell === 5 ? "w-full" : cell === 0 ? "w-40" : "w-20"}`} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-slate-100 px-4 py-3">
        <div className="h-3 w-40 animate-pulse rounded bg-slate-100" />
      </div>
    </div>
  );
}

function Pagination({ page, totalPages, total, perPage, onChange }) {
  if (totalPages <= 1) return null;
  const start = (page - 1) * perPage + 1;
  const end   = Math.min(page * perPage, total);
  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => onChange(page - 1)}
        disabled={page === 1}
        className="px-2 py-1 rounded text-xs border border-gray-200 disabled:opacity-40 hover:bg-gray-50"
      >
        ‹
      </button>
      {[...Array(totalPages)].map((_, i) => {
        const p = i + 1;
        // Show first, last, current ±1, and ellipses
        if (p !== 1 && p !== totalPages && Math.abs(p - page) > 1) {
          if (p === 2 || p === totalPages - 1) return <span key={p} className="px-1 text-xs text-gray-400">…</span>;
          return null;
        }
        return (
          <button
            key={p}
            onClick={() => onChange(p)}
            className={`px-2.5 py-1 rounded text-xs border transition-colors ${
              p === page
                ? "bg-gray-900 text-white border-gray-900"
                : "border-gray-200 hover:bg-gray-50 text-gray-600"
            }`}
          >
            {p}
          </button>
        );
      })}
      <button
        onClick={() => onChange(page + 1)}
        disabled={page === totalPages}
        className="px-2 py-1 rounded text-xs border border-gray-200 disabled:opacity-40 hover:bg-gray-50"
      >
        ›
      </button>
    </div>
  );
}

export function ResourceTable({
  items = [],
  filters = {},
  onRowClick,
  onActionClick,
  actionLabel = "View →",
  loading,
  onClearFilters,
  hasActiveFilters,
  accountMap = {},
}) {
  const navigate  = useNavigate();
  const [sort, setSort] = useState({ key: "_urgency", dir: "asc" });
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => applyFilters(items, filters), [items, filters]);

  const sorted = useMemo(() => {
    if (sort.key === "_urgency") return [...filtered].sort(urgencySort);
    return [...filtered].sort((a, b) => {
      let av = a[sort.key] ?? "";
      let bv = b[sort.key] ?? "";
      if (sort.key === "days_to_eol") {
        av = av === null ? 99999 : Number(av);
        bv = bv === null ? 99999 : Number(bv);
      }
      if (av < bv) return sort.dir === "asc" ? -1 : 1;
      if (av > bv) return sort.dir === "asc" ? 1 : -1;
      return 0;
    });
  }, [filtered, sort]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / PER_PAGE));
  const paginated  = useMemo(() => sorted.slice((page - 1) * PER_PAGE, page * PER_PAGE), [sorted, page]);

  // Reset to page 1 whenever the filtered set changes
  const filterKey = JSON.stringify(filters) + sort.key + sort.dir;
  useEffect(() => setPage(1), [filterKey]);

  function toggleSort(key) {
    if (key === "_action") return;
    setSort(s => s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" });
  }

  function SortIcon({ col }) {
    if (!col.sortable || col.key === "_action") return null;
    if (sort.key !== col.key) return <span className="text-gray-300 ml-1">↕</span>;
    return <span className="ml-1" style={{ color: "#2A85D8" }}>{sort.dir === "asc" ? "↑" : "↓"}</span>;
  }

  if (loading) return <SkeletonTable />;

  const start = (page - 1) * PER_PAGE + 1;
  const end   = Math.min(page * PER_PAGE, sorted.length);

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="overflow-x-auto scrollbar-thin">
        <table className="min-w-[1390px] w-full table-fixed text-sm border-collapse">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50">
              {COLS.map(col => (
                <th
                  key={col.key}
                  onClick={col.sortable ? () => toggleSort(col.key) : undefined}
                  className={`${col.width} px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 whitespace-nowrap
                    ${col.sortable ? "cursor-pointer select-none hover:text-slate-800" : ""}
                    ${col.sticky === "left"  ? `sticky ${col.stickyOffset ?? "left-0"} z-20 bg-slate-50` : ""}
                    ${col.sticky === "right" ? `sticky ${col.stickyOffset ?? "right-0"} z-20 bg-slate-50` : ""}
                    ${col.stickyEdge ? "border-r border-slate-200" : ""}`}
                >
                  {col.label}<SortIcon col={col} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={COLS.length} className="px-6 py-14 text-center">
                  <p className="text-sm font-semibold text-slate-700">
                    {hasActiveFilters ? "No resources match your filters." : "No scan data yet"}
                  </p>
                  <p className="mt-1 text-sm text-slate-500">
                    {hasActiveFilters ? "Try clearing filters or broadening your search." : "Run an account scan to populate your inventory."}
                  </p>
                  {hasActiveFilters && onClearFilters && (
                    <button
                      type="button"
                      onClick={onClearFilters}
                      className="mt-4 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 transition-colors hover:bg-slate-50"
                    >
                      Clear filters
                    </button>
                  )}
                </td>
              </tr>
            ) : paginated.map(item => (
              <tr
                key={`${item.resource_id}#${item.service_type}`}
                onClick={() => onRowClick?.(item)}
                className="group border-b border-slate-100 cursor-pointer transition-colors hover:bg-blue-50/30"
              >
                <td className="sticky left-0 z-10 w-[175px] bg-white px-4 py-3 font-medium text-slate-900 transition-colors group-hover:bg-blue-50/30" title={String(item.resource_name || item.resource_id)}>
                  <span className="block truncate">{item.resource_name || item.resource_id}</span>
                </td>
                <td className="sticky left-[175px] z-10 w-[155px] border-r border-slate-100 bg-white px-4 py-3 transition-colors group-hover:bg-blue-50/30"
                    title={accountMap[item.account_id]?.name ?? item.account_id ?? ""}>
                  <AccountCell accountId={item.account_id} accountMap={accountMap} />
                </td>
                <td className="w-[175px] px-4 py-3 text-slate-600" title={serviceLabel(item.service_type)}>
                  <span className="block truncate">{serviceLabel(item.service_type)}</span>
                </td>
                <td className="w-[115px] px-4 py-3 text-slate-500 font-mono text-xs whitespace-nowrap">{item.region || "—"}</td>
                <td className="w-[135px] px-4 py-3 font-mono text-xs text-slate-600" title={item.version || ""}>
                  <span className="block truncate">{item.version || "—"}</span>
                </td>
                <td className="w-[195px] px-4 py-3"><StatusBadge status={item.eol_status} /></td>
                <td className="w-[225px] px-4 py-3 text-slate-700">
                  <EOLTimeline daysToEol={item.days_to_eol} eolDate={item.eol_date} status={item.eol_status}
                    eolLabel={item.service_type === "EC2" ? "Lifecycle end" : "EOL"} />
                </td>
                <td className="w-[115px] px-4 py-3 text-slate-500 text-xs whitespace-nowrap">
                  {NON_LIFECYCLE.has(item.eol_status) ? "—" : (item.eol_date ?? "—")}
                </td>
                <td className="sticky right-0 z-10 w-[100px] bg-white px-4 py-3 transition-colors group-hover:bg-blue-50/30 border-l border-slate-100" onClick={e => e.stopPropagation()}>
                  <button
                    onClick={() => onActionClick
                      ? onActionClick(item)
                      : navigate(`/resource/${encodeURIComponent(item.resource_id)}`)}
                    className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-500
                               transition-colors hover:border-blue-300 hover:text-blue-600 whitespace-nowrap"
                  >
                    {actionLabel}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer — count + pagination */}
      <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3">
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-400">
            {sorted.length === 0
              ? "0 resources"
              : `Showing ${start}–${end} of ${sorted.length} resources`}
          </span>
          {sort.key !== "_urgency" && (
            <button
              onClick={() => setSort({ key: "_urgency", dir: "asc" })}
              className="text-xs text-blue-400 hover:underline"
            >
              Reset sort
            </button>
          )}
        </div>
        <Pagination
          page={page}
          totalPages={totalPages}
          total={sorted.length}
          perPage={PER_PAGE}
          onChange={setPage}
        />
      </div>
    </div>
  );
}
