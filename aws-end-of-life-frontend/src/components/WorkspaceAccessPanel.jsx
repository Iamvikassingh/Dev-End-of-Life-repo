/**
 * Workspace access panel — used both inline (within app layout) and
 * standalone (WorkspaceAccessPage). Accepts onSuccess() callback.
 * Optional title/subtitle props let callers pass page-specific copy.
 */
import React, { useState } from "react";
import { KeyRound, Eye, EyeOff, Copy, Check, Plus, Download, AlertTriangle, Mail, LogIn, ShieldCheck, ChevronDown } from "lucide-react";
import { API_BASE_URL, HAS_API } from "../utils/config";
import { setWorkspace, getWorkspaceId } from "../utils/workspace";
import { copyToClipboard } from "../utils/clipboard";
import { useAuthConfig } from "../hooks/useAuthConfig";

function friendlyError(status, data, fallback) {
  const msg = data?.error?.message || data?.error || "";
  if (status === 404 || (typeof msg === "string" && msg.startsWith("No route for"))) {
    return "Service temporarily unavailable. Please restart the backend and try again.";
  }
  return msg || fallback;
}

function csvCell(value) {
  return `"${String(value ?? "").replace(/"/g, '""')}"`;
}

function safeFilePart(value) {
  return String(value || "workspace")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || "workspace";
}

function downloadWorkspaceCsv(result) {
  const createdAt = result.created_at || new Date().toISOString();
  const rows = [
    ["Workspace Name", "Workspace ID", "Access Token", "Created At", "Note"],
    [
      result.name || "",
      result.workspace_id || "",
      result.token || "",
      createdAt,
      "Save this token now. It will not be shown again.",
    ],
  ];
  const csv = rows.map(row => row.map(csvCell).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url;
  a.download = `aws-eol-monitor-workspace-${safeFilePart(result.name || result.workspace_id)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function CopyBtn({ value, onCopied }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    const ok = await copyToClipboard(value);
    if (ok) {
      setCopied(true);
      onCopied?.();
      setTimeout(() => setCopied(false), 2000);
    }
  }
  return (
    <button type="button" onClick={copy}
      className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
        copied
          ? "bg-emerald-50 text-emerald-600"
          : "bg-gray-100 text-gray-500 hover:bg-gray-200 hover:text-gray-700"
      }`}>
      {copied ? <><Check size={11} strokeWidth={2.5} /> Copied</> : <><Copy size={11} strokeWidth={1.75} /> Copy</>}
    </button>
  );
}

function AccessForm({ onSuccess }) {
  const rememberedId              = getWorkspaceId() || "";
  const [wsId, setWsId]           = useState(rememberedId);
  const [token, setToken]         = useState("");
  const [show, setShow]           = useState(false);
  const [error, setError]         = useState("");
  const [loading, setLoading]     = useState(false);

  const inputCls = "w-full rounded-xl border border-gray-200 px-3.5 py-2.5 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-300/60 focus:border-indigo-300 transition-colors";
  const isRemembered = rememberedId && wsId === rememberedId;

  async function submit(e) {
    e.preventDefault();
    const id  = wsId.trim();
    const tok = token.trim();
    if (!id || !tok) { setError("Both Workspace ID and Access Token are required."); return; }
    setLoading(true); setError("");
    try {
      if (HAS_API) {
        const r    = await fetch(`${API_BASE_URL}/workspaces/${id}/validate`, {
          headers: { "X-Workspace-Token": tok },
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.valid) {
          setError(friendlyError(r.status, data, "Invalid workspace ID or token."));
          setLoading(false); return;
        }
        setWorkspace(id, tok, data.workspace?.name || "");
      } else {
        setWorkspace(id, tok, "Demo Workspace");
      }
      onSuccess();
    } catch { setError("Could not reach the server. Check your connection."); }
    setLoading(false);
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1.5">Workspace ID</label>
        <input
          type="text"
          name="username"
          id="ws-workspace-id"
          autoComplete="username"
          placeholder="ws_xxxxxxxxxxxxxxxx"
          value={wsId}
          onChange={e => { setWsId(e.target.value); setError(""); }}
          className={inputCls}
          autoFocus={!rememberedId}
        />
        {isRemembered && (
          <p className="text-xs text-slate-400 mt-1">
            Last used workspace ID. Enter its access token to continue.
          </p>
        )}
      </div>
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1.5">Access Token</label>
        <div className="relative">
          <input
            type={show ? "text" : "password"}
            name="password"
            id="ws-access-token"
            autoComplete="current-password"
            placeholder="eolm_ws_••••••••••••"
            value={token}
            onChange={e => { setToken(e.target.value); setError(""); }}
            className={`${inputCls} pr-10`}
            autoFocus={!!rememberedId}
          />
          <button type="button" onClick={() => setShow(v => !v)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
            {show ? <EyeOff size={15} strokeWidth={1.75} /> : <Eye size={15} strokeWidth={1.75} />}
          </button>
        </div>
      </div>
      {error && <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
      <button type="submit" disabled={loading}
        className="w-full rounded-xl bg-slate-900 py-2.5 text-sm font-bold text-white hover:bg-slate-700 transition-colors disabled:opacity-60">
        {loading ? "Verifying…" : "Access Workspace →"}
      </button>
    </form>
  );
}

function CreateForm({ onSuccess }) {
  const [name, setName]       = useState("");
  const [result, setResult]   = useState(null);
  const [saved, setSaved]     = useState(false);
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(false);

  const inputCls = "w-full rounded-xl border border-gray-200 px-3.5 py-2.5 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-300/60 focus:border-indigo-300 transition-colors";

  async function submit(e) {
    e.preventDefault();
    if (!name.trim()) { setError("Workspace name is required."); return; }
    setLoading(true); setError("");
    try {
      if (HAS_API) {
        const r    = await fetch(`${API_BASE_URL}/workspaces`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: name.trim() }),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
          setError(friendlyError(r.status, data, "Failed to create workspace."));
          setLoading(false); return;
        }
        setResult({ ...data, created_at: data.created_at || new Date().toISOString() });
        setSaved(false);
        setWorkspace(data.workspace_id, data.token, data.name);
      } else {
        const fakeId    = `ws_demo_${Math.random().toString(36).slice(2, 10)}`;
        const fakeToken = `eolm_live_${Math.random().toString(36).slice(2, 22)}`;
        const data      = { workspace_id: fakeId, token: fakeToken, name: name.trim(), created_at: new Date().toISOString(), demo: true };
        setResult(data);
        setSaved(false);
        setWorkspace(fakeId, fakeToken, name.trim());
      }
    } catch { setError("Could not reach the server. Check your connection."); }
    setLoading(false);
  }

  function handleDownloadCsv() {
    if (result?.demo) return;
    downloadWorkspaceCsv(result);
    setSaved(true);
  }

  if (result) {
    const isDemo = !!result.demo;
    return (
      <div className="space-y-4">
        <div className="rounded-xl bg-emerald-50 ring-1 ring-emerald-200 px-4 py-3">
          <p className="text-xs font-bold text-emerald-700 mb-0.5">Workspace created!</p>
          <p className="text-xs text-emerald-600">
            {isDemo ? "Demo credentials created for local exploration." : "Save this access token now. It will not be shown again."}
          </p>
        </div>
        <div className="space-y-2">
          <div className="bg-gray-50 rounded-xl px-4 py-3 space-y-1">
            <p className="text-xs text-gray-400 font-medium">Workspace ID</p>
            <div className="flex items-center justify-between gap-2">
              <code className="text-sm font-mono font-semibold text-gray-800">{result.workspace_id}</code>
              <CopyBtn value={result.workspace_id} />
            </div>
          </div>
          <div className="bg-amber-50 ring-1 ring-amber-200 rounded-xl px-4 py-3 space-y-1">
            <p className="text-xs text-amber-600 font-semibold">Access Token — save this now</p>
            <p className="text-xs text-amber-700">
              {isDemo
                ? "Sample/demo token for this browser session."
                : "This token is shown only once. Copy it or download the CSV before continuing."}
            </p>
            <div className="flex items-center justify-between gap-2">
              <code className="text-xs font-mono font-semibold text-amber-900 break-all leading-relaxed">{result.token}</code>
              <CopyBtn value={result.token} onCopied={() => setSaved(true)} />
            </div>
          </div>
        </div>
        {!isDemo && (
          <div className="rounded-xl bg-orange-50 ring-1 ring-orange-100 px-4 py-3 text-xs text-orange-700">
            <p className="flex gap-2 font-semibold">
              <AlertTriangle size={14} className="mt-px shrink-0" strokeWidth={2} />
              Anyone with this token can access this workspace. Store it securely.
            </p>
          </div>
        )}
        <button
          type="button"
          onClick={handleDownloadCsv}
          disabled={isDemo}
          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white py-2.5 text-sm font-bold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          title={isDemo ? "Demo workspace credentials are sample data; CSV download is disabled." : undefined}
        >
          <Download size={15} strokeWidth={2} />
          Download credentials CSV
        </button>
        <p className={`text-xs ${saved ? "text-emerald-600" : "text-amber-700"}`}>
          {saved
            ? "Credentials saved. You can continue now."
            : "Copy the access token or download the CSV to continue."}
        </p>
        <button onClick={onSuccess} disabled={!saved}
          className="w-full rounded-xl bg-slate-900 py-2.5 text-sm font-bold text-white hover:bg-slate-700 transition-colors disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500">
          Continue to Dashboard →
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1.5">Workspace Name</label>
        <input type="text" placeholder="e.g. Acme Corp, My Team, Production"
          value={name} onChange={e => { setName(e.target.value); setError(""); }}
          className={inputCls} autoFocus />
        <p className="text-xs text-gray-400 mt-1">A friendly name for your workspace.</p>
      </div>
      {error && <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
      <button type="submit" disabled={loading}
        className="w-full rounded-xl bg-slate-900 py-2.5 text-sm font-bold text-white hover:bg-slate-700 transition-colors disabled:opacity-60">
        {loading ? "Creating…" : "Create Workspace →"}
      </button>
    </form>
  );
}

// ── Email signup form (shown when AUTH_EMAIL_SIGNUP_ENABLED=true) ─────────────

function EmailSignupForm({ captchaEnabled, captchaProvider, captchaSiteKey }) {
  const [email,   setEmail]   = useState("");
  const [name,    setName]    = useState("");
  const [status,  setStatus]  = useState("idle"); // idle | loading | sent | error
  const [message, setMessage] = useState("");

  const inputCls = "w-full rounded-xl border border-gray-200 px-3.5 py-2.5 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-300/60 focus:border-indigo-300 transition-colors";

  async function submit(e) {
    e.preventDefault();
    if (!email.trim() || !name.trim()) {
      setMessage("Name and email are required."); setStatus("error"); return;
    }
    setStatus("loading"); setMessage("");
    try {
      const body = { email: email.trim(), name: name.trim() };
      const r    = await fetch(`${API_BASE_URL}/auth/signup`, {
        method:      "POST",
        headers:     { "Content-Type": "application/json" },
        credentials: "include",
        body:        JSON.stringify(body),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setMessage(data.message || "Signup failed. Please try again.");
        setStatus("error"); return;
      }
      if (data.status === "verification_required") {
        setStatus("sent");
        setMessage(data.message || "Check your email for a verification link.");
      } else {
        // No verification needed — session cookie set
        window.location.reload();
      }
    } catch {
      setMessage("Could not reach the server. Check your connection.");
      setStatus("error");
    }
  }

  if (status === "sent") {
    return (
      <div className="rounded-xl bg-emerald-50 ring-1 ring-emerald-200 px-4 py-5 text-center">
        <Mail size={28} className="mx-auto mb-2 text-emerald-600" strokeWidth={1.5} />
        <p className="text-sm font-bold text-emerald-800 mb-1">Check your email</p>
        <p className="text-xs text-emerald-700 leading-relaxed">{message}</p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1.5">Full name</label>
        <input type="text" placeholder="Your name" value={name}
          onChange={e => { setName(e.target.value); setStatus("idle"); setMessage(""); }}
          className={inputCls} autoFocus />
      </div>
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1.5">Email address</label>
        <input type="email" placeholder="you@company.com" value={email}
          onChange={e => { setEmail(e.target.value); setStatus("idle"); setMessage(""); }}
          className={inputCls} />
      </div>
      {captchaEnabled && captchaProvider === "turnstile" && captchaSiteKey && (
        <div className="cf-turnstile" data-sitekey={captchaSiteKey} />
      )}
      {message && (
        <p className={`text-xs rounded-lg px-3 py-2 ${status === "error" ? "text-red-600 bg-red-50" : "text-slate-600 bg-slate-50"}`}>
          {message}
        </p>
      )}
      <button type="submit" disabled={status === "loading"}
        className="w-full rounded-xl bg-indigo-600 py-2.5 text-sm font-bold text-white hover:bg-indigo-700 transition-colors disabled:opacity-60">
        {status === "loading" ? "Signing up…" : "Sign up with email →"}
      </button>
    </form>
  );
}

// ── Google OAuth button (shown when AUTH_GOOGLE_SIGNUP_ENABLED=true) ───────────

function GoogleSignInButton({ label = "Continue with Google" }) {
  function startGoogle() {
    window.location.href = `${API_BASE_URL}/auth/google/start`;
  }
  return (
    <button
      type="button"
      onClick={startGoogle}
      className="w-full flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors shadow-sm"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" className="shrink-0">
        <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
        <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
        <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
        <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
      </svg>
      {label}
    </button>
  );
}

// ── SSO / SAML button (shown when AUTH_SAML_ENABLED=true) ─────────────────────

function SSOButton() {
  const wsId = getWorkspaceId();
  function startSSO() {
    const next = window.location.pathname || "/overview";
    const qs   = wsId
      ? `?workspace_id=${encodeURIComponent(wsId)}&next=${encodeURIComponent(next)}`
      : `?next=${encodeURIComponent(next)}`;
    window.location.href = `${API_BASE_URL}/auth/saml/login${qs}`;
  }
  return (
    <button
      type="button"
      onClick={startSSO}
      className="w-full flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors shadow-sm"
    >
      <ShieldCheck size={17} className="text-indigo-500 shrink-0" strokeWidth={1.75} />
      Continue with SSO
    </button>
  );
}

const TRUST_POINTS = [
  "No signup required",
  "Workspace-isolated data",
  "No AWS access keys stored",
];

const DEFAULT_TITLE    = "Access workspace to continue";
const DEFAULT_SUBTITLE = "Workspaces keep AWS accounts, scan results, alerts, and settings isolated.";

function Divider() {
  return (
    <div className="flex items-center gap-3 my-5">
      <div className="h-px flex-1 bg-slate-200" />
      <span className="text-xs text-slate-400 font-medium">or</span>
      <div className="h-px flex-1 bg-slate-200" />
    </div>
  );
}

export default function WorkspaceAccessPanel({ onSuccess, title, subtitle }) {
  const { authConfig } = useAuthConfig();
  const { emailSignupEnabled, googleSignupEnabled, captchaEnabled,
          captchaProvider, captchaSiteKey, samlEnabled } = authConfig;

  const [tab,       setTab]       = useState("access");
  const [showEmail, setShowEmail] = useState(false);

  const hasGoogle = googleSignupEnabled;
  const hasSSO    = samlEnabled;
  const hasEmail  = emailSignupEnabled;
  const hasOAuth  = hasGoogle || hasSSO;

  const TABS = [
    { key: "access", label: "Access Workspace" },
    { key: "create", label: "Create Workspace"  },
  ];

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-7 w-full">
      {/* Header */}
      <h2 className="text-lg font-extrabold text-slate-900 leading-tight mb-1">
        {title || DEFAULT_TITLE}
      </h2>
      <p className="text-xs text-slate-500 leading-relaxed mb-5">
        {subtitle || DEFAULT_SUBTITLE}
      </p>

      {/* 2-tab switcher */}
      <div className="flex border-b border-slate-200 mb-5">
        {TABS.map(({ key, label }) => (
          <button key={key} onClick={() => { setTab(key); setShowEmail(false); }}
            className={`flex-1 pb-3 text-xs font-bold border-b-2 -mb-px transition-all ${
              tab === key
                ? "border-slate-900 text-slate-900"
                : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
            }`}>
            {label}
          </button>
        ))}
      </div>

      {/* Tab 1 — Access Workspace */}
      {tab === "access" && (
        <>
          <AccessForm onSuccess={onSuccess} />
          {hasOAuth && (
            <>
              <Divider />
              <div className="space-y-3">
                {hasSSO    && <SSOButton />}
                {hasGoogle && <GoogleSignInButton label="Continue with Google" />}
              </div>
            </>
          )}
        </>
      )}

      {/* Tab 2 — Create Workspace */}
      {tab === "create" && (
        <>
          <CreateForm onSuccess={onSuccess} />
          {hasOAuth && (
            <>
              <Divider />
              <div className="space-y-3">
                {hasSSO    && <SSOButton />}
                {hasGoogle && <GoogleSignInButton label="Create workspace with Google" />}
              </div>
            </>
          )}
          {/* Trust points — only on create tab */}
          <div className="mt-5 pt-4 border-t border-slate-100 flex flex-wrap gap-x-5 gap-y-1.5">
            {TRUST_POINTS.map(pt => (
              <span key={pt} className="inline-flex items-center gap-1.5 text-xs text-slate-500">
                <Check size={11} className="text-emerald-500 shrink-0" strokeWidth={2.5} />
                {pt}
              </span>
            ))}
          </div>
          <p className="text-xs text-slate-400 mt-4">
            Just exploring?{" "}
            <a href="/general-eol" className="text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
              Browse public EOL library →
            </a>
          </p>
        </>
      )}

      {/* Member email link — always at bottom */}
      {hasEmail && (
        <div className="mt-5 pt-4 border-t border-slate-100">
          <p className="text-xs text-slate-400">
            Invited as a member?{" "}
            <button type="button"
              onClick={() => setShowEmail(v => !v)}
              className="text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
              Sign in with email →
            </button>
          </p>
          {showEmail && (
            <div className="mt-4">
              <EmailSignupForm
                captchaEnabled={captchaEnabled}
                captchaProvider={captchaProvider}
                captchaSiteKey={captchaSiteKey}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
