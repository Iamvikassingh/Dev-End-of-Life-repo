import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { API_BASE_URL } from "../utils/config";

const DEFAULT_AUTH_CONFIG = {
  emailSignupEnabled:        false,
  googleSignupEnabled:       false,
  captchaEnabled:            false,
  emailVerificationRequired: false,
  sessionEnabled:            true,
  anonymousWorkspaceCreate:  true,
  samlEnabled:               false,
  samlLoginUrl:              null,
  captchaProvider:           null,
  captchaSiteKey:            "",
  orgScanEnabled:            false,
};

export function useAuthConfig() {
  const { data, isLoading } = useQuery({
    queryKey:    ["auth-config"],
    queryFn:     async () => {
      const { data } = await axios.get(`${API_BASE_URL}/auth/config`, {
        withCredentials: true,
        timeout: 5000,
      });
      const config = data?.auth ?? data ?? {};
      return { ...DEFAULT_AUTH_CONFIG, ...config };
    },
    staleTime:      5 * 60 * 1000, // 5 minutes — flags rarely change
    gcTime:         10 * 60 * 1000,
    retry:          1,
    refetchOnWindowFocus: false,
  });

  return {
    authConfig: data ?? DEFAULT_AUTH_CONFIG,
    isLoading,
  };
}
