import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, Download, FileText, Printer, RefreshCw } from "lucide-react";
import { hasMemberSession, getMemberRole } from "../utils/workspace";
import {
  reportCsvUrl,
  useBaseReportSummary,
  useCreateReportSnapshot,
  useReportSnapshots,
  useReportSummary,
} from "../hooks/useReports";
import { AppSelect } from "../components/AppSelect";
import { getWorkspaceName, workspaceHeaders } from "../utils/workspace";

const STATUS_LABEL = {
  EOL: "EOL",
  EXPIRING_SOON: "Expiring Soon",
  EXTENDED_SUPPORT: "Ext. Support",
  SUPPORTED: "Supported",
  UNKNOWN: "Unknown",
};

const RISK_CLS = {
  LOW:      "bg-green-50 text-green-700 ring-green-200",
  MEDIUM:   "bg-amber-50 text-amber-700 ring-amber-200",
  HIGH:     "bg-orange-50 text-orange-700 ring-orange-200",
  CRITICAL: "bg-red-50 text-red-700 ring-red-200",
};

const RISK_INFO = {
  LOW: {
    title: "LOW risk",
    desc:  "No immediate lifecycle action needed.",
    body:  "This scope has no major EOL or expiring resource risk right now.",
    range: "Score range: 0 – 19",
  },
  MEDIUM: {
    title: "MEDIUM risk",
    desc:  "Review and plan upgrades.",
    body:  "Some resources may be approaching lifecycle deadlines.",
    range: "Score range: 20 – 49",
  },
  HIGH: {
    title: "HIGH risk",
    desc:  "Active lifecycle risk — prioritize remediation.",
    body:  "This scope has multiple EOL or expiring resources. Prioritize upgrade planning.",
    range: "Score range: 50 – 79",
  },
  CRITICAL: {
    title: "CRITICAL risk",
    desc:  "Urgent action required.",
    body:  "This scope has severe lifecycle exposure and should be remediated immediately.",
    range: "Score range: 80 – 100",
  },
};

// ── Scope config ───────────────────────────────────────────────────────────────

const STATIC_SCOPE_OPTIONS = [
  { value: "workspace",    label: "All Workspace" },
  { value: "account-scan", label: "Account Scan only" },
  { value: "org-scan",     label: "Organization Scan only" },
];

function buildScopeParams(scope, accountId) {
  if (scope === "account") return { scope: "account", accountId };
  if (scope === "workspace") return {};
  return { scope };
}

function scopeSourceLabel(scope, accountLabel) {
  if (scope === "account-scan") return "manually connected accounts";
  if (scope === "org-scan")     return "AWS Organization member accounts";
  if (scope === "account")      return `account-level report: ${accountLabel}`;
  return "Account Scan + Organization Scan";
}

function scopeDisplayLabel(scope, accountLabel) {
  if (scope === "account-scan") return "Account Scan only";
  if (scope === "org-scan")     return "Organization Scan only";
  if (scope === "account")      return accountLabel;
  return "All Workspace";
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function RiskBadgeWithTooltip({ level }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const info = RISK_INFO[level] ?? RISK_INFO.LOW;
  const cls  = RISK_CLS[level] ?? "bg-slate-50 text-slate-600 ring-slate-200";

  return (
    <span
      ref={ref}
      className="relative inline-flex group"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        onFocus={() => setOpen(true)}
        onBlur={(e) => { if (!ref.current?.contains(e.relatedTarget)) setOpen(false); }}
        className={`inline-flex cursor-pointer select-none rounded-full px-2.5 py-1
                    text-xs font-bold ring-1 ${cls}`}
        aria-label={`${level} risk — ${info.desc}`}
        aria-haspopup="true"
        aria-expanded={open}
      >
        {level}
      </button>

      <div
        role="tooltip"
        className={`${open ? "block" : "hidden"} group-hover:block group-focus-within:block
                    absolute right-0 top-8 z-50 w-72 rounded-xl border border-slate-200
                    bg-white p-3 text-left shadow-xl print:hidden`}
      >
        <p className="text-sm font-extrabold text-slate-900">{info.title}</p>
        <p className="mt-1 text-sm font-semibold text-slate-600 leading-snug">{info.desc}</p>
        <p className="mt-1 text-xs text-slate-500 leading-relaxed">{info.body}</p>
        <p className="mt-2 text-xs font-semibold text-slate-500">{info.range}</p>
        <p className="mt-2 border-t border-slate-100 pt-2 text-[11px] text-slate-400 leading-relaxed">
          Score = EOL × 10 + Expiring Soon × 4 + Extended Support × 3 + Unknown × 1. Max 100.
        </p>
      </div>
    </span>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <p className="text-2xl font-extrabold text-slate-900">{value ?? 0}</p>
      <p className="mt-1 text-xs font-bold uppercase tracking-wide text-slate-400">{label}</p>
    </div>
  );
}

function Bar({ value, max, color = "bg-slate-800" }) {
  const pct = max > 0 ? Math.max(4, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-2 rounded-full bg-slate-100">
      <div className={`h-2 rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function formatTrendDate(raw) {
  if (!raw) return "—";
  try {
    const d = new Date(raw);
    const date = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
    const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    return `${date}, ${time}`;
  } catch {
    return raw.slice(0, 16).replace("T", " ");
  }
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  // Derive scope + accountId from URL
  const urlScope     = searchParams.get("scope") || "workspace";
  const urlAccountId = searchParams.get("accountId") || "";

  // Build the params object for the scoped query
  const scopeParams = useMemo(
    () => buildScopeParams(urlScope, urlAccountId),
    [urlScope, urlAccountId]
  );

  // Base (workspace-level) query — always fetched; used to populate dropdown options
  const { data: baseData } = useBaseReportSummary();

  // Scoped query — re-fetches when scope changes
  const { data, isLoading, isError } = useReportSummary(scopeParams);

  const { data: snapshots = [] } = useReportSnapshots();
  const createSnapshot = useCreateReportSnapshot();

  const _memberSession = hasMemberSession();
  const canCreateSnapshot = !_memberSession || ["EDITOR", "ADMIN"].includes(getMemberRole());
  const wsName  = getWorkspaceName();
  const genTime = new Date().toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", timeZoneName: "short",
  });

  // Build dropdown options: 3 static + per-account from base workspace data
  const scopeOptions = useMemo(() => {
    const baseAccounts = baseData?.byAccount ?? [];
    const accountOptions = baseAccounts.map(a => ({
      value: `account::${a.accountId}`,
      label: a.accountName || a.accountId,
    }));
    return [...STATIC_SCOPE_OPTIONS, ...accountOptions];
  }, [baseData]);

  // Current dropdown value
  const dropdownValue = urlScope === "account" ? `account::${urlAccountId}` : urlScope;

  function handleScopeChange(val) {
    if (val.startsWith("account::")) {
      const acctId = val.replace("account::", "");
      setSearchParams({ scope: "account", accountId: acctId }, { replace: true });
    } else if (val === "workspace") {
      setSearchParams({}, { replace: true });
    } else {
      setSearchParams({ scope: val }, { replace: true });
    }
  }

  // Selected account name label (for subtitle and CSV filename)
  const selectedAccountLabel = useMemo(() => {
    if (urlScope !== "account" || !urlAccountId) return "";
    const acc = (baseData?.byAccount ?? []).find(a => a.accountId === urlAccountId);
    return acc?.accountName || urlAccountId;
  }, [urlScope, urlAccountId, baseData]);

  const summary   = data?.summary ?? {};
  const topRisks  = data?.topRisks ?? [];
  const byService = data?.byService ?? [];
  const byAccount = data?.byAccount ?? [];

  const topServiceByAccount = useMemo(() => {
    const svcCounts = {};
    for (const r of topRisks) {
      const id = r.accountId;
      if (!id) continue;
      if (!svcCounts[id]) svcCounts[id] = {};
      svcCounts[id][r.service] = (svcCounts[id][r.service] || 0) + 1;
    }
    const result = {};
    for (const [id, svcs] of Object.entries(svcCounts)) {
      result[id] = Object.entries(svcs).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
    }
    return result;
  }, [topRisks]);

  const trend = data?.trend ?? snapshots.slice(0, 12).map(s => ({
    id: s.id, createdAt: s.createdAt, period: s.period,
    eol:          s.summary?.eol          ?? 0,
    expiringSoon: s.summary?.expiringSoon  ?? 0,
    riskScore:    s.summary?.riskScore     ?? 0,
  }));
  const maxTrend = Math.max(1, ...trend.map(t => t.riskScore ?? 0));

  async function downloadCsv() {
    const response = await fetch(reportCsvUrl(scopeParams), { headers: workspaceHeaders() });
    if (!response.ok) throw new Error("CSV export failed");
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match?.[1] || "aws-eol-risk-report.csv";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  const sourceLabel  = scopeSourceLabel(urlScope, selectedAccountLabel);
  const displayLabel = scopeDisplayLabel(urlScope, selectedAccountLabel);
  const hasNoData    = !isLoading && !isError && summary.total === 0;

  if (isLoading) {
    return (
      <div className="mx-auto max-w-7xl px-4 sm:px-6 py-6 sm:py-8 animate-pulse space-y-4">
        <div className="h-3 w-40 rounded bg-slate-200" />
        <div className="h-9 w-64 rounded bg-slate-200" />
        <div className="h-4 w-96 rounded bg-slate-100" />
        <div className="h-32 rounded-2xl bg-white shadow-sm ring-1 ring-slate-100" />
        <div className="h-64 rounded-2xl bg-white shadow-sm ring-1 ring-slate-100" />
      </div>
    );
  }
  if (isError) {
    return (
      <div className="mx-auto max-w-7xl px-4 sm:px-6 py-6 sm:py-8">
        <div className="rounded-2xl border border-red-100 bg-white px-6 py-10 text-center">
          <p className="text-base font-bold text-slate-900 mb-1">Unable to load reports</p>
          <p className="text-sm text-slate-500">Check backend connection and try again.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="print-container mx-auto max-w-7xl px-4 sm:px-6 py-6 sm:py-8 print:px-6 print:py-8 print:bg-white">
      {/* Print CSS */}
      <style>{`
        @media print {
          /* ── Hide layout chrome ── */
          aside, nav, header,
          .no-print,
          [data-sidebar],
          [class*="sidebar"] { display: none !important; }
          /* Mobile sticky top-bar */
          main > div:first-child { display: none !important; }

          /* ── Layout reset ── */
          @page { margin: 14mm 12mm; }
          html, body { overflow: visible !important; background: white !important; margin: 0 !important; }
          main { overflow: visible !important; }

          /* ── Report container ── */
          .print-container {
            max-width: none !important;
            width: 100% !important;
            padding: 0 !important;
            margin: 0 !important;
          }

          /* ── Table: no scroll, fixed layout, wrap cells ── */
          .overflow-x-auto { overflow: visible !important; }
          table {
            min-width: 0 !important;
            width: 100% !important;
            table-layout: fixed !important;
            font-size: 10px !important;
            border-collapse: collapse !important;
          }
          th, td {
            word-break: break-word !important;
            white-space: normal !important;
            overflow: visible !important;
            padding: 4px 5px !important;
          }
          .truncate {
            overflow: visible !important;
            white-space: normal !important;
            text-overflow: clip !important;
            max-width: none !important;
          }

          /* ── 2-col grid → 1-col in print ── */
          .print-grid-1 { grid-template-columns: 1fr !important; }

          /* ── Page breaks ── */
          .print-break { break-before: page !important; page-break-before: always !important; }
          .print-avoid-break { break-inside: avoid !important; page-break-inside: avoid !important; }

          /* ── Colours and shadows ── */
          * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
          .shadow-sm, .shadow { box-shadow: none !important; }
        }
      `}</style>

      {/* ── Page header ── */}
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-1 text-xs font-bold uppercase tracking-[0.24em] text-indigo-500">
            Compliance Reporting
          </p>
          <h1 className="text-3xl font-extrabold text-slate-900">EOL Risk Reports</h1>
          <p className="mt-1 text-sm text-slate-500">
            Workspace-scoped evidence for lifecycle risk reviews.
          </p>
          {/* Report metadata — shown in print too */}
          <p className="mt-1.5 text-xs text-slate-400">
            Workspace: <span className="font-semibold text-slate-600">{wsName}</span>
            {" · "}Generated: {genTime}
            {" · "}Scope: <span className="font-semibold text-slate-600">{displayLabel}</span>
            {" · "}Source: {sourceLabel}
          </p>
        </div>
        <div className="no-print flex flex-wrap gap-2 pt-1">
          {canCreateSnapshot && (
            <div className="relative group">
              <button
                onClick={() => createSnapshot.mutate()}
                disabled={createSnapshot.isPending}
                className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-bold text-white disabled:opacity-60 hover:bg-slate-700 transition-colors"
              >
                <RefreshCw size={14} className={createSnapshot.isPending ? "animate-spin" : ""} />
                Save Risk Report
              </button>
              <div className="pointer-events-none absolute right-0 top-11 z-50 hidden w-72 rounded-xl border border-slate-200 bg-white p-3 text-left shadow-xl group-hover:block">
                <p className="text-xs font-bold text-slate-800">Save a point-in-time EOL risk report</p>
                <p className="mt-1 text-xs text-slate-500 leading-relaxed">
                  Captures current workspace resource counts and risk score for trend comparison.
                  Always saved at workspace scope.
                </p>
              </div>
            </div>
          )}
          <button
            onClick={downloadCsv}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-700 hover:bg-slate-50 transition-colors"
          >
            <Download size={14} /> Download CSV
          </button>
          <button
            onClick={() => window.print()}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-700 hover:bg-slate-50 transition-colors"
          >
            <Printer size={14} /> Print / Save PDF
          </button>
        </div>
      </div>

      {/* ── Scope selector ── */}
      <div className="no-print mb-5 flex items-center gap-3">
        <span className="text-xs font-bold uppercase tracking-wide text-slate-400">
          Report Scope
        </span>
        <AppSelect
          size="md"
          value={dropdownValue}
          options={scopeOptions}
          onChange={handleScopeChange}
        />
      </div>

      {/* ── Empty state for filtered scope ── */}
      {hasNoData ? (
        <div className="rounded-2xl border border-slate-100 bg-white px-6 py-12 text-center">
          <p className="text-base font-bold text-slate-800 mb-1">
            No scanned resources found for this report scope
          </p>
          <p className="text-sm text-slate-500">
            Try selecting a different scope, or run a scan first.
          </p>
        </div>
      ) : (
        <>
          {/* ── Executive Summary ── */}
          <section className="mb-5 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText size={16} className="text-slate-400" />
                <h2 className="text-sm font-extrabold uppercase tracking-wide text-slate-500">
                  Executive Summary
                </h2>
              </div>
              <div className="flex items-center gap-3">
                <div className="text-right">
                  <p className="text-xs font-semibold text-slate-400 mb-0.5">Risk Score</p>
                  <p className="text-3xl font-extrabold text-slate-900 leading-none">
                    {summary.riskScore ?? 0}
                    <span className="text-base font-semibold text-slate-300 ml-1">/ 100</span>
                  </p>
                </div>
                <RiskBadgeWithTooltip level={summary.riskLevel ?? "LOW"} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
              <Stat label="Total"         value={summary.total}           />
              <Stat label="EOL"           value={summary.eol}             />
              <Stat label="Expiring Soon" value={summary.expiringSoon}    />
              <Stat label="Ext. Support"  value={summary.extendedSupport} />
              <Stat label="Supported"     value={summary.supported}       />
              <Stat label="Unknown"       value={summary.unknown}         />
            </div>
          </section>

          {/* ── Top Risks ── */}
          <section className="print-break mb-5 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
            <h2 className="mb-3 text-sm font-extrabold uppercase tracking-wide text-slate-500">
              Top Risks
            </h2>
            {topRisks.length === 0 ? (
              <p className="text-sm text-slate-500 py-4 text-center">
                No EOL or expiring-soon resources found in the current inventory.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[900px] text-sm">
                  <colgroup>
                    <col style={{ width: "18%" }} />
                    <col style={{ width: "9%"  }} />
                    <col style={{ width: "11%" }} />
                    <col style={{ width: "10%" }} />
                    <col style={{ width: "9%"  }} />
                    <col style={{ width: "10%" }} />
                    <col style={{ width: "10%" }} />
                    <col style={{ width: "23%" }} />
                  </colgroup>
                  <thead className="text-xs uppercase text-slate-400">
                    <tr>
                      <th className="py-2 text-left">Resource</th>
                      <th className="text-left">Service</th>
                      <th className="text-left">Account</th>
                      <th className="text-left">Region</th>
                      <th className="text-left">Version</th>
                      <th className="text-left">Status</th>
                      <th className="text-left">EOL Date</th>
                      <th className="text-left">Recommendation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topRisks.map(r => {
                      const rec = r.recommendation || "Review lifecycle risk.";
                      return (
                        <tr key={r.resourceId} className="print-avoid-break border-t border-slate-100 hover:bg-slate-50">
                          <td className="py-2 font-medium text-slate-900">{r.resourceName || r.resourceId}</td>
                          <td>{r.service}</td>
                          <td>{r.accountName}</td>
                          <td className="font-mono text-xs">{r.region}</td>
                          <td className="font-mono text-xs">{r.version}</td>
                          <td>{STATUS_LABEL[r.status] ?? r.status}</td>
                          <td className="tabular-nums">{r.eolDate || "—"}</td>
                          <td className="max-w-[260px] truncate text-slate-500" title={rec}>{rec}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* ── Risk by Service / Account ── */}
          <div className="print-break print-grid-1 mb-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
            <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <h2 className="mb-3 text-sm font-extrabold uppercase tracking-wide text-slate-500">
                Risk by Service
              </h2>
              {byService.length === 0 ? (
                <p className="text-sm text-slate-400 py-2">No service data available.</p>
              ) : (
                <div className="space-y-3">
                  {byService.map(s => <BreakdownRow key={s.service} label={s.service} item={s} />)}
                </div>
              )}
            </section>
            <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <h2 className="mb-3 text-sm font-extrabold uppercase tracking-wide text-slate-500">
                Risk by Account
              </h2>
              {byAccount.length === 0 ? (
                <p className="text-sm text-slate-400 py-2">No account data available.</p>
              ) : (
                <div className="space-y-3">
                  {byAccount.map(a => (
                    <AccountCard
                      key={a.accountId}
                      item={a}
                      topService={topServiceByAccount[a.accountId] ?? null}
                    />
                  ))}
                </div>
              )}
            </section>
          </div>

          {/* ── Risk Score History ── */}
          <section className="print-break mb-5 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
            <div className="mb-3 flex items-baseline justify-between gap-4">
              <h2 className="text-sm font-extrabold uppercase tracking-wide text-slate-500">
                Risk Score History
              </h2>
              <span className="text-xs text-slate-400">
                Score = EOL ×10 + Expiring ×4 + Ext.Support ×3 + Unknown ×1 · Max 100
              </span>
            </div>
            {trend.length === 0 ? (
              <p className="text-sm text-slate-500">
                No saved reports yet. Click <span className="font-semibold">Save Risk Report</span> to start tracking EOL risk over time.
              </p>
            ) : (
              <div className="space-y-3">
                {trend.slice(0, 12).map(t => (
                  <div key={t.id} className="grid grid-cols-[200px_1fr_auto] items-center gap-3 text-sm">
                    <span className="text-slate-500 tabular-nums text-xs">
                      {formatTrendDate(t.createdAt || t.period)}
                    </span>
                    <Bar value={t.riskScore ?? 0} max={maxTrend} color="bg-indigo-500" />
                    <span className="text-right font-bold text-slate-800 tabular-nums whitespace-nowrap">
                      {t.riskScore ?? 0}
                      <span className="ml-0.5 text-xs font-normal text-slate-400">/ 100</span>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* ── Compliance Mapping ── */}
          <section className="print-break rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
            <h2 className="mb-3 text-sm font-extrabold uppercase tracking-wide text-slate-500">
              Compliance Mapping MVP
            </h2>
            <p className="mb-4 text-sm text-slate-600">
              EOL and unsupported software may impact security maintenance, vulnerability management,
              and change management controls. Use this report as supporting evidence for lifecycle
              risk reviews. Final compliance interpretation depends on your control environment.
            </p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
              {[
                "Vulnerability Management",
                "Patch Management",
                "Asset Inventory",
                "Change Management",
                "Risk Acceptance",
              ].map(x => (
                <div key={x}
                  className="rounded-xl bg-slate-50 p-3 text-xs font-bold text-slate-600 ring-1 ring-slate-100">
                  {x}
                  <p className="mt-1 font-medium text-slate-400">SOC 2 · ISO 27001 · CIS Controls</p>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function BreakdownRow({ label, item }) {
  return (
    <div className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-100">
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="truncate text-sm font-bold text-slate-900">{label}</p>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-slate-400 font-medium">
            Risk Score <span className="font-bold text-slate-800">{item.riskScore}</span>
            <span className="text-slate-300"> / 100</span>
          </span>
          <RiskBadgeWithTooltip level={item.riskLevel} />
        </div>
      </div>
      <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 text-xs text-slate-500">
        <span>Total {item.total}</span>
        <span>EOL {item.eol}</span>
        <span>Exp {item.expiringSoon}</span>
        <span>Supp {item.supported}</span>
        <span>Unk {item.unknown}</span>
      </div>
    </div>
  );
}

// ── Account-specific helpers ───────────────────────────────────────────────────

function _getReason(item) {
  const parts = [];
  if (item.eol > 0)             parts.push(`${item.eol} EOL`);
  if (item.expiringSoon > 0)    parts.push(`${item.expiringSoon} Expiring Soon`);
  if (item.extendedSupport > 0) parts.push(`${item.extendedSupport} Ext. Support`);
  if (item.unknown > 0)         parts.push(`${item.unknown} Unknown`);
  return parts.length > 0 ? parts.join(", ") : null;
}

function _getAction(item, topService) {
  const svc    = topService ? ` ${topService}` : "";
  const level  = item.riskLevel ?? "LOW";
  const urgent = level === "CRITICAL" || level === "HIGH";
  if (item.eol > 0)
    return `${urgent ? "Prioritize this account. " : ""}Upgrade ${item.eol} EOL${svc} resource${item.eol > 1 ? "s" : ""} immediately.`;
  if (item.expiringSoon > 0)
    return `${urgent ? "Plan now. " : "Monitor. "}Schedule${svc} upgrade for ${item.expiringSoon} expiring resource${item.expiringSoon > 1 ? "s" : ""} before support ends.`;
  if (item.extendedSupport > 0)
    return `Monitor. ${item.extendedSupport} resource${item.extendedSupport > 1 ? "s" : ""} in extended support — budget for upgrade.`;
  return "Monitor. No immediate lifecycle action required.";
}

const RISK_BAR = {
  CRITICAL: "bg-red-500",
  HIGH:     "bg-orange-400",
  MEDIUM:   "bg-amber-400",
  LOW:      "bg-green-500",
};

function AccountCard({ item, topService }) {
  const navigate   = useNavigate();
  const reason     = _getReason(item);
  const action     = _getAction(item, topService);
  const barColor   = RISK_BAR[item.riskLevel] ?? "bg-slate-400";
  const scorePct   = Math.min(100, item.riskScore ?? 0);

  return (
    <div className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-100">
      {/* Header row */}
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-slate-900 leading-snug">
            {item.accountName}
          </p>
          {item.scanSource === "ORG_SCAN" && (
            <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide bg-violet-50 text-violet-600 ring-1 ring-violet-200">
              Org Scan
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-slate-400 font-medium whitespace-nowrap">
            Risk Score{" "}
            <span className="font-bold text-slate-800">{item.riskScore}</span>
            <span className="text-slate-300"> / 100</span>
          </span>
          <RiskBadgeWithTooltip level={item.riskLevel} />
        </div>
      </div>

      {/* Score bar */}
      <div className="mb-2.5 h-1.5 rounded-full bg-slate-200">
        <div className={`h-1.5 rounded-full ${barColor}`} style={{ width: `${scorePct}%` }} />
      </div>

      {/* Count pills */}
      <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
        <span>Total {item.total}</span>
        {item.eol > 0 && (
          <span className="font-semibold text-red-600">EOL {item.eol}</span>
        )}
        {item.expiringSoon > 0 && (
          <span className="font-semibold text-amber-600">Exp {item.expiringSoon}</span>
        )}
        {item.extendedSupport > 0 && (
          <span className="text-orange-500">Ext. Support {item.extendedSupport}</span>
        )}
        <span>Supp {item.supported}</span>
        {item.unknown > 0 && <span>Unk {item.unknown}</span>}
      </div>

      {/* Reason + top service */}
      {reason && (
        <p className="mb-1 text-xs text-slate-500 leading-snug">
          <span className="font-semibold text-slate-700">Risk: </span>{reason}
          {topService && (
            <span className="ml-1 text-slate-400">· Top service: <span className="font-semibold text-slate-600">{topService}</span></span>
          )}
        </p>
      )}

      {/* Action */}
      <p className="mb-2.5 text-xs text-slate-500 leading-snug">
        <span className="font-semibold text-slate-700">Action: </span>{action}
      </p>

      {/* View link — hidden in print */}
      <button
        type="button"
        onClick={() => navigate(`/account-results/${item.accountId}`, {
          state: { accountName: item.accountName, scanSource: item.scanSource, from: "reports" },
        })}
        className="no-print inline-flex items-center gap-1 rounded-lg border border-slate-200
                   bg-white px-2.5 py-1 text-xs font-bold text-slate-700
                   hover:bg-indigo-50 hover:border-indigo-200 hover:text-indigo-700
                   transition-colors"
      >
        View Account Risks <ArrowRight size={11} />
      </button>
    </div>
  );
}
