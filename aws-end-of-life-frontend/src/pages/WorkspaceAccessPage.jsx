import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { CloudCog } from "lucide-react";
import WorkspaceAccessPanel from "../components/WorkspaceAccessPanel";

export default function WorkspaceAccessPage() {
  const navigate = useNavigate();
  const location = useLocation();

  const params      = new URLSearchParams(location.search);
  const destination = params.get("returnTo") || "/connected-accounts";

  return (
    <div className="min-h-screen flex items-center justify-center px-4"
      style={{ background: "#F0F4F8" }}>
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2.5 justify-center mb-8">
          <CloudCog size={28} className="text-sky-500" strokeWidth={1.5} />
          <div>
            <p className="font-extrabold text-slate-900 text-lg leading-tight">AWS EOL Monitor</p>
            <p className="text-xs text-slate-400 leading-tight">Track service end-of-life risk</p>
          </div>
        </div>
        <WorkspaceAccessPanel onSuccess={() => navigate(destination, { replace: true })} />
      </div>
    </div>
  );
}
