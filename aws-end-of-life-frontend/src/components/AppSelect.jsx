import React, { useState, useRef, useEffect } from "react";
import { ChevronDown, Check } from "lucide-react";

/**
 * AppSelect — product-wide custom dropdown replacing native <select>.
 *
 * Props:
 *   value        – current selected value (string)
 *   onChange     – callback(newValue: string)
 *   options      – [{ value: string, label: string }]
 *   placeholder  – label shown when value is "" or unmatched (default "Select…")
 *   size         – "sm" | "md" (default) | "lg"
 *   fullWidth    – if true, trigger button stretches to parent width
 *   disabled     – disables interaction
 *   className    – extra classes applied to the trigger button
 */
export function AppSelect({
  value,
  onChange,
  options = [],
  placeholder = "Select…",
  size = "md",
  fullWidth = false,
  disabled = false,
  className = "",
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  // Close on outside click
  useEffect(() => {
    function onMouseDown(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, []);

  // Close on Escape
  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const SIZE = {
    sm: { h: "h-8",  pad: "pl-2.5 pr-7",  text: "text-xs",  radius: "rounded-lg",  chevron: 12 },
    md: { h: "h-9",  pad: "pl-3.5 pr-8",  text: "text-sm",  radius: "rounded-xl",  chevron: 13 },
    lg: { h: "h-10", pad: "pl-3.5 pr-8",  text: "text-sm",  radius: "rounded-xl",  chevron: 13 },
  };
  const s = SIZE[size] ?? SIZE.md;

  const selected  = options.find(o => o.value === value);
  const label     = selected?.label ?? placeholder;
  const hasValue  = value !== "" && value != null;
  const wFull     = fullWidth ? "w-full" : "";

  return (
    <div ref={containerRef} className={`relative ${wFull}`}>
      {/* Trigger */}
      <button
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setOpen(o => !o)}
        className={`
          inline-flex items-center justify-between gap-2
          ${s.h} ${s.pad} ${s.radius} ${s.text} ${wFull}
          border font-semibold whitespace-nowrap transition-all
          ${open
            ? "border-indigo-300 ring-2 ring-indigo-100 bg-white text-slate-900"
            : hasValue
              ? "border-indigo-200 bg-indigo-50 text-indigo-800 hover:border-indigo-300"
              : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50"
          }
          ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
          ${className}
        `.trim().replace(/\s+/g, " ")}
      >
        <span className="truncate">{label}</span>
        <ChevronDown
          size={s.chevron}
          strokeWidth={2.5}
          className={`shrink-0 transition-transform duration-150 ${
            open ? "rotate-180 text-indigo-400" : "text-slate-400"
          }`}
        />
      </button>

      {/* Dropdown panel */}
      {open && (
        <div className="absolute left-0 top-full mt-1.5 z-50 min-w-full min-w-[180px] rounded-xl border border-slate-200 bg-white shadow-xl shadow-slate-200/60 py-1 overflow-hidden">
          <div className="max-h-56 overflow-y-auto">
            {options.map(opt => {
              const isSel = opt.value === value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => { onChange(opt.value); setOpen(false); }}
                  className={`w-full flex items-center justify-between gap-4 px-3.5 py-2 text-sm text-left transition-colors ${
                    isSel
                      ? "bg-indigo-50 text-indigo-700 font-semibold"
                      : "text-slate-700 font-medium hover:bg-slate-50"
                  }`}
                >
                  <span>{opt.label}</span>
                  {isSel && <Check size={13} strokeWidth={2.5} className="shrink-0 text-indigo-500" />}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
