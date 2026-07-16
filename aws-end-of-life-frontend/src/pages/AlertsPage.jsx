import React, { useMemo, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Bell, Info, AlertCircle, Check, BellOff, RotateCcw, X, ExternalLink, Clock } from "lucide-react";
import { useAlerts, useAlertAction } from "../hooks/useAlerts";
import { HAS_API, API_BASE_URL } from "../utils/config";
import { hasMemberSession, getMemberRole, getWorkspaceId, workspaceHeaders } from "../utils/workspace";
import { StatusBadge } from "../components/StatusBadge";
import { serviceLabel } from "../utils/classify";
import { formatDistanceToNow } from "date-fns";
import { fetchAccountsFromServer } from "../utils/connectedAccounts";
import { ModernSelect } from "../components/ModernSelect";

const PER_PAGE = 20;

// Format snoozedUntil as "13 Jun 2026, 12:55 UTC"
function fmtSnoozeUntil(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
      timeZone: "UTC", timeZoneName: "short",
    });
  } catch { return iso; }
}

// ── Severity badge ────────────────────────────────────────────────────────────

function SeverityBadge({ severity }) {
  const cfg = {
    HIGH:   "bg-red-50 text-red-700 ring-1 ring-red-200",
    MEDIUM: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
    LOW:    "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
  }[severity] ?? "bg-slate-50 text-slate-500";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide ${cfg}`}>
      {severity}
    </span>
  );
}

// ── Source badge ──────────────────────────────────────────────────────────────

function SourceBadge({ scanSource }) {
  if (scanSource === "ORG_SCAN") {
    return (
      <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold bg-violet-50 text-violet-700 ring-1 ring-violet-200 whitespace-nowrap">
        Org Scan
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold bg-sky-50 text-sky-700 ring-1 ring-sky-200 whitespace-nowrap">
      Account Scan
    </span>
  );
}

// ── Summary cards ─────────────────────────────────────────────────────────────

const CARD_META = [
  { key: "total",        label: "Total",        bg: "bg-slate-50",  text: "text-slate-800"  },
  { key: "high",         label: "High",         bg: "bg-red-50",    text: "text-red-700"    },
  { key: "medium",       label: "Medium",       bg: "bg-amber-50",  text: "text-amber-700"  },
  { key: "active",       label: "Active",       bg: "bg-indigo-50", text: "text-indigo-700" },
  { key: "acknowledged", label: "Acknowledged", bg: "bg-green-50",  text: "text-green-700"  },
  { key: "snoozed",      label: "Snoozed",      bg: "bg-purple-50", text: "text-purple-700" },
];

function SummaryCards({ counts }) {
  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-6">
      {CARD_META.map(({ key, label, bg, text }) => (
        <div key={key} className={`rounded-xl ${bg} px-4 py-3`}>
          <p className={`text-xl font-extrabold ${text}`}>{counts?.[key] ?? 0}</p>
          <p className={`text-xs font-semibold uppercase tracking-wide mt-0.5 ${text} opacity-70`}>{label}</p>
        </div>
      ))}
    </div>
  );
}

// ── Snooze dialog ─────────────────────────────────────────────────────────────

const SNOOZE_OPTIONS = [
  { label: "1 day",   hours: 24  },
  { label: "3 days",  hours: 72  },
  { label: "7 days",  hours: 168 },
  { label: "30 days", hours: 720 },
];

function SnoozeDialog({ alertId, onClose, onSnooze }) {
  const [selected, setSelected] = useState(SNOOZE_OPTIONS[1]);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState("");

  async function handleSnooze() {
    setLoading(true);
    setError("");
    const until = new Date(Date.now() + selected.hours * 3_600_000).toISOString();
    const result = await onSnooze(alertId, until);
    setLoading(false);
    if (result?.ok === false) {
      setError(result.error || "Could not snooze alert. Please try again.");
      return;
    }
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-bold text-slate-900">Snooze alert</h3>
            <p className="text-xs text-slate-500 mt-0.5">This alert will be hidden from Active Alerts and return automatically after the selected period.</p>
          </div>
          <button onClick={onClose} disabled={loading} className="text-slate-400 hover:text-slate-700 rounded-lg p-1 hover:bg-slate-100 transition-colors">
            <X size={15} strokeWidth={2} />
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {SNOOZE_OPTIONS.map(opt => (
            <button
              key={opt.hours}
              onClick={() => { setSelected(opt); setError(""); }}
              disabled={loading}
              className={`rounded-xl border py-2.5 text-sm font-semibold transition-all disabled:opacity-50 ${
                selected.hours === opt.hours
                  ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                  : "border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        {error && (
          <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} disabled={loading}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button onClick={handleSnooze} disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-60 transition-colors">
            <BellOff size={13} strokeWidth={2} />
            {loading ? "Snoozing…" : `Snooze for ${selected.label}`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Alert detail drawer ───────────────────────────────────────────────────────

const STATUS_BAR = {
  HIGH:   "bg-red-500",
  MEDIUM: "bg-amber-400",
  LOW:    "bg-blue-400",
};

function fmtLastSeen(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
      timeZoneName: "short",
    });
  } catch { return iso; }
}

function DrawerRow({ label, children }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5 border-b border-slate-100 last:border-0">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-400 shrink-0 w-28">{label}</span>
      <span className="text-xs text-right text-slate-700 font-medium break-all">{children}</span>
    </div>
  );
}

function AlertDrawer({ alert, onClose, accountName }) {
  const navigate = useNavigate();
  if (!alert) return null;

  const barColor = STATUS_BAR[alert.severity] ?? "bg-slate-300";
  const isStale  = alert.status === "RESOLVED" && !!alert.resolvedReason;
  const scanLabel = alert.scanSource === "ORG_SCAN" ? "Organization Scan" : "Account Scan";
  const acctDisplay = accountName || (alert.accountId ? `****${String(alert.accountId).slice(-4)}` : "—");

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/20 backdrop-blur-[1px] z-30" onClick={onClose} />

      {/* Panel */}
      <div className="fixed right-0 top-0 h-full w-full sm:w-[420px] bg-white shadow-2xl z-40 flex flex-col border-l border-slate-100">
        {/* Status accent bar */}
        <div className={`h-1 shrink-0 ${barColor}`} />

        {/* Header */}
        <div className="flex items-start justify-between px-6 py-4 border-b border-slate-100 shrink-0">
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-0.5">
              {serviceLabel(alert.service)} Alert
            </p>
            <h2 className="text-sm font-extrabold text-slate-900 leading-snug break-all"
                title={alert.resourceName || alert.resourceId}>
              {alert.resourceName || alert.resourceId}
            </h2>
            <p className="mt-0.5 text-[11px] text-slate-400 font-mono truncate" title={alert.resourceId}>
              {alert.resourceId}
            </p>
          </div>
          <button onClick={onClose}
            className="ml-3 mt-0.5 shrink-0 p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors">
            <X size={16} strokeWidth={2} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">

          {/* Reason / risk description */}
          {alert.reason && (
            <div className={`rounded-xl p-4 ring-1 ${
              alert.severity === "HIGH"
                ? "bg-red-50 ring-red-100 text-red-800"
                : alert.severity === "MEDIUM"
                  ? "bg-amber-50 ring-amber-100 text-amber-800"
                  : "bg-blue-50 ring-blue-100 text-blue-800"
            }`}>
              <p className="text-xs font-bold uppercase tracking-wide opacity-60 mb-1">Why this alert</p>
              <p className="text-sm font-semibold leading-snug">{alert.reason}</p>
            </div>
          )}

          {/* Stale notice */}
          {isStale && (
            <div className="rounded-xl bg-slate-50 ring-1 ring-slate-200 p-4">
              <p className="text-xs font-bold uppercase tracking-wide text-slate-400 mb-1">Stale Alert</p>
              <p className="text-sm text-slate-600 font-medium">{alert.resolvedReason}</p>
              <p className="mt-1 text-xs text-slate-400">
                This resource was not found in the most recent scan. The alert has been auto-resolved.
              </p>
            </div>
          )}

          {/* Scan provenance */}
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-2">Scan Provenance</p>
            <div className="bg-slate-50 rounded-xl px-4 py-1">
              <DrawerRow label="Status">
                {isStale ? (
                  <span className="text-slate-500">Stale — resolved</span>
                ) : (
                  <span className={`font-bold ${
                    alert.status === "ACTIVE" ? "text-indigo-600"
                    : alert.status === "ACKNOWLEDGED" ? "text-green-600"
                    : alert.status === "SNOOZED" ? "text-purple-600"
                    : "text-slate-500"
                  }`}>{alert.status}</span>
                )}
              </DrawerRow>
              <DrawerRow label="Source">{scanLabel}</DrawerRow>
              <DrawerRow label="Account">{acctDisplay}</DrawerRow>
              <DrawerRow label="Last seen">
                <span className="flex items-center gap-1">
                  <Clock size={11} className="text-slate-400 shrink-0" />
                  {fmtLastSeen(alert.lastSeenAt)}
                </span>
              </DrawerRow>
              {alert.createdAt && (
                <DrawerRow label="First seen">{fmtLastSeen(alert.createdAt)}</DrawerRow>
              )}
            </div>
          </div>

          {/* Resource details */}
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-2">Resource Details</p>
            <div className="bg-slate-50 rounded-xl px-4 py-1">
              <DrawerRow label="Service">{serviceLabel(alert.service)}</DrawerRow>
              <DrawerRow label="Region"><span className="font-mono">{alert.region || "—"}</span></DrawerRow>
              <DrawerRow label="Version"><span className="font-mono">{alert.version || "—"}</span></DrawerRow>
              <DrawerRow label="Lifecycle">
                <StatusBadge status={alert.lifecycleStatus} size="sm" />
              </DrawerRow>
              {alert.eolDate && (
                <DrawerRow label="EOL Date">
                  <span className={
                    alert.lifecycleStatus === "EOL" ? "text-red-600 font-bold"
                    : alert.lifecycleStatus === "EXPIRING_SOON" ? "text-amber-600 font-bold"
                    : "text-slate-700"
                  }>{alert.eolDate}</span>
                </DrawerRow>
              )}
            </div>
          </div>
        </div>

        {/* Footer — navigate to full resource detail */}
        <div className="shrink-0 px-6 py-4 border-t border-slate-100">
          <button
            onClick={() => { onClose(); navigate(`/resource/${encodeURIComponent(alert.resourceId)}`); }}
            className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-bold text-white hover:bg-slate-700 transition-colors"
          >
            View Full Resource <ExternalLink size={14} />
          </button>
        </div>
      </div>
    </>
  );
}

// ── Alert row ─────────────────────────────────────────────────────────────────

function AlertRow({ alert, tabStatus, onView, onAck, onSnooze, onReopen, canEdit, accountName }) {
  const isActive  = alert.status === "ACTIVE";
  const isAcked   = alert.status === "ACKNOWLEDGED";
  const isSnoozed = alert.status === "SNOOZED";

  // Fallback display for account: masked last-4 of accountId
  const accountDisplay = accountName
    || (alert.accountId
        ? `****${String(alert.accountId).slice(-4)}`
        : "—");

  return (
    <tr className="group border-b border-slate-100 hover:bg-slate-50 transition-colors">
      {/* Resource name */}
      <td className="sticky left-0 z-10 bg-white group-hover:bg-slate-50 transition-colors px-4 py-3 w-[200px] cursor-pointer"
          onClick={() => onView(alert)}>
        <div className="font-semibold text-slate-900 text-sm truncate max-w-[180px]"
             title={alert.resourceName || alert.resourceId}>
          {alert.resourceName || alert.resourceId}
        </div>
        <div className="text-[11px] text-slate-400 font-mono truncate mt-0.5 max-w-[180px]"
             title={alert.resourceId}>
          {alert.resourceId}
        </div>
        {tabStatus === "STALE" ? (
          <span className="mt-1 inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide bg-slate-100 text-slate-500 ring-1 ring-slate-200">
            Not found in latest scan
          </span>
        ) : alert.reason && (
          <div className="mt-0.5 text-[11px] text-slate-400 truncate max-w-[180px]" title={alert.reason}>
            {alert.reason}
          </div>
        )}
      </td>

      {/* Source */}
      <td className="px-4 py-3 whitespace-nowrap">
        <SourceBadge scanSource={alert.scanSource || "ACCOUNT_SCAN"} />
      </td>

      {/* Account */}
      <td className="px-4 py-3 whitespace-nowrap max-w-[150px]">
        <span className="block truncate text-sm text-slate-600" title={accountName || alert.accountId}>
          {accountDisplay}
        </span>
      </td>

      {/* Severity */}
      <td className="px-4 py-3 whitespace-nowrap">
        <SeverityBadge severity={alert.severity} />
      </td>

      {/* Service */}
      <td className="px-4 py-3 text-sm text-slate-600 whitespace-nowrap">
        {serviceLabel(alert.service)}
      </td>

      {/* Region */}
      <td className="px-4 py-3 text-xs text-slate-500 font-mono whitespace-nowrap">
        {alert.region || "—"}
      </td>

      {/* Version */}
      <td className="px-4 py-3 text-xs font-mono text-slate-600 whitespace-nowrap">
        {alert.version || "—"}
      </td>

      {/* Lifecycle status */}
      <td className="px-4 py-3">
        <StatusBadge status={alert.lifecycleStatus} />
      </td>

      {/* EOL date */}
      <td className="px-4 py-3 text-sm text-slate-700 whitespace-nowrap">
        {alert.eolDate ?? "—"}
      </td>

      {/* Last seen / Snoozed until */}
      <td className="px-4 py-3 text-xs text-slate-400 whitespace-nowrap">
        {tabStatus === "SNOOZED" && alert.snoozedUntil
          ? <span className="text-purple-600 font-medium">{fmtSnoozeUntil(alert.snoozedUntil)}</span>
          : alert.lastSeenAt
            ? formatDistanceToNow(new Date(alert.lastSeenAt), { addSuffix: true })
            : "—"}
      </td>

      {/* Actions */}
      <td className="sticky right-0 z-10 bg-white group-hover:bg-slate-50 transition-colors px-3 py-3">
        <div className="flex items-center gap-1.5 justify-end">
          <button
            onClick={() => onView(alert)}
            className="text-xs font-semibold text-indigo-500 hover:text-indigo-700 whitespace-nowrap transition-colors">
            View →
          </button>
          {isActive && canEdit && (
            <>
              <span className="text-slate-200">|</span>
              <button
                onClick={() => onAck(alert.id)}
                title="Acknowledge"
                className="p-1 rounded text-slate-400 hover:text-green-600 hover:bg-green-50 transition-colors">
                <Check size={13} strokeWidth={2.5} />
              </button>
              <button
                onClick={() => onSnooze(alert.id)}
                title="Snooze"
                className="p-1 rounded text-slate-400 hover:text-purple-600 hover:bg-purple-50 transition-colors">
                <BellOff size={13} strokeWidth={2} />
              </button>
            </>
          )}
          {(isAcked || isSnoozed) && canEdit && (
            <>
              <span className="text-slate-200">|</span>
              <button
                onClick={() => onReopen(alert.id)}
                title="Reopen"
                className="p-1 rounded text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors">
                <RotateCcw size={12} strokeWidth={2} />
              </button>
            </>
          )}
        </div>
      </td>
    </tr>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function SkeletonRows() {
  return (
    <>
      {[...Array(5)].map((_, i) => (
        <tr key={i} className="border-b border-slate-100">
          {[200, 90, 120, 70, 90, 80, 100, 90, 90, 80, 90].map((w, j) => (
            <td key={j} className="px-4 py-3">
              <div className="h-4 bg-slate-100 animate-pulse rounded" style={{ width: w }} />
              {j === 0 && <div className="h-3 bg-slate-100 animate-pulse rounded mt-1.5 w-36" />}
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

const EMPTY_COPY = {
  ACKNOWLEDGED: { title: "No acknowledged alerts",  body: "Acknowledge active alerts to move them here."                                          },
  SNOOZED:      { title: "No snoozed alerts",       body: "Snooze active alerts to temporarily suppress them."                                    },
  RESOLVED:     { title: "No resolved alerts",      body: "Alerts appear here when a resource's lifecycle improves (EOL → Supported) or is manually resolved." },
  STALE:        { title: "No stale alerts",         body: "Alerts appear here when a previously flagged resource is no longer found in the latest scan — it may have been deleted or removed from AWS." },
};

const ACTIVE_EMPTY = {
  ORG_SCAN: {
    title: "No active organization alerts",
    body:  "Organization scan resources are currently healthy or lifecycle-not-tracked. EOL and expiring-soon resources will appear here after the next scan.",
    cta:   "Go to Organization Scan",
    path:  "/org-scan",
  },
  ACCOUNT_SCAN: {
    title: "No active account alerts",
    body:  "EOL and expiring-soon resources from connected accounts will appear here after you run a scan.",
    cta:   "Go to Connected Accounts",
    path:  "/connected-accounts",
  },
  "": {
    title: "No active alerts",
    body:  "EOL and expiring-soon resources will appear here after you run a scan.",
    cta:   "Go to Dashboard",
    path:  "/",
  },
};

function EmptyState({ tabStatus, sourceFilter, onAction }) {
  const { title, body } = EMPTY_COPY[tabStatus] ?? ACTIVE_EMPTY[sourceFilter ?? ""] ?? ACTIVE_EMPTY[""];
  const activeInfo = ACTIVE_EMPTY[sourceFilter ?? ""] ?? ACTIVE_EMPTY[""];
  return (
    <div className="py-10 text-center">
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-slate-100">
        <Bell size={20} className="text-slate-400" strokeWidth={1.5} />
      </div>
      <p className="text-slate-700 font-semibold text-sm mb-1">{title}</p>
      <p className="text-xs text-slate-400 leading-relaxed max-w-xs mx-auto mb-5">{body}</p>
      {tabStatus === "ACTIVE" && (
        <button
          onClick={onAction}
          className="inline-flex items-center rounded-xl bg-slate-900 px-4 py-2 text-xs font-bold text-white hover:bg-slate-700 transition-colors">
          {activeInfo.cta}
        </button>
      )}
    </div>
  );
}

// ── Source filter tabs ────────────────────────────────────────────────────────

const SOURCE_FILTERS = [
  { label: "All Alerts",    value: ""             },
  { label: "Account Scan",  value: "ACCOUNT_SCAN" },
  { label: "Org Scan",      value: "ORG_SCAN"     },
];

// ── Page ──────────────────────────────────────────────────────────────────────

const TABS = [
  { label: "Active",       value: "ACTIVE"       },
  { label: "Acknowledged", value: "ACKNOWLEDGED" },
  { label: "Snoozed",      value: "SNOOZED"      },
  { label: "Resolved",     value: "RESOLVED"     },
  { label: "Stale",        value: "STALE"        },
];

export default function AlertsPage() {
  const navigate    = useNavigate();
  const [tabStatus,      setTabStatus]      = useState("ACTIVE");
  const [sourceFilter,   setSourceFilter]   = useState(""); // "" | "ACCOUNT_SCAN" | "ORG_SCAN"
  const [accountFilter,  setAccountFilter]  = useState(""); // "" | specific accountId
  const [serviceFilter,  setServiceFilter]  = useState(""); // "" | service string
  const [severityFilter, setSeverityFilter] = useState(""); // "" | HIGH | MEDIUM | LOW
  const [page,           setPage]           = useState(1);
  const [snoozeId,     setSnoozeId]     = useState(null);
  const [drawerAlert,  setDrawerAlert]  = useState(null);
  const [toast,        setToast]        = useState(null);

  // Account name resolution
  const [connectedAccounts, setConnectedAccounts] = useState([]);
  const [orgMemberAccounts, setOrgMemberAccounts] = useState([]);

  // Fetch all alerts for this workspace (all statuses), filter client-side per tab + source
  const { data: alertData, isLoading, isError, refetch } = useAlerts({ limit: 500 });
  const allAlerts = alertData?.alerts ?? [];
  const isMock    = alertData?.isMock ?? false;

  const { mutateAsync: doAction } = useAlertAction();

  const canEdit = !hasMemberSession() || ["EDITOR", "ADMIN"].includes(getMemberRole());

  // Fetch connected accounts for account name display
  useEffect(() => {
    fetchAccountsFromServer().then(list => { if (list) setConnectedAccounts(list); });
  }, []);

  // Fetch org member accounts when Org Scan filter is active or there are org scan alerts
  useEffect(() => {
    const hasOrgAlerts = allAlerts.some(a => a.scanSource === "ORG_SCAN");
    if (!hasOrgAlerts && sourceFilter !== "ORG_SCAN") return;
    const wsId = getWorkspaceId();
    if (!wsId) return;
    let cancelled = false;
    (async () => {
      try {
        const r1 = await axios.get(
          `${API_BASE_URL}/workspaces/${wsId}/org-connections`,
          { headers: workspaceHeaders(), timeout: 6000 }
        );
        const activeConn = (r1.data.connections || []).find(c => c.status === "CONNECTED");
        if (!activeConn || cancelled) return;
        const r2 = await axios.get(
          `${API_BASE_URL}/workspaces/${wsId}/org-connections/${activeConn.id}/accounts`,
          { headers: workspaceHeaders(), timeout: 6000 }
        );
        if (!cancelled) setOrgMemberAccounts((r2.data.accounts || []).filter(a => a.status === "ACTIVE"));
      } catch { /* non-fatal */ }
    })();
    return () => { cancelled = true; };
  }, [allAlerts, sourceFilter]); // eslint-disable-line

  // Build account ID → display name map
  const accountMap = useMemo(() => {
    const map = {};
    for (const a of connectedAccounts) {
      map[a.id] = a.accountName || a.name || a.id;
    }
    for (const a of orgMemberAccounts) {
      map[a.awsAccountId] = a.name || a.awsAccountId;
    }
    return map;
  }, [connectedAccounts, orgMemberAccounts]);

  // Apply source filter first
  const sourceFiltered = useMemo(() =>
    sourceFilter
      ? allAlerts.filter(a => (a.scanSource || "ACCOUNT_SCAN") === sourceFilter)
      : allAlerts,
    [allAlerts, sourceFilter]
  );

  // Account dropdown list for the active source
  const accountFilterList = useMemo(() => {
    if (sourceFilter === "ORG_SCAN") {
      return orgMemberAccounts.map(a => ({ id: a.awsAccountId, name: a.name || a.awsAccountId }));
    }
    if (sourceFilter === "ACCOUNT_SCAN") {
      return connectedAccounts.map(a => ({ id: a.id, name: a.accountName || a.name || a.id }));
    }
    return [];
  }, [sourceFilter, connectedAccounts, orgMemberAccounts]);

  // Apply account filter
  const accountFiltered = useMemo(() => {
    if (!accountFilter) return sourceFiltered;
    return sourceFiltered.filter(a => a.accountId === accountFilter);
  }, [sourceFiltered, accountFilter]);

  // Service list from current source+account filtered alerts (for dropdown options)
  const serviceList = useMemo(() => {
    const seen = new Set();
    for (const a of accountFiltered) if (a.service) seen.add(a.service);
    return [...seen].sort();
  }, [accountFiltered]);

  // Apply service + severity filters
  const fullyFiltered = useMemo(() => {
    let r = accountFiltered;
    if (serviceFilter)  r = r.filter(a => a.service === serviceFilter);
    if (severityFilter) r = r.filter(a => a.severity === severityFilter);
    return r;
  }, [accountFiltered, serviceFilter, severityFilter]);

  // Counts scoped to all active filters (for summary cards + tab badges)
  const filteredCounts = useMemo(() => ({
    total:        fullyFiltered.length,
    active:       fullyFiltered.filter(a => a.status === "ACTIVE").length,
    acknowledged: fullyFiltered.filter(a => a.status === "ACKNOWLEDGED").length,
    snoozed:      fullyFiltered.filter(a => a.status === "SNOOZED").length,
    resolved:     fullyFiltered.filter(a => a.status === "RESOLVED" && !a.resolvedReason).length,
    stale:        fullyFiltered.filter(a => a.status === "RESOLVED" && !!a.resolvedReason).length,
    high:         fullyFiltered.filter(a => a.severity === "HIGH").length,
    medium:       fullyFiltered.filter(a => a.severity === "MEDIUM").length,
  }), [fullyFiltered]);

  // Apply status tab filter — Stale = RESOLVED with a resolvedReason set;
  // Resolved = RESOLVED without one (lifecycle improved or manually resolved).
  const filtered = useMemo(() => {
    if (tabStatus === "STALE") {
      return fullyFiltered.filter(a => a.status === "RESOLVED" && !!a.resolvedReason);
    }
    if (tabStatus === "RESOLVED") {
      return fullyFiltered.filter(a => a.status === "RESOLVED" && !a.resolvedReason);
    }
    return fullyFiltered.filter(a => a.status === tabStatus);
  }, [fullyFiltered, tabStatus]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PER_PAGE));
  const paginated  = useMemo(() =>
    filtered.slice((page - 1) * PER_PAGE, page * PER_PAGE),
    [filtered, page]
  );

  function switchTab(val) { setTabStatus(val); setPage(1); }
  function switchSource(val) {
    setSourceFilter(val);
    setAccountFilter("");
    setServiceFilter("");
    setSeverityFilter("");
    setPage(1);
  }

  function handleView(alert) {
    setDrawerAlert(alert);
  }

  function handleAck(alertId) {
    doAction({ alertId, action: "acknowledge" });
  }

  function handleReopen(alertId) {
    doAction({ alertId, action: "reopen" });
  }

  async function handleSnooze(alertId, snoozeUntil) {
    try {
      await doAction({ alertId, action: "snooze", body: { snoozeUntil } });
      setSnoozeId(null);
      const label = fmtSnoozeUntil(snoozeUntil);
      setToast({ type: "success", msg: `Alert snoozed until ${label}.` });
      setTimeout(() => setToast(null), 5000);
      return { ok: true };
    } catch (err) {
      const msg = err?.message || "Could not snooze alert. Please try again.";
      return { ok: false, error: msg };
    }
  }

  // Options arrays for ModernSelect
  const accountOptions = useMemo(() => [
    { value: "", label: sourceFilter === "ORG_SCAN" ? "All Org Accounts" : "All Accounts" },
    ...accountFilterList.map(a => ({ value: a.id, label: a.name })),
  ], [sourceFilter, accountFilterList]);

  const serviceOptions = useMemo(() => [
    { value: "", label: "All Services" },
    ...serviceList.map(s => ({ value: s, label: s })),
  ], [serviceList]);

  const SEVERITY_OPTIONS = [
    { value: "",       label: "All Severity" },
    { value: "HIGH",   label: "High"         },
    { value: "MEDIUM", label: "Medium"       },
    { value: "LOW",    label: "Low"          },
  ];

  const lastColHeader = tabStatus === "SNOOZED" ? "Reactivates" : "Last seen";
  const TABLE_HEADERS = [
    "Resource", "Source", "Account", "Severity", "Service",
    "Region", "Version", "Status", "EOL date", lastColHeader, "Actions",
  ];

  return (
    <div className="px-4 sm:px-6 py-6 sm:py-8 max-w-7xl mx-auto">

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-7">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-indigo-500 mb-2">Alert History</p>
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 mb-1.5">Alerts</h1>
          <p className="text-sm text-slate-500 leading-relaxed">
            In-app alerts generated from scanned inventory. EOL → High, Expiring Soon → Medium.
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="shrink-0 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl border border-slate-200 text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors"
        >
          ↻ Refresh
        </button>
      </div>

      {/* Summary cards (scoped to active source filter) */}
      <SummaryCards counts={filteredCounts} />

      {/* Banners */}
      {isMock && (
        <div className="flex items-center gap-2 text-sm text-amber-700 bg-amber-50 rounded-xl px-4 py-2.5 mb-5 ring-1 ring-amber-100">
          <Info size={15} className="shrink-0" strokeWidth={1.75} />
          <span>Demo mode — showing sample alerts. Run a real account scan to see live EOL alerts.</span>
        </div>
      )}
      {isError && HAS_API && (
        <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 rounded-xl px-4 py-2.5 mb-5 ring-1 ring-red-100">
          <AlertCircle size={15} className="shrink-0" strokeWidth={1.75} />
          <span>Unable to load alerts from backend.</span>
        </div>
      )}

      {/* Row 1: Source selector */}
      <div className="mb-4">
        <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2">Source</p>
        <div className="flex flex-wrap items-center gap-2">
          {SOURCE_FILTERS.map(({ label, value }) => (
            <button
              key={value}
              onClick={() => switchSource(value)}
              className={`h-9 px-4 rounded-xl text-sm font-semibold transition-all border ${
                sourceFilter === value
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50 hover:border-slate-300"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Row 2: Contextual filters (shown when source is selected) */}
      {sourceFilter !== "" && (
        <div className="mb-4">
          <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2">Filters</p>
          <div className="flex flex-wrap items-center gap-2">
            {/* Account */}
            {accountFilterList.length > 0 && (
              <ModernSelect
                value={accountFilter}
                options={accountOptions}
                onChange={val => { setAccountFilter(val); setPage(1); }}
              />
            )}

            {/* Service */}
            {serviceList.length > 0 && (
              <ModernSelect
                value={serviceFilter}
                options={serviceOptions}
                onChange={val => { setServiceFilter(val); setPage(1); }}
              />
            )}

            {/* Severity */}
            <ModernSelect
              value={severityFilter}
              options={SEVERITY_OPTIONS}
              onChange={val => { setSeverityFilter(val); setPage(1); }}
            />

            {/* Clear filters — outline button, only when a filter is active */}
            {(accountFilter || serviceFilter || severityFilter) && (
              <button
                onClick={() => { setAccountFilter(""); setServiceFilter(""); setSeverityFilter(""); setPage(1); }}
                className="inline-flex items-center gap-1 h-9 px-3 rounded-xl border border-slate-200 bg-white text-xs font-semibold text-slate-500 hover:text-slate-700 hover:border-slate-300 hover:bg-slate-50 transition-all"
              >
                <X size={11} strokeWidth={2.5} />
                Clear filters
              </button>
            )}
          </div>
        </div>
      )}

      {/* Row 3: Status tabs */}
      <div className="flex flex-wrap gap-2 mb-5">
        {TABS.map(({ label, value }) => {
          const cnt = filteredCounts[value.toLowerCase()] ?? 0;
          return (
            <button
              key={value}
              onClick={() => switchTab(value)}
              className={`px-3.5 py-1.5 rounded-lg text-sm font-semibold transition-all border ${
                tabStatus === value
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
              }`}
            >
              {label}
              <span className={`ml-1.5 text-xs ${tabStatus === value ? "opacity-60" : "text-slate-400"}`}>
                {cnt}
              </span>
            </button>
          );
        })}
      </div>

      {/* Table */}
      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="overflow-x-auto scrollbar-thin">
            <table className="min-w-[1280px] w-full text-sm border-collapse">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  {TABLE_HEADERS.map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody><SkeletonRows /></tbody>
            </table>
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            tabStatus={tabStatus}
            sourceFilter={sourceFilter}
            onAction={() => navigate(ACTIVE_EMPTY[sourceFilter ?? ""]?.path ?? "/")}
          />
        ) : (
          <div className="overflow-x-auto scrollbar-thin">
            <table className="min-w-[1280px] w-full text-sm border-collapse">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="sticky left-0 z-20 bg-slate-50 w-[200px] px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">Resource</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">Source</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">Account</th>
                  {TABLE_HEADERS.slice(3, -1).map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">{h}</th>
                  ))}
                  <th className="sticky right-0 z-20 bg-slate-50 w-[120px] px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">Actions</th>
                </tr>
              </thead>
              <tbody>
                {paginated.map(alert => (
                  <AlertRow
                    key={alert.id}
                    alert={alert}
                    tabStatus={tabStatus}
                    onView={handleView}
                    onAck={handleAck}
                    onSnooze={id => setSnoozeId(id)}
                    onReopen={handleReopen}
                    canEdit={canEdit}
                    accountName={accountMap[alert.accountId] ?? null}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Footer */}
        {!isLoading && filtered.length > 0 && (
          <div className="px-4 py-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-400">
            <span>
              {`Showing ${(page-1)*PER_PAGE+1}–${Math.min(page*PER_PAGE, filtered.length)} of ${filtered.length}`}
            </span>
            {totalPages > 1 && (
              <div className="flex items-center gap-1">
                <button onClick={() => setPage(p => Math.max(1, p-1))} disabled={page===1}
                  className="px-2 py-1 rounded border border-slate-200 disabled:opacity-40 hover:bg-slate-50">‹</button>
                <span className="px-3">{page} / {totalPages}</span>
                <button onClick={() => setPage(p => Math.min(totalPages, p+1))} disabled={page===totalPages}
                  className="px-2 py-1 rounded border border-slate-200 disabled:opacity-40 hover:bg-slate-50">›</button>
              </div>
            )}
          </div>
        )}
      </div>

      {drawerAlert && (
        <AlertDrawer
          alert={drawerAlert}
          onClose={() => setDrawerAlert(null)}
          accountName={accountMap[drawerAlert.accountId] ?? null}
        />
      )}

      {snoozeId && (
        <SnoozeDialog
          alertId={snoozeId}
          onClose={() => setSnoozeId(null)}
          onSnooze={handleSnooze}
        />
      )}

      {toast && (
        <div className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg text-sm font-medium ring-1 ${
          toast.type === "success"
            ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
            : "bg-red-50 text-red-800 ring-red-200"
        }`}>
          <span>{toast.msg}</span>
          <button onClick={() => setToast(null)} className="ml-1 opacity-60 hover:opacity-100 text-base leading-none">×</button>
        </div>
      )}
    </div>
  );
}
