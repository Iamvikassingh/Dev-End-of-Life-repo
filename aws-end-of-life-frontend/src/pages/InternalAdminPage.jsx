import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  Shield, Eye, EyeOff, Copy, Check, RefreshCw, AlertTriangle,
  LogOut, CloudCog, X, Search, Server, Activity, Database, Clock,
  RotateCcw, CheckCircle, XCircle, Loader2, Download, BookOpen,
  ExternalLink, Edit2, Trash2, Globe,
} from "lucide-react";
import { API_BASE_URL, HAS_API } from "../utils/config";
import { AppSelect } from "../components/AppSelect";
import {
  hasAdminSession, setAdminSession, clearAdminSession,
  getAdminToken, getAdminSessionExpiry,
} from "../utils/adminAuth";
import { copyToClipboard } from "../utils/clipboard";

// ── Helpers ───────────────────────────────────────────────────────────────────

const TABS = [
  { key: "workspaces", label: "Workspaces"     },
  { key: "scans",      label: "Scan Runs"      },
  { key: "system",     label: "System"         },
  { key: "guides",     label: "Upgrade Guides" },
];

const GUIDE_SERVICES = [
  "Lambda", "EC2", "RDS", "EKS", "ElastiCache",
  "MSK", "OpenSearch", "DocumentDB", "Neptune", "Glue", "Aurora",
  "CodeBuild", "ElasticBeanstalk", "CloudFrontFunctions", "ECR", "EMR",
];
const GUIDE_SERVICE_OPTIONS = [
  { value: "", label: "Select service…" },
  ...GUIDE_SERVICES.map(s => ({ value: s, label: s })),
];
const GUIDE_STATUS_OPTIONS = [
  { value: "DRAFT",     label: "Draft"     },
  { value: "PUBLISHED", label: "Published" },
];

const ADMIN_CONTAINER = "mx-auto w-[calc(100%_-_32px)] max-w-[1280px] sm:w-[calc(100%_-_48px)]";

const SCAN_STATUS_FILTERS = ["ALL", "SUCCESS", "PARTIAL_SUCCESS", "FAILED", "RUNNING", "QUEUED"];

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function fmtDateParts(iso) {
  if (!iso) return null;
  const date = new Date(iso);
  return {
    date: date.toLocaleDateString(undefined, {
      year: "numeric", month: "short", day: "numeric",
    }),
    time: date.toLocaleTimeString(undefined, {
      hour: "2-digit", minute: "2-digit",
    }),
  };
}

function fmtExpiry(ms) {
  const diff = ms - Date.now();
  if (diff <= 0) return "Expired";
  const m = Math.floor(diff / 60_000);
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
}

function scanDuration(run) {
  if (!run.startedAt || !run.completedAt) return "—";
  const secs = Math.round((new Date(run.completedAt) - new Date(run.startedAt)) / 1000);
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

function isLocalhost() {
  return ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);
}

// True when this build was compiled with the dev-only HTTP override.
// Default: false — admin is blocked over insecure HTTP unless HTTPS or localhost.
const ALLOW_INSECURE_ADMIN = process.env.REACT_APP_ALLOW_INSECURE_ADMIN === "true";

// Returns true when the current context is HTTP + non-localhost (i.e. not safe).
function isInsecureContext() {
  return window.location.protocol !== "https:" && !isLocalhost();
}

async function adminFetch(path, options = {}) {
  const token = getAdminToken();
  const r = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Token": token,
      ...(options.headers || {}),
    },
  });
  const contentType = r.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await r.json().catch(() => ({}))
    : {};
  return { ok: r.ok, status: r.status, data };
}

function apiError(data, status, fallback = "Request failed.") {
  if (status === 404) return "API route not found (404). Ensure Nginx proxies /admin/* to port 3001 and backend is restarted.";
  if (status === 401) return data?.error?.message || "Admin session expired or token invalid.";
  return data?.error?.message || `${fallback} (HTTP ${status})`;
}

// ── Copy button ───────────────────────────────────────────────────────────────

function CopyBtn({ value, label = "Copy", onCopied }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    const ok = await copyToClipboard(value);
    if (ok) { setCopied(true); onCopied?.(); setTimeout(() => setCopied(false), 2000); }
  }
  return (
    <button type="button" onClick={copy}
      className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
        copied
          ? "bg-emerald-50 text-emerald-600"
          : "bg-slate-100 text-slate-500 hover:bg-slate-200 hover:text-slate-700"
      }`}>
      {copied ? <><Check size={11} strokeWidth={2.5} /> Copied</> : <><Copy size={11} strokeWidth={1.75} /> {label}</>}
    </button>
  );
}

// ── Admin login form ──────────────────────────────────────────────────────────

function AdminAccessForm({ onSuccess }) {
  const [token,       setToken]       = useState("");
  const [show,        setShow]        = useState(false);
  const [error,       setError]       = useState("");
  const [loading,     setLoading]     = useState(false);
  const [helperOpen,  setHelperOpen]  = useState(false);

  const insecureCtx = isInsecureContext();
  // Hard block: HTTP + not localhost + dev flag NOT set
  const isBlocked  = insecureCtx && !ALLOW_INSECURE_ADMIN;
  // Dev warning: HTTP + not localhost + dev flag explicitly set to true
  const isDevHttp  = insecureCtx && ALLOW_INSECURE_ADMIN;

  async function submit(e) {
    e.preventDefault();
    if (isBlocked) return;
    const tok = token.trim();
    if (!tok) { setError("Admin token is required."); return; }
    setLoading(true); setError("");
    try {
      if (HAS_API) {
        const r = await fetch(`${API_BASE_URL}/admin/validate`, {
          headers: { "X-Admin-Token": tok },
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
          setError(data?.error?.message || data?.error || "Invalid admin token.");
          setLoading(false);
          return;
        }
      }
      setAdminSession(tok);
      onSuccess();
    } catch {
      setError("Could not reach the server. Check your connection.");
    }
    setLoading(false);
  }

  return (
    <div className="min-h-screen px-4 py-10" style={{ background: "#F0F4F8" }}>
      <div className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-md items-center">
        <div className="w-full">
          <div className="mb-8 flex items-center justify-center gap-2.5">
            <CloudCog size={26} className="text-sky-500" strokeWidth={1.5} />
            <div>
              <p className="text-base font-extrabold leading-tight text-slate-900">AWS EOL Monitor</p>
              <p className="text-xs leading-tight text-slate-400">Internal Admin</p>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
            <div className="mb-1 flex items-center gap-2">
              <Shield size={16} className="text-indigo-500" strokeWidth={1.75} />
              <h1 className="text-lg font-extrabold text-slate-900">Admin Access</h1>
            </div>
            <p className="mb-5 text-sm text-slate-500">Internal team only. Use admin access only over HTTPS.</p>

            {isBlocked && (
              <div className="mb-4 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
                Admin access is disabled over insecure HTTP. Use HTTPS to continue.
              </div>
            )}
            {isDevHttp && (
              <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
                <span className="font-semibold">Dev mode:</span> Admin is allowed over HTTP. Do not use this setting in production.
              </div>
            )}

            <button type="button" onClick={() => setHelperOpen(v => !v)}
              className="mb-4 flex w-full items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-left text-sm font-semibold text-slate-700">
              Need the initial admin token?
              <span className="text-slate-400">{helperOpen ? "Hide" : "Show"}</span>
            </button>
            {helperOpen && (
              <div className="mb-5 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
                Check the server startup log, or run this on the server:
                <code className="mt-2 block rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-800">
                  cat $EOL_DATA_DIR/secrets/initial-admin-token
                </code>
                <p className="mt-2 text-xs text-slate-400">Or set ADMIN_PORTAL_TOKEN directly.</p>
              </div>
            )}

            <form onSubmit={submit} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-xs font-semibold text-slate-600">Admin token</label>
                <div className="relative">
                  <input
                    type={show ? "text" : "password"}
                    placeholder="eolm_admin_..."
                    value={token}
                    disabled={isBlocked}
                    onChange={e => { setToken(e.target.value); setError(""); }}
                    className="w-full rounded-xl border border-slate-200 px-3.5 py-2.5 pr-10 text-sm text-slate-800 transition-colors focus:border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-300/60 disabled:bg-slate-50 disabled:text-slate-400"
                    autoFocus
                  />
                  <button type="button" onClick={() => setShow(v => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
                    {show ? <EyeOff size={15} strokeWidth={1.75} /> : <Eye size={15} strokeWidth={1.75} />}
                  </button>
                </div>
              </div>
              {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>}
              <button type="submit" disabled={loading || isBlocked}
                className="w-full rounded-xl bg-slate-950 py-2.5 text-sm font-bold text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50">
                {loading ? "Verifying..." : "Continue →"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── CSV helpers ───────────────────────────────────────────────────────────────

function csvCell(v) { return `"${String(v ?? "").replace(/"/g, '""')}"`; }

function safeFilePart(v) {
  return String(v || "workspace").trim().toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "workspace";
}

function downloadRotatedTokenCsv({ workspaceId, workspaceName, token }) {
  const rotatedAt = new Date().toISOString();
  const rows = [
    ["Workspace Name", "Workspace ID", "Access Token", "Rotated At", "Note"],
    [workspaceName || "", workspaceId, token, rotatedAt, "Save this token now. It will not be shown again."],
  ];
  const csv  = rows.map(r => r.map(csvCell).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url;
  a.download = `aws-eol-monitor-token-${safeFilePart(workspaceName || workspaceId)}.csv`;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a); URL.revokeObjectURL(url);
}

// ── New token panel ───────────────────────────────────────────────────────────

function NewTokenPanel({ token, workspaceId, workspaceName, onClose }) {
  const [saved,          setSaved]          = useState(false);
  const [closeWarning,   setCloseWarning]   = useState(false);

  if (!token) return null;

  function handleClose() {
    if (!saved) { setCloseWarning(true); return; }
    onClose();
  }

  function handleDownload() {
    downloadRotatedTokenCsv({ workspaceId, workspaceName, token });
    setSaved(true);
    setCloseWarning(false);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl">

        {/* Header */}
        <div className="flex items-start justify-between gap-4 px-6 pt-6 pb-4 border-b border-slate-100">
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-amber-600">Token rotated</p>
            <h2 className="mt-1 text-lg font-extrabold text-slate-900">Save this workspace token now</h2>
            <p className="mt-1 text-sm text-slate-500">
              Token for <span className="font-mono text-slate-700">{workspaceId}</span> is shown once only.
            </p>
          </div>
          <button type="button" onClick={handleClose}
            className="mt-0.5 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 transition-colors shrink-0">
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-3">
          {/* Workspace ID row */}
          <div className="rounded-xl bg-slate-50 border border-slate-200 px-4 py-3">
            <p className="text-xs font-medium text-slate-400 mb-1">Workspace ID</p>
            <div className="flex items-center justify-between gap-2">
              <code className="text-sm font-mono font-semibold text-slate-800 truncate">{workspaceId}</code>
              <CopyBtn value={workspaceId} label="Copy" />
            </div>
          </div>

          {/* Access token row */}
          <div className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-3">
            <p className="text-xs font-semibold text-amber-600 mb-1">Access Token — save this now</p>
            <div className="flex items-start justify-between gap-2">
              <code className="text-xs font-mono font-semibold text-amber-900 break-all leading-relaxed">{token}</code>
              <CopyBtn value={token} label="Copy token"
                onCopied={() => { setSaved(true); setCloseWarning(false); }} />
            </div>
          </div>

          {/* Security warning */}
          <div className="rounded-xl bg-orange-50 border border-orange-100 px-4 py-3 text-xs text-orange-700 flex gap-2">
            <AlertTriangle size={14} className="mt-px shrink-0" strokeWidth={2} />
            <span>Anyone with this token can access this workspace. Store it securely — the old token is now invalid.</span>
          </div>

          {/* Close warning (shown if X clicked before saving) */}
          {closeWarning && (
            <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 flex items-start justify-between gap-3">
              <div className="flex gap-2">
                <AlertTriangle size={15} className="mt-px shrink-0" strokeWidth={2} />
                <span>This token has not been saved. If you close now, it cannot be viewed again.</span>
              </div>
              <button type="button" onClick={onClose}
                className="shrink-0 text-xs font-bold underline text-red-700 hover:text-red-900 whitespace-nowrap">
                Close anyway
              </button>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex flex-col gap-2 px-6 pb-6">
          <button type="button" onClick={handleDownload}
            className="w-full inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white py-2.5 text-sm font-bold text-slate-700 hover:bg-slate-50 transition-colors">
            <Download size={15} strokeWidth={2} />
            Download credentials CSV
          </button>
          <p className={`text-xs text-center ${saved ? "text-emerald-600" : "text-amber-700"}`}>
            {saved ? "Credentials saved. You can close now." : "Copy the token or download CSV before closing."}
          </p>
          <button type="button" onClick={onClose} disabled={!saved}
            className="w-full rounded-xl bg-slate-950 py-2.5 text-sm font-bold text-white hover:bg-slate-800 transition-colors disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500">
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Confirm modal ─────────────────────────────────────────────────────────────

function ConfirmModal({ type, workspace, onCancel, onConfirm, busy }) {
  const [text, setText] = useState("");
  const isDelete  = type === "delete";
  const canConfirm = !isDelete || text === workspace.name || text === workspace.id;
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/40 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <h2 className="text-lg font-extrabold text-slate-900">
          {isDelete ? "Delete workspace" : "Rotate workspace token"}
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-500">
          {isDelete
            ? `This permanently removes ${workspace.name}. Type the workspace name or ID to confirm.`
            : `This invalidates the current customer token for ${workspace.name}. The new token will be shown once.`}
        </p>
        {isDelete && (
          <input value={text} onChange={e => setText(e.target.value)} placeholder={workspace.name || workspace.id}
            className="mt-4 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-red-200" />
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50">Cancel</button>
          <button type="button" onClick={() => onConfirm(text)} disabled={!canConfirm || busy}
            className={`rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50 ${
              isDelete ? "bg-red-600 hover:bg-red-700" : "bg-slate-950 hover:bg-slate-800"
            }`}>
            {busy ? "Working..." : isDelete ? "Delete Workspace" : "Rotate Token"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, hint, Icon, tone = "slate", compact = false }) {
  const tones = {
    slate: "border-slate-200 bg-white text-slate-900",
    red:   "border-red-100   bg-red-50   text-red-800",
    blue:  "border-blue-100  bg-blue-50  text-blue-800",
    green: "border-emerald-100 bg-emerald-50 text-emerald-800",
    amber: "border-amber-100 bg-amber-50 text-amber-800",
  };
  return (
    <div className={`min-h-[132px] rounded-2xl border p-4 shadow-sm ${tones[tone] ?? tones.slate}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-bold uppercase tracking-wide opacity-70">{label}</p>
          <div className={`mt-2 font-bold leading-none ${compact ? "text-2xl" : "text-3xl"}`}>{value ?? "—"}</div>
        </div>
        {Icon && <Icon size={18} className="opacity-70" strokeWidth={1.75} />}
      </div>
      {hint && <p className="mt-2 text-xs opacity-65">{hint}</p>}
    </div>
  );
}

// ── Empty placeholder ─────────────────────────────────────────────────────────

function EmptyTab({ title, text }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-6 py-12 text-center shadow-sm">
      <Activity size={26} className="mx-auto mb-3 text-slate-300" strokeWidth={1.5} />
      <h3 className="text-base font-bold text-slate-900">{title}</h3>
      <p className="mx-auto mt-1 max-w-md text-sm leading-relaxed text-slate-500">{text}</p>
    </div>
  );
}

// ── Workspace detail drawer ───────────────────────────────────────────────────

function WorkspaceDetailDrawer({ workspace, onClose }) {
  if (!workspace) return null;
  return (
    <div className="fixed inset-0 z-30 flex justify-end bg-slate-950/30">
      <div className="h-full w-full max-w-xl overflow-y-auto bg-white shadow-2xl">
        <div className="sticky top-0 border-b border-slate-100 bg-white px-6 py-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-wide text-indigo-500">Workspace Detail</p>
              <h2 className="mt-1 text-xl font-extrabold text-slate-900">{workspace.name || "Untitled workspace"}</h2>
              <p className="mt-1 font-mono text-xs text-slate-400">{workspace.id}</p>
            </div>
            <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100"><X size={18} /></button>
          </div>
        </div>
        <div className="space-y-4 p-6">
          <div className="grid grid-cols-2 gap-3">
            <StatCard label="Connected Accounts" value={workspace.account_count ?? 0} Icon={Server} />
            <StatCard label="Status" value="Active" hint="Workspace record exists" Icon={CheckCircle} tone="green" />
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <h3 className="text-sm font-bold text-slate-900">Metadata</h3>
            <div className="mt-3 divide-y divide-slate-100 text-sm">
              {[
                ["Created",             fmtDate(workspace.created_at)],
                ["Last token rotation", fmtDate(workspace.rotated_at)],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 py-2">
                  <span className="text-slate-500">{k}</span>
                  <span className="text-right font-medium text-slate-800">{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Workspaces tab ────────────────────────────────────────────────────────────

function WorkspacesTable({ workspaces, loading, onView, onRotate, onDelete }) {
  if (loading) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="flex gap-4 border-b border-slate-100 px-4 py-4 last:border-0">
            {[...Array(7)].map((__, j) => <div key={j} className="h-4 flex-1 animate-pulse rounded bg-slate-100" />)}
          </div>
        ))}
      </div>
    );
  }
  if (!workspaces.length) {
    return <EmptyTab title="No workspaces found" text="Create a workspace from the public app, then refresh." />;
  }
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="max-h-[560px] overflow-auto scrollbar-thin">
        <table className="min-w-[1100px] w-full table-fixed text-sm">
          <thead className="sticky top-0 z-10">
            <tr className="border-b border-slate-200 bg-slate-50">
              {[["Workspace Name","w-[190px]"],["Workspace ID","w-[230px]"],["Accounts","w-[90px]"],["Created","w-[160px]"],["Token Rotated","w-[160px]"],["Status","w-[90px]"],["Actions","w-[180px]"]].map(([label, width]) => (
                <th key={label} className={`${width} px-4 py-3 text-left text-[11px] font-bold uppercase tracking-wide text-slate-500`}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {workspaces.map(ws => (
              <tr key={ws.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70">
                <td className="px-4 py-3 font-semibold text-slate-900"><span className="block truncate">{ws.name || "Untitled"}</span></td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <code className="truncate text-xs text-slate-500">{ws.id}</code>
                    <CopyBtn value={ws.id} label="ID" />
                  </div>
                </td>
                <td className="px-4 py-3 text-slate-700">{ws.account_count ?? 0}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{fmtDate(ws.created_at)}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{fmtDate(ws.rotated_at)}</td>
                <td className="px-4 py-3"><span className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-bold text-emerald-700">Active</span></td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1.5">
                    <button type="button" onClick={() => onView(ws)} className="h-8 rounded-lg border border-slate-200 px-2.5 text-xs font-semibold text-slate-600 hover:bg-slate-50">View</button>
                    <button type="button" onClick={() => onRotate(ws)} className="h-8 rounded-lg border border-slate-200 px-2.5 text-xs font-semibold text-slate-600 hover:bg-slate-50">Rotate</button>
                    <button type="button" onClick={() => onDelete(ws)} className="h-8 rounded-lg border border-red-100 px-2.5 text-xs font-semibold text-red-600 hover:bg-red-50">Delete</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Scan runs tab ─────────────────────────────────────────────────────────────

const SCAN_STATUS_CFG = {
  SUCCESS:         { cls: "bg-emerald-100 text-emerald-700", label: "Success"  },
  PARTIAL_SUCCESS: { cls: "bg-amber-100   text-amber-700",   label: "Partial"  },
  FAILED:          { cls: "bg-red-100     text-red-700",     label: "Failed"   },
  RUNNING:         { cls: "bg-blue-100    text-blue-700",    label: "Running"  },
  QUEUED:          { cls: "bg-slate-100   text-slate-600",   label: "Queued"   },
};

function ScanRunsTab() {
  const [scans,        setScans]        = useState([]);
  const [total,        setTotal]        = useState(0);
  const [hasMore,      setHasMore]      = useState(false);
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [wsFilter,     setWsFilter]     = useState("");
  const [searchInput,  setSearchInput]  = useState("");
  const [search,       setSearch]       = useState("");   // debounced
  const [page,         setPage]         = useState(0);
  const [pageSize,     setPageSize]     = useState(25);
  const [errModal,     setErrModal]     = useState(null); // run object for error modal

  // Debounce search input → reset to page 0 on change
  useEffect(() => {
    const t = setTimeout(() => { setSearch(searchInput.trim()); setPage(0); }, 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const p = new URLSearchParams({ limit: String(pageSize), offset: String(page * pageSize) });
      if (statusFilter !== "ALL") p.set("status", statusFilter);
      if (wsFilter)               p.set("workspaceId", wsFilter);
      if (search)                 p.set("search", search);
      const { ok, data } = await adminFetch(`/admin/scans?${p}`);
      if (!ok) {
        setError(data?.error?.message || data?.error || "Failed to load scan runs.");
      } else {
        setScans(data.scans || []);
        setTotal(data.total ?? data.count ?? 0);
        setHasMore(data.hasMore ?? false);
      }
    } catch {
      setError("Could not reach the server.");
    }
    setLoading(false);
  }, [statusFilter, wsFilter, search, page, pageSize]);

  useEffect(() => { load(); }, [load]);

  const firstItem = total === 0 ? 0 : page * pageSize + 1;
  const lastItem  = Math.min(page * pageSize + scans.length, total);

  return (
    <div className="space-y-4">
      {/* Filters row */}
      <div className="flex flex-wrap gap-2 items-center">
        <div className="flex rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
          {SCAN_STATUS_FILTERS.map(f => (
            <button key={f} type="button" onClick={() => { setStatusFilter(f); setPage(0); }}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors ${
                statusFilter === f ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-50"
              }`}>
              {f === "ALL" ? "All" : f.charAt(0) + f.slice(1).toLowerCase().replace("_", " ")}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input value={searchInput} onChange={e => setSearchInput(e.target.value)}
            placeholder="Search workspace / account..."
            className="h-9 w-60 rounded-lg border border-slate-200 bg-white pl-8 pr-3 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-200" />
        </div>
        <button type="button" onClick={() => { setPage(0); load(); }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50">
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* Table */}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <div className="space-y-0">
            {[...Array(pageSize > 10 ? 8 : pageSize)].map((_, i) => (
              <div key={i} className="flex gap-4 border-b border-slate-100 px-4 py-3.5 last:border-0">
                {[...Array(9)].map((__, j) => <div key={j} className="h-4 flex-1 animate-pulse rounded bg-slate-100" />)}
              </div>
            ))}
          </div>
        ) : scans.length === 0 ? (
          <div className="py-10 text-center">
            <Activity size={24} className="mx-auto mb-3 text-slate-300" strokeWidth={1.5} />
            <p className="text-sm text-slate-500 font-semibold">No scan runs found</p>
            <p className="text-xs text-slate-400 mt-1">
              {search || statusFilter !== "ALL"
                ? "Try adjusting your filters."
                : "Scan runs will appear here after workspaces run account scans."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-[1200px] w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50">
                  {["Workspace","Account","Status","Started","Duration","Total","EOL","Expiring","Unknown","Error"].map(h => (
                    <th key={h} className="px-3 py-3 text-left text-xs font-bold uppercase tracking-wide text-slate-500 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {scans.map(run => {
                  const sc  = SCAN_STATUS_CFG[run.status] ?? SCAN_STATUS_CFG.QUEUED;
                  const sum = run.summary;
                  return (
                    <tr key={run.scanId} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70">
                      <td className="px-3 py-3 font-semibold text-slate-900 whitespace-nowrap max-w-[140px]">
                        <span className="block truncate">{run.workspaceName || run.workspaceId || "—"}</span>
                      </td>
                      <td className="px-3 py-3 text-xs font-mono text-slate-500 whitespace-nowrap max-w-[140px]">
                        <span className="block truncate">{run.accountId || "—"}</span>
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap">
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-bold ${sc.cls}`}>
                          {sc.label}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-500 whitespace-nowrap">{fmtDate(run.startedAt)}</td>
                      <td className="px-3 py-3 text-xs text-slate-500 whitespace-nowrap">{scanDuration(run)}</td>
                      <td className="px-3 py-3 text-xs text-slate-700 font-semibold">{sum?.total ?? "—"}</td>
                      <td className="px-3 py-3 text-xs text-red-700   font-semibold">{sum?.eol ?? "—"}</td>
                      <td className="px-3 py-3 text-xs text-amber-700 font-semibold">{sum?.expiringSoon ?? "—"}</td>
                      <td className="px-3 py-3 text-xs text-slate-400 font-semibold">{sum?.unknown ?? "—"}</td>
                      <td className="px-3 py-3 text-xs text-slate-400 max-w-[200px]">
                        {run.error ? (
                          <button type="button" onClick={() => setErrModal(run)}
                            className="block truncate text-red-500 font-mono text-left hover:underline" title="Click to view full error">
                            {run.error}
                          </button>
                        ) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination footer */}
      {!loading && total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
            Showing <span className="font-semibold">{firstItem}–{lastItem}</span> of{" "}
            <span className="font-semibold">{total}</span> scan run{total !== 1 ? "s" : ""}
          </p>
          <div className="flex items-center gap-2">
            <select value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setPage(0); }}
              className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-200">
              {[25, 50, 100].map(n => <option key={n} value={n}>{n} / page</option>)}
            </select>
            <button type="button" disabled={page === 0 || loading} onClick={() => setPage(p => p - 1)}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">
              Previous
            </button>
            <span className="text-xs text-slate-500 font-semibold">Page {page + 1}</span>
            <button type="button" disabled={!hasMore || loading} onClick={() => setPage(p => p + 1)}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">
              Next
            </button>
          </div>
        </div>
      )}

      {/* Error details modal */}
      {errModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4" onClick={() => setErrModal(null)}>
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <h2 className="text-base font-extrabold text-slate-900">Scan Error Details</h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  {errModal.workspaceName || errModal.workspaceId} · {errModal.accountId || "—"} · {fmtDate(errModal.startedAt)}
                </p>
              </div>
              <button type="button" onClick={() => setErrModal(null)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
                <X size={16} />
              </button>
            </div>
            <pre className="whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-4 text-xs text-red-300 max-h-72 overflow-y-auto font-mono">
              {errModal.error || "No error message recorded."}
            </pre>
            <div className="mt-4 flex justify-end">
              <button type="button" onClick={() => setErrModal(null)}
                className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50">
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── System tab ────────────────────────────────────────────────────────────────

function SystemTab() {
  const [data,       setData]       = useState(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const { ok, data: d } = await adminFetch("/admin/system");
      if (!ok) setError(d?.error?.message || d?.error || "Failed to load system info.");
      else     setData(d);
    } catch {
      setError("Could not reach the server.");
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleRefreshCache() {
    setRefreshing(true); setRefreshMsg("");
    try {
      const { ok, data: d } = await adminFetch("/admin/general-eol/refresh", { method: "POST" });
      if (ok) {
        setRefreshMsg(`Cache refreshed — ${d?.count ?? 0} records loaded.`);
        load();
      } else {
        setRefreshMsg(d?.error?.message || "Refresh failed.");
      }
    } catch {
      setRefreshMsg("Network error.");
    }
    setRefreshing(false);
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {!loading && !data ? (
        <EmptyTab title="No system data" text="System health and cache details will appear here once the admin API responds." />
      ) : (
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Backend health */}
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-bold text-slate-900">Backend health</h2>
            <button type="button" onClick={load}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50">
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Refresh
            </button>
          </div>
          {loading ? (
            <div className="space-y-2">{[...Array(4)].map((_, i) => <div key={i} className="h-5 rounded bg-slate-100 animate-pulse" />)}</div>
          ) : (
            <div className="divide-y divide-slate-100 text-sm">
              <div className="flex justify-between py-2">
                <span className="text-slate-500">Status</span>
                <span className="flex items-center gap-1.5 font-semibold text-emerald-700">
                  <CheckCircle size={13} strokeWidth={2} /> {data?.backend?.status ?? "—"}
                </span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-slate-500">Storage backend</span>
                <span className="font-mono text-xs font-semibold text-slate-700">{data?.backend?.storage ?? "—"}</span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-slate-500">API base</span>
                <span className="font-mono text-xs text-slate-500">{API_BASE_URL || "same origin"}</span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-slate-500">Admin session</span>
                <span className="font-semibold text-slate-700">{fmtExpiry(getAdminSessionExpiry())}</span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-slate-500">Total scan runs</span>
                <span className="font-semibold text-slate-700">{data?.scanRuns?.total ?? "—"}</span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-slate-500">Failed scans</span>
                <span className={`font-semibold ${(data?.scanRuns?.failed ?? 0) > 0 ? "text-red-600" : "text-slate-700"}`}>
                  {data?.scanRuns?.failed ?? "—"}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* EOL cache */}
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-base font-bold text-slate-900 mb-4">General EOL cache</h2>
          {loading ? (
            <div className="space-y-2">{[...Array(4)].map((_, i) => <div key={i} className="h-5 rounded bg-slate-100 animate-pulse" />)}</div>
          ) : (
            <>
              <div className="divide-y divide-slate-100 text-sm mb-4">
                <div className="flex justify-between py-2">
                  <span className="text-slate-500">Status</span>
                  <span className={`font-semibold flex items-center gap-1.5 ${
                    data?.eolCache?.isEmpty ? "text-amber-600"
                    : data?.eolCache?.isStale ? "text-amber-600"
                    : "text-emerald-700"
                  }`}>
                    {data?.eolCache?.isEmpty
                      ? <><XCircle size={13} /> Empty</>
                      : data?.eolCache?.isStale
                        ? <><AlertTriangle size={13} /> Stale</>
                        : <><CheckCircle size={13} strokeWidth={2} /> Fresh</>
                    }
                  </span>
                </div>
                <div className="flex justify-between py-2">
                  <span className="text-slate-500">Record count</span>
                  <span className="font-semibold text-slate-700">{data?.eolCache?.recordCount ?? "—"}</span>
                </div>
                <div className="flex justify-between py-2">
                  <span className="text-slate-500">Last refreshed</span>
                  <span className="text-xs font-medium text-slate-500">{fmtDate(data?.eolCache?.refreshedAt)}</span>
                </div>
              </div>

              {refreshMsg && (
                <p className={`text-xs rounded-lg px-3 py-2 mb-3 ${
                  refreshMsg.includes("failed") || refreshMsg.includes("error")
                    ? "bg-red-50 text-red-600"
                    : "bg-emerald-50 text-emerald-700"
                }`}>{refreshMsg}</p>
              )}

              <button
                type="button"
                onClick={handleRefreshCache}
                disabled={refreshing}
                className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {refreshing
                  ? <><Loader2 size={14} className="animate-spin" /> Refreshing…</>
                  : <><RotateCcw size={14} /> Refresh EOL cache</>
                }
              </button>
              <p className="mt-2 text-xs text-slate-400">Fetches fresh data from endoflife.date. Takes 15–30 seconds.</p>
            </>
          )}
        </div>

        {/* Feature flags */}
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-2">
          <h2 className="text-base font-bold text-slate-900 mb-4">Feature flags</h2>
          {loading ? (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              {[...Array(5)].map((_, i) => <div key={i} className="h-12 rounded-xl bg-slate-100 animate-pulse" />)}
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              {[
                ["Organization Scan", data?.featureFlags?.organizationScan],
                ["Remediation Tracking", data?.featureFlags?.remediation],
                ["SSO/SAML", data?.featureFlags?.ssoSaml],
                ["SaaS/Billing", data?.featureFlags?.billing],
                ["CI/CD Scan-on-push", data?.featureFlags?.cicdScanOnPush],
              ].map(([label, enabled]) => (
                <div key={label} className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-2.5">
                  <p className="text-xs font-semibold text-slate-500">{label}</p>
                  <span className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-xs font-bold ${
                    enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-500"
                  }`}>
                    {enabled ? "Enabled" : "Disabled"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  );
}

// ── Upgrade Guides tab ────────────────────────────────────────────────────────

const GUIDE_STATUS_CFG = {
  PUBLISHED: { cls: "bg-emerald-100 text-emerald-700", label: "Published" },
  DRAFT:     { cls: "bg-slate-100   text-slate-600",   label: "Draft"     },
};

function GuideFormModal({ guide, busy, onClose, onSave }) {
  const isNew = !guide.id;
  const [form,  setForm]  = useState({
    title:          guide.title          ?? "",
    service:        guide.service        ?? "",
    versionPattern: guide.versionPattern ?? "",
    targetVersion:  guide.targetVersion  ?? "",
    guideUrl:       guide.guideUrl       ?? "",
    summary:        guide.summary        ?? "",
    testedInLab:    guide.testedInLab    ?? false,
    status:         guide.status         ?? "DRAFT",
  });
  const [error, setError] = useState("");

  function set(k, v) { setForm(f => ({ ...f, [k]: v })); setError(""); }

  async function submit(e) {
    e.preventDefault();
    setError("");
    const payload = isNew ? form : { ...form, id: guide.id };
    const err = await onSave(payload);
    if (err) setError(err);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 overflow-y-auto">
      <div className="relative my-4 w-full max-w-xl rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 px-6 pt-6 pb-4 border-b border-slate-100">
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-indigo-500">
              {isNew ? "Add Guide" : "Edit Guide"}
            </p>
            <h2 className="mt-1 text-lg font-extrabold text-slate-900">
              {isNew ? "New Upgrade Guide" : form.title || "Edit Guide"}
            </h2>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={submit} className="px-6 py-5 space-y-4">
          {/* Title */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Guide Title *</label>
            <input value={form.title} onChange={e => set("title", e.target.value)}
              placeholder="Upgrade Lambda Node.js 18.x to Node.js 22.x"
              className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200" />
          </div>

          {/* Service + Version Pattern */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1">Service *</label>
              <AppSelect
                value={form.service}
                options={GUIDE_SERVICE_OPTIONS}
                onChange={val => set("service", val)}
                size="lg"
                fullWidth
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-600 mb-1">Version Pattern</label>
              <input value={form.versionPattern} onChange={e => set("versionPattern", e.target.value)}
                placeholder="nodejs18.x  /  python3.*  /  *"
                className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200" />
              <p className="mt-1 text-[11px] text-slate-400">Leave blank or * for service-level fallback</p>
            </div>
          </div>

          {/* Target Version */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Target Version</label>
            <input value={form.targetVersion} onChange={e => set("targetVersion", e.target.value)}
              placeholder="nodejs22.x"
              className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200" />
          </div>

          {/* Guide URL */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Guide URL *</label>
            <input value={form.guideUrl} onChange={e => set("guideUrl", e.target.value)}
              placeholder="https://cloudkeeper.com/blog/..."
              type="url"
              className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200" />
          </div>

          {/* Summary */}
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Summary</label>
            <textarea value={form.summary} onChange={e => set("summary", e.target.value)}
              rows={3} placeholder="Brief description shown in Resource Detail…"
              className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 resize-none" />
          </div>

          {/* Tested in lab + Status */}
          <div className="flex items-center justify-between gap-4">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input type="checkbox" checked={form.testedInLab} onChange={e => set("testedInLab", e.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-400" />
              <span className="text-sm font-semibold text-slate-700">Tested in lab</span>
            </label>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-slate-500">Status:</span>
              <AppSelect
                value={form.status}
                options={GUIDE_STATUS_OPTIONS}
                onChange={val => set("status", val)}
                size="sm"
              />
            </div>
          </div>

          {error && (
            <div className="rounded-xl bg-red-50 border border-red-100 px-4 py-2.5 text-sm text-red-700 flex gap-2">
              <AlertTriangle size={15} className="shrink-0 mt-px" /> {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50">
              Cancel
            </button>
            <button type="submit" disabled={busy}
              className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-bold text-white hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed">
              {busy ? "Saving…" : isNew ? "Create Guide" : "Save Changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function DeleteGuideModal({ guide, busy, onCancel, onConfirm }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <h2 className="text-lg font-extrabold text-slate-900">Delete guide?</h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-500">
          This will permanently remove <strong>{guide.title}</strong>. Published guides will immediately
          stop appearing in Resource Detail across all workspaces.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50">
            Cancel
          </button>
          <button type="button" onClick={onConfirm} disabled={busy}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50">
            {busy ? "Deleting…" : "Delete Guide"}
          </button>
        </div>
      </div>
    </div>
  );
}

function UpgradeGuidesTab() {
  const [guides,      setGuides]      = useState([]);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState("");
  const [editGuide,   setEditGuide]   = useState(null);   // null=closed, {}=new, {...}=edit
  const [delTarget,   setDelTarget]   = useState(null);
  const [busySave,    setBusySave]    = useState(false);
  const [busyDelete,  setBusyDelete]  = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const { ok, status, data } = await adminFetch("/admin/upgrade-guides");
      if (!ok) setError(apiError(data, status, "Failed to load guides"));
      else     setGuides(data.guides || []);
    } catch {
      setError("Could not reach the server.");
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleSave(formData) {
    setBusySave(true);
    const isNew  = !formData.id;
    const path   = isNew ? "/admin/upgrade-guides" : `/admin/upgrade-guides/${formData.id}`;
    const method = isNew ? "POST" : "PATCH";
    const { ok, status, data } = await adminFetch(path, { method, body: JSON.stringify(formData) });
    setBusySave(false);
    if (!ok) return apiError(data, status, "Save failed");
    setEditGuide(null);
    load();
    return null;
  }

  async function handleDelete() {
    setBusyDelete(true);
    const { ok, status, data } = await adminFetch(`/admin/upgrade-guides/${delTarget.id}`, { method: "DELETE" });
    setBusyDelete(false);
    setDelTarget(null);
    if (!ok) setError(apiError(data, status, "Delete failed"));
    else     setGuides(prev => prev.filter(g => g.id !== delTarget.id));
  }

  async function handleToggleStatus(guide) {
    const newStatus = guide.status === "PUBLISHED" ? "DRAFT" : "PUBLISHED";
    const { ok, status, data } = await adminFetch(`/admin/upgrade-guides/${guide.id}`, {
      method: "PATCH",
      body:   JSON.stringify({ status: newStatus }),
    });
    if (ok) setGuides(prev => prev.map(g => g.id === guide.id ? { ...g, status: newStatus } : g));
    else    setError(apiError(data, status, "Status update failed"));
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-bold text-slate-900">Upgrade Guides</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Global CK guides. Published guides appear in Resource Detail across all workspaces.
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={load}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50">
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
          <button type="button" onClick={() => setEditGuide({})}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2 text-sm font-bold text-white hover:bg-slate-800 transition-colors">
            + Add Guide
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* Table */}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <div>
            {[...Array(4)].map((_, i) => (
              <div key={i} className="flex gap-4 border-b border-slate-100 px-4 py-4 last:border-0">
                {[...Array(7)].map((__, j) => <div key={j} className="h-4 flex-1 animate-pulse rounded bg-slate-100" />)}
              </div>
            ))}
          </div>
        ) : guides.length === 0 ? (
          <div className="py-14 text-center">
            <BookOpen size={26} className="mx-auto mb-3 text-slate-300" strokeWidth={1.5} />
            <p className="text-sm font-semibold text-slate-500">No upgrade guides yet</p>
            <p className="text-xs text-slate-400 mt-1">Add a guide to make it appear in Resource Detail.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-[1000px] w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50">
                  {["Title","Service","Version Pattern","Target","Lab","Status","Updated","Actions"].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-[11px] font-bold uppercase tracking-wide text-slate-500 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {guides.map(g => {
                  const sc = GUIDE_STATUS_CFG[g.status] ?? GUIDE_STATUS_CFG.DRAFT;
                  return (
                    <tr key={g.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70">
                      <td className="px-4 py-3 font-semibold text-slate-900 max-w-[220px]">
                        <span className="block truncate" title={g.title}>{g.title}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-bold text-indigo-700">{g.service}</span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">
                        {g.versionPattern || <span className="text-slate-300">*</span>}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">
                        {g.targetVersion || "—"}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {g.testedInLab
                          ? <span className="text-emerald-600 font-bold text-sm">✓</span>
                          : <span className="text-slate-300 text-sm">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-bold ${sc.cls}`}>{sc.label}</span>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-400 whitespace-nowrap">
                        {fmtDate(g.updatedAt)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <button type="button" onClick={() => setEditGuide(g)}
                            className="h-7 rounded-lg border border-slate-200 px-2 text-xs font-semibold text-slate-600 hover:bg-slate-50 inline-flex items-center gap-1">
                            <Edit2 size={10} /> Edit
                          </button>
                          <button type="button" onClick={() => handleToggleStatus(g)}
                            className={`h-7 rounded-lg border px-2 text-xs font-semibold inline-flex items-center gap-1 ${
                              g.status === "PUBLISHED"
                                ? "border-amber-200 text-amber-700 hover:bg-amber-50"
                                : "border-emerald-200 text-emerald-700 hover:bg-emerald-50"
                            }`}>
                            {g.status === "PUBLISHED" ? "Unpublish" : "Publish"}
                          </button>
                          {g.guideUrl && (
                            <a href={g.guideUrl} target="_blank" rel="noopener noreferrer"
                              className="h-7 rounded-lg border border-slate-200 px-2 text-xs font-semibold text-slate-600 hover:bg-slate-50 inline-flex items-center gap-1">
                              <Globe size={10} /> Preview
                            </a>
                          )}
                          <button type="button" onClick={() => setDelTarget(g)}
                            className="h-7 rounded-lg border border-red-100 px-2 text-xs font-semibold text-red-600 hover:bg-red-50 inline-flex items-center gap-1">
                            <Trash2 size={10} /> Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {!loading && guides.length > 0 && (
        <p className="text-xs text-slate-400">
          {guides.length} guide{guides.length !== 1 ? "s" : ""} ·{" "}
          {guides.filter(g => g.status === "PUBLISHED").length} published
        </p>
      )}

      {editGuide !== null && (
        <GuideFormModal guide={editGuide} busy={busySave}
          onClose={() => setEditGuide(null)} onSave={handleSave} />
      )}
      {delTarget && (
        <DeleteGuideModal guide={delTarget} busy={busyDelete}
          onCancel={() => setDelTarget(null)} onConfirm={handleDelete} />
      )}
    </div>
  );
}

// ── Admin dashboard ───────────────────────────────────────────────────────────

function AdminDashboard() {
  const [workspaces, setWorkspaces] = useState([]);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState("");
  const [activeTab,  setActiveTab]  = useState("workspaces");
  const [search,     setSearch]     = useState("");
  const [confirm,    setConfirm]    = useState(null);
  const [busy,       setBusy]       = useState(false);
  const [newToken,   setNewToken]   = useState(null);
  const [detail,     setDetail]     = useState(null);
  // Lightweight stats fetched from /admin/system
  const [stats,      setStats]      = useState(null);
  const expiry = getAdminSessionExpiry();

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [wsRes, sysRes] = await Promise.all([
        adminFetch("/admin/workspaces"),
        adminFetch("/admin/system"),
      ]);
      if (!wsRes.ok) setError(wsRes.data?.error?.message || wsRes.data?.error || "Failed to load workspaces.");
      else setWorkspaces(wsRes.data.workspaces || []);
      if (sysRes.ok) setStats(sysRes.data);
    } catch {
      setError("Could not reach the server.");
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return workspaces;
    return workspaces.filter(ws =>
      (ws.name || "").toLowerCase().includes(q) ||
      (ws.id   || "").toLowerCase().includes(q)
    );
  }, [workspaces, search]);

  const totals = useMemo(() => ({
    workspaces: workspaces.length,
    accounts:   workspaces.reduce((n, ws) => n + Number(ws.account_count || 0), 0),
    scans:      stats?.scanRuns?.total,
    failed:     stats?.scanRuns?.failed,
    eolCache:   fmtDateParts(stats?.eolCache?.refreshedAt),
  }), [workspaces, stats]);

  async function handleRotate(ws) {
    setBusy(true);
    const { ok, data } = await adminFetch(`/admin/workspaces/${ws.id}/rotate-token`, { method: "POST" });
    setBusy(false); setConfirm(null);
    if (ok) { setNewToken({ token: data.token, workspaceId: ws.id, workspaceName: ws.name }); load(); }
    else    { setError(data?.error?.message || data?.error || "Rotate token failed."); }
  }

  async function handleDelete(ws, confirmationText) {
    setBusy(true);
    const qs = confirmationText ? `?confirmation=${encodeURIComponent(confirmationText)}` : "";
    const { ok, data } = await adminFetch(`/admin/workspaces/${ws.id}${qs}`, { method: "DELETE" });
    setBusy(false); setConfirm(null);
    if (ok) setWorkspaces(prev => prev.filter(w => w.id !== ws.id));
    else    setError(data?.error?.message || data?.error || "Delete workspace failed.");
  }

  function signOut() { clearAdminSession(); window.location.reload(); }

  return (
    <div className="min-h-screen" style={{ background: "#F0F4F8" }}>
      {/* Top bar */}
      <div className="border-b border-slate-200 bg-white">
        <div className={`${ADMIN_CONTAINER} flex items-center justify-between gap-4 py-4`}>
          <div className="flex items-center gap-3">
            <CloudCog size={22} className="text-sky-500" strokeWidth={1.5} />
            <div>
              <p className="text-sm font-bold text-slate-900">AWS EOL Monitor</p>
              <p className="text-xs text-slate-400">Internal Admin</p>
            </div>
          </div>
        </div>
      </div>

      <main className={`${ADMIN_CONTAINER} py-8`}>
        {/* Page title */}
        <div className="mb-7 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.24em] text-indigo-500">Internal Admin</p>
            <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-slate-900">Admin Console</h1>
            <p className="mt-1 text-sm text-slate-500">Internal workspace and scan operations</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <span className="inline-flex h-10 items-center gap-1.5 text-xs font-medium text-slate-500">
              <Clock size={12} strokeWidth={1.75} />
              Session {fmtExpiry(expiry)}
            </span>
            <button type="button" onClick={load}
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 text-sm font-semibold text-slate-600 shadow-sm hover:bg-slate-50">
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh
            </button>
            <button type="button" onClick={signOut}
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 text-sm font-semibold text-slate-600 shadow-sm hover:bg-slate-50">
              <LogOut size={14} /> Clear session
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-6 flex items-center gap-2 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
            <AlertTriangle size={15} /> {error}
          </div>
        )}

        {/* Overview cards */}
        <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <StatCard label="Total Workspaces"   value={totals.workspaces} Icon={CloudCog}      tone="blue"  />
          <StatCard label="Connected Accounts" value={totals.accounts}   Icon={Server}                    />
          <StatCard label="Total Scan Runs"    value={totals.scans}      Icon={Activity}                  />
          <StatCard label="Failed Scans"       value={totals.failed}     Icon={AlertTriangle} tone={totals.failed > 0 ? "red" : "slate"} />
          <StatCard
            label="Last EOL Refresh"
            value={totals.eolCache ? (
              <span className="block">
                <span className="block">{totals.eolCache.date}</span>
                <span className="mt-1 block">{totals.eolCache.time}</span>
              </span>
            ) : "—"}
            Icon={Database}
            tone="green"
            compact
          />
        </div>

        {/* Tab bar */}
        <div className="mb-5 rounded-2xl border border-slate-200 bg-white p-1.5 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex overflow-x-auto">
              {TABS.map(tab => (
                <button key={tab.key} type="button" onClick={() => setActiveTab(tab.key)}
                  className={`h-10 whitespace-nowrap rounded-xl px-4 text-sm font-bold transition-colors ${
                    activeTab === tab.key ? "bg-slate-950 text-white shadow-sm" : "text-slate-600 hover:bg-slate-50"
                  }`}>
                  {tab.label}
                </button>
              ))}
            </div>
            {activeTab === "workspaces" && (
              <div className="relative w-full lg:w-[300px]">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input value={search} onChange={e => setSearch(e.target.value)}
                  placeholder="Search workspaces..."
                  className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 pl-8 pr-3 text-sm focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200" />
              </div>
            )}
          </div>
        </div>

        {/* Tab content */}
        {activeTab === "workspaces" && (
          <WorkspacesTable workspaces={filtered} loading={loading}
            onView={setDetail}
            onRotate={ws => setConfirm({ type: "rotate", workspace: ws })}
            onDelete={ws => setConfirm({ type: "delete", workspace: ws })} />
        )}
        {activeTab === "scans"  && <ScanRunsTab />}
        {activeTab === "system" && <SystemTab />}
        {activeTab === "guides" && <UpgradeGuidesTab />}

        <div className="mt-5 flex items-start gap-2 rounded-2xl border border-slate-200/80 bg-white/65 px-4 py-3 text-xs text-slate-500 shadow-sm">
          <Shield size={13} strokeWidth={1.5} className="mt-0.5 shrink-0" />
          <span>Workspace tokens are shown only once after rotation. Admin actions require X-Admin-Token.</span>
        </div>
      </main>

      {confirm && (
        <ConfirmModal
          type={confirm.type}
          workspace={confirm.workspace}
          busy={busy}
          onCancel={() => setConfirm(null)}
          onConfirm={(text) => confirm.type === "delete"
            ? handleDelete(confirm.workspace, text)
            : handleRotate(confirm.workspace)
          }
        />
      )}
      <NewTokenPanel
        token={newToken?.token}
        workspaceId={newToken?.workspaceId}
        workspaceName={newToken?.workspaceName}
        onClose={() => setNewToken(null)}
      />
      <WorkspaceDetailDrawer workspace={detail} onClose={() => setDetail(null)} />
    </div>
  );
}

// ── Page root ─────────────────────────────────────────────────────────────────

export default function InternalAdminPage() {
  const [authed, setAuthed] = useState(hasAdminSession());
  return authed ? <AdminDashboard /> : <AdminAccessForm onSuccess={() => setAuthed(true)} />;
}
