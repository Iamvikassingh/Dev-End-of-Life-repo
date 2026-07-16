import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { API_BASE_URL, isDemoEnabled } from "../utils/config";
import {
  GENERAL_EOL_DATA,
  computeGeneralSummary,
} from "../mocks/mockGeneralEolData";

// ── Fetchers ──────────────────────────────────────────────────────────────────
// API_BASE_URL can be:
//   "http://13.235.42.248:3001"  → absolute URL (production/direct)
//   ""                           → relative URL, CRA proxy forwards to localhost:3001

async function fetchGeneralEol(params = {}) {
  const cleaned = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );
  const query = new URLSearchParams(cleaned).toString();
  const url   = `${API_BASE_URL}/eol/general${query ? `?${query}` : ""}`;
  const { data } = await axios.get(url, { timeout: 5000 });
  if (!data.ok) {
    const err = new Error(data.error?.message ?? "API error");
    err.code    = data.error?.code;
    err.details = data.error?.details;
    throw err;
  }
  return { records: data.data, meta: data.meta };
}

async function triggerRefreshAndFetch(params = {}) {
  await axios.post(`${API_BASE_URL}/eol/general/refresh`, {}, { timeout: 60000 });
  return fetchGeneralEol(params);
}

async function fetchGeneralEolSummary(params = {}) {
  const query = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""))
  ).toString();
  const url = `${API_BASE_URL}/eol/general/summary${query ? `?${query}` : ""}`;
  const { data } = await axios.get(url, { timeout: 10000 });
  if (!data.ok) throw new Error(data.error?.message ?? "API error");
  return { counts: data.data, meta: data.meta };
}

// ── Client-side filter for demo/mock data ─────────────────────────────────────

function applyMockFilters(rows, { service, status, search }) {
  if (service) rows = rows.filter(r => r.service.toLowerCase().includes(service.toLowerCase()));
  if (status)  rows = rows.filter(r => r.status === status);
  if (search) {
    const q = search.toLowerCase();
    rows = rows.filter(r =>
      r.service.toLowerCase().includes(q) ||
      r.version.toLowerCase().includes(q) ||
      (r.family ?? "").toLowerCase().includes(q)
    );
  }
  return rows;
}

// ── useGeneralEol ─────────────────────────────────────────────────────────────

export function useGeneralEol(filters = {}) {
  const { service = "", status = "", search = "", includeLegacy = false } = filters;
  const qc = useQueryClient();

  const query = useQuery({
    queryKey: ["general-eol", service, status, search, includeLegacy],
    queryFn: async () => {
      // Use API when not in demo-only mode.
      // API_BASE_URL="" → relative URL → CRA proxy → localhost:3001 (dev/EC2).
      // API_BASE_URL="http://..." → absolute URL → direct (production).
      if (!isDemoEnabled()) {
        return fetchGeneralEol({ service, status, search, includeLegacy });
      }
      // Demo mode: mock data with client-side filtering
      const filtered = applyMockFilters(GENERAL_EOL_DATA, { service, status, search });
      return { records: filtered, meta: { source: "demo", refreshed_at: null }, isMock: true };
    },
    retry:     false,
    staleTime: 1000 * 60 * 5,
  });

  const refreshMutation = useMutation({
    mutationFn: () => triggerRefreshAndFetch({ service, status, search, includeLegacy }),
    onSuccess: (result) => {
      qc.setQueryData(["general-eol", service, status, search, includeLegacy], result);
      qc.invalidateQueries({ queryKey: ["general-eol-summary"] });
    },
  });

  const isMock       = query.data?.isMock === true;
  const isCacheEmpty = query.isError && query.error?.code === "CACHE_EMPTY";

  return {
    data:           query.data?.records ?? [],
    meta:           query.data?.meta    ?? null,
    loading:        query.isLoading,
    error:          query.error,
    isError:        query.isError && !isCacheEmpty,
    isCacheEmpty,
    isRefreshing:   refreshMutation.isPending,
    refreshError:   refreshMutation.isError,
    triggerRefresh: refreshMutation.mutate,
    isMock,
    refetch:        query.refetch,
  };
}

// ── useGeneralEolSummary ──────────────────────────────────────────────────────

export function useGeneralEolSummary(includeLegacy = false) {
  const query = useQuery({
    queryKey: ["general-eol-summary", includeLegacy],
    queryFn: async () => {
      if (!isDemoEnabled()) {
        return fetchGeneralEolSummary({ includeLegacy });
      }
      return { counts: computeGeneralSummary(GENERAL_EOL_DATA), meta: null, isMock: true };
    },
    retry:     false,
    staleTime: 1000 * 60 * 5,
  });

  return {
    summary: query.data?.counts ?? {},
    isMock:  query.data?.isMock === true,
  };
}
