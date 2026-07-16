import React from "react";
import { useNavigate } from "react-router-dom";
import { FlaskConical, X, ArrowRight } from "lucide-react";
import { clearWorkspace } from "../utils/workspace";

export default function DemoWorkspaceBanner() {
  const navigate = useNavigate();

  function exitDemo() {
    clearWorkspace();
    navigate("/overview", { replace: true });
  }

  return (
    <div className="w-full bg-amber-50 border-b border-amber-200 px-4 py-2.5 flex items-center justify-between gap-4 shrink-0">
      <div className="flex items-center gap-2.5 min-w-0">
        <FlaskConical size={15} className="text-amber-600 shrink-0" strokeWidth={1.75} />
        <span className="text-sm font-medium text-amber-800">
          Demo workspace — sample data only.
        </span>
        <button
          onClick={() => navigate("/account-scan")}
          className="hidden sm:inline-flex items-center gap-1 text-xs font-semibold text-amber-700 hover:text-amber-900 underline underline-offset-2 transition-colors"
        >
          Connect your AWS account for real results
          <ArrowRight size={11} strokeWidth={2.5} />
        </button>
      </div>
      <button
        onClick={exitDemo}
        className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1 text-xs font-semibold text-amber-700 hover:bg-amber-100 transition-colors"
      >
        <X size={12} strokeWidth={2.5} />
        Exit Demo
      </button>
    </div>
  );
}
