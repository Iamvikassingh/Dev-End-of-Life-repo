import React from "react";
import { getMetadataFields } from "../config/serviceRegistry";

// Panel variant: horizontal flex (label left, value right) — used in DetailPanel sidebar.
function PanelRow({ label, value, mono }) {
  if (value === null || value === undefined || value === "" || value === "unknown") return null;
  return (
    <div className="flex items-start justify-between gap-4 py-2.5 border-b border-gray-100 last:border-0">
      <span className="text-xs font-medium text-gray-400 uppercase tracking-wide shrink-0 w-28">{label}</span>
      <span className={`text-xs text-right text-gray-800 break-all ${mono ? "font-mono" : "font-medium"}`}>
        {String(value)}
      </span>
    </div>
  );
}

// Page variant: vertical stack (label above value) — used in ResourceDetailPage.
function PageRow({ label, value, mono }) {
  if (value === null || value === undefined || value === "" || value === "unknown") return null;
  return (
    <div className="py-2.5 border-b border-gray-100 last:border-0">
      <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-0.5">{label}</p>
      <p className={`text-sm text-gray-900 font-medium break-all ${mono ? "font-mono text-xs" : ""}`}>
        {String(value)}
      </p>
    </div>
  );
}

/**
 * Renders service-specific metadata fields driven by serviceRegistry metadataFields config.
 * Does NOT render common fields (service, region, version, account, resource ID, scanned_at) —
 * those are rendered by the parent component.
 *
 * compact=true  → PanelRow style (DetailPanel sidebar)
 * compact=false → PageRow style  (ResourceDetailPage full view)
 */
export function GenericMetadataPanel({ item, compact = false }) {
  if (!item) return null;
  const Row    = compact ? PanelRow : PageRow;
  const fields = getMetadataFields(item.service_type);

  return (
    <>
      {fields.map(field => {
        let value = item[field.key];

        // Boolean fields need transformation before null-check
        if (field.transform) {
          value = field.transform(value);
        }

        if (value === null || value === undefined || value === "" || value === "unknown") return null;

        // Skip if value is same as a sibling field (e.g. final_eol_date === eol_date)
        if (field.skipIfSameAs && String(value) === String(item[field.skipIfSameAs])) return null;

        return <Row key={field.key} label={field.label} value={value} mono={field.mono} />;
      })}
    </>
  );
}
