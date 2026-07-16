import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL, isDemoEnabled } from "../utils/config";
import { getWorkspaceId, workspaceHeaders } from "../utils/workspace";

const TERMINAL = new Set(["SUCCESS", "FAILED", "PARTIAL_SUCCESS"]);

// ── useStartScan ──────────────────────────────────────────────────────────────
// Returns a mutation that POSTs to /workspaces/:wsId/accounts/:acctId/scans.
// In demo mode simulates a 1.5s delay and returns a fake SUCCESS result.

export function useStartScan() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();

  return useMutation({
    mutationFn: async (accountId) => {
      if (isDemoEnabled()) {
        await new Promise(r => setTimeout(r, 1500));
        return {
          scanId:  `scan_demo_${Date.now()}`,
          status:  "SUCCESS",
          summary: { total: 28, eol: 8, expiringSoon: 8, extendedSupport: 4, supported: 7, unknown: 1 },
        };
      }
      const r    = await fetch(`${API_BASE_URL}/workspaces/${wsId}/accounts/${accountId}/scans`, {
        method:  "POST",
        headers: workspaceHeaders(),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        const msg = data?.error?.message || data?.error?.code || data?.error || "Scan failed";
        throw new Error(msg);
      }
      return data;
    },
    onSuccess: () => {
      // Bust all workspace-scoped caches so dashboard/services/alerts refresh
      qc.invalidateQueries({ queryKey: ["accounts",  wsId] });
      qc.invalidateQueries({ queryKey: ["summary",   wsId] });
      qc.invalidateQueries({ queryKey: ["inventory", wsId] });
      qc.invalidateQueries({ queryKey: ["alerts",    wsId] });
    },
  });
}

// ── useScanStatus ─────────────────────────────────────────────────────────────
// Polls GET /workspaces/:wsId/scans/:scanId every 2.5s while QUEUED or RUNNING.
// Stops polling automatically once a terminal status is reached.

export function useScanStatus(scanId, enabled = true) {
  const wsId = getWorkspaceId();

  return useQuery({
    queryKey: ["scan", wsId, scanId],
    queryFn:  async () => {
      if (!scanId) return null;
      const r    = await fetch(`${API_BASE_URL}/workspaces/${wsId}/scans/${scanId}`, {
        headers: workspaceHeaders(),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error("Failed to get scan status");
      return data.scan ?? null;
    },
    enabled:         enabled && !!scanId && !isDemoEnabled(),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status || TERMINAL.has(status)) return false;
      return 2500;
    },
    staleTime: 0,
    retry:     2,
  });
}

// ── useLatestScan ─────────────────────────────────────────────────────────────
// Fetches the latest scan run for a given account.

export function useLatestScan(accountId) {
  const wsId = getWorkspaceId();

  return useQuery({
    queryKey: ["latestScan", wsId, accountId],
    queryFn:  async () => {
      if (!accountId) return null;
      const r    = await fetch(
        `${API_BASE_URL}/workspaces/${wsId}/accounts/${accountId}/latest-scan`,
        { headers: workspaceHeaders() }
      );
      const data = await r.json().catch(() => ({}));
      if (!r.ok) return null;
      return data.scan ?? null;
    },
    enabled:   !!accountId && !isDemoEnabled(),
    staleTime: 30_000,
    retry:     2,
  });
}

// ── useAccountScanRuns ────────────────────────────────────────────────────────
// Fetches scan run history for a given account (newest-first, up to `limit`).

export function useAccountScanRuns(accountId, limit = 20, enabled = true) {
  const wsId = getWorkspaceId();

  return useQuery({
    queryKey: ["scanRuns", wsId, accountId, limit],
    queryFn:  async () => {
      if (!accountId || isDemoEnabled()) return [];
      const r    = await fetch(
        `${API_BASE_URL}/workspaces/${wsId}/accounts/${accountId}/scans?limit=${limit}`,
        { headers: workspaceHeaders() }
      );
      const data = await r.json().catch(() => ({}));
      if (!r.ok) return [];
      return data.scans ?? [];
    },
    enabled:   enabled && !!accountId && !isDemoEnabled(),
    staleTime: 30_000,
    retry:     1,
  });
}

// ── useWorkspaceSummary ───────────────────────────────────────────────────────
// Fetches GET /workspaces/:wsId/summary for dashboard-level overview.

export function useWorkspaceSummary() {
  const wsId = getWorkspaceId();

  return useQuery({
    queryKey: ["wsSummary", wsId],
    queryFn:  async () => {
      if (isDemoEnabled()) {
        return {
          workspace:       { id: wsId, name: "Demo Workspace" },
          accounts:        { total: 1, connected: 1 },
          lastScan:        { status: "SUCCESS", completedAt: new Date().toISOString() },
          resources:       { total: 28, eol: 8, expiringSoon: 8, extendedSupport: 4, supported: 7, unknown: 1 },
          serviceBreakdown: [],
          topRisks:         [],
          isMock:           true,
        };
      }
      const r    = await fetch(`${API_BASE_URL}/workspaces/${wsId}/summary`, {
        headers: workspaceHeaders(),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data?.error?.message || "Failed to load summary");
      return { ...data, isMock: false };
    },
    enabled:         !!wsId,
    refetchInterval: 60_000,
    staleTime:       30_000,
    retry:           2,
  });
}
