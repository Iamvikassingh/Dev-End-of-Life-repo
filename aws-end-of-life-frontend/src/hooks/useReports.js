import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { API_BASE_URL } from "../utils/config";
import { getWorkspaceId, workspaceHeaders } from "../utils/workspace";

export function useReportSummary(scopeParams = {}) {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["reports", wsId, "summary", scopeParams],
    queryFn: async () => {
      const { data } = await axios.get(`${API_BASE_URL}/workspaces/${wsId}/reports/summary`, {
        headers: workspaceHeaders(),
        params: scopeParams,
        timeout: 10000,
      });
      return data;
    },
    enabled: !!wsId,
    staleTime: 30_000,
    retry: 2,
  });
}

// Always fetches workspace (unfiltered) scope — used to populate the scope selector dropdown.
// Shares the React Query cache with useReportSummary({}) when scope=workspace is active.
export function useBaseReportSummary() {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["reports", wsId, "summary", {}],
    queryFn: async () => {
      const { data } = await axios.get(`${API_BASE_URL}/workspaces/${wsId}/reports/summary`, {
        headers: workspaceHeaders(),
        timeout: 10000,
      });
      return data;
    },
    enabled: !!wsId,
    staleTime: 60_000,
    retry: 2,
  });
}

export function useReportSnapshots() {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["reports", wsId, "snapshots"],
    queryFn: async () => {
      const { data } = await axios.get(`${API_BASE_URL}/workspaces/${wsId}/reports/snapshots`, {
        headers: workspaceHeaders(),
        timeout: 10000,
      });
      return data.snapshots ?? [];
    },
    enabled: !!wsId,
    staleTime: 30_000,
  });
}

export function useCreateReportSnapshot() {
  const wsId = getWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await axios.post(`${API_BASE_URL}/workspaces/${wsId}/reports/snapshots`, {}, {
        headers: workspaceHeaders(),
        timeout: 10000,
      });
      return data.snapshot;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports", wsId, "summary"] });
      qc.invalidateQueries({ queryKey: ["reports", wsId, "snapshots"] });
    },
  });
}

export function reportCsvUrl(scopeParams = {}) {
  const wsId = getWorkspaceId();
  const base = `${API_BASE_URL}/workspaces/${wsId}/reports/export.csv`;
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(scopeParams).filter(([, v]) => v))
  ).toString();
  return qs ? `${base}?${qs}` : base;
}
