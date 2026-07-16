import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { API_BASE_URL } from "../utils/config";

export function useAuthMe() {
  return useQuery({
    queryKey: ["auth-me"],
    queryFn:  async () => {
      const { data } = await axios.get(`${API_BASE_URL}/auth/me`, {
        withCredentials: true,
        timeout: 5000,
      });
      return data?.user ?? null;
    },
    staleTime:      2 * 60 * 1000,
    retry:          false,
    refetchOnWindowFocus: false,
  });
}

export function useAuthLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await axios.post(`${API_BASE_URL}/auth/logout`, {}, { withCredentials: true });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["auth-me"] });
    },
  });
}
