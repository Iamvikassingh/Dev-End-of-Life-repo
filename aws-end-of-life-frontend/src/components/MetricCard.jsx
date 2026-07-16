import React from "react";

const STATUS_META = {
  EOL:              { border: "border-l-red-500",   bg: "bg-red-50",    text: "text-red-700",   num: "text-red-800",   ring: "ring-red-400",   hint: "Already unsupported"      },
  EXPIRING_SOON:    { border: "border-l-amber-500", bg: "bg-amber-50",  text: "text-amber-700", num: "text-amber-800", ring: "ring-amber-400", hint: "Needs upgrade planning"   },
  EXTENDED_SUPPORT: { border: "border-l-blue-500",  bg: "bg-blue-50",   text: "text-blue-700",  num: "text-blue-800",  ring: "ring-blue-400",  hint: "Review paid support"      },
  SUPPORTED:        { border: "border-l-green-500", bg: "bg-green-50",  text: "text-green-700", num: "text-green-800", ring: "ring-green-400", hint: "Healthy resources"          },
  UNKNOWN:          { border: "border-l-slate-400", bg: "bg-slate-50",  text: "text-slate-600", num: "text-slate-800", ring: "ring-slate-300", hint: "Version not confirmed"     },
};

export function MetricCard({ label, value, status, onClick, loading, active }) {
  const c = STATUS_META[status] ?? { border: "border-l-gray-400", bg: "bg-white", text: "text-gray-500", num: "text-gray-800", ring: "ring-gray-300", hint: "" };

  return (
    <button
      onClick={onClick}
      className={`h-full min-h-[118px] w-full text-left rounded-2xl p-5 border-l-4 shadow-sm transition-all
        hover:shadow-md hover:-translate-y-0.5 ${c.border} ${c.bg}
        ${active ? `ring-2 ${c.ring} ring-offset-1` : ""}
        ${onClick ? "cursor-pointer" : "cursor-default"}`}
    >
      <p className={`text-xs font-bold uppercase tracking-widest ${c.text}`}>{label}</p>
      {loading ? (
        <div className="mt-2 h-8 w-16 bg-current opacity-20 animate-pulse rounded" />
      ) : (
        <p className={`text-3xl font-bold mt-2 mb-1 leading-none ${c.num}`}>{value ?? 0}</p>
      )}
      {active
        ? <p className={`text-xs ${c.text} opacity-70`}>Filtering ✓ — click to clear</p>
        : <p className={`text-xs ${c.text} opacity-60`}>{c.hint}</p>}
    </button>
  );
}
