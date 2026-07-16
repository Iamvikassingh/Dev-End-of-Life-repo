import React, { useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { API_BASE_URL } from "../utils/config";
import { setMemberSession } from "../utils/workspace";
import { ShieldCheck, Loader, AlertTriangle, ArrowRight } from "lucide-react";

export default function AcceptInvitePage() {
  const [params]   = useSearchParams();
  const navigate   = useNavigate();
  const wsId       = params.get("wsId")  || "";
  const token      = params.get("token") || "";

  const [name,    setName]    = useState("");
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState("");
  const [done,    setDone]    = useState(false);

  const invalid = !wsId || !token;

  async function handleAccept() {
    setError("");
    setLoading(true);
    try {
      const { data } = await axios.post(
        `${API_BASE_URL}/workspaces/${wsId}/members/accept-invite`,
        { token, name: name.trim() || undefined },
        { timeout: 8000 }
      );
      setMemberSession(
        data.workspaceId,
        data.workspaceName,
        data.memberSessionToken,
        data.role,
        data.memberId,
        data.memberName,
        data.expiresAt,
      );
      setDone(true);
      // Brief pause so the user sees the success state, then redirect
      setTimeout(() => navigate("/dashboard", { replace: true }), 1200);
    } catch (e) {
      const msg = e?.response?.data?.error?.message;
      setError(msg || "Failed to accept invite. The link may have expired.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl p-8 space-y-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="rounded-2xl bg-blue-50 p-3">
            <ShieldCheck size={28} className="text-blue-600" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900">Accept Invitation</h1>
            <p className="text-sm text-slate-500 mt-1">You've been invited to join an AWS EOL Monitor workspace.</p>
          </div>
        </div>

        {invalid && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 flex items-start gap-2">
            <AlertTriangle size={16} className="text-red-500 mt-0.5 shrink-0" />
            <p className="text-sm text-red-700">This invite link is invalid or incomplete.</p>
          </div>
        )}

        {!invalid && !done && (
          <>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Your name (optional)</label>
              <input
                type="text"
                placeholder="Jane Smith"
                value={name}
                onChange={e => setName(e.target.value)}
                onKeyDown={e => e.key === "Enter" && handleAccept()}
                className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            {error && (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 flex items-start gap-2">
                <AlertTriangle size={14} className="text-red-500 mt-0.5 shrink-0" />
                <p className="text-xs text-red-700">{error}</p>
              </div>
            )}
            <button
              onClick={handleAccept}
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60 transition-colors">
              {loading && <Loader size={15} className="animate-spin" />}
              Accept Invitation
            </button>
          </>
        )}

        {done && (
          <div className="space-y-4">
            <div className="rounded-xl border border-green-200 bg-green-50 p-4 text-center space-y-2">
              <p className="text-sm font-semibold text-green-800">You're in! Redirecting to your workspace…</p>
              <Loader size={16} className="animate-spin text-green-600 mx-auto" />
            </div>
            <button
              onClick={() => navigate("/dashboard", { replace: true })}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-slate-800 px-4 py-3 text-sm font-semibold text-white hover:bg-slate-700 transition-colors">
              Continue to Dashboard <ArrowRight size={15} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
