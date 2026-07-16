import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { API_BASE_URL, isDemoEnabled } from "../utils/config";
import { getWorkspaceId, workspaceHeaders } from "../utils/workspace";
import { getApiErrorMessage } from "../utils/apiErrors";

const DEFAULT_SETTINGS = {
  email: {
    enabled:          false,
    recipients:       [],
    sendImmediate:    true,
    sendWeeklyDigest: true,
  },
  slack: {
    enabled:          false,
    webhookUrl:       "",
    sendImmediate:    true,
    sendWeeklyDigest: true,
  },
  thresholds: {
    sendEol:          true,
    sendExpiringSoon: true,
    sendUnknown:      false,
  },
  lastUpdatedAt: null,
};

export function notificationErrorMessage(error, fallback = "Test notification failed.") {
  const envelope = error?.response?.data?.error;
  const status = error?.response?.status;
  const code = envelope?.code || error?.response?.data?.code;

  if (status === 405) {
    return "Notification settings API method is not available. Restart backend or verify route registration.";
  }
  if (code === "EMAIL_NOT_CONFIGURED") return "Email provider is not configured.";
  if (code === "NO_WEBHOOK_URL" || code === "INVALID_WEBHOOK_URL") {
    return "Slack webhook is not configured or invalid.";
  }
  return getApiErrorMessage(error, fallback);
}

export function useNotificationSettings() {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["notification-settings", wsId],
    queryFn: async () => {
      if (isDemoEnabled()) {
        return { settings: DEFAULT_SETTINGS, emailConfigured: false, slackConfigurable: true };
      }
      const { data } = await axios.get(
        `${API_BASE_URL}/workspaces/${wsId}/notification-settings`,
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    enabled: !!wsId || isDemoEnabled(),
    staleTime: 30_000,
  });
}

export function useSaveNotificationSettings() {
  const qc   = useQueryClient();
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async (patch) => {
      if (isDemoEnabled()) return { settings: patch, emailConfigured: false };
      const { data } = await axios.patch(
        `${API_BASE_URL}/workspaces/${wsId}/notification-settings`,
        patch,
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    onSuccess: (data) => {
      qc.setQueryData(["notification-settings", wsId], (prev) => ({
        ...(prev || {}),
        settings: data.settings,
      }));
    },
  });
}

export function useSendTestNotification() {
  const wsId = getWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ channel }) => {
      if (isDemoEnabled()) {
        await new Promise((r) => setTimeout(r, 800));
        return { success: true, channel };
      }
      const { data } = await axios.post(
        `${API_BASE_URL}/workspaces/${wsId}/notifications/test`,
        { channel },
        { headers: workspaceHeaders(), timeout: 15000 }
      );
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["notification-logs", wsId] });
    },
  });
}

export function useNotificationLogs(enabled = true) {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["notification-logs", wsId],
    queryFn: async () => {
      if (isDemoEnabled()) return { logs: [], count: 0 };
      const { data } = await axios.get(
        `${API_BASE_URL}/workspaces/${wsId}/notifications/logs`,
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return data;
    },
    enabled: enabled && (!!wsId || isDemoEnabled()),
    staleTime: 60_000,
  });
}
