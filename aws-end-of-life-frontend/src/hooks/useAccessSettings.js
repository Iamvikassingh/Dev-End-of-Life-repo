import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { API_BASE_URL, isDemoEnabled } from "../utils/config";
import { getWorkspaceId, workspaceHeaders } from "../utils/workspace";

// ── API Tokens ────────────────────────────────────────────────────────────────

export function useApiTokens() {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["api-tokens", wsId],
    queryFn: async () => {
      if (isDemoEnabled()) return { tokens: [], count: 0 };
      const { data } = await axios.get(
        `${API_BASE_URL}/workspaces/${wsId}/api-tokens`,
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    enabled: !!wsId,
    staleTime: 30_000,
  });
}

export function useCreateApiToken() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async ({ name, role, expiresAt }) => {
      if (isDemoEnabled()) {
        await new Promise(r => setTimeout(r, 600));
        return {
          token:    { id: `api_tok_demo`, name, role, prefix: "eolm_api_abc...", createdAt: new Date().toISOString(), revokedAt: null, expiresAt: expiresAt || null, lastUsedAt: null },
          rawToken: "eolm_api_demo_not_real_token",
          note:     "Demo mode — token is not real.",
        };
      }
      const { data } = await axios.post(
        `${API_BASE_URL}/workspaces/${wsId}/api-tokens`,
        { name, role, expiresAt: expiresAt || undefined },
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-tokens", wsId] });
      qc.invalidateQueries({ queryKey: ["audit-logs", wsId] });
    },
  });
}

export function useRevokeApiToken() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async (tokenId) => {
      if (isDemoEnabled()) {
        await new Promise(r => setTimeout(r, 400));
        return { success: true, id: tokenId };
      }
      const { data } = await axios.delete(
        `${API_BASE_URL}/workspaces/${wsId}/api-tokens/${tokenId}`,
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-tokens", wsId] });
      qc.invalidateQueries({ queryKey: ["audit-logs", wsId] });
    },
  });
}

export function useUpdateApiToken() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async ({ tokenId, patch }) => {
      const { data } = await axios.patch(
        `${API_BASE_URL}/workspaces/${wsId}/api-tokens/${tokenId}`,
        patch,
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-tokens", wsId] });
    },
  });
}

// ── Audit Logs ────────────────────────────────────────────────────────────────

export function useAuditLogs(limit = 50) {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["audit-logs", wsId, limit],
    queryFn: async () => {
      if (isDemoEnabled()) return { logs: [], count: 0 };
      const { data } = await axios.get(
        `${API_BASE_URL}/workspaces/${wsId}/audit-logs?limit=${limit}`,
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    enabled: !!wsId,
    staleTime: 30_000,
  });
}

// ── Members ───────────────────────────────────────────────────────────────────

export function useMembers() {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["members", wsId],
    queryFn: async () => {
      if (isDemoEnabled()) return { members: [], count: 0 };
      const { data } = await axios.get(
        `${API_BASE_URL}/workspaces/${wsId}/members`,
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    enabled: !!wsId,
    staleTime: 30_000,
  });
}

export function useInviteMember() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async ({ email, role, name }) => {
      if (isDemoEnabled()) {
        await new Promise(r => setTimeout(r, 600));
        return {
          member:      { id: "mbr_demo", email, role, status: "INVITED", invitedAt: new Date().toISOString() },
          inviteToken: "inv_demo_not_real",
          note:        "Demo mode — token is not real.",
        };
      }
      const { data } = await axios.post(
        `${API_BASE_URL}/workspaces/${wsId}/members`,
        { email, role, name: name || undefined },
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["members", wsId] });
      qc.invalidateQueries({ queryKey: ["audit-logs", wsId] });
      qc.invalidateQueries({ queryKey: ["access-summary", wsId] });
    },
  });
}

export function useUpdateMember() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async ({ memberId, patch }) => {
      if (isDemoEnabled()) {
        await new Promise(r => setTimeout(r, 400));
        return { member: { id: memberId, ...patch } };
      }
      const { data } = await axios.patch(
        `${API_BASE_URL}/workspaces/${wsId}/members/${memberId}`,
        patch,
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["members", wsId] });
      qc.invalidateQueries({ queryKey: ["audit-logs", wsId] });
    },
  });
}

export function useRemoveMember() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async (memberId) => {
      if (isDemoEnabled()) {
        await new Promise(r => setTimeout(r, 400));
        return { removed: true };
      }
      const { data } = await axios.delete(
        `${API_BASE_URL}/workspaces/${wsId}/members/${memberId}`,
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["members", wsId] });
      qc.invalidateQueries({ queryKey: ["audit-logs", wsId] });
      qc.invalidateQueries({ queryKey: ["access-summary", wsId] });
    },
  });
}

// ── Access summary ────────────────────────────────────────────────────────────

export function useAccessSummary() {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["access-summary", wsId],
    queryFn: async () => {
      if (isDemoEnabled()) {
        return { currentSessionRole: "ADMIN", apiTokensActive: 0, apiTokensTotal: 0, auditLogCount: 0, membersCount: 0 };
      }
      const { data } = await axios.get(
        `${API_BASE_URL}/workspaces/${wsId}/access/summary`,
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    enabled: !!wsId,
    staleTime: 60_000,
  });
}
