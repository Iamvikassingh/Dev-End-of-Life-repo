import { API_BASE_URL, HAS_API, isDemoEnabled } from "./config";
import { getWorkspaceId, workspaceHeaders } from "./workspace";

const KEY = "eolm_connected_accounts";

// ── LocalStorage (cache layer) ────────────────────────────────────────────────

function accountsKey() {
  const wsId = getWorkspaceId();
  return wsId ? `${KEY}:${wsId}` : KEY;
}

export function loadAccounts() {
  try { return JSON.parse(localStorage.getItem(accountsKey()) || "[]"); }
  catch { return []; }
}

export function saveAccounts(list) {
  localStorage.setItem(accountsKey(), JSON.stringify(list));
}

export function addAccount(fields) {
  const list = loadAccounts();
  const account = {
    id: `conn-${Date.now()}`,
    connectedAt: new Date().toISOString(),
    lastScanAt: null,
    lastScanStatus: null,
    lastScanSummary: null,
    ...fields,
  };
  saveAccounts([...list, account]);
  return account;
}

export function removeAccount(id) {
  saveAccounts(loadAccounts().filter(a => a.id !== id));
}

export function updateAccount(id, patch) {
  saveAccounts(loadAccounts().map(a => a.id === id ? { ...a, ...patch } : a));
}

export function regionScopeLabel(account) {
  if (!account) return "—";
  // New canonical format
  if (account.scanAllRegions === true) return "All enabled regions";
  if (Array.isArray(account.regions)) {
    if (account.regions.length === 0) return "All enabled regions";
    if (account.regions.length === 1) return account.regions[0];
    return `${account.regions.length} regions`;
  }
  // Legacy string format
  if (account.regions === "single") return account.singleRegion || "—";
  if (account.regions === "selected") {
    const n = (account.selectedRegions || []).length;
    if (n === 0) return "No regions";
    return n === 1 ? account.selectedRegions[0] : `${n} regions`;
  }
  return "All enabled regions";
}

// ── Workspace-scoped server API ───────────────────────────────────────────────
// All calls go to /workspaces/:wsId/accounts with X-Workspace-Token header.
// localStorage is used as a local cache — UI stays instant even if API is slow.

function wsBase() {
  const wsId = getWorkspaceId();
  return wsId ? `${API_BASE_URL}/workspaces/${wsId}/accounts` : null;
}

export async function fetchAccountsFromServer() {
  if (!HAS_API || isDemoEnabled()) return null;
  const base = wsBase();
  if (!base) return null;
  try {
    const r = await fetch(base, { headers: workspaceHeaders() });
    if (!r.ok) return null;
    const data = await r.json();
    return Array.isArray(data.accounts) ? data.accounts : null;
  } catch { return null; }
}

export async function saveAccountToServer(account) {
  if (!HAS_API || isDemoEnabled()) return account;
  const base = wsBase();
  if (!base) return account;
  try {
    const r = await fetch(base, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...workspaceHeaders() },
      body: JSON.stringify(account),
    });
    if (!r.ok) return account;
    const data = await r.json();
    return data.account ?? account;
  } catch { return account; }
}

export async function updateAccountOnServer(id, patch) {
  if (!HAS_API || isDemoEnabled()) return true;
  const base = wsBase();
  if (!base) return true;
  try {
    const r = await fetch(`${base}/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...workspaceHeaders() },
      body: JSON.stringify(patch),
    });
    return r.ok;
  } catch { return false; }
}

export async function fetchWorkspaceInventory() {
  if (!HAS_API || isDemoEnabled()) return [];
  const wsId = getWorkspaceId();
  if (!wsId) return [];
  try {
    const r = await fetch(`${API_BASE_URL}/workspaces/${wsId}/inventory`, { headers: workspaceHeaders() });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return [];
    if (Array.isArray(data.items)) return data.items;
    if (Array.isArray(data)) return data;
    return [];
  } catch { return []; }
}

export async function validateRoleOnServer({ roleArn, externalId, awsAccountId, accountName }) {
  const wsId = getWorkspaceId();
  if (!wsId) return { ok: false, error: { code: "NO_WORKSPACE", message: "No workspace selected." } };
  try {
    const r = await fetch(`${API_BASE_URL}/workspaces/${wsId}/accounts/validate-role`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...workspaceHeaders() },
      body: JSON.stringify({ roleArn, externalId, awsAccountId, accountName }),
    });
    const data = await r.json().catch(() => ({}));
    if (r.ok && data.ok) return { ok: true, accountId: data.accountId, message: data.message };
    const err = data?.error || {};
    return { ok: false, error: { code: err.code || "VALIDATION_FAILED", message: err.message || "Validation failed." } };
  } catch {
    return { ok: false, error: { code: "NETWORK_ERROR", message: "Network error. Check connection and try again." } };
  }
}

export async function scanAccountOnServer(accountId) {
  if (!HAS_API) return null;
  const wsId = getWorkspaceId();
  if (!wsId) return null;
  try {
    const r = await fetch(`${API_BASE_URL}/workspaces/${wsId}/accounts/${accountId}/scan`, {
      method: "POST",
      headers: workspaceHeaders(),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return { error: data.details || data.error || "Scan failed" };
    return data;
  } catch { return { error: "Could not reach the server." }; }
}

// ── Scan run model (new API) ──────────────────────────────────────────────────

export async function startScanOnServer(accountId) {
  if (!HAS_API || isDemoEnabled()) return null;
  const wsId = getWorkspaceId();
  if (!wsId) return null;
  try {
    const r = await fetch(`${API_BASE_URL}/workspaces/${wsId}/accounts/${accountId}/scans`, {
      method: "POST",
      headers: workspaceHeaders(),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg          = data?.error?.message || data?.error?.code || data?.error || "Scan failed";
      const code         = data?.error?.code || "SCAN_FAILED";
      const runningScanId = data?.runningScan?.scanId ?? null;
      return { error: msg, errorCode: code, runningScanId };
    }
    return data; // { scanId, status, summary? }
  } catch { return { error: "Could not reach the server." }; }
}

export async function getScanStatus(scanId) {
  if (!HAS_API || isDemoEnabled() || !scanId) return null;
  const wsId = getWorkspaceId();
  if (!wsId) return null;
  try {
    const r = await fetch(`${API_BASE_URL}/workspaces/${wsId}/scans/${scanId}`, {
      headers: workspaceHeaders(),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return null;
    return data.scan ?? null;
  } catch { return null; }
}

// Normalize lastScanSummary to canonical ALLCAPS keys regardless of how it was stored.
// Backend stores raw_sum (ALLCAPS); API response returns normalized (camelCase).
// This handles both shapes defensively so cards always read consistent keys.
// total is recomputed from category buckets — never trusts stored total which can be stale.
export function normalizeScanSummary(sum) {
  if (!sum) return null;
  const eol                = sum.EOL                   ?? sum.eol                 ?? 0;
  const expiringSoon       = sum.EXPIRING_SOON         ?? sum.expiringSoon         ?? 0;
  const extendedSupport    = sum.EXTENDED_SUPPORT      ?? sum.extendedSupport      ?? 0;
  const supported          = sum.SUPPORTED             ?? sum.supported            ?? 0;
  const unknown            = sum.UNKNOWN               ?? sum.unknown              ?? 0;
  const needsInspection    = sum.NEEDS_INSPECTION      ?? sum.needsInspection      ?? 0;
  const lifecycleNotTracked= sum.LIFECYCLE_NOT_TRACKED ?? sum.lifecycleNotTracked  ?? 0;
  return {
    total:                 eol + expiringSoon + extendedSupport + supported + unknown + needsInspection + lifecycleNotTracked,
    EOL:                   eol,
    EXPIRING_SOON:         expiringSoon,
    EXTENDED_SUPPORT:      extendedSupport,
    SUPPORTED:             supported,
    UNKNOWN:               unknown,
    NEEDS_INSPECTION:      needsInspection,
    LIFECYCLE_NOT_TRACKED: lifecycleNotTracked,
  };
}

export async function deleteAccountFromServer(id) {
  if (!HAS_API || isDemoEnabled()) return true;
  const base = wsBase();
  if (!base) return true;
  try {
    const r = await fetch(`${base}/${id}`, {
      method: "DELETE",
      headers: workspaceHeaders(),
    });
    return r.ok;
  } catch { return false; }
}
