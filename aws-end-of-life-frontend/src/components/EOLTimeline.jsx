import React from "react";
import { daysLabel, getStatusConfig } from "../utils/classify";

const NON_LIFECYCLE_STATUSES = new Set(["NEEDS_INSPECTION", "LIFECYCLE_NOT_TRACKED"]);

export function EOLTimeline({ daysToEol, eolDate, status, eolLabel = "EOL" }) {
  const cfg = getStatusConfig(status);

  if (NON_LIFECYCLE_STATUSES.has(status)) {
    return (
      <span className="text-xs text-slate-400 italic">
        {status === "LIFECYCLE_NOT_TRACKED" ? "No published EOL schedule" : "Not applicable"}
      </span>
    );
  }

  const pct = daysToEol === null ? 0
    : daysToEol < 0 ? 100
    : Math.max(0, Math.min(100, ((730 - daysToEol) / 730) * 100));

  const displayDate = eolDate && eolDate !== "unknown" ? eolDate : null;
  const label = daysLabel(daysToEol) + (displayDate ? ` · ${eolLabel}: ${displayDate}` : "");

  return (
    <div className="w-full min-w-[140px]">
      <div className="text-xs text-gray-500 mb-1 truncate" title={label}>
        {label}
      </div>
      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: cfg.hex }}
        />
      </div>
    </div>
  );
}
