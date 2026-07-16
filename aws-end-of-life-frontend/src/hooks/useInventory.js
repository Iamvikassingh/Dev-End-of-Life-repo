import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { API_BASE_URL, isDemoEnabled } from "../utils/config";
import { MOCK_INVENTORY, MOCK_SUMMARY } from "../mocks/eolMockData";
import { getWorkspaceId, workspaceHeaders } from "../utils/workspace";

function normalize(item) {
  return {
    resource_id:   item.resource_id   ?? item.resourceId   ?? item.id             ?? "",
    resource_name: item.resource_name ?? item.resourceName ?? item.resource ?? item.name ?? "",
    service_type:  item.service_type  ?? item.serviceType  ?? item.service         ?? "",
    region:        item.region                                                      ?? "",
    account_id:    item.account_id    ?? item.accountId                            ?? "",
    version:       item.version       ?? item.runtime      ?? item.engineVersion   ?? "",
    eol_status:    item.eol_status    ?? item.status                               ?? "UNKNOWN",
    eol_date:      item.eol_date      ?? item.eolDate                              ?? null,
    days_to_eol:   item.days_to_eol !== undefined ? Number(item.days_to_eol)
                   : item.daysToEol  !== undefined ? Number(item.daysToEol)        : null,
    scanned_at:         item.scanned_at         ?? item.lastScanned                     ?? null,
    ami_id:             item.ami_id             ?? item.amiId                          ?? undefined,
    instance_type:      item.instance_type      ?? item.instanceType                   ?? undefined,
    platform_details:   item.platform_details   ?? item.platformDetails                ?? undefined,
    image_name:         item.image_name         ?? item.imageName                      ?? undefined,
    image_description:  item.image_description  ?? item.imageDescription               ?? undefined,
    os_source:          item.os_source          ?? item.osSource                       ?? undefined,
    detection_source:   item.detection_source   ?? item.detectionSource                ?? undefined,
    confidence:         item.confidence         ?? item.detectionConfidence            ?? undefined,
    ssm_managed:        item.ssm_managed        ?? item.ssmManaged                     ?? undefined,
    ssm_platform_name:  item.ssm_platform_name  ?? item.ssmPlatformName                ?? undefined,
    ssm_platform_version: item.ssm_platform_version ?? item.ssmPlatformVersion          ?? undefined,
    ssm_platform_type:  item.ssm_platform_type  ?? item.ssmPlatformType                ?? undefined,
    ssm_computer_name:  item.ssm_computer_name  ?? item.ssmComputerName                ?? undefined,
    ssm_agent_status:   item.ssm_agent_status   ?? item.ssmAgentStatus                 ?? undefined,
    ssm_inventory_unavailable: item.ssm_inventory_unavailable ?? item.ssmInventoryUnavailable ?? undefined,
    scan_warning:       item.scan_warning       ?? item.scanWarning                    ?? undefined,
    resource_type:      item.resource_type      ?? item.resourceType                   ?? undefined,
    codebuild_image:    item.codebuild_image    ?? item.codebuildImage                 ?? undefined,
    environment_type:   item.environment_type   ?? item.environmentType                ?? undefined,
    compute_type:       item.compute_type       ?? item.computeType                    ?? undefined,
    privileged_mode:    item.privileged_mode    ?? item.privilegedMode                 ?? undefined,
    application_name:   item.application_name   ?? item.applicationName                ?? undefined,
    environment_name:   item.environment_name   ?? item.environmentName                ?? undefined,
    platform_arn:       item.platform_arn       ?? item.platformArn                    ?? undefined,
    solution_stack_name:item.solution_stack_name?? item.solutionStackName              ?? undefined,
    environment_status: item.environment_status ?? item.environmentStatus              ?? undefined,
    cluster_id:         item.cluster_id         ?? item.clusterId                      ?? undefined,
    release_label:      item.release_label      ?? item.releaseLabel                   ?? undefined,
    cluster_state:      item.cluster_state      ?? item.clusterState                   ?? undefined,
    applications:       item.applications                                             ?? undefined,
    kafka_version:      item.kafka_version      ?? item.kafkaVersion                   ?? undefined,
    broker_node_count:  item.broker_node_count  ?? item.brokerNodeCount                ?? undefined,
    current_version:    item.current_version    ?? item.currentVersion                 ?? undefined,
    glue_version:       item.glue_version       ?? item.glueVersion                    ?? undefined,
    python_version:     item.python_version     ?? item.pythonVersion                  ?? undefined,
    spark_version:      item.spark_version      ?? item.sparkVersion                   ?? undefined,
    worker_type:        item.worker_type        ?? item.workerType                     ?? undefined,
    command_name:       item.command_name       ?? item.commandName                    ?? undefined,
    command_script_location: item.command_script_location ?? item.commandScriptLocation ?? undefined,
    function_runtime:   item.function_runtime   ?? item.functionRuntime                ?? undefined,
    function_stage:     item.function_stage     ?? item.functionStage                  ?? undefined,
    function_status:    item.function_status    ?? item.functionStatus                 ?? undefined,
    repository_name:    item.repository_name    ?? item.repositoryName                 ?? undefined,
    image_tag:          item.image_tag          ?? item.imageTag                       ?? undefined,
    image_digest:       item.image_digest       ?? item.imageDigest                    ?? undefined,
    short_digest:         item.short_digest         ?? item.shortDigest                  ?? undefined,
    image_pushed_at:      item.image_pushed_at      ?? item.imagePushedAt               ?? undefined,
    image_size_in_bytes:  item.image_size_in_bytes  ?? item.imageSizeInBytes            ?? undefined,
    base_image_status:    item.base_image_status    ?? item.baseImageStatus             ?? undefined,
    status_label:         item.status_label         ?? item.statusLabel                 ?? undefined,
    lifecycle_applicable: item.lifecycle_applicable ?? item.lifecycleApplicable         ?? undefined,
    classification_type:  item.classification_type  ?? item.classificationType          ?? undefined,
    recommendation:     item.recommendation     ?? item.recommendedAction              ?? undefined,
    support_end_date:       item.support_end_date       ?? item.supportEndDate         ?? undefined,
    final_eol_date:         item.final_eol_date         ?? item.finalEolDate           ?? undefined,
    engine:                 item.engine                 ?? item.engineName             ?? undefined,
    db_instance_class:      item.db_instance_class      ?? item.dbInstanceClass        ?? undefined,
    db_instance_status:     item.db_instance_status     ?? item.dbInstanceStatus       ?? undefined,
    multi_az:               item.multi_az               ?? item.multiAz                ?? undefined,
    cluster_status:         item.cluster_status         ?? item.clusterStatus          ?? undefined,
    engine_mode:            item.engine_mode            ?? item.engineMode             ?? undefined,
    platform_version:       item.platform_version       ?? item.platformVersion        ?? undefined,
    endpoint_public_access: item.endpoint_public_access ?? item.endpointPublicAccess   ?? undefined,
    endpoint_private_access:item.endpoint_private_access?? item.endpointPrivateAccess  ?? undefined,
    created_at:             item.created_at             ?? item.createdAt              ?? undefined,
    // Lifecycle metadata — source trust information
    lifecycle_source:   item.lifecycle_source   ?? item.lifecycleSource               ?? undefined,
    officialSourceUrl:  item.officialSourceUrl  ?? item.source_url                    ?? undefined,
    validatedBy:        item.validatedBy                                               ?? undefined,
    lastValidatedAt:    item.lastValidatedAt                                           ?? undefined,
    validationStatus:   item.validationStatus                                          ?? undefined,
    classification_reason: item.classification_reason ?? item.classificationReason    ?? undefined,
    scan_source:           item.scan_source           ?? item.scanSource              ?? "ACCOUNT_SCAN",
  };
}

// Convert backend serviceBreakdown array → { [serviceKey]: { EOL, EXPIRING_SOON, … } }
function normServiceBreakdown(raw) {
  if (!raw) return {};
  if (!Array.isArray(raw)) return raw; // already object (local-api.py shape)
  const obj = {};
  for (const item of raw) {
    const key = item.service ?? item.service_type ?? "Unknown";
    obj[key] = {
      EOL:                   item.EOL                   ?? item.eol                  ?? 0,
      EXPIRING_SOON:         item.EXPIRING_SOON         ?? item.expiringSoon          ?? 0,
      EXTENDED_SUPPORT:      item.EXTENDED_SUPPORT      ?? item.extendedSupport       ?? 0,
      SUPPORTED:             item.SUPPORTED             ?? item.supported             ?? 0,
      UNKNOWN:               item.UNKNOWN               ?? item.unknown               ?? 0,
      NEEDS_INSPECTION:      item.NEEDS_INSPECTION      ?? item.needsInspection       ?? 0,
      LIFECYCLE_NOT_TRACKED: item.LIFECYCLE_NOT_TRACKED ?? item.lifecycleNotTracked   ?? 0,
    };
  }
  return obj;
}

// ── useInventory ──────────────────────────────────────────────────────────────
// Calls workspace-scoped /workspaces/:wsId/inventory — only returns resources
// belonging to this workspace. Falls back to mock data in demo mode.

export function useInventory(filters = {}, options = {}) {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["inventory", wsId, filters],
    queryFn:  async () => {
      if (isDemoEnabled()) {
        let items = MOCK_INVENTORY.map(normalize);
        if (filters.status)  items = items.filter(i => i.eol_status === filters.status.toUpperCase());
        if (filters.service) items = items.filter(i => i.service_type.toLowerCase().includes(filters.service.toLowerCase()));
        if (filters.region)  items = items.filter(i => i.region.includes(filters.region));
        return { items, isMock: true };
      }

      if (!wsId) return { items: [], isMock: false };

      const params = new URLSearchParams(
        Object.fromEntries(Object.entries(filters).filter(([, v]) => v))
      ).toString();
      const url = `${API_BASE_URL}/workspaces/${wsId}/inventory${params ? `?${params}` : ""}`;
      const { data } = await axios.get(url, { headers: workspaceHeaders(), timeout: 8000 });
      return { items: (data.items ?? []).map(normalize), isMock: false };
    },
    enabled:         (options.enabled !== false) && (!!wsId || isDemoEnabled()),
    refetchInterval: 60_000,
    staleTime:       30_000,
    retry:           2,
  });
}

// ── useSummary ────────────────────────────────────────────────────────────────
// Calls workspace-scoped /workspaces/:wsId/summary. Normalises the response
// to the same shape the legacy /eol/summary returned so Dashboard is unchanged.

export function useSummary(params = {}) {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["summary", wsId, params],
    queryFn:  async () => {
      if (isDemoEnabled()) {
        return { ...MOCK_SUMMARY, accounts_total: 4, org_accounts: 0, isMock: true };
      }

      if (!wsId) return { totals: {}, resources_count: 0, accounts_total: 0, org_accounts: 0, isMock: false };

      const qs = new URLSearchParams(
        Object.fromEntries(Object.entries(params).filter(([, v]) => v))
      ).toString();
      const url = `${API_BASE_URL}/workspaces/${wsId}/summary${qs ? `?${qs}` : ""}`;
      const { data } = await axios.get(url, { headers: workspaceHeaders(), timeout: 8000 });

      // Normalise workspace summary → legacy Dashboard shape
      return {
        totals: {
          EOL:               data.resources?.eol              ?? 0,
          EXPIRING_SOON:     data.resources?.expiringSoon     ?? 0,
          EXTENDED_SUPPORT:  data.resources?.extendedSupport  ?? 0,
          SUPPORTED:         data.resources?.supported        ?? 0,
          UNKNOWN:           data.resources?.unknown          ?? 0,
          NEEDS_INSPECTION:      data.resources?.needsInspection     ?? 0,
          LIFECYCLE_NOT_TRACKED: data.resources?.lifecycleNotTracked ?? 0,
        },
        resources_count:  data.resources?.total     ?? 0,
        last_scanned:     data.lastScan?.completedAt ?? null,
        accounts_total:   data.accounts?.total       ?? 0,
        org_accounts:     data.accounts?.org         ?? 0,
        by_service:       normServiceBreakdown(data.serviceBreakdown),
        isMock: false,
      };
    },
    enabled:         !!wsId || isDemoEnabled(),
    refetchInterval: 60_000,
    staleTime:       30_000,
    retry:           2,
  });
}

// ── useResource ───────────────────────────────────────────────────────────────

export function useResource(id) {
  const wsId = getWorkspaceId();
  return useQuery({
    queryKey: ["resource", wsId, id],
    queryFn:  async () => {
      if (isDemoEnabled()) {
        const found = MOCK_INVENTORY.find(i => i.resource_id === id);
        return found ? { item: normalize(found), ckGuide: null } : null;
      }
      if (!wsId) return null;
      const { data } = await axios.get(
        `${API_BASE_URL}/workspaces/${wsId}/resource/${encodeURIComponent(id)}`,
        { headers: workspaceHeaders(), timeout: 8000 }
      );
      return { item: normalize(data.item), ckGuide: data.ckGuide ?? null };
    },
    enabled:   !!id && (!!wsId || isDemoEnabled()),
    staleTime: 5_000,
    retry:     2,
  });
}
