import React, { useState, useRef, useCallback } from "react";
import { createPortal } from "react-dom";
import { Info } from "lucide-react";
import { getStatusConfig } from "../utils/classify";

function InfoTooltip({ text }) {
  const [pos, setPos]       = useState(null);
  const ref                 = useRef(null);
  const TOOLTIP_W           = 264;

  const show = useCallback(() => {
    if (!ref.current) return;
    const rect  = ref.current.getBoundingClientRect();
    let   left  = rect.left;
    const top   = rect.bottom + 6;
    if (left + TOOLTIP_W > window.innerWidth - 8) {
      left = window.innerWidth - TOOLTIP_W - 8;
    }
    setPos({ top, left });
  }, []);

  const hide = useCallback(() => setPos(null), []);

  return (
    <span ref={ref} onMouseEnter={show} onMouseLeave={hide}
      className="inline-flex items-center cursor-help">
      <Info size={12} className="text-slate-400" strokeWidth={2} />
      {pos && createPortal(
        <span style={{ position: "fixed", top: pos.top, left: pos.left, width: TOOLTIP_W, zIndex: 9999 }}
          className="rounded-lg bg-slate-900 px-3 py-2 text-xs leading-relaxed text-white shadow-xl pointer-events-none">
          {text}
        </span>,
        document.body
      )}
    </span>
  );
}

export function StatusBadge({ status, size = "sm" }) {
  const cfg     = getStatusConfig(status);
  const padding = size === "sm" ? "px-2.5 py-0.5 text-xs" : "px-3 py-1 text-sm";
  const badge   = (
    <span className={`inline-flex items-center rounded-full font-bold whitespace-nowrap ${padding} ${cfg.bg} ${cfg.text}`}>
      {cfg.label}
    </span>
  );

  if (!cfg.tooltip) return badge;

  return (
    <span className="inline-flex items-center gap-1">
      {badge}
      <InfoTooltip text={cfg.tooltip} />
    </span>
  );
}
