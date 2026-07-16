import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Server, Plus, RefreshCw, Trash2, Settings2, ChevronRight,
  CheckCircle, AlertCircle, Clock, Loader2, Copy, Check, X, History,
} from "lucide-react";
import { isDemoEnabled } from "../utils/config";
import { isDemoWorkspace, hasMemberSession, getMemberRole } from "../utils/workspace";
import { MOCK_CONNECTED_ACCOUNTS } from "../mocks/mockAccountScanData";
import {
  loadAccounts, saveAccounts, removeAccount, updateAccount, regionScopeLabel,
  fetchAccountsFromServer, saveAccountToServer, updateAccountOnServer, deleteAccountFromServer,
  startScanOnServer, getScanStatus, normalizeScanSummary,
} from "../utils/connectedAccounts";
import { copyToClipboard } from "../utils/clipboard";
import { useAccountScanRuns } from "../hooks/useScans";

const AWS_REGIONS = [
  { value: "us-east-1",      label: "us-east-1 (N. Virginia)"    },
  { value: "us-east-2",      label: "us-east-2 (Ohio)"           },
  { value: "us-west-1",      label: "us-west-1 (N. California)"  },
  { value: "us-west-2",      label: "us-west-2 (Oregon)"         },
  { value: "ap-south-1",     label: "ap-south-1 (Mumbai)"        },
  { value: "ap-southeast-1", label: "ap-southeast-1 (Singapore)" },
  { value: "ap-southeast-2", label: "ap-southeast-2 (Sydney)"    },
  { value: "ap-northeast-1", label: "ap-northeast-1 (Tokyo)"     },
  { value: "eu-west-1",      label: "eu-west-1 (Ireland)"        },
  { value: "eu-west-2",      label: "eu-west-2 (London)"         },
  { value: "eu-central-1",   label: "eu-central-1 (Frankfurt)"   },
  { value: "ca-central-1",   label: "ca-central-1 (Canada)"      },
  { value: "sa-east-1",      label: "sa-east-1 (São Paulo)"      },
];

const DEMO_RESULT  = { total: 28, EOL: 8, EXPIRING_SOON: 8, EXTENDED_SUPPORT: 4, SUPPORTED: 7, UNKNOWN: 1 };
const EMPTY_RESULT = { total: 0,  EOL: 0, EXPIRING_SOON: 0, EXTENDED_SUPPORT: 0, SUPPORTED: 0, UNKNOWN: 0 };

const SCAN_ERROR_MESSAGES = {
  ASSUME_ROLE_FAILED:    "Could not assume the IAM role. Verify the role ARN, external ID, and trust policy.",
  ACCESS_DENIED:         "Access denied. Check that the IAM role has the required permissions.",
  SERVICE_ACCESS_DENIED: "IAM role assumed, but one or more services were inaccessible. Check service-level IAM permissions.",
  SCAN_FAILED:           "Scan failed due to an unexpected error.",
};

// ── Copy button with visible label ────────────────────────────────────────────

function CopyBtn({ value, label }) {
  const [copied, setCopied] = useState(false);
  async function copy(e) {
    e.stopPropagation();
    const ok = await copyToClipboard(value);
    if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2000); }
  }
  return (
    <button
      onClick={copy}
      aria-label={`Copy ${label ?? "value"}`}
      className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
        copied
          ? "bg-emerald-50 text-emerald-600"
          : "bg-gray-100 text-gray-500 hover:bg-gray-200 hover:text-gray-700"
      }`}
    >
      {copied
        ? <><Check size={11} strokeWidth={2.5} /> Copied</>
        : <><Copy size={11} strokeWidth={1.75} /> Copy</>}
    </button>
  );
}

// ── Status pill ───────────────────────────────────────────────────────────────

function ScanStatusPill({ status, isScanning }) {
  if (isScanning) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold text-blue-700">
        <Loader2 size={11} strokeWidth={2} className="animate-spin" />
        Scanning…
      </span>
    );
  }
  const cfg = {
    success: { cls: "bg-emerald-100 text-emerald-700", Icon: CheckCircle, label: "Connected"    },
    failed:  { cls: "bg-red-100 text-red-700",         Icon: AlertCircle, label: "Scan Failed"  },
  }[status] ?? { cls: "bg-gray-100 text-gray-500", Icon: Clock, label: "Never Scanned" };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.cls}`}>
      <cfg.Icon size={11} strokeWidth={2} />
      {cfg.label}
    </span>
  );
}

// ── Scan summary pills ────────────────────────────────────────────────────────

function CountPill({ value, label, color }) {
  const cls = {
    red:   "bg-red-50   text-red-700",
    amber: "bg-amber-50 text-amber-700",
    blue:  "bg-blue-50  text-blue-700",
    green: "bg-green-50 text-green-700",
  }[color] ?? "bg-gray-100 text-gray-500";
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-bold ${cls}`}>
      <span>{value}</span>
      <span className="font-normal opacity-75">{label}</span>
    </span>
  );
}

// ── Account card ──────────────────────────────────────────────────────────────

function AccountCard({ account, isScanning, scanProgressMsg, onViewResults, onRescan, onEditRegions, onDelete, onHistory, canScan, canAdmin }) {
  const sum   = normalizeScanSummary(account.lastScanSummary);
  const total = sum ? (sum.total || 0) : 0;

  const lastScanLabel = account.lastScanAt
    ? new Date(account.lastScanAt).toLocaleString("en-GB", {
        day: "2-digit", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit",
        timeZone: "UTC",
      }) + " UTC"
    : "Never";

  const scanTotalLabel = !account.lastScanAt
    ? null
    : total === 0
    ? "No resources found"
    : `(${total} total)`;

  const btnLabel = isScanning
    ? "Scanning…"
    : account.lastScanAt
    ? "Run Scan Again"
    : "Run First Scan";

  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      {/* ── Card header ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-start justify-between gap-4 px-4 sm:px-6 py-4 sm:py-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <h3 className="text-lg font-extrabold text-slate-900 leading-tight">{account.accountName}</h3>
            <ScanStatusPill status={account.lastScanStatus} isScanning={isScanning} />
          </div>
          <p className="text-sm font-mono text-slate-400">{account.accountId}</p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Last scan</p>
          <p className="mt-0.5 text-sm font-semibold text-slate-700">
            {isScanning ? "Scanning…" : lastScanLabel}
          </p>
        </div>
      </div>

      {/* ── Connection details ───────────────────────────────────────────────── */}
      <div className="border-t border-slate-100 px-4 sm:px-6 py-5 space-y-3.5">
        {canAdmin && (
          <>
            <div className="grid items-center gap-3" style={{ gridTemplateColumns: "7rem 1fr auto" }}>
              <span className="text-xs text-slate-400 font-medium">Role ARN</span>
              <code className="text-xs font-mono font-semibold text-slate-700 truncate" title={account.roleArn}>
                {account.roleArn}
              </code>
              <CopyBtn value={account.roleArn} label="Role ARN" />
            </div>
            <div className="grid items-center gap-3" style={{ gridTemplateColumns: "7rem 1fr auto" }}>
              <span className="text-xs text-slate-400 font-medium">ExternalId</span>
              <code className="text-xs font-mono font-semibold text-slate-700 truncate" title={account.externalId}>
                {account.externalId}
              </code>
              <CopyBtn value={account.externalId} label="ExternalId" />
            </div>
          </>
        )}
        <div className="grid items-center gap-3" style={{ gridTemplateColumns: "7rem 1fr" }}>
          <span className="text-xs text-slate-400 font-medium">Regions</span>
          <span className="text-xs font-semibold text-slate-700">{regionScopeLabel(account)}</span>
        </div>
      </div>

      {/* ── Scan summary ─────────────────────────────────────────────────────── */}
      <div className="border-t border-slate-100 px-6 py-4">
        {sum ? (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-slate-400 font-medium mr-1">Scan</span>
            {(sum.EOL || 0) > 0 && <CountPill value={sum.EOL} label="EOL" color="red" />}
            {(sum.EXPIRING_SOON || 0) > 0 && <CountPill value={sum.EXPIRING_SOON} label="Expiring" color="amber" />}
            {(sum.EXTENDED_SUPPORT || 0) > 0 && <CountPill value={sum.EXTENDED_SUPPORT} label="Ext." color="blue" />}
            {(sum.SUPPORTED || 0) > 0 && <CountPill value={sum.SUPPORTED} label="Supported" color="green" />}
            {(sum.UNKNOWN || 0) > 0 && <CountPill value={sum.UNKNOWN} label="Unknown" color="gray" />}
            {(sum.NEEDS_INSPECTION || 0) > 0 && <CountPill value={sum.NEEDS_INSPECTION} label="Needs Inspection" color="gray" />}
            {(sum.LIFECYCLE_NOT_TRACKED || 0) > 0 && <CountPill value={sum.LIFECYCLE_NOT_TRACKED} label="Not Tracked" color="gray" />}
            {total === 0 && <span className="text-xs text-slate-400 italic">No resources found</span>}
            {total > 0 && (
              <span className="text-xs text-slate-400 ml-1">({total} total)</span>
            )}
          </div>
        ) : (
          <p className="text-xs text-slate-400 italic">
            No scan data yet · Run first scan to see results
          </p>
        )}
      </div>

      {/* ── Scan progress ─────────────────────────────────────────────────────── */}
      {isScanning && scanProgressMsg && (
        <div className="mx-6 mb-3 flex items-center gap-2 rounded-lg bg-blue-50 ring-1 ring-blue-100 px-3 py-2 text-xs text-blue-700">
          <Loader2 size={11} strokeWidth={2} className="animate-spin shrink-0" />
          {scanProgressMsg}
        </div>
      )}

      {/* ── Scan error ───────────────────────────────────────────────────────── */}
      {!isScanning && account.lastScanStatus === "failed" && (
        <div className="mx-6 mb-3 rounded-lg bg-red-50 ring-1 ring-red-200 px-3 py-2 text-xs text-red-700">
          <span className="font-semibold">Scan failed: </span>
          {SCAN_ERROR_MESSAGES[account.lastScanErrorCode] || account.lastScanError || "An unexpected error occurred."}
          {account.lastScanId && (
            <span className="ml-1.5 font-mono opacity-50">ID: {account.lastScanId}</span>
          )}
        </div>
      )}

      {/* ── Actions ──────────────────────────────────────────────────────────── */}
      <div className="border-t border-slate-100 flex items-center gap-2.5 px-4 sm:px-6 py-4 sm:py-5 flex-wrap">
        <button
          onClick={onViewResults}
          disabled={!sum || isScanning}
          className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-2 text-xs font-bold text-white transition-colors hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          View Results <ChevronRight size={13} strokeWidth={2.5} />
        </button>
        {canScan && (
          <button
            onClick={onRescan}
            disabled={isScanning}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <RefreshCw size={12} strokeWidth={2} className={isScanning ? "animate-spin" : ""} />
            {btnLabel}
          </button>
        )}
        {canAdmin && (
          <button
            onClick={onEditRegions}
            disabled={isScanning}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Settings2 size={12} strokeWidth={2} />
            Edit Regions
          </button>
        )}
        <button
          onClick={onHistory}
          disabled={isScanning}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <History size={12} strokeWidth={2} />
          History
        </button>
        {canAdmin && (
          <button
            onClick={onDelete}
            disabled={isScanning || isDemoWorkspace()}
            title={isDemoWorkspace() ? "Not available in demo workspace" : undefined}
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-red-100 px-3.5 py-2 text-xs font-semibold text-red-500 transition-colors hover:bg-red-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Trash2 size={12} strokeWidth={2} />
            Delete
          </button>
        )}
      </div>
    </div>
  );
}

// ── Delete confirmation modal ─────────────────────────────────────────────────

function DeleteModal({ account, onConfirm, onCancel }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md space-y-4 rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-red-100">
            <Trash2 size={18} className="text-red-600" strokeWidth={2} />
          </div>
          <div className="min-w-0">
            <h3 className="font-bold text-slate-900">Delete this account connection?</h3>
            <p className="text-sm text-slate-500 truncate">
              {account.accountName} · {account.accountId}
            </p>
          </div>
        </div>
        <div className="rounded-xl bg-amber-50 px-4 py-3 text-xs text-amber-800 ring-1 ring-amber-100 space-y-1.5">
          <p className="font-semibold">This will:</p>
          <ul className="list-inside list-disc space-y-0.5 text-amber-700">
            <li>Remove the saved connection and scan history from AWS EOL Monitor.</li>
            <li>Not delete the IAM role from your AWS account.</li>
          </ul>
        </div>
        <p className="text-xs text-slate-500">
          To fully revoke access, delete the CloudFormation stack or IAM role from your AWS account.
        </p>
        <div className="flex justify-end gap-2 pt-1">
          <button
            onClick={onCancel}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 transition-colors"
          >
            Delete Connection
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Edit regions modal ────────────────────────────────────────────────────────

function EditRegionsModal({ account, onSave, onCancel }) {
  const initMode = account.scanAllRegions === true ? "all"
    : Array.isArray(account.regions)
      ? (account.regions.length === 0 ? "all" : account.regions.length === 1 ? "single" : "selected")
      : (account.regions || "all");
  const initSingle = Array.isArray(account.regions) && account.regions.length === 1
    ? account.regions[0]
    : (account.singleRegion || "us-east-1");
  const initSelected = Array.isArray(account.regions) && account.regions.length > 1
    ? account.regions
    : (account.selectedRegions || []);

  const [mode, setMode]         = useState(initMode);
  const [single, setSingle]     = useState(initSingle);
  const [selected, setSelected] = useState(initSelected);
  const [saving, setSaving]     = useState(false);

  function toggle(r) {
    setSelected(prev => prev.includes(r) ? prev.filter(x => x !== r) : [...prev, r]);
  }

  async function handleSave() {
    if (!canSave || saving) return;
    setSaving(true);
    const patch = mode === "all"
      ? { regions: [], scanAllRegions: true }
      : mode === "single"
      ? { regions: [single].filter(Boolean), scanAllRegions: false }
      : { regions: selected, scanAllRegions: false };
    try {
      await Promise.resolve(onSave(patch));
    } finally {
      setSaving(false);
    }
  }

  const regionName = r => r.label.split("(")[1]?.replace(")", "") ?? r.label;
  const selectedCount = mode === "all" ? AWS_REGIONS.length : mode === "single" ? (single ? 1 : 0) : selected.length;
  const canClear = mode !== "all" && selectedCount > 0;
  const canSave = mode === "all" || (mode === "single" ? Boolean(single) : selected.length > 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="flex max-h-[85vh] w-full max-w-xl flex-col rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 px-6 pb-4 pt-6">
          <div>
            <h3 className="text-lg font-extrabold tracking-tight text-slate-950">Edit Region Scope</h3>
            <p className="mt-1 text-sm font-medium text-slate-500">{account.accountName} · {account.accountId}</p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Close region scope modal"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-300"
          >
            <X size={18} strokeWidth={2.25} />
          </button>
        </div>

        <div className="mx-6 grid grid-cols-3 gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1">
          {[
            { v: "all",      label: "All regions"    },
            { v: "single",   label: "Single region"  },
            { v: "selected", label: "Select regions" },
          ].map(o => (
            <button key={o.v}
              type="button"
              onClick={() => { setMode(o.v); setSelected([]); }}
              className={`h-11 rounded-lg px-2 text-sm font-bold transition-all focus:outline-none focus:ring-2 focus:ring-indigo-300 ${
                mode === o.v
                  ? "bg-slate-950 text-white shadow-sm"
                  : "bg-white text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              }`}>
              {o.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {mode === "all" && (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-600">
              All enabled AWS regions will be scanned. This may take longer in large accounts.
            </div>
          )}

          {mode === "single" && (
            <div className="space-y-3">
              <p className="text-xs font-medium text-slate-500">Only one region will be scanned.</p>
              <div className="max-h-64 space-y-2 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-2">
                {AWS_REGIONS.map(r => {
                  const checked = single === r.value;
                  return (
                    <button
                      key={r.value}
                      type="button"
                      onClick={() => setSingle(r.value)}
                      className={`flex w-full items-center gap-3 rounded-xl border px-3 py-3 text-left transition focus:outline-none focus:ring-2 focus:ring-indigo-300 ${
                        checked
                          ? "border-indigo-200 bg-indigo-50"
                          : "border-slate-200 bg-white hover:bg-slate-50"
                      }`}
                    >
                      <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                        checked ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-300 bg-white"
                      }`}>
                        {checked && <Check size={11} strokeWidth={3} />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className={`block text-sm font-semibold leading-tight ${checked ? "text-indigo-800" : "text-slate-900"}`}>
                          {r.value}
                        </span>
                        <span className="mt-0.5 block text-xs text-slate-500">{regionName(r)}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {mode === "selected" && (
            <div className="max-h-72 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-2">
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {AWS_REGIONS.map(r => {
                  const checked = selected.includes(r.value);
                  return (
                    <button key={r.value}
                      type="button"
                      onClick={() => toggle(r.value)}
                      className={`flex w-full items-start gap-3 rounded-xl border px-3 py-3 text-left transition focus:outline-none focus:ring-2 focus:ring-indigo-300 ${
                        checked ? "border-indigo-200 bg-indigo-50" : "border-slate-200 bg-white hover:bg-slate-50"
                      }`}>
                      <input type="checkbox" checked={checked} readOnly
                        className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer accent-indigo-600" />
                      <span className="min-w-0">
                        <span className={`block text-sm font-semibold leading-tight ${checked ? "text-indigo-800" : "text-slate-900"}`}>
                          {r.value}
                        </span>
                        <span className="mt-0.5 block text-xs text-slate-500">{regionName(r)}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-slate-100 px-6 py-3">
          <p className={`text-sm font-medium ${canSave ? "text-slate-600" : "text-amber-600"}`}>
            {canSave
              ? `${selectedCount} region${selectedCount !== 1 ? "s" : ""} selected`
              : mode === "single" ? "Select one region." : "Select at least one region."}
          </p>
          {canClear && (
            <button
              type="button"
              onClick={() => mode === "single" ? setSingle("") : setSelected([])}
              className="text-sm font-semibold text-slate-500 transition-colors hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-300"
            >
              Clear
            </button>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4">
          <button type="button" onClick={onCancel}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-indigo-300">
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!canSave || saving}
            className="rounded-lg bg-slate-950 px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-50">
            {saving ? "Saving..." : "Save Regions"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Scan history modal ────────────────────────────────────────────────────────

const DEMO_SCAN_HISTORY = [
  {
    scanId:      "scan_demo_1",
    status:      "SUCCESS",
    startedAt:   new Date(Date.now() - 2 * 3_600_000).toISOString(),
    completedAt: new Date(Date.now() - 2 * 3_600_000 + 90_000).toISOString(),
    summary:     { total: 28, eol: 8, expiringSoon: 8, extendedSupport: 4, supported: 7, unknown: 1 },
    regions:     ["us-east-1"],
  },
  {
    scanId:      "scan_demo_2",
    status:      "FAILED",
    startedAt:   new Date(Date.now() - 26 * 3_600_000).toISOString(),
    completedAt: new Date(Date.now() - 26 * 3_600_000 + 5_000).toISOString(),
    error:       "AccessDenied: User is not authorized to call sts:AssumeRole",
    regions:     ["us-east-1"],
  },
  {
    scanId:      "scan_demo_3",
    status:      "SUCCESS",
    startedAt:   new Date(Date.now() - 3 * 86_400_000).toISOString(),
    completedAt: new Date(Date.now() - 3 * 86_400_000 + 75_000).toISOString(),
    summary:     { total: 25, eol: 7, expiringSoon: 7, extendedSupport: 3, supported: 7, unknown: 1 },
    regions:     ["us-east-1", "us-west-2"],
  },
];

function scanDuration(run) {
  if (!run.startedAt || !run.completedAt) return "—";
  const secs = Math.round(
    (new Date(run.completedAt) - new Date(run.startedAt)) / 1000
  );
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

const STATUS_CFG = {
  SUCCESS:         { cls: "bg-emerald-100 text-emerald-700", label: "Success"        },
  PARTIAL_SUCCESS: { cls: "bg-amber-100 text-amber-700",   label: "Partial"         },
  FAILED:          { cls: "bg-red-100 text-red-700",        label: "Failed"          },
  RUNNING:         { cls: "bg-blue-100 text-blue-700",      label: "Running"         },
  QUEUED:          { cls: "bg-slate-100 text-slate-600",    label: "Queued"          },
};

function ScanHistoryModal({ account, onClose }) {
  const { data: runs = [], isLoading } = useAccountScanRuns(
    isDemoEnabled() ? null : account.id,
    20,
    !isDemoEnabled()
  );
  const displayRuns = isDemoEnabled() ? DEMO_SCAN_HISTORY : runs;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 overflow-y-auto">
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl mt-12 mb-12">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 px-6 pt-6 pb-4 border-b border-slate-100">
          <div>
            <h3 className="text-base font-extrabold text-slate-900">Scan History</h3>
            <p className="text-xs text-slate-400 mt-0.5">
              {account.accountName} · {account.accountId}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
          >
            <X size={16} strokeWidth={2} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-3 max-h-[60vh] overflow-y-auto">
          {isLoading && !isDemoEnabled() ? (
            <div className="space-y-2">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-16 rounded-xl bg-slate-100 animate-pulse" />
              ))}
            </div>
          ) : displayRuns.length === 0 ? (
            <div className="py-12 text-center">
              <Clock size={28} className="mx-auto mb-3 text-slate-300" strokeWidth={1.5} />
              <p className="text-sm text-slate-500 font-semibold">No scan history yet</p>
              <p className="text-xs text-slate-400 mt-1">Run a scan to see history here.</p>
            </div>
          ) : (
            displayRuns.map(run => {
              const sc = STATUS_CFG[run.status] ?? STATUS_CFG.QUEUED;
              const s  = run.summary;
              return (
                <div key={run.scanId} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3.5 space-y-2.5">
                  {/* Row 1: status + time */}
                  <div className="flex items-center justify-between gap-4">
                    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold ${sc.cls}`}>
                      {sc.label}
                    </span>
                    <div className="flex items-center gap-4 text-xs text-slate-400">
                      <span title="Started">
                        {run.startedAt
                          ? new Date(run.startedAt).toLocaleString("en-GB", {
                              day: "2-digit", month: "short", year: "numeric",
                              hour: "2-digit", minute: "2-digit", timeZone: "UTC",
                            }) + " UTC"
                          : "—"}
                      </span>
                      <span className="font-medium text-slate-500">{scanDuration(run)}</span>
                    </div>
                  </div>

                  {/* Row 2: summary pills */}
                  {s && (
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {s.eol > 0              && <span className="rounded-md bg-red-50   text-red-700   px-2 py-0.5 text-xs font-bold">{s.eol} EOL</span>}
                      {s.expiringSoon > 0      && <span className="rounded-md bg-amber-50 text-amber-700 px-2 py-0.5 text-xs font-bold">{s.expiringSoon} Expiring</span>}
                      {s.extendedSupport > 0   && <span className="rounded-md bg-blue-50  text-blue-700  px-2 py-0.5 text-xs font-bold">{s.extendedSupport} Ext.</span>}
                      {s.supported > 0         && <span className="rounded-md bg-green-50 text-green-700 px-2 py-0.5 text-xs font-bold">{s.supported} OK</span>}
                      <span className="text-xs text-slate-400 ml-1">{s.total} total</span>
                    </div>
                  )}

                  {/* Row 3: regions */}
                  {run.regions?.length > 0 && (
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-xs text-slate-400">Regions:</span>
                      {run.regions.map(r => (
                        <span key={r} className="rounded-md bg-white border border-slate-200 px-2 py-0.5 text-xs font-mono text-slate-600">{r}</span>
                      ))}
                    </div>
                  )}

                  {/* Row 4: error */}
                  {run.error && (
                    <p className="text-xs text-red-600 font-mono break-all bg-red-50 rounded-lg px-3 py-2">
                      {run.error}
                    </p>
                  )}

                  {/* Row 5: scan ID */}
                  <p className="text-[10px] font-mono text-slate-300">{run.scanId}</p>
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-100 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ onConnect }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center shadow-sm">
      <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-slate-100">
        <Server size={24} className="text-slate-400" strokeWidth={1.5} />
      </div>
      <h3 className="text-base font-bold text-slate-900 mb-1">No accounts connected yet</h3>
      <p className="text-sm text-slate-500 max-w-xs mx-auto mb-6">
        Connect an AWS account to scan for EOL risks across your resources.
      </p>
      {onConnect ? (
        <button onClick={onConnect}
          className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-slate-700 transition-colors">
          <Plus size={15} strokeWidth={2.5} />
          Connect AWS Account
        </button>
      ) : (
        <p className="text-xs text-slate-400">Ask your workspace admin to connect an AWS account.</p>
      )}
    </div>
  );
}

// ── Page root ─────────────────────────────────────────────────────────────────

export default function ConnectedAccountsPage() {
  const navigate = useNavigate();

  const _memberSession = hasMemberSession();
  const _memberRole    = _memberSession ? getMemberRole() : "ADMIN";
  const canAdmin = !_memberSession || _memberRole === "ADMIN";
  const canScan  = !_memberSession || ["EDITOR", "ADMIN"].includes(_memberRole);

  // Sync init from localStorage — prevents empty-state flash on refresh
  const [accounts, setAccounts]         = useState(() => {
    const list = loadAccounts();
    return !list.length && isDemoEnabled() ? MOCK_CONNECTED_ACCOUNTS : list;
  });
  const [scanningIds, setScanningIds]   = useState(new Set());
  // Map<accountId, progressMessage> — shown inside AccountCard while scanning
  const [scanProgress, setScanProgress] = useState(new Map());
  const [deleteTarget, setDeleteTarget]   = useState(null);
  const [editTarget, setEditTarget]       = useState(null);
  const [historyTarget, setHistoryTarget] = useState(null);

  function refresh() { setAccounts(loadAccounts()); }

  useEffect(() => {
    async function init() {
      // Try server first (cross-browser persistence); fall back to localStorage
      const serverList = await fetchAccountsFromServer();
      if (serverList !== null) {
        saveAccounts(serverList);         // keep localStorage in sync as cache
        setAccounts(serverList);
      } else {
        let list = loadAccounts();
        if (list.length === 0 && isDemoEnabled()) {
          saveAccounts(MOCK_CONNECTED_ACCOUNTS);
          list = MOCK_CONNECTED_ACCOUNTS;
        }
        setAccounts(list);
      }
    }
    init();
  }, []);

  const DONE_SCAN = new Set(["SUCCESS", "FAILED", "PARTIAL_SUCCESS"]);

  function _stopScan(id) {
    setScanningIds(prev => { const s = new Set(prev); s.delete(id); return s; });
    setScanProgress(prev => { const m = new Map(prev); m.delete(id); return m; });
  }

  function _setProgress(id, msg) {
    setScanProgress(prev => new Map(prev).set(id, msg));
  }

  function _applyResult(id, status, summary, error) {
    if (status === "SUCCESS" || status === "PARTIAL_SUCCESS") {
      // Normalize to canonical ALLCAPS shape (handles both camelCase and ALLCAPS API responses)
      updateAccount(id, {
        lastScanAt:      new Date().toISOString(),
        lastScanStatus:  "success",
        lastScanSummary: normalizeScanSummary(summary) ?? {},
        lastScanError:   null,
      });
    } else {
      updateAccount(id, {
        lastScanAt:     new Date().toISOString(),
        lastScanStatus: "failed",
        lastScanError:  error || "Scan failed",
      });
    }
  }

  async function handleRescan(account) {
    const id = account.id;
    setScanningIds(prev => new Set([...prev, id]));
    _setProgress(id, "Starting scan…");

    if (isDemoEnabled()) {
      _setProgress(id, "Scanning resources…");
      setTimeout(() => {
        const patch = {
          lastScanAt:      new Date().toISOString(),
          lastScanStatus:  "success",
          lastScanSummary: DEMO_RESULT,
          lastScanError:   null,
        };
        updateAccount(id, patch);
        updateAccountOnServer(id, patch);
        _stopScan(id);
        refresh();
      }, 2000);
      return;
    }

    // Start scan via new /scans endpoint
    _setProgress(id, "Requesting scan…");
    const result = await startScanOnServer(id);

    if (!result || result.error) {
      if (result?.errorCode === "SCAN_IN_PROGRESS") {
        // Another scan is already running — not a failure. Poll the existing scan.
        const runningScanId = result?.runningScanId;
        _setProgress(id, "Scan already running…");
        if (runningScanId) {
          let attempts = 0;
          const poll = setInterval(async () => {
            attempts++;
            if (attempts > 120) { clearInterval(poll); _stopScan(id); refresh(); return; }
            const run = await getScanStatus(runningScanId);
            if (!run) return;
            if (DONE_SCAN.has(run.status)) {
              clearInterval(poll);
              _applyResult(id, run.status, run.summary, run.error);
              _stopScan(id);
              refresh();
            }
          }, 2500);
        } else {
          setTimeout(() => { _stopScan(id); refresh(); }, 8000);
        }
        return;
      }
      updateAccount(id, {
        lastScanAt:     new Date().toISOString(),
        lastScanStatus: "failed",
        lastScanError:  result?.error || "Scan failed to start",
      });
      _stopScan(id);
      refresh();
      return;
    }

    // Sync scan already returned terminal status (common in Lambda)
    if (DONE_SCAN.has(result.status)) {
      _applyResult(id, result.status, result.summary, result.error);
      _stopScan(id);
      refresh();
      return;
    }

    // Async: poll every 2.5s until terminal status
    const { scanId } = result;
    _setProgress(id, "Scan running…");

    let attempts = 0;
    const poll = setInterval(async () => {
      attempts++;
      if (attempts > 120) {
        clearInterval(poll);
        updateAccount(id, {
          lastScanAt:     new Date().toISOString(),
          lastScanStatus: "failed",
          lastScanError:  "Scan timed out after 5 minutes",
        });
        _stopScan(id);
        refresh();
        return;
      }
      const run = await getScanStatus(scanId);
      if (!run) return;
      if (DONE_SCAN.has(run.status)) {
        clearInterval(poll);
        _applyResult(id, run.status, run.summary, run.error);
        _stopScan(id);
        refresh();
      }
    }, 2500);
  }

  async function handleDelete(id) {
    await deleteAccountFromServer(id);
    removeAccount(id);
    setDeleteTarget(null);
    refresh();
  }

  async function handleEditSave(account, patch) {
    await updateAccountOnServer(account.id, patch);
    updateAccount(account.id, patch);
    setEditTarget(null);
    refresh();
  }

  return (
    <div className="px-4 sm:px-6 py-6 sm:py-8 max-w-7xl mx-auto">
      {/* ── Page header ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-8">
        <div className="min-w-0">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-indigo-500 mb-2">
            Single Account Scan
          </p>
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">
            Connected Accounts
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-500 max-w-lg">
            {canScan
              ? "Manage your connected AWS accounts, view scan results, and trigger new scans."
              : "View connected AWS accounts and scan results in read-only mode."}
          </p>
        </div>
        {canAdmin && (
          <button
            onClick={() => navigate("/account-scan")}
            className="shrink-0 inline-flex items-center gap-2 rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-slate-700 transition-colors"
          >
            <Plus size={15} strokeWidth={2.5} />
            Connect Account
          </button>
        )}
      </div>

      {!canScan && (
        <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-800">
          VIEWER role: connected accounts are read-only. Only workspace admins can change account settings or run scans.
        </div>
      )}

      {/* ── Account count ────────────────────────────────────────────────────── */}
      {accounts.length > 0 && (
        <p className="text-sm font-medium text-slate-500 mb-4">
          {accounts.length} account{accounts.length !== 1 ? "s" : ""} connected
          {isDemoEnabled() && <span className="ml-2 text-xs text-slate-400">· Demo Mode</span>}
        </p>
      )}

      {/* ── List or empty ────────────────────────────────────────────────────── */}
      {accounts.length === 0 ? (
        <EmptyState onConnect={canAdmin ? () => navigate("/account-scan") : null} />
      ) : (
        <div className="space-y-4">
          {accounts.map(account => (
            <AccountCard
              key={account.id}
              account={account}
              isScanning={scanningIds.has(account.id)}
              scanProgressMsg={scanProgress.get(account.id) ?? null}
              onViewResults={() => navigate(`/account-results/${account.id}`)}
              onRescan={() => handleRescan(account)}
              onEditRegions={() => setEditTarget(account)}
              onDelete={() => setDeleteTarget(account)}
              onHistory={() => setHistoryTarget(account)}
              canScan={canScan}
              canAdmin={canAdmin}
            />
          ))}
        </div>
      )}

      {/* ── Security note ───────────────────────────────────────────────────── */}
      {accounts.length > 0 && (
        <p className="mt-6 text-xs text-slate-500 text-center">
          We use read-only access and never ask for AWS access keys.
          You can revoke access anytime by deleting the IAM role from your AWS account.
        </p>
      )}

      {/* ── Delete modal ─────────────────────────────────────────────────────── */}
      {deleteTarget && (
        <DeleteModal
          account={deleteTarget}
          onConfirm={() => handleDelete(deleteTarget.id)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {/* ── Edit regions modal ───────────────────────────────────────────────── */}
      {editTarget && (
        <EditRegionsModal
          account={editTarget}
          onSave={patch => handleEditSave(editTarget, patch)}
          onCancel={() => setEditTarget(null)}
        />
      )}

      {/* ── Scan history modal ───────────────────────────────────────────────── */}
      {historyTarget && (
        <ScanHistoryModal
          account={historyTarget}
          onClose={() => setHistoryTarget(null)}
        />
      )}
    </div>
  );
}
