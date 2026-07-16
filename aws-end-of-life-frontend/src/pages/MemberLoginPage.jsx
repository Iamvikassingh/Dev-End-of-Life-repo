import React, { useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { API_BASE_URL } from "../utils/config";
import { copyToClipboard } from "../utils/clipboard";
import { ShieldCheck, Loader, AlertTriangle, Mail, ArrowRight, Copy, Check } from "lucide-react";

export default function MemberLoginPage() {
  const [wsId,    setWsId]    = useState("");
  const [email,   setEmail]   = useState("");
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState("");
  const [sent,    setSent]    = useState(false);
  const [devLink, setDevLink] = useState("");
  const [copied,  setCopied]  = useState(false);

  async function handleSubmit() {
    setError("");
    if (!wsId.trim())   { setError("Workspace ID is required."); return; }
    if (!email.trim())  { setError("Email address is required."); return; }
    setLoading(true);
    try {
      const { data } = await axios.post(
        `${API_BASE_URL}/workspaces/${wsId.trim()}/members/login-link`,
        { email: email.trim() },
        { timeout: 10000 },
      );
      setSent(true);
      if (data.devLoginLink) setDevLink(data.devLoginLink);
    } catch (e) {
      const msg = e?.response?.data?.error?.message;
      setError(msg || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function handleCopyDevLink() {
    const ok = await copyToClipboard(devLink);
    if (ok) { setCopied(true); setTimeout(() => setCopied(false), 3000); }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl p-8 space-y-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="rounded-2xl bg-blue-50 p-3">
            <ShieldCheck size={28} className="text-blue-600" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900">Member Sign In</h1>
            <p className="text-sm text-slate-500 mt-1">We'll email you a one-time login link.</p>
          </div>
        </div>

        {!sent ? (
          <>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Workspace ID</label>
                <input
                  type="text"
                  placeholder="ws_abc123..."
                  value={wsId}
                  onChange={e => setWsId(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && handleSubmit()}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                />
                <p className="text-xs text-slate-400 mt-1">Ask your workspace admin for this ID.</p>
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Email address</label>
                <input
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && handleSubmit()}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            {error && (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 flex items-start gap-2">
                <AlertTriangle size={14} className="text-red-500 mt-0.5 shrink-0" />
                <p className="text-xs text-red-700">{error}</p>
              </div>
            )}

            <button
              onClick={handleSubmit}
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60 transition-colors">
              {loading ? <Loader size={15} className="animate-spin" /> : <Mail size={15} />}
              Send login link
            </button>
          </>
        ) : (
          <div className="space-y-4">
            <div className="rounded-xl border border-green-200 bg-green-50 p-4 space-y-1">
              <p className="text-sm font-semibold text-green-800">Check your inbox</p>
              <p className="text-xs text-green-700">
                If <strong>{email}</strong> is registered in that workspace, a login link has been sent.
                It expires in 15 minutes.
              </p>
            </div>

            {devLink && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 space-y-2">
                <p className="text-xs font-semibold text-amber-800">Dev login link</p>
                <div className="flex flex-wrap gap-2">
                  <a href={devLink}
                    className="inline-flex items-center gap-1 rounded-lg bg-amber-100 px-3 py-2 text-xs font-semibold text-amber-900 hover:bg-amber-200 transition-colors">
                    Open login link
                    <ArrowRight size={13} />
                  </a>
                  <button type="button" onClick={handleCopyDevLink}
                    className="inline-flex items-center gap-1 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-amber-900 border border-amber-200 hover:bg-amber-100 transition-colors">
                    {copied ? <Check size={13} /> : <Copy size={13} />}
                    {copied ? "Copied!" : "Copy link"}
                  </button>
                </div>
              </div>
            )}

            <button
              onClick={() => { setSent(false); setDevLink(""); setCopied(false); setError(""); }}
              className="w-full text-sm text-slate-500 hover:text-slate-700 transition-colors">
              Try a different email
            </button>
          </div>
        )}

        <div className="border-t border-slate-100 pt-4 text-center">
          <p className="text-xs text-slate-400">
            Have a workspace token?{" "}
            <Link to="/overview" className="text-blue-600 hover:underline font-medium">Sign in here</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
