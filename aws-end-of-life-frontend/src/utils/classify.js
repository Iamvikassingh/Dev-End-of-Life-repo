export const STATUS_CONFIG = {
  EOL:               { label: "EOL",              bg: "bg-red-100",    text: "text-red-800",    hex: "#922B21", bghex: "#FDEDEC" },
  EXPIRING_SOON:     { label: "Expiring Soon",    bg: "bg-amber-100",  text: "text-amber-800",  hex: "#B7770D", bghex: "#FEF9E7" },
  EXTENDED_SUPPORT:  { label: "Ext. Support",     bg: "bg-blue-100",   text: "text-blue-800",   hex: "#1A6EBD", bghex: "#D6EAF8" },
  SUPPORTED:         { label: "Supported",        bg: "bg-green-100",  text: "text-green-800",  hex: "#0D6E56", bghex: "#D5F5E3" },
  UNKNOWN:           { label: "Unknown",          bg: "bg-gray-100",   text: "text-gray-600",   hex: "#6B7280", bghex: "#F3F4F6" },
  NEEDS_INSPECTION: {
    label: "Needs Inspection",
    bg: "bg-violet-100", text: "text-violet-700", hex: "#6D28D9", bghex: "#EDE9FE",
    tooltip: "Discovered, but lifecycle cannot be calculated from AWS metadata alone. Inspect the image/base runtime using SBOM or image scanning.",
  },
  LIFECYCLE_NOT_TRACKED: {
    label: "Lifecycle Not Tracked",
    bg: "bg-slate-100", text: "text-slate-500", hex: "#94A3B8", bghex: "#F1F5F9",
    tooltip: "Discovered, but no public EOL lifecycle is currently tracked for this resource type. It is excluded from main EOL risk counts.",
  },
};

export function classifyStatus(daysToEol, isExtended = false) {
  if (daysToEol === null || daysToEol === undefined) return "UNKNOWN";
  if (daysToEol < 0) return "EOL";
  if (daysToEol <= 180) return "EXPIRING_SOON";
  if (isExtended) return "EXTENDED_SUPPORT";
  return "SUPPORTED";
}

export function getStatusConfig(status) {
  return STATUS_CONFIG[status] ?? STATUS_CONFIG.UNKNOWN;
}

export function daysLabel(days) {
  if (days === null || days === undefined) return "Unknown";
  if (days < 0) return `${Math.abs(days)} days past EOL`;
  if (days === 0) return "EOL today";
  return `${days} days remaining`;
}

export const SERVICE_LABELS = {
  "Lambda":           "Lambda",
  "EKS":              "EKS",
  "RDS_postgres":     "RDS PostgreSQL",
  "RDS_mysql":        "RDS MySQL",
  "RDS_mariadb":      "RDS MariaDB",
  "RDS_postgresql":   "RDS PostgreSQL",
  "Aurora_PostgreSQL":"Aurora PostgreSQL",
  "Aurora_MySQL":     "Aurora MySQL",
  "ElastiCache":      "ElastiCache",
  "EC2":              "EC2",
  "CodeBuild":        "CodeBuild",
  "ElasticBeanstalk": "Elastic Beanstalk",
  "EMR":              "EMR",
  "MSK":              "MSK",
  "OpenSearch":       "OpenSearch",
  "DocumentDB":       "DocumentDB",
  "Neptune":          "Neptune",
  "Glue":             "Glue",
  "CloudFrontFunctions": "CloudFront Functions",
  "ECR":              "ECR",
};

export function serviceLabel(type) {
  if (!type) return "—";
  return SERVICE_LABELS[type] ?? type.replace(/_/g, " ");
}

// Runtime → recommended upgrade target (used in DetailPanel + ResourceDetailPage)
export const LAMBDA_UPGRADES = {
  "python3.7":   "python3.13",
  "python3.8":   "python3.13",
  "python3.9":   "python3.13",
  "python3.10":  "python3.13",
  "nodejs14.x":  "nodejs22.x",
  "nodejs16.x":  "nodejs22.x",
  "nodejs18.x":  "nodejs22.x",
  "java8":       "java21",
  "java8.al2":   "java21",
  "java11":      "java21",
  "ruby2.7":     "ruby3.3",
  "ruby3.2":     "ruby3.3",
  "dotnet6":     "dotnet8",
  "go1.x":       "provided.al2023",
};
