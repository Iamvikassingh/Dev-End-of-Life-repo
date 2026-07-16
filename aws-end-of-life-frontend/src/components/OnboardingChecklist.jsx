import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Circle, ChevronDown, ChevronUp, X, ArrowRight } from "lucide-react";
import { isDemoWorkspace, getWorkspaceId } from "../utils/workspace";

function dismissKey() {
  const wsId = getWorkspaceId() || "default";
  return `eolm_onboarding_dismissed_${wsId}`;
}

function Step({ done, label, actionLabel, onAction }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2.5">
        {done
          ? <CheckCircle2 size={16} className="text-emerald-500 shrink-0" strokeWidth={2} />
          : <Circle      size={16} className="text-slate-300  shrink-0" strokeWidth={1.75} />}
        <span className={`text-sm ${done ? "text-slate-400 line-through" : "text-slate-700 font-medium"}`}>
          {label}
        </span>
      </div>
      {!done && actionLabel && (
        <button
          onClick={onAction}
          className="shrink-0 inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-800 transition-colors"
        >
          {actionLabel} <ArrowRight size={11} strokeWidth={2.5} />
        </button>
      )}
    </div>
  );
}

// Props:
//   hasAccounts — true/false/null (null = still loading from server)
//   hasScanned  — true/false/null
//   hasAlerts   — true/false
export default function OnboardingChecklist({ hasAccounts, hasScanned, hasAlerts }) {
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState(
    () => !!localStorage.getItem(dismissKey())
  );
  const [collapsed, setCollapsed] = useState(false);

  if (dismissed) return null;
  if (isDemoWorkspace()) return null;

  // Hide once both key setup steps are complete. Alerts CTA is optional.
  const setupComplete = hasAccounts === true && hasScanned === true;
  if (setupComplete) return null;

  function dismiss() {
    localStorage.setItem(dismissKey(), "1");
    setDismissed(true);
  }

  const steps = [
    {
      done: true,
      label: "Access workspace",
      actionLabel: null,
      onAction: null,
    },
    {
      done: hasAccounts === true,
      label: "Connect an AWS account",
      actionLabel: "Connect →",
      onAction: () => navigate("/account-scan"),
    },
    {
      done: hasScanned === true,
      label: "Run first scan",
      actionLabel: "Go to Accounts",
      onAction: () => navigate("/connected-accounts"),
    },
    // Only show "Review alerts" step when a scan has run and alerts exist
    ...(hasScanned === true && hasAlerts ? [{
      done: false,
      label: "Review alerts",
      actionLabel: "View Alerts",
      onAction: () => navigate("/alerts"),
    }] : []),
  ];

  const completedCount = steps.filter(s => s.done).length;
  const total = steps.length;

  return (
    <div className="mx-6 mt-4 rounded-2xl border border-indigo-100 bg-indigo-50/60 px-4 py-3.5 shadow-sm">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2.5">
          <span className="text-sm font-bold text-indigo-700">Getting started</span>
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-600">
            {completedCount}/{total}
          </span>
          <div className="h-1.5 w-24 rounded-full bg-indigo-100 overflow-hidden">
            <div
              className="h-full bg-indigo-400 rounded-full transition-all"
              style={{ width: `${(completedCount / total) * 100}%` }}
            />
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setCollapsed(c => !c)}
            className="p-1 rounded-md text-indigo-400 hover:text-indigo-700 hover:bg-indigo-100 transition-colors"
          >
            {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </button>
          <button
            onClick={dismiss}
            className="p-1 rounded-md text-indigo-300 hover:text-indigo-600 hover:bg-indigo-100 transition-colors"
            title="Dismiss checklist"
          >
            <X size={13} strokeWidth={2} />
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="space-y-2.5">
          {steps.map((step, i) => (
            <Step key={i} {...step} />
          ))}
        </div>
      )}
    </div>
  );
}
