import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL, isDemoEnabled } from "../utils/config";
import { MOCK_INVENTORY } from "../mocks/eolMockData";
import { getWorkspaceId, workspaceHeaders } from "../utils/workspace";

const ALERT_STATUSES = new Set(["EOL", "EXPIRING_SOON", "EXTENDED_SUPPORT"]);
const SEVERITY_MAP   = { EOL: "HIGH", EXPIRING_SOON: "MEDIUM", EXTENDED_SUPPORT: "LOW" };

// Build demo alerts from mock inventory so the Alerts page has realistic data
function buildDemoAlerts() {
  const now = new Date().toISOString();
  return MOCK_INVENTORY
    .filter(i => ALERT_STATUSES.has(i.eol_status))
    .slice(0, 40)
    .map((i, idx) => ({
      id:              `alert_demo_${idx}`,
      workspaceId:     "ws_demo",
      accountId:       "conn_demo",
      resourceId:      i.resource_id,
      service:         i.service_type,
      resourceName:    i.resource_name ?? i.resource_id,
      region:          i.region ?? "",
      version:         i.version ?? "",
      lifecycleStatus: i.eol_status,
      severity:        SEVERITY_MAP[i.eol_status] ?? "LOW",
      reason:          `${i.service_type} ${i.version ?? ""} — ${i.eol_status === "EOL" ? "end of life reached" : "expiring soon"}`,
      eolDate:         i.eol_date ?? null,
      status:          "ACTIVE",
      createdAt:       now,
      lastSeenAt:      now,
      acknowledgedAt:  null,
      snoozedUntil:    null,
      resolvedAt:      null,
    }));
}

// ── useAlerts ─────────────────────────────────────────────────────────────────

export function useAlerts({ status, accountId, limit = 200 } = {}) {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["alerts", wsId, status, accountId, limit],
    queryFn:  async () => {
      if (isDemoEnabled()) {
        const all = buildDemoAlerts();
        return { alerts: all, counts: _countAlerts(all), isMock: true };
      }
      const p = new URLSearchParams();
      if (status)    p.set("status",    status);
      if (accountId) p.set("accountId", accountId);
      p.set("limit", String(limit));
      const r    = await fetch(`${API_BASE_URL}/workspaces/${wsId}/alerts?${p}`, {
        headers: workspaceHeaders(),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data?.error?.message || "Failed to load alerts");
      return { ...data, isMock: false };
    },
    refetchInterval: 60_000,
    staleTime:       30_000,
    retry:           2,
    enabled:         !!wsId,
  });
}

function _countAlerts(alerts) {
  return {
    total:        alerts.length,
    active:       alerts.filter(a => a.status === "ACTIVE").length,
    acknowledged: alerts.filter(a => a.status === "ACKNOWLEDGED").length,
    snoozed:      alerts.filter(a => a.status === "SNOOZED").length,
    resolved:     alerts.filter(a => a.status === "RESOLVED").length,
    high:         alerts.filter(a => a.severity === "HIGH").length,
    medium:       alerts.filter(a => a.severity === "MEDIUM").length,
  };
}

// ── useAlertAction ────────────────────────────────────────────────────────────
// Mutation to acknowledge / snooze / resolve / reopen a single alert.

export function useAlertAction() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();

  return useMutation({
    mutationFn: async ({ alertId, action, body = {} }) => {
      if (isDemoEnabled()) {
        return { success: true };  // no-op in demo
      }
      const r    = await fetch(
        `${API_BASE_URL}/workspaces/${wsId}/alerts/${alertId}/${action}`,
        {
          method:  "POST",
          headers: { "Content-Type": "application/json", ...workspaceHeaders() },
          body:    JSON.stringify(body),
        }
      );
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data?.error?.message || `Action ${action} failed`);
      return data;
    },
    onSuccess: () => {
      // Invalidate all alert queries for this workspace
      qc.invalidateQueries({ queryKey: ["alerts", wsId] });
    },
  });
}
