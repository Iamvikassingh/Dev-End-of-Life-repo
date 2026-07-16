import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { API_BASE_URL, isDemoEnabled } from "../utils/config";
import { getWorkspaceId, workspaceHeaders } from "../utils/workspace";

const CONFIG_DEFAULTS = {
  warn_days: 180, alert_email: "", slack_webhook: "",
  scan_schedule: "cron(0 8 * * ? *)", scan_org: false,
  sns_topic_arn: "",
  enabled_services: ["Lambda","EKS","RDS","Aurora","ElastiCache","EC2","CodeBuild","ElasticBeanstalk","EMR","MSK","OpenSearch","DocumentDB","Neptune","Glue"],
};

export function useConfig() {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["config", wsId],
    queryFn: async () => {
      if (!isDemoEnabled()) {
        const { data } = await axios.get(`${API_BASE_URL}/workspaces/${wsId}/config`, {
          headers: workspaceHeaders(),
          timeout: 8000,
        });
        return { ...data, isMock: false };
      }
      return { ...CONFIG_DEFAULTS, isMock: true };
    },
    enabled: !!wsId || isDemoEnabled(),
    initialData: { ...CONFIG_DEFAULTS },
    staleTime:   60_000,
    retry:       2,
  });
}

export function useSaveConfig() {
  const qc = useQueryClient();
  const wsId = getWorkspaceId();
  return useMutation({
    mutationFn: async (config) => {
      if (!isDemoEnabled()) {
        const { data } = await axios.patch(`${API_BASE_URL}/workspaces/${wsId}/config`, config, {
          headers: workspaceHeaders(),
          timeout: 8000,
        });
        return { ...data, isMock: false };
      }
      return { message: "Settings saved locally in demo mode.", isMock: true };
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["config", wsId] }),
  });
}
