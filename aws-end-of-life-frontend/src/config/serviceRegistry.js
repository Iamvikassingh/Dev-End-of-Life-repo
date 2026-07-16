// Central service registry — single source of truth for display names, guide URLs,
// upgrade steps, and service-specific metadata fields shown in detail views.
// Add a new entry here when adding a new AWS service collector.

const _RDS_INSTANCE_GUIDE = {
  url:   "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_UpgradeDBInstance.Upgrading.html",
  text:  "Modify the DB instance to choose a newer engine version. Take a snapshot first.",
  steps: [
    "Create a manual snapshot before starting.",
    "Test the upgrade on a restored copy in a staging environment.",
    "Modify the DB instance engine version via the AWS Console or CLI.",
    "Monitor application compatibility and performance after upgrade.",
  ],
};

const _AURORA_GUIDE = {
  url:   "https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraMySQL.Updates.Patching.html",
  text:  "Modify the Aurora cluster to a newer engine version. Clone first for safety.",
  steps: [
    "Clone the Aurora cluster to validate the upgrade.",
    "Upgrade the cluster engine version in the AWS Console.",
    "Test application compatibility on the cloned cluster.",
    "Switch production traffic after successful validation.",
  ],
};

const _RDS_INSTANCE_FIELDS = [
  { key: "engine",             label: "Engine",               mono: true },
  { key: "db_instance_class",  label: "Instance Class",       mono: true },
  { key: "db_instance_status", label: "DB Status"                        },
  { key: "support_end_date",   label: "Standard Support End"             },
  { key: "final_eol_date",     label: "Extended Support End", skipIfSameAs: "eol_date" },
];

const _AURORA_FIELDS = [
  { key: "engine",           label: "Engine",               mono: true },
  { key: "cluster_status",   label: "Cluster Status"                   },
  { key: "engine_mode",      label: "Engine Mode"                      },
  { key: "support_end_date", label: "Standard Support End"             },
  { key: "final_eol_date",   label: "Extended Support End", skipIfSameAs: "eol_date" },
];

export const SERVICE_REGISTRY = {
  Lambda: {
    displayName:             "Lambda",
    category:                "Compute",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html",
      text:  "Upgrade the Lambda runtime in your function configuration.",
      steps: [
        "Review code and dependency compatibility with the target runtime.",
        "Update the runtime in Lambda function configuration (Console or AWS CLI).",
        "Test with a function alias or version in staging.",
        "Publish a new version and update event source mappings.",
      ],
    },
    metadataFields: [],
  },

  EC2: {
    displayName:             "EC2",
    category:                "Compute",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/linux/al2023/ug/migrate-to-al2023.html",
      text:  "Launch a new instance with Amazon Linux 2023 and migrate the workload.",
      steps: null,
    },
    metadataFields: [
      { key: "instance_type",            label: "Instance Type",      mono: true },
      { key: "instance_type_generation", label: "Instance Generation"            },
      { key: "instance_type_note",       label: "Instance Type Note"             },
      { key: "ami_id",                   label: "AMI ID",             mono: true },
      { key: "image_name",               label: "AMI Name",           mono: true },
      { key: "platform_details",         label: "Platform"                       },
      { key: "os_source",                label: "OS Detected Via"                },
      { key: "ssm_managed",              label: "SSM Managed",
        transform: v => v != null ? (v ? "Yes" : "No") : null },
      { key: "ssm_agent_status",         label: "SSM Agent Status"               },
      { key: "ssm_platform_name",        label: "SSM Platform"                   },
      { key: "ssm_platform_version",     label: "SSM Platform Version", mono: true },
      { key: "ssm_platform_type",        label: "SSM Platform Type"              },
      { key: "ssm_computer_name",        label: "SSM Computer Name",  mono: true },
      { key: "scan_warning",             label: "Scan Warning"                   },
    ],
  },

  EKS: {
    displayName:             "EKS",
    category:                "Containers",
    supportsExtendedSupport: true,
    guide: {
      url:   "https://docs.aws.amazon.com/eks/latest/userguide/update-cluster.html",
      text:  "Use eksctl or the AWS Console to upgrade the control plane, then upgrade node groups.",
      steps: [
        "Check add-on compatibility with the target version.",
        "Upgrade the control plane with eksctl or AWS Console.",
        "Update managed node groups or self-managed nodes.",
        "Verify workloads are healthy after upgrade.",
      ],
    },
    metadataFields: [
      { key: "platform_version",      label: "Platform Version",    mono: true },
      { key: "cluster_status",        label: "Cluster Status"                  },
      { key: "endpoint_public_access", label: "Public Endpoint",
        transform: v => v != null ? (v ? "Yes" : "No") : null },
      { key: "endpoint_private_access", label: "Private Endpoint",
        transform: v => v != null ? (v ? "Yes" : "No") : null },
      { key: "support_end_date",      label: "Standard Support End"            },
      { key: "final_eol_date",        label: "Extended Support End", skipIfSameAs: "eol_date" },
    ],
  },

  // RDS — base key used by DetailPanel/ResourceDetailPage serviceBase lookup
  RDS: {
    displayName:             "RDS",
    category:                "Database",
    supportsExtendedSupport: true,
    guide:          _RDS_INSTANCE_GUIDE,
    metadataFields: _RDS_INSTANCE_FIELDS,
  },
  RDS_mysql: {
    displayName:             "RDS MySQL",
    category:                "Database",
    supportsExtendedSupport: true,
    guide:          _RDS_INSTANCE_GUIDE,
    metadataFields: _RDS_INSTANCE_FIELDS,
  },
  RDS_postgres: {
    displayName:             "RDS PostgreSQL",
    category:                "Database",
    supportsExtendedSupport: true,
    guide:          _RDS_INSTANCE_GUIDE,
    metadataFields: _RDS_INSTANCE_FIELDS,
  },
  RDS_postgresql: {
    displayName:             "RDS PostgreSQL",
    category:                "Database",
    supportsExtendedSupport: true,
    guide:          _RDS_INSTANCE_GUIDE,
    metadataFields: _RDS_INSTANCE_FIELDS,
  },
  RDS_mariadb: {
    displayName:             "RDS MariaDB",
    category:                "Database",
    supportsExtendedSupport: false,
    guide:          _RDS_INSTANCE_GUIDE,
    metadataFields: _RDS_INSTANCE_FIELDS,
  },

  // Aurora — base key used by ResourceDetailPage (isAurora → "Aurora")
  Aurora: {
    displayName:             "Aurora",
    category:                "Database",
    supportsExtendedSupport: true,
    guide:          _AURORA_GUIDE,
    metadataFields: _AURORA_FIELDS,
  },
  Aurora_MySQL: {
    displayName:             "Aurora MySQL",
    category:                "Database",
    supportsExtendedSupport: true,
    guide:          _AURORA_GUIDE,
    metadataFields: _AURORA_FIELDS,
  },
  Aurora_PostgreSQL: {
    displayName:             "Aurora PostgreSQL",
    category:                "Database",
    supportsExtendedSupport: true,
    guide:          _AURORA_GUIDE,
    metadataFields: _AURORA_FIELDS,
  },

  ElastiCache: {
    displayName:             "ElastiCache",
    category:                "Caching",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/AmazonElastiCache/latest/red-ug/VersionManagement.html",
      text:  "Modify the cluster to upgrade the Redis engine version in-place.",
      steps: null,
    },
    metadataFields: [],
  },

  MSK: {
    displayName:             "MSK",
    category:                "Streaming",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/msk/latest/developerguide/version-upgrades.html",
      text:  "Use the AWS Console or API to update the broker version.",
      steps: null,
    },
    metadataFields: [
      { key: "kafka_version",     label: "Kafka Version", mono: true },
      { key: "cluster_state",     label: "Cluster State"             },
      { key: "broker_node_count", label: "Broker Nodes"              },
      { key: "current_version",   label: "MSK Current Version", mono: true },
    ],
  },

  CodeBuild: {
    displayName:             "CodeBuild",
    category:                "Developer Tools",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/codebuild/latest/userguide/build-env-ref-available.html",
      text:  "Update the project environment image to a current AWS managed image or maintained custom image.",
      steps: null,
    },
    metadataFields: [
      { key: "codebuild_image",  label: "Build Image", mono: true },
      { key: "environment_type", label: "Environment Type" },
      { key: "compute_type",     label: "Compute Type", mono: true },
      { key: "privileged_mode",  label: "Privileged Mode",
        transform: v => v != null ? (v ? "Yes" : "No") : null },
    ],
  },

  ElasticBeanstalk: {
    displayName:             "Elastic Beanstalk",
    category:                "Compute",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/using-features.platform.upgrade.html",
      text:  "Update the environment to a current Elastic Beanstalk platform branch/version.",
      steps: null,
    },
    metadataFields: [
      { key: "application_name",    label: "Application" },
      { key: "environment_name",    label: "Environment" },
      { key: "environment_status",  label: "Environment Status" },
      { key: "platform_arn",        label: "Platform ARN", mono: true },
      { key: "solution_stack_name", label: "Solution Stack", mono: true },
    ],
  },

  EMR: {
    displayName:             "EMR",
    category:                "Analytics",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/emr/latest/ReleaseGuide/emr-release-components.html",
      text:  "Move workloads to a current EMR release label and validate application compatibility.",
      steps: null,
    },
    metadataFields: [
      { key: "cluster_id",    label: "Cluster ID", mono: true },
      { key: "release_label", label: "Release Label", mono: true },
      { key: "cluster_state", label: "Cluster State" },
      { key: "applications",  label: "Applications" },
    ],
  },

  OpenSearch: {
    displayName:             "OpenSearch",
    category:                "Search",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/opensearch-service/latest/developerguide/version-migration.html",
      text:  "Use in-place or blue-green upgrade to a supported OpenSearch version.",
      steps: null,
    },
    metadataFields: [],
  },

  DocumentDB: {
    displayName:             "DocumentDB",
    category:                "Database",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/documentdb/latest/developerguide/upgrading.html",
      text:  "Upgrade the DocumentDB cluster to a supported engine version.",
      steps: null,
    },
    metadataFields: [],
  },

  Neptune: {
    displayName:             "Neptune",
    category:                "Database",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/neptune/latest/userguide/engine-releases.html",
      text:  "Upgrade the Neptune cluster to a supported engine version.",
      steps: null,
    },
    metadataFields: [],
  },

  Glue: {
    displayName:             "Glue",
    category:                "Analytics",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/glue/latest/dg/release-notes.html",
      text:  "Update jobs to a supported Glue version.",
      steps: null,
    },
    metadataFields: [
      { key: "glue_version", label: "Glue Version", mono: true },
      { key: "python_version", label: "Python Version", mono: true },
      { key: "spark_version", label: "Spark Version", mono: true },
      { key: "worker_type", label: "Worker Type", mono: true },
      { key: "command_name", label: "Command" },
      { key: "command_script_location", label: "Script", mono: true },
    ],
  },

  CloudFrontFunctions: {
    displayName:             "CloudFront Functions",
    category:                "Edge",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/cloudfront-functions.html",
      text:  "Review the function runtime and update to a current supported CloudFront Functions runtime.",
      steps: null,
    },
    metadataFields: [
      { key: "function_runtime", label: "Runtime", mono: true },
      { key: "function_stage",   label: "Stage" },
      { key: "function_status",  label: "Status" },
    ],
  },

  ECR: {
    displayName:             "ECR",
    category:                "Containers",
    supportsExtendedSupport: false,
    guide: {
      url:   "https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-scanning.html",
      text:  "Review image tags and base images; update containers to current maintained OS/runtime bases.",
      steps: null,
    },
    metadataFields: [
      { key: "repository_name", label: "Repository", mono: true },
      { key: "image_tag",       label: "Image Tag", mono: true },
      { key: "image_digest",    label: "Digest", mono: true },
      { key: "image_pushed_at", label: "Pushed At" },
      { key: "base_image_status", label: "Base Image Detection" },
    ],
  },
};

function _lookup(serviceType) {
  if (!serviceType) return null;
  if (SERVICE_REGISTRY[serviceType]) return SERVICE_REGISTRY[serviceType];
  // Fallback to base type (strip _<suffix>), e.g. "RDS_mysql" → "RDS"
  const base = serviceType.replace(/_.*/, "");
  return SERVICE_REGISTRY[base] ?? null;
}

export function getServiceDisplayName(serviceType) {
  return _lookup(serviceType)?.displayName ?? (serviceType ? serviceType.replace(/_/g, " ") : "—");
}

export function getServiceCategory(serviceType) {
  return _lookup(serviceType)?.category ?? null;
}

export function getAwsGuideUrl(serviceType) {
  return _lookup(serviceType)?.guide?.url ?? null;
}

export function getServiceGuide(serviceType) {
  return _lookup(serviceType)?.guide ?? null;
}

export function getMetadataFields(serviceType) {
  return _lookup(serviceType)?.metadataFields ?? [];
}
