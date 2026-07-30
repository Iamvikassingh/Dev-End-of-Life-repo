/**
 * React Query hooks for SNS Email Alert Subscriptions.
 *
 * Endpoints (all workspace-scoped):
 *   GET    /workspaces/:wsId/alerts/email-subscriptions
 *   POST   /workspaces/:wsId/alerts/email-subscriptions
 *   DELETE /workspaces/:wsId/alerts/email-subscriptions/:subId
 *   POST   /workspaces/:wsId/alerts/email-subscriptions/verify
 *   GET    /workspaces/:wsId/alerts/email-notifications/history
 *   POST   /workspaces/:wsId/alerts/email-notify
 *   POST   /workspaces/:wsId/alerts/email-test
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL, isDemoEnabled } from "../utils/config";
import { getWorkspaceId, workspaceHeaders } from "../utils/workspace";

const DEMO_SUBS = [];
const DEMO_HISTORY = [];

// ── Helper ────────────────────────────────────────────────────────────────────

async function _call(path, method = "GET", body = null) {
  const opts = {
    method,
    headers: {
      "Content-Type": "application/json",
      ...workspaceHeaders(),
    },
  };
  if (body !== null) opts.body = JSON.stringify(body);
  const r    = await fetch(`${API_BASE_URL}${path}`, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(data?.error?.message || `Request failed (${r.status})`);
    err.code  = data?.error?.code || "UNKNOWN";
    throw err;
  }
  return data;
}

// ── useSnsSubscriptions ───────────────────────────────────────────────────────

export function useSnsSubscriptions() {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey:  ["sns-subscriptions", wsId],
    queryFn:   async () => {
      if (isDemoEnabled()) return { subscriptions: DEMO_SUBS, count: 0 };
      return _call(`/workspaces/${wsId}/alerts/email-subscriptions`);
    },
    enabled:   !!wsId,
    staleTime: 30_000,
    retry:     1,
  });
}

// ── useSubscribeEmail ─────────────────────────────────────────────────────────

export function useSubscribeEmail() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async ({ email }) => {
      if (isDemoEnabled()) return { ok: true, subscription: { id: "demo_sub", email, status: "PENDING" }, message: "Demo mode — no real SNS call" };
      return _call(`/workspaces/${wsId}/alerts/email-subscriptions`, "POST", { email });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sns-subscriptions", wsId] }),
  });
}

// ── useVerifySubscription ─────────────────────────────────────────────────────

export function useVerifySubscription() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async ({ subId, token, subscribeUrl }) => {
      if (isDemoEnabled()) return { ok: true };
      const body = { sub_id: subId };
      if (token) body.token = token;
      if (subscribeUrl) body.subscribe_url = subscribeUrl;
      return _call(`/workspaces/${wsId}/alerts/email-subscriptions/verify`, "POST", body);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sns-subscriptions", wsId] }),
  });
}

// ── useUnsubscribeEmail ───────────────────────────────────────────────────────

export function useUnsubscribeEmail() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async ({ subId }) => {
      if (isDemoEnabled()) return { ok: true };
      return _call(`/workspaces/${wsId}/alerts/email-subscriptions/${subId}`, "DELETE");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sns-subscriptions", wsId] }),
  });
}

// ── useSnsNotificationHistory ─────────────────────────────────────────────────

export function useSnsNotificationHistory(limit = 50) {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey:  ["sns-history", wsId, limit],
    queryFn:   async () => {
      if (isDemoEnabled()) return { history: DEMO_HISTORY, count: 0 };
      return _call(`/workspaces/${wsId}/alerts/email-notifications/history?limit=${limit}`);
    },
    enabled:   !!wsId,
    staleTime: 60_000,
    retry:     1,
  });
}

// ── useTriggerEmailAlert ──────────────────────────────────────────────────────

export function useTriggerEmailAlert() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async () => {
      if (isDemoEnabled()) return { ok: true, dispatched: 3 };
      return _call(`/workspaces/${wsId}/alerts/email-notify`, "POST");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sns-history", wsId] }),
  });
}

// ── useSendTestAlert ──────────────────────────────────────────────────────────

export function useSendTestAlert() {
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async () => {
      if (isDemoEnabled()) return { ok: true, messageId: "demo_msg_id" };
      return _call(`/workspaces/${wsId}/alerts/email-test`, "POST");
    },
  });
}
