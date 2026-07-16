import React, { useMemo } from "react";
import { Search, X } from "lucide-react";
import { AppSelect } from "./AppSelect";

const SERVICE_OPTIONS = [
  { value: "",            label: "All Services"         },
  { value: "Lambda",      label: "Lambda"               },
  { value: "EKS",         label: "EKS"                  },
  { value: "RDS",         label: "RDS"                  },
  { value: "Aurora",      label: "Aurora"               },
  { value: "ElastiCache", label: "ElastiCache"          },
  { value: "EC2",         label: "EC2"                  },
  { value: "CodeBuild",   label: "CodeBuild"            },
  { value: "ElasticBeanstalk", label: "Elastic Beanstalk" },
  { value: "EMR",         label: "EMR"                  },
  { value: "MSK",         label: "MSK"                  },
  { value: "OpenSearch",  label: "OpenSearch"           },
  { value: "DocumentDB",  label: "DocumentDB"           },
  { value: "Neptune",     label: "Neptune"              },
  { value: "Glue",        label: "Glue"                 },
  { value: "CloudFrontFunctions", label: "CloudFront Functions" },
  { value: "ECR",         label: "ECR"                  },
];

const STATUS_OPTIONS = [
  { value: "",                     label: "All statuses"        },
  { value: "EOL",                  label: "EOL"                 },
  { value: "EXPIRING_SOON",        label: "Expiring Soon"       },
  { value: "EXTENDED_SUPPORT",     label: "Ext. Support"        },
  { value: "SUPPORTED",            label: "Supported"           },
  { value: "UNKNOWN",              label: "Unknown"             },
  { value: "NEEDS_INSPECTION",     label: "Needs Inspection"    },
  { value: "LIFECYCLE_NOT_TRACKED",label: "Lifecycle Not Tracked"},
];

const CONTROL_CLS = "h-10 text-sm border border-slate-200 rounded-lg bg-white px-3 text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-300";

export function FilterBar({ filters, onChange, totalFiltered, accounts = [], accountLabel = "All Accounts" }) {
  function set(key, value) {
    onChange({ ...filters, [key]: value });
  }

  const hasFilters = Object.values(filters).some(Boolean);
  const showAccountFilter = accounts.length > 1;

  const accountOptions = useMemo(() => [
    { value: "", label: accountLabel },
    ...accounts.map(a => ({ value: a.id, label: a.accountName || a.name || a.id })),
  ], [accounts, accountLabel]);

  const gridCls = showAccountFilter
    ? "lg:grid-cols-[minmax(240px,1.4fr)_minmax(150px,0.7fr)_minmax(140px,0.7fr)_minmax(160px,0.8fr)_minmax(170px,0.8fr)_auto]"
    : "lg:grid-cols-[minmax(260px,1.4fr)_minmax(140px,0.7fr)_minmax(160px,0.8fr)_minmax(180px,0.8fr)_auto]";

  return (
    <div className={`mb-5 grid grid-cols-1 items-center gap-3 sm:grid-cols-2 ${gridCls}`}>
      {/* Search */}
      <div className="relative min-w-0">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        <input
          type="text"
          placeholder="Search resources, versions…"
          value={filters.search ?? ""}
          onChange={e => set("search", e.target.value)}
          className={`${CONTROL_CLS} w-full pl-8`}
        />
      </div>

      {/* Account filter */}
      {showAccountFilter && (
        <AppSelect
          value={filters.account_id ?? ""}
          options={accountOptions}
          onChange={val => set("account_id", val)}
          size="lg"
          fullWidth
        />
      )}

      {/* Service */}
      <AppSelect
        value={filters.service ?? ""}
        options={SERVICE_OPTIONS}
        onChange={val => set("service", val)}
        size="lg"
        fullWidth
      />

      {/* Status */}
      <AppSelect
        value={filters.status ?? ""}
        options={STATUS_OPTIONS}
        onChange={val => set("status", val)}
        size="lg"
        fullWidth
      />

      {/* Region */}
      <input
        type="text"
        placeholder="Region (e.g. us-east-1)"
        value={filters.region ?? ""}
        onChange={e => set("region", e.target.value)}
        className={`${CONTROL_CLS} w-full`}
      />

      {/* Clear filters */}
      {hasFilters && (
        <button
          onClick={() => onChange({ search: "", account_id: "", service: "", status: "", region: "" })}
          className="flex h-10 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-600 transition-all hover:bg-slate-50"
        >
          <X size={13} strokeWidth={2} /> Clear filters
        </button>
      )}

      {/* Filtered count */}
      {hasFilters && totalFiltered !== undefined && (
        <span className={`text-xs text-gray-400 ${showAccountFilter ? "lg:col-span-6" : "lg:col-span-5"}`}>
          Showing {totalFiltered} resource{totalFiltered !== 1 ? "s" : ""}
        </span>
      )}
    </div>
  );
}
