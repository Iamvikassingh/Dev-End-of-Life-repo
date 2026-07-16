import React, { useEffect, useState } from "react";
import { Settings2, Bell, Clock, Target, Cloud, Info, AlertTriangle, Check, KeyRound, Copy, Users, RefreshCw, X, Mail, Hash, ChevronRight, Loader, Download, UserPlus, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useConfig, useSaveConfig } from "../hooks/useConfig";
import {
  notificationErrorMessage,
  useNotificationSettings,
  useSaveNotificationSettings,
  useSendTestNotification,
  useNotificationLogs,
} from "../hooks/useNotifications";
import {
  useApiTokens,
  useCreateApiToken,
  useRevokeApiToken,
  useAuditLogs,
  useMembers,
  useInviteMember,
  useUpdateMember,
  useRemoveMember,
} from "../hooks/useAccessSettings";
import { HAS_API, API_BASE_URL, isDemoEnabled } from "../utils/config";
import { getWorkspaceId, getWorkspaceName, clearWorkspace, getSessionExpiry, setWorkspace, isDemoWorkspace, workspaceHeaders, hasMemberSession, getMemberRole } from "../utils/workspace";
import { copyToClipboard } from "../utils/clipboard";
import { SERVICE_REGISTRY } from "../config/serviceRegistry";
import { loadAccounts } from "../utils/connectedAccounts";
import { AppSelect } from "../components/AppSelect";
import { useSummary } from "../hooks/useInventory";
import { getApiErrorMessage } from "../utils/apiErrors";

// ── Service registry ──────────────────────────────────────────────────────────
const SERVICES_INFO = [
  { key: "Lambda",      desc: "Function runtimes — Python, Node.js, Java, Ruby, .NET" },
  { key: "EC2",         desc: "Amazon Linux AMI versions on running instances" },
  { key: "RDS",         label: "RDS / Aurora", desc: "Relational database engine versions and support windows" },
  { key: "EKS",         desc: "Kubernetes cluster versions" },
  { key: "ElastiCache", desc: "Redis and Memcached engine versions" },
  { key: "CodeBuild",   desc: "Build project runtime images" },
  { key: "ElasticBeanstalk", label: "Elastic Beanstalk", desc: "Application platform versions" },
  { key: "EMR",         desc: "Cluster release labels" },
  { key: "MSK",         desc: "Managed Streaming for Kafka broker versions" },
  { key: "OpenSearch",  desc: "OpenSearch and legacy Elasticsearch domains" },
  { key: "DocumentDB",  desc: "DocumentDB cluster engine versions" },
  { key: "Neptune",     desc: "Neptune graph database engine versions" },
  { key: "Glue",        desc: "AWS Glue ETL job versions" },
];

// Services that collect inventory metadata but have no published EOL lifecycle.
// Disabled by default — enabling adds inventory-only records to the scan.
const INVENTORY_ONLY_SERVICES = [
  { key: "ECR",                 desc: "Container image registry metadata (tag, digest, push date). EOL requires base image / SBOM analysis — not performed yet." },
  { key: "CloudFrontFunctions", label: "CloudFront Functions", desc: "Edge function metadata. No published EOL calendar from AWS." },
];

const NAV_SECTIONS = [
  { key: "general",   label: "General",           desc: "Risk thresholds",       Icon: Settings2 },
  { key: "notify",    label: "Notifications",      desc: "Alert delivery",        Icon: Bell      },
  { key: "schedule",  label: "Scan Schedule",      desc: "Automated scans",       Icon: Clock     },
  { key: "scope",     label: "Scan Scope",         desc: "Regions and accounts",  Icon: Target    },
  { key: "services",  label: "Monitored Services", desc: "Enabled scanners",      Icon: Cloud     },
  { key: "workspace", label: "Workspace Access",   desc: "Session and token",     Icon: KeyRound  },
  { key: "members",   label: "Members",             desc: "Invite and manage",     Icon: Users     },
];

// ── Primitives ────────────────────────────────────────────────────────────────
function Field({ label, hint, error, children }) {
  return (
    <div className="mb-6 last:mb-0">
      <label className="block text-sm font-semibold text-slate-800 mb-1">{label}</label>
      {hint && <p className="text-xs leading-relaxed text-slate-500 mb-2">{hint}</p>}
      {children}
      {error && <p className="text-xs text-red-500 mt-1.5">{error}</p>}
    </div>
  );
}

const inputClsNoW = (err) =>
  `border rounded-lg px-3 py-2.5 text-sm text-gray-700 focus:outline-none focus:ring-2 transition-colors ${
    err
      ? "border-red-300 focus:ring-red-300/50"
      : "border-gray-200 focus:ring-indigo-300/50 focus:border-indigo-300"
  }`;

function RadioCard({ checked, onChange, title, desc, warning, disabled, badge }) {
  return (
    <label className={`flex items-start gap-3 p-4 rounded-xl border transition-all ${
      disabled
        ? "border-slate-100 bg-slate-50 opacity-60 cursor-not-allowed"
        : checked
        ? "border-indigo-200 bg-indigo-50/70 ring-1 ring-indigo-100 cursor-pointer"
        : "border-slate-200 bg-white hover:border-indigo-200 hover:bg-slate-50 cursor-pointer"
    }`}>
      <input type="radio" checked={checked} onChange={disabled ? undefined : onChange}
        disabled={disabled} className="mt-0.5 accent-indigo-500 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold text-slate-900">{title}</p>
          {badge && (
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">{badge}</span>
          )}
        </div>
        <p className="text-xs leading-relaxed text-slate-500 mt-0.5">{desc}</p>
        {warning && checked && (
          <p className="text-xs text-amber-600 mt-2 font-medium flex items-center gap-1">
            <AlertTriangle size={12} strokeWidth={2} />
            {warning}
          </p>
        )}
      </div>
    </label>
  );
}

// ── Loading skeleton ──────────────────────────────────────────────────────────
function Skeleton() {
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6 sm:py-8 animate-pulse">
      <div className="h-3 w-28 bg-slate-200 rounded mb-4" />
      <div className="h-9 w-36 bg-slate-200 rounded mb-3" />
      <div className="h-4 w-96 bg-slate-100 rounded mb-7" />
      <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
        <div className="space-y-2 rounded-2xl bg-white p-2 ring-1 ring-slate-100">
          {[...Array(6)].map((_, i) => <div key={i} className="h-14 bg-slate-100 rounded-xl" />)}
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 space-y-5">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="space-y-2">
              <div className="h-4 w-32 bg-slate-200 rounded" />
              <div className="h-10 bg-slate-100 rounded-lg" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ErrorState({ onRetry }) {
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
      <div className="rounded-2xl border border-red-100 bg-white px-6 py-12 text-center shadow-sm">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-50">
          <AlertTriangle size={22} className="text-red-500" strokeWidth={1.75} />
        </div>
        <h2 className="text-base font-bold text-slate-900">Unable to load settings</h2>
        <p className="mt-1 text-sm text-slate-500">Try again, or check the backend connection for this workspace.</p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-5 rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-slate-800"
        >
          Retry
        </button>
      </div>
    </div>
  );
}

function ComingSoonCard({ title, children }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <p className="text-sm font-semibold text-slate-900">{title}</p>
      <p className="mt-1 text-sm leading-relaxed text-slate-600">{children}</p>
    </div>
  );
}

// ── Notification settings section ─────────────────────────────────────────────

function NotifySection() {
  const { data: remote, isLoading } = useNotificationSettings();
  const saveSettings  = useSaveNotificationSettings();
  const testNotif     = useSendTestNotification();
  const { data: logsData } = useNotificationLogs();

  const settings         = remote?.settings;
  const emailConfigured  = remote?.emailConfigured ?? false;

  const [email, setEmail]     = useState(null);
  const [slack, setSlack]     = useState(null);
  const [thresholds, setThr]  = useState(null);
  const [dirty, setDirty]     = useState(false);
  const [saveOk, setSaveOk]   = useState(false);
  const [saveErr, setSaveErr] = useState("");

  const [emailTest, setEmailTest] = useState({ loading: false, ok: false, err: "" });
  const [slackTest, setSlackTest] = useState({ loading: false, ok: false, err: "" });

  // Sync remote → local once loaded
  useEffect(() => {
    if (!settings) return;
    setEmail({ ...settings.email });
    setSlack({ ...settings.slack });
    setThr({ ...settings.thresholds });
    setDirty(false);
  }, [settings]);

  if (isLoading || !email || !slack || !thresholds) {
    return (
      <div>
        <h2 className="text-lg font-bold text-slate-900 mb-1">Notifications</h2>
        <p className="text-sm text-slate-500 mb-5">Configure alert delivery for EOL and expiring-soon resources.</p>
        <div className="animate-pulse space-y-3">
          <div className="h-28 rounded-xl bg-slate-100" />
          <div className="h-28 rounded-xl bg-slate-100" />
          <div className="h-16 rounded-xl bg-slate-100" />
        </div>
      </div>
    );
  }

  function mark(fn) {
    fn();
    setDirty(true);
    setSaveOk(false);
    setSaveErr("");
  }

  async function handleSave() {
    setSaveErr("");
    setSaveOk(false);
    try {
      await saveSettings.mutateAsync({ email, slack, thresholds });
      setDirty(false);
      setSaveOk(true);
      setTimeout(() => setSaveOk(false), 3000);
    } catch (e) {
      setSaveErr(notificationErrorMessage(e, "Failed to save. Try again."));
    }
  }

  async function handleTest(channel) {
    const setter = channel === "EMAIL" ? setEmailTest : setSlackTest;
    setter({ loading: true, ok: false, err: "" });
    try {
      await testNotif.mutateAsync({ channel });
      setter({ loading: false, ok: true, err: "" });
      setTimeout(() => setter({ loading: false, ok: false, err: "" }), 4000);
    } catch (e) {
      const msg = notificationErrorMessage(e, "Test notification failed.");
      setter({ loading: false, ok: false, err: msg });
    }
  }

  const logs = logsData?.logs ?? [];

  return (
    <div>
      <h2 className="text-lg font-bold text-slate-900 mb-1">Notifications</h2>
      <p className="text-sm text-slate-500 mb-5">
        Receive alerts via email or Slack when a scan finds EOL or expiring resources.
      </p>

      {/* ── Email ── */}
      <div className="rounded-xl border border-slate-200 bg-white mb-4 overflow-hidden">
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-100">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-50">
              <Mail size={14} className="text-indigo-500" strokeWidth={2} />
            </div>
            <div>
              <p className="text-sm font-bold text-slate-900">Email</p>
              {!emailConfigured && (
                <p className="text-xs text-amber-600">
                  Server-side email not configured — set NOTIFICATIONS_FROM_EMAIL env var
                </p>
              )}
            </div>
          </div>
          <label className="relative inline-flex cursor-pointer items-center gap-2 select-none">
            <input
              type="checkbox"
              className="sr-only peer"
              checked={email.enabled}
              onChange={() => mark(() => setEmail(e => ({ ...e, enabled: !e.enabled })))}
            />
            <div className="h-5 w-9 rounded-full bg-slate-200 peer-checked:bg-indigo-500 transition-colors after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-all peer-checked:after:translate-x-4 after:shadow-sm" />
            <span className="text-xs font-semibold text-slate-600">{email.enabled ? "On" : "Off"}</span>
          </label>
        </div>

        {email.enabled && (
          <div className="px-4 py-4 space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">
                Recipients <span className="text-slate-400 font-normal">(one per line, max 10)</span>
              </label>
              <textarea
                rows={3}
                placeholder={"alerts@yourcompany.com\nops@yourcompany.com"}
                value={email.recipients.join("\n")}
                onChange={e => mark(() => setEmail(prev => ({
                  ...prev,
                  recipients: e.target.value.split("\n").map(s => s.trim()).filter(Boolean),
                })))}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-300/50 focus:border-indigo-300 resize-none"
              />
            </div>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" className="accent-indigo-500"
                  checked={email.sendImmediate}
                  onChange={() => mark(() => setEmail(e => ({ ...e, sendImmediate: !e.sendImmediate })))} />
                <span className="text-xs font-medium text-slate-700">Send after each scan</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" className="accent-indigo-500"
                  checked={email.sendWeeklyDigest}
                  onChange={() => mark(() => setEmail(e => ({ ...e, sendWeeklyDigest: !e.sendWeeklyDigest })))} />
                <span className="text-xs font-medium text-slate-700">Weekly digest</span>
              </label>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleTest("EMAIL")}
                disabled={emailTest.loading || !email.recipients.length}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-50 transition-colors"
              >
                {emailTest.loading
                  ? <Loader size={11} className="animate-spin" strokeWidth={2} />
                  : <Mail size={11} strokeWidth={2} />}
                {emailTest.loading ? "Sending…" : "Send test"}
              </button>
              {emailTest.ok  && <span className="text-xs text-emerald-600 font-semibold flex items-center gap-1"><Check size={11} strokeWidth={2.5} /> Sent!</span>}
              {emailTest.err && <span className="text-xs text-red-500">{emailTest.err}</span>}
            </div>
          </div>
        )}
      </div>

      {/* ── Slack ── */}
      <div className="rounded-xl border border-slate-200 bg-white mb-4 overflow-hidden">
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-100">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-purple-50">
              <Hash size={14} className="text-purple-500" strokeWidth={2} />
            </div>
            <p className="text-sm font-bold text-slate-900">Slack</p>
          </div>
          <label className="relative inline-flex cursor-pointer items-center gap-2 select-none">
            <input
              type="checkbox"
              className="sr-only peer"
              checked={slack.enabled}
              onChange={() => mark(() => setSlack(s => ({ ...s, enabled: !s.enabled })))}
            />
            <div className="h-5 w-9 rounded-full bg-slate-200 peer-checked:bg-indigo-500 transition-colors after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-all peer-checked:after:translate-x-4 after:shadow-sm" />
            <span className="text-xs font-semibold text-slate-600">{slack.enabled ? "On" : "Off"}</span>
          </label>
        </div>

        {slack.enabled && (
          <div className="px-4 py-4 space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">
                Incoming webhook URL
              </label>
              <input
                type="url"
                placeholder="https://hooks.slack.com/services/T.../B.../..."
                value={slack.webhookUrl}
                onChange={e => mark(() => setSlack(s => ({ ...s, webhookUrl: e.target.value })))}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-300/50 focus:border-indigo-300"
              />
              <p className="text-xs text-slate-400 mt-1">
                Create one in your Slack app under <strong>Incoming Webhooks</strong>.
              </p>
            </div>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" className="accent-indigo-500"
                  checked={slack.sendImmediate}
                  onChange={() => mark(() => setSlack(s => ({ ...s, sendImmediate: !s.sendImmediate })))} />
                <span className="text-xs font-medium text-slate-700">Send after each scan</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" className="accent-indigo-500"
                  checked={slack.sendWeeklyDigest}
                  onChange={() => mark(() => setSlack(s => ({ ...s, sendWeeklyDigest: !s.sendWeeklyDigest })))} />
                <span className="text-xs font-medium text-slate-700">Weekly digest</span>
              </label>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleTest("SLACK")}
                disabled={slackTest.loading || !slack.webhookUrl.startsWith("https://hooks.slack.com/")}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-50 transition-colors"
              >
                {slackTest.loading
                  ? <Loader size={11} className="animate-spin" strokeWidth={2} />
                  : <Hash size={11} strokeWidth={2} />}
                {slackTest.loading ? "Sending…" : "Send test"}
              </button>
              {slackTest.ok  && <span className="text-xs text-emerald-600 font-semibold flex items-center gap-1"><Check size={11} strokeWidth={2.5} /> Sent!</span>}
              {slackTest.err && <span className="text-xs text-red-500">{slackTest.err}</span>}
            </div>
          </div>
        )}
      </div>

      {/* ── Thresholds ── */}
      <div className="rounded-xl border border-slate-200 bg-white mb-5 px-4 py-4">
        <p className="text-sm font-bold text-slate-900 mb-3">Alert thresholds</p>
        <div className="flex flex-wrap gap-4">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input type="checkbox" className="accent-indigo-500"
              checked={thresholds.sendEol}
              onChange={() => mark(() => setThr(t => ({ ...t, sendEol: !t.sendEol })))} />
            <span className="text-xs font-medium text-slate-700">
              <span className="inline-block rounded-full bg-red-100 text-red-700 font-bold px-1.5 py-0.5 text-[10px] mr-1">EOL</span>
              Notify for end-of-life
            </span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input type="checkbox" className="accent-indigo-500"
              checked={thresholds.sendExpiringSoon}
              onChange={() => mark(() => setThr(t => ({ ...t, sendExpiringSoon: !t.sendExpiringSoon })))} />
            <span className="text-xs font-medium text-slate-700">
              <span className="inline-block rounded-full bg-amber-100 text-amber-700 font-bold px-1.5 py-0.5 text-[10px] mr-1">SOON</span>
              Notify for expiring soon
            </span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input type="checkbox" className="accent-indigo-500"
              checked={thresholds.sendUnknown}
              onChange={() => mark(() => setThr(t => ({ ...t, sendUnknown: !t.sendUnknown })))} />
            <span className="text-xs font-medium text-slate-700">
              <span className="inline-block rounded-full bg-slate-100 text-slate-500 font-bold px-1.5 py-0.5 text-[10px] mr-1">?</span>
              Notify for unknown status
            </span>
          </label>
        </div>
      </div>

      {/* ── Save ── */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={!dirty || saveSettings.isPending}
          className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-bold text-white hover:bg-slate-700 disabled:opacity-50 transition-colors"
        >
          {saveSettings.isPending
            ? <><Loader size={13} className="animate-spin" strokeWidth={2} /> Saving…</>
            : "Save notification settings"}
        </button>
        {saveOk  && <span className="text-xs text-emerald-600 font-semibold flex items-center gap-1"><Check size={12} strokeWidth={2.5} /> Saved</span>}
        {saveErr && <span className="text-xs text-red-500">{saveErr}</span>}
      </div>

      {/* ── Delivery logs ── */}
      {logs.length > 0 && (
        <div className="mt-8">
          <p className="text-sm font-bold text-slate-900 mb-3">Recent deliveries</p>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide">Channel</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide">Type</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide">Status</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide hidden sm:table-cell">Alerts</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide hidden md:table-cell">Date</th>
                </tr>
              </thead>
              <tbody>
                {logs.slice(0, 10).map(log => (
                  <tr key={log.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="px-3 py-2 font-semibold text-slate-700">{log.channel}</td>
                    <td className="px-3 py-2 text-slate-500">{log.type?.replace("_", " ") ?? "—"}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-bold text-[10px] ${
                        log.status === "SUCCESS" ? "bg-emerald-50 text-emerald-700"
                        : log.status === "FAILED"  ? "bg-red-50 text-red-600"
                        : "bg-slate-100 text-slate-500"
                      }`}>
                        {log.status === "SUCCESS" ? <Check size={9} strokeWidth={3} /> : null}
                        {log.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-500 hidden sm:table-cell">{log.alertCount ?? "—"}</td>
                    <td className="px-3 py-2 text-slate-400 hidden md:table-cell">
                      {log.createdAt ? new Date(log.createdAt).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}


// ── Create API token modal ────────────────────────────────────────────────────

const ROLE_INFO = {
  VIEWER: "Read-only access to dashboard, alerts, reports, and inventory. Can read Reports, CSV exports, snapshots, and audit logs via API.",
  EDITOR: "Can run scans, acknowledge alerts, and create report snapshots. Can also create report snapshots via API token.",
  ADMIN:  "Full access: manage accounts, API tokens, and settings.",
};

function CreateApiTokenModal({ onClose, onCreated }) {
  const [name,          setName]          = useState("");
  const [role,          setRole]          = useState("VIEWER");
  const [expiresAt,     setExpiresAt]     = useState("");
  const [result,        setResult]        = useState(null);
  const [copied,        setCopied]        = useState(false);
  const [hasSavedToken, setHasSavedToken] = useState(false);
  const [copyErr,       setCopyErr]       = useState("");
  const [error,         setError]         = useState("");
  const create = useCreateApiToken();

  async function handleCreate() {
    setError("");
    try {
      const data = await create.mutateAsync({ name: name.trim(), role, expiresAt: expiresAt || undefined });
      setResult(data);
    } catch (e) {
      setError(e?.response?.data?.error?.message || "Failed to create token.");
    }
  }

  async function handleCopy() {
    setCopyErr("");
    const ok = await copyToClipboard(result.rawToken);
    if (ok) {
      setCopied(true);
      setHasSavedToken(true);
      setTimeout(() => setCopied(false), 3000);
    } else {
      setCopyErr("Copy failed. Select and copy the token manually, or download CSV.");
    }
  }

  function handleDownloadCsv() {
    const wsId = getWorkspaceId();
    const rows = [
      ["Token Name", "Token Role", "API Token", "Workspace ID", "Created At", "Note"],
      [
        result.token?.name || name,
        result.token?.role || role,
        result.rawToken,
        wsId,
        result.token?.createdAt || new Date().toISOString(),
        "Save this token now. It will not be shown again.",
      ],
    ];
    const csv = rows.map(row => row.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `api-token-${result.token?.id || "new"}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setHasSavedToken(true);
  }

  function handleClose() {
    if (result && !hasSavedToken) {
      // eslint-disable-next-line no-alert
      if (!window.confirm("This token will not be shown again. Copy or download it before closing.")) return;
    }
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl p-6 space-y-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-bold text-slate-900">Create API Token</h3>
            <p className="text-xs text-slate-500 mt-0.5">Token is shown once only — save it immediately.</p>
          </div>
          <button onClick={handleClose} className="rounded-lg p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors">
            <X size={16} strokeWidth={2} />
          </button>
        </div>

        {!result ? (
          <>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Token name</label>
                <input
                  type="text"
                  placeholder="e.g. GitHub Actions, CI Pipeline"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  maxLength={80}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300/50 focus:border-indigo-300"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Role</label>
                <div className="space-y-2">
                  {["VIEWER", "EDITOR", "ADMIN"].map(r => (
                    <label key={r} className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${
                      role === r ? "border-indigo-200 bg-indigo-50/60" : "border-slate-200 bg-white hover:bg-slate-50"
                    }`}>
                      <input type="radio" name="role" value={r} checked={role === r}
                        onChange={() => setRole(r)} className="mt-0.5 accent-indigo-500" />
                      <div>
                        <p className="text-xs font-bold text-slate-900">{r}</p>
                        <p className="text-xs text-slate-500 mt-0.5">{ROLE_INFO[r]}</p>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Expiry <span className="font-normal text-slate-400">(optional)</span>
                </label>
                <input
                  type="date"
                  value={expiresAt}
                  onChange={e => setExpiresAt(e.target.value)}
                  min={new Date().toISOString().slice(0, 10)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300/50 focus:border-indigo-300"
                />
              </div>
            </div>
            {error && <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
            <div className="flex justify-end gap-2">
              <button onClick={handleClose}
                className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors">
                Cancel
              </button>
              <button onClick={handleCreate} disabled={!name.trim() || create.isPending}
                className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-60 transition-colors">
                {create.isPending ? "Creating…" : "Create Token"}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="rounded-xl bg-amber-50 ring-1 ring-amber-200 px-4 py-3">
              <p className="text-xs font-bold text-amber-700 mb-1">Save this token now</p>
              <p className="text-xs text-amber-600">This is the only time the raw token will be shown. It cannot be retrieved after closing this dialog.</p>
            </div>
            <div className="rounded-xl bg-slate-50 ring-1 ring-slate-200 px-3 py-2.5">
              <p className="text-[11px] text-slate-400 mb-1 font-semibold uppercase tracking-wide">Raw Token</p>
              <p className="font-mono text-xs text-slate-800 break-all leading-relaxed select-all">{result.rawToken}</p>
            </div>
            {copyErr && <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{copyErr}</p>}
            <div className="flex flex-wrap justify-end gap-2">
              <button onClick={handleCopy}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-semibold transition-colors ${
                  copied
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                    : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                }`}>
                {copied
                  ? <><Check size={13} strokeWidth={2.5} /> Copied!</>
                  : <><Copy size={13} strokeWidth={2} /> Copy Token</>}
              </button>
              <button onClick={handleDownloadCsv}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors">
                <Download size={13} strokeWidth={2} />
                Download CSV
              </button>
              <button onClick={() => { onCreated?.(result.token); onClose(); }} disabled={!hasSavedToken}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                Done
              </button>
            </div>
            {!hasSavedToken && (
              <p className="text-xs text-amber-600 text-right">Copy or download to enable Done.</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}


// ── Workspace access section ──────────────────────────────────────────────────

function WorkspaceAccessSection({ workspaceId, workspaceName, sessionExpiry, onRotate }) {
  const { data: tokData,  isLoading: tokLoading }  = useApiTokens();
  const { data: logData,  isLoading: logLoading }  = useAuditLogs(20);
  const revokeToken = useRevokeApiToken();

  const [showCreate, setShowCreate] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState(null); // tokenId to confirm

  const tokens    = tokData?.tokens ?? [];
  const auditLogs = logData?.logs ?? [];
  // sessionExpiry is null for workspace-owner sessions (no expiry) and a formatted
  // string like "2h 30m" for member sessions that have real server-side expiry.
  const expired   = sessionExpiry === "Expired";

  const fmtDate = (iso) => {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  };

  const ACTION_LABEL = {
    WORKSPACE_CREATED:             "Workspace created",
    WORKSPACE_ACCESSED:            "Workspace accessed",
    ACCOUNT_CONNECTED:             "Account connected",
    ACCOUNT_UPDATED:               "Account updated",
    ACCOUNT_DELETED:               "Account deleted",
    SCAN_STARTED:                  "Scan started",
    SCAN_COMPLETED:                "Scan completed",
    SCAN_FAILED:                   "Scan failed",
    ALERT_ACKNOWLEDGED:            "Alert acknowledged",
    ALERT_SNOOZED:                 "Alert snoozed",
    ALERT_RESOLVED:                "Alert resolved",
    REPORT_SNAPSHOT_CREATED:       "Report snapshot created",
    NOTIFICATION_SETTINGS_UPDATED: "Notification settings updated",
    NOTIFICATION_TEST_SENT:        "Test notification sent",
    WORKSPACE_TOKEN_ROTATED:       "Workspace token rotated",
    API_TOKEN_CREATED:             "API token created",
    API_TOKEN_REVOKED:             "API token revoked",
    API_TOKEN_UPDATED:             "API token updated",
    SETTINGS_UPDATED:              "Settings updated",
  };

  return (
    <div className="space-y-6">
      {showCreate && (
        <CreateApiTokenModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {}}
        />
      )}

      {/* ── Current session ── */}
      <div>
        <h2 className="text-lg font-bold text-slate-900 mb-1">Workspace access</h2>
        <p className="text-sm text-slate-500 mb-4">Manage this workspace's identity, session, and integration tokens.</p>

        <div className="divide-y divide-slate-100 rounded-xl border border-slate-200 overflow-hidden mb-4">
          {[
            { label: "Workspace name", value: workspaceName },
            { label: "Workspace ID",   value: workspaceId, copy: true },
            { label: "Role",           value: "Admin (workspace session)" },
          ].map(({ label, value, copy: showCopy }) => (
            <div key={label} className="flex items-center justify-between gap-4 px-4 py-3 bg-white">
              <span className="text-xs text-slate-400 font-medium w-36 shrink-0">{label}</span>
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <span className="text-sm text-slate-800 font-mono truncate">{value || "—"}</span>
                {showCopy && value && <CopyIdBtn value={value} />}
              </div>
            </div>
          ))}
          <div className="flex items-center justify-between gap-4 px-4 py-3 bg-white">
            <span className="text-xs text-slate-400 font-medium w-36 shrink-0">Token status</span>
            <span className={`text-sm font-medium ${expired ? "text-red-500" : "text-emerald-600"}`}>
              {expired ? "Expired" : sessionExpiry ? `Expires in ${sessionExpiry}` : "Workspace unlocked"}
            </span>
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 overflow-hidden mb-4">
          <div className="flex items-center justify-between gap-4 px-4 py-2.5 bg-slate-50">
            <p className="text-xs text-slate-500">Workspace token works like a password — valid until rotated or revoked. Rotating invalidates the current token immediately.</p>
            <button
              onClick={onRotate}
              disabled={isDemoEnabled()}
              title={isDemoEnabled() ? "Not available in demo" : undefined}
              className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <RefreshCw size={12} strokeWidth={2} />
              Rotate Token
            </button>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="text-sm font-semibold text-slate-900">Connected accounts</p>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">Manage AWS account connections and per-account region scope.</p>
            <button type="button" onClick={() => window.location.href = "/connected-accounts"}
              className="mt-3 inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50">
              <Users size={14} strokeWidth={2} />
              Connected Accounts
            </button>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="text-sm font-semibold text-slate-900">Browser session</p>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">Clears workspace ID, name, and token from local storage.</p>
            <button onClick={() => { clearWorkspace(); window.location.href = "/overview"; }}
              className="mt-3 inline-flex items-center gap-2 rounded-lg border border-red-100 bg-white px-3 py-2 text-sm font-semibold text-red-600 transition-colors hover:bg-red-50">
              Clear session
            </button>
          </div>
        </div>
      </div>

      {/* ── API Tokens ── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-base font-bold text-slate-900">API Tokens</h3>
            <p className="text-xs text-slate-500 mt-0.5">Use API tokens for CI/CD integrations and programmatic access.</p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            disabled={isDemoEnabled()}
            title={isDemoEnabled() ? "Not available in demo" : undefined}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-bold text-white hover:bg-slate-700 disabled:opacity-40 transition-colors"
          >
            + New Token
          </button>
        </div>

        {tokLoading ? (
          <div className="h-20 animate-pulse rounded-xl bg-slate-100" />
        ) : tokens.length === 0 ? (
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-5 text-center">
            <p className="text-sm font-semibold text-slate-600">No API tokens yet</p>
            <p className="text-xs text-slate-400 mt-1">Create a token to enable programmatic access for CI/CD pipelines or integrations.</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide">Name</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide">Role</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide hidden sm:table-cell">Prefix</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide hidden md:table-cell">Created</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide hidden lg:table-cell">Last used</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide">Status</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {tokens.map(tok => {
                  const active = !tok.revokedAt && (!tok.expiresAt || tok.expiresAt > new Date().toISOString());
                  return (
                    <tr key={tok.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                      <td className="px-3 py-2.5 font-semibold text-slate-900">{tok.name}</td>
                      <td className="px-3 py-2.5">
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                          tok.role === "ADMIN"  ? "bg-purple-50 text-purple-700" :
                          tok.role === "EDITOR" ? "bg-blue-50 text-blue-700" :
                          "bg-slate-100 text-slate-600"
                        }`}>{tok.role}</span>
                      </td>
                      <td className="px-3 py-2.5 font-mono text-slate-400 hidden sm:table-cell">{tok.prefix}</td>
                      <td className="px-3 py-2.5 text-slate-400 hidden md:table-cell">{fmtDate(tok.createdAt)}</td>
                      <td className="px-3 py-2.5 text-slate-400 hidden lg:table-cell">{tok.lastUsedAt ? fmtDate(tok.lastUsedAt) : "Never"}</td>
                      <td className="px-3 py-2.5">
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                          active ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-600"
                        }`}>
                          {tok.revokedAt ? "Revoked" : !active ? "Expired" : "Active"}
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        {active && (
                          confirmRevoke === tok.id ? (
                            <div className="flex items-center gap-1.5">
                              <button onClick={() => { revokeToken.mutate(tok.id); setConfirmRevoke(null); }}
                                className="text-[10px] font-bold text-red-600 hover:text-red-800 px-2 py-1 rounded-lg bg-red-50">
                                Confirm
                              </button>
                              <button onClick={() => setConfirmRevoke(null)}
                                className="text-[10px] text-slate-400 hover:text-slate-700 px-2 py-1">
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button onClick={() => setConfirmRevoke(tok.id)}
                              className="text-xs font-semibold text-red-500 hover:text-red-700 transition-colors">
                              Revoke
                            </button>
                          )
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* API token auth note */}
        <div className="mt-3 rounded-xl bg-slate-50 ring-1 ring-slate-100 px-4 py-3">
          <p className="text-xs text-slate-600 leading-relaxed">
            Use tokens with the header{" "}
            <code className="font-mono text-[10px] bg-white px-1.5 py-0.5 rounded ring-1 ring-slate-200">X-API-Token: eolm_api_...</code>
            {" "}or{" "}
            <code className="font-mono text-[10px] bg-white px-1.5 py-0.5 rounded ring-1 ring-slate-200">Authorization: Bearer eolm_api_...</code>
          </p>
        </div>
      </div>

      {/* ── Audit Log ── */}
      <div>
        <h3 className="text-base font-bold text-slate-900 mb-1">Audit Log</h3>
        <p className="text-xs text-slate-500 mb-3">Last 20 workspace events. Capped at 1,000 records.</p>
        {logLoading ? (
          <div className="h-20 animate-pulse rounded-xl bg-slate-100" />
        ) : auditLogs.length === 0 ? (
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4 text-center">
            <p className="text-sm text-slate-400">No audit events recorded yet. Events are logged as you use the workspace.</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide hidden md:table-cell">Time</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide hidden sm:table-cell">Actor</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide">Action</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-500 uppercase tracking-wide">Message</th>
                </tr>
              </thead>
              <tbody>
                {auditLogs.map(log => (
                  <tr key={log.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="px-3 py-2 text-slate-400 tabular-nums hidden md:table-cell whitespace-nowrap">
                      {fmtDate(log.createdAt)}
                    </td>
                    <td className="px-3 py-2 text-slate-500 hidden sm:table-cell">
                      {log.actor?.label || log.actor?.type || "—"}
                    </td>
                    <td className="px-3 py-2 font-semibold text-slate-700 whitespace-nowrap">
                      {ACTION_LABEL[log.action] ?? log.action}
                    </td>
                    <td className="px-3 py-2 text-slate-500 max-w-[240px] truncate" title={log.message}>
                      {log.message || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

    </div>
  );
}


// ── Rotate token modal ────────────────────────────────────────────────────────

function RotateTokenModal({ workspaceId, onClose, onRotated }) {
  const [loading,   setLoading]   = useState(false);
  const [newToken,  setNewToken]  = useState(null);
  const [error,     setError]     = useState("");
  const [copied,    setCopied]    = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const saved = copied || downloaded;

  async function handleRotate() {
    setLoading(true); setError(""); setCopied(false); setDownloaded(false);
    try {
      if (isDemoEnabled()) {
        const fake = `eolm_demo_${Math.random().toString(36).slice(2,22)}`;
        setNewToken(fake);
        onRotated?.(fake);
      } else {
        const r    = await fetch(`${API_BASE_URL}/workspaces/${workspaceId}/token/rotate`, {
          method: "POST",
          headers: workspaceHeaders(),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
          setError(getApiErrorMessage({ response: { status: r.status, data } }, "Rotation failed. Try again."));
          setLoading(false);
          return;
        }
        setNewToken(data.newToken || data.token || "");
        onRotated?.(data.newToken || data.token || "");
      }
    } catch { setError("Could not reach the server."); }
    setLoading(false);
  }

  async function copyToken() {
    const ok = await copyToClipboard(newToken);
    if (ok) setCopied(true);
  }

  function downloadTokenCsv() {
    const rows = [
      ["Workspace Name", "Workspace ID", "Access Token", "Rotated At", "Note"],
      [getWorkspaceName(), workspaceId, newToken, new Date().toISOString(), "Save this token now. It will not be shown again."],
    ];
    const csv = rows.map(row => row.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `aws-eol-monitor-token-${workspaceId}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setDownloaded(true);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl p-6 space-y-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-bold text-slate-900">Rotate workspace token</h3>
            <p className="text-xs text-slate-500 mt-0.5">The current token will be invalidated immediately.</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors">
            <X size={16} strokeWidth={2} />
          </button>
        </div>

        {!newToken ? (
          <>
            <div className="rounded-xl bg-amber-50 ring-1 ring-amber-100 px-4 py-3 text-xs text-amber-700 space-y-1">
              <p className="font-semibold">Before rotating:</p>
              <ul className="list-disc list-inside space-y-0.5 text-amber-600">
                <li>The new token is shown once only — save it immediately.</li>
                <li>Any other browser sessions using the old token will be invalidated.</li>
              </ul>
            </div>
            {error && <p className="text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
            <div className="flex justify-end gap-2">
              <button onClick={onClose}
                className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors">
                Cancel
              </button>
              <button onClick={handleRotate} disabled={loading}
                className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-60 transition-colors">
                <RefreshCw size={13} strokeWidth={2} className={loading ? "animate-spin" : ""} />
                {loading ? "Rotating…" : "Rotate Token"}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="rounded-xl bg-emerald-50 ring-1 ring-emerald-200 px-4 py-2.5">
              <p className="text-xs font-bold text-emerald-700 mb-0.5">Token rotated successfully</p>
              <p className="text-xs text-emerald-600">Copy and save your new token — it will not be shown again.</p>
            </div>
            <div className="rounded-xl bg-amber-50 ring-1 ring-amber-200 px-4 py-3">
              <p className="text-xs font-semibold text-amber-700 mb-2">New access token — save now</p>
              <div className="flex items-start justify-between gap-3">
                <code className="text-xs font-mono text-amber-900 break-all leading-relaxed flex-1">{newToken}</code>
                <button onClick={copyToken}
                  className={`shrink-0 inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                    copied ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700 hover:bg-amber-200"
                  }`}>
                  {copied ? <><Check size={11} strokeWidth={2.5} /> Copied</> : <><Copy size={11} strokeWidth={1.75} /> Copy</>}
                </button>
              </div>
            </div>
            <button onClick={downloadTokenCsv}
              className="w-full inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors">
              <Download size={14} strokeWidth={2} />
              Download credentials CSV
            </button>
            <p className={`text-xs text-center ${saved ? "text-emerald-600" : "text-amber-700"}`}>
              {saved ? "Credentials saved. You can close now." : "Copy the token or download CSV before closing."}
            </p>
            <button onClick={onClose} disabled={!saved}
              className="w-full rounded-xl bg-slate-900 py-2.5 text-sm font-semibold text-white hover:bg-slate-700 transition-colors disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500">
              Done
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ── Members ───────────────────────────────────────────────────────────────────

const ROLE_OPTIONS = [
  { value: "VIEWER", label: "VIEWER" },
  { value: "EDITOR", label: "EDITOR" },
  { value: "ADMIN",  label: "ADMIN"  },
];

const ROLE_BADGE = {
  VIEWER: "bg-blue-50 text-blue-700 border-blue-200",
  EDITOR: "bg-amber-50 text-amber-700 border-amber-200",
  ADMIN:  "bg-purple-50 text-purple-700 border-purple-200",
};

const STATUS_BADGE = {
  INVITED:  "bg-yellow-50 text-yellow-700 border-yellow-200",
  ACTIVE:   "bg-green-50 text-green-700 border-green-200",
  DISABLED: "bg-slate-100 text-slate-500 border-slate-200",
};

function InviteMemberModal({ onClose }) {
  const [email,   setEmail]   = useState("");
  const [role,    setRole]    = useState("VIEWER");
  const [name,    setName]    = useState("");
  const [result,  setResult]  = useState(null);
  const [copied,  setCopied]  = useState(false);
  const [error,   setError]   = useState("");
  const invite = useInviteMember();
  const wsId   = getWorkspaceId();

  async function handleInvite() {
    setError("");
    if (!email.trim()) { setError("Email is required."); return; }
    try {
      const data = await invite.mutateAsync({ email: email.trim(), role, name: name.trim() || undefined });
      setResult(data);
    } catch (e) {
      const msg = e?.response?.data?.error?.message;
      setError(msg || "Failed to send invite.");
    }
  }

  async function handleCopy() {
    const link = `${window.location.origin}/accept-invite?wsId=${wsId}&token=${result.inviteToken}`;
    const ok = await copyToClipboard(link);
    if (ok) { setCopied(true); setTimeout(() => setCopied(false), 3000); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl p-6 space-y-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-bold text-slate-900">Invite Member</h3>
            <p className="text-xs text-slate-500 mt-0.5">An invite link will be generated for you to share.</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors">
            <X size={16} strokeWidth={2} />
          </button>
        </div>

        {!result ? (
          <>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Email address <span className="text-red-500">*</span></label>
                <input
                  type="email"
                  placeholder="colleague@example.com"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Display name (optional)</label>
                <input
                  type="text"
                  placeholder="Jane Smith"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-2">Role</label>
                <div className="grid grid-cols-3 gap-2">
                  {["VIEWER", "EDITOR", "ADMIN"].map(r => (
                    <button key={r} type="button" onClick={() => setRole(r)}
                      className={`rounded-lg border px-3 py-2 text-xs font-semibold transition-colors ${role === r ? `${ROLE_BADGE[r]} border-current` : "border-slate-200 text-slate-500 hover:border-slate-300"}`}>
                      {r}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            {error && <p className="text-xs text-red-500">{error}</p>}
            <div className="flex justify-end gap-2 pt-1">
              <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 transition-colors">Cancel</button>
              <button onClick={handleInvite} disabled={invite.isPending}
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60 transition-colors">
                {invite.isPending && <Loader size={14} className="animate-spin" />}
                Send Invite
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="rounded-xl border border-green-200 bg-green-50 p-4 space-y-3">
              <div className="flex items-center gap-2 text-green-700 font-semibold text-sm">
                <Check size={16} /> Invite created for {result.member?.email}
              </div>
              <p className="text-xs text-slate-600">Share this link with the invitee. It expires in 7 days.</p>
              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-mono text-slate-700 break-all">
                {`${window.location.origin}/accept-invite?wsId=${wsId}&token=${result.inviteToken}`}
              </div>
              <button onClick={handleCopy}
                className="flex items-center gap-1.5 rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 transition-colors">
                {copied ? <Check size={12} /> : <Copy size={12} />}
                {copied ? "Copied!" : "Copy Invite Link"}
              </button>
            </div>
            <div className="flex justify-end">
              <button onClick={onClose} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 transition-colors">Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ConfirmModal({ title, body, confirmLabel, confirmClass, onConfirm, onCancel, isPending, error }) {
  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") onCancel(); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={e => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl p-6 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-base font-bold text-slate-900">{title}</h3>
          <button onClick={onCancel} className="rounded-lg p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors">
            <X size={16} strokeWidth={2} />
          </button>
        </div>
        <p className="text-sm text-slate-600">{body}</p>
        {error && <p className="text-xs text-red-500 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button autoFocus onClick={onCancel} disabled={isPending}
            className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button onClick={onConfirm} disabled={isPending}
            className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold text-white transition-colors disabled:opacity-60 ${confirmClass}`}>
            {isPending && <Loader size={14} className="animate-spin" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function MembersSection({ isAdminView }) {
  const [showInvite,    setShowInvite]    = useState(false);
  const [removeTarget,  setRemoveTarget]  = useState(null);
  const [disableTarget, setDisableTarget] = useState(null);
  const [modalError,    setModalError]    = useState("");
  const [rowPending,    setRowPending]    = useState(new Set());
  const { data, isLoading, isError, refetch } = useMembers();
  const updateMember = useUpdateMember();
  const removeMember = useRemoveMember();
  const members = data?.members ?? [];

  function markPending(id, active) {
    setRowPending(prev => {
      const next = new Set(prev);
      active ? next.add(id) : next.delete(id);
      return next;
    });
  }

  async function handleRoleChange(member, newRole) {
    try { await updateMember.mutateAsync({ memberId: member.id, patch: { role: newRole } }); }
    catch { /* errors shown inline by query invalidation */ }
  }

  async function handleEnable(member) {
    markPending(member.id, true);
    try { await updateMember.mutateAsync({ memberId: member.id, patch: { status: "ACTIVE" } }); }
    catch { /* silent — list refreshes */ }
    finally { markPending(member.id, false); }
  }

  async function handleDisableConfirm() {
    if (!disableTarget) return;
    setModalError("");
    try {
      await updateMember.mutateAsync({ memberId: disableTarget.id, patch: { status: "DISABLED" } });
      setDisableTarget(null);
    } catch (e) {
      setModalError(e?.response?.data?.error?.message || "Failed to disable member.");
    }
  }

  async function handleRemoveConfirm() {
    if (!removeTarget) return;
    setModalError("");
    try {
      await removeMember.mutateAsync(removeTarget.id);
      setRemoveTarget(null);
    } catch (e) {
      setModalError(e?.response?.data?.error?.message || "Failed to remove member.");
    }
  }

  function openDisable(m) { setModalError(""); setDisableTarget(m); }
  function openRemove(m)  { setModalError(""); setRemoveTarget(m); }

  function fmtDate(iso) {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-lg font-bold text-slate-900 mb-1">Members</h2>
          <p className="text-sm text-slate-500">Invite teammates and manage their access roles.</p>
        </div>
        <button onClick={() => setShowInvite(true)}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 transition-colors">
          <UserPlus size={15} /> Invite Member
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-slate-500 text-sm py-8 justify-center">
          <Loader size={16} className="animate-spin" /> Loading members…
        </div>
      )}

      {isError && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 flex items-center justify-between">
          <span className="text-sm text-red-700">Failed to load members.</span>
          <button onClick={refetch} className="text-xs font-medium text-red-600 hover:underline flex items-center gap-1">
            <RefreshCw size={12} /> Retry
          </button>
        </div>
      )}

      {!isLoading && !isError && members.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 py-12 flex flex-col items-center gap-2">
          <Users size={32} className="text-slate-300" />
          <p className="text-sm font-medium text-slate-500">No members yet</p>
          <p className="text-xs text-slate-400">Click "Invite Member" to add teammates.</p>
        </div>
      )}

      {!isLoading && !isError && members.length > 0 && (
        <div className="rounded-xl border border-slate-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Member</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Role</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">Status</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide hidden sm:table-cell">Invited</th>
                {isAdminView && <th className="px-4 py-3"></th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {members.map(m => {
                const isPendingRow = rowPending.has(m.id);
                return (
                  <tr key={m.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-800">{m.name || m.email}</div>
                      {m.name && <div className="text-xs text-slate-400">{m.email}</div>}
                    </td>
                    <td className="px-4 py-3">
                      {m.status === "INVITED" || !isAdminView ? (
                        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${ROLE_BADGE[m.role]}`}>
                          {m.role}
                        </span>
                      ) : (
                        <AppSelect
                          value={m.role}
                          options={ROLE_OPTIONS}
                          onChange={val => handleRoleChange(m, val)}
                          disabled={updateMember.isPending || isPendingRow}
                          size="sm"
                        />
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${STATUS_BADGE[m.status] || "bg-slate-100 text-slate-500"}`}>
                        {m.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400 hidden sm:table-cell">
                      {fmtDate(m.invitedAt)}
                    </td>
                    {isAdminView && (
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1">
                          {m.status === "ACTIVE" && (
                            <button
                              onClick={() => openDisable(m)}
                              disabled={isPendingRow}
                              className="rounded-md px-2 py-1 text-xs font-medium text-amber-600 hover:bg-amber-50 transition-colors disabled:opacity-50">
                              Disable
                            </button>
                          )}
                          {m.status === "DISABLED" && (
                            <button
                              onClick={() => handleEnable(m)}
                              disabled={isPendingRow}
                              className="rounded-md px-2 py-1 text-xs font-medium text-green-600 hover:bg-green-50 transition-colors disabled:opacity-50 flex items-center gap-1">
                              {isPendingRow ? <><Loader size={11} className="animate-spin" /> Enabling…</> : "Enable"}
                            </button>
                          )}
                          <button
                            onClick={() => openRemove(m)}
                            disabled={isPendingRow}
                            className="rounded-md p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors disabled:opacity-50"
                            title="Remove member">
                            <X size={14} strokeWidth={2} />
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showInvite && <InviteMemberModal onClose={() => setShowInvite(false)} />}

      {disableTarget && (
        <ConfirmModal
          title="Disable member?"
          body={`${disableTarget.name || disableTarget.email} will lose access immediately. You can re-enable them later.`}
          confirmLabel="Disable"
          confirmClass="bg-amber-500 hover:bg-amber-600"
          isPending={updateMember.isPending}
          error={modalError}
          onConfirm={handleDisableConfirm}
          onCancel={() => { setDisableTarget(null); setModalError(""); }}
        />
      )}

      {removeTarget && (
        <ConfirmModal
          title="Remove member?"
          body={`${removeTarget.email} will be permanently removed from this workspace.`}
          confirmLabel="Remove member"
          confirmClass="bg-red-600 hover:bg-red-700"
          isPending={removeMember.isPending}
          error={modalError}
          onConfirm={handleRemoveConfirm}
          onCancel={() => { setRemoveTarget(null); setModalError(""); }}
        />
      )}
    </div>
  );
}

function fmtExpiry(ms) {
  if (!ms) return null;
  const diff = ms - Date.now();
  if (diff <= 0) return "Expired";
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor((diff % 3_600_000) / 60_000);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function CopyIdBtn({ value }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    const ok = await copyToClipboard(value);
    if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2000); }
  }
  return (
    <button onClick={copy}
      className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
        copied
          ? "bg-emerald-50 text-emerald-600"
          : "bg-gray-100 text-gray-500 hover:bg-gray-200 hover:text-gray-700"
      }`}>
      {copied
        ? <><Check size={11} strokeWidth={2.5} /> Copied</>
        : <><Copy size={11} strokeWidth={1.75} /> Copy</>}
    </button>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function SettingsPage() {
  const navigate = useNavigate();
  const { data: config, isError, refetch } = useConfig();
  const { mutate: save, isPending: saving, isSuccess: saved, data: saveResult } = useSaveConfig();
  const [form,         setForm]         = useState(config);
  const [originalForm, setOriginalForm] = useState(config);
  const [errors,       setErrors]       = useState({});
  const [settingsSaveErr, setSettingsSaveErr] = useState("");
  const [activeSection, setActiveSection] = useState("general");
  const [showRotate,   setShowRotate]   = useState(false);

  // Role-based nav: non-ADMIN member sessions cannot access admin-only sections
  const memberSession = hasMemberSession();
  const memberRole    = memberSession ? getMemberRole() : "ADMIN";
  const isAdminView   = !memberSession || memberRole === "ADMIN";
  const ADMIN_ONLY_SECTIONS = new Set(["workspace", "members"]);
  const visibleNav = isAdminView
    ? NAV_SECTIONS
    : NAV_SECTIONS.filter(s => !ADMIN_ONLY_SECTIONS.has(s.key));

  useEffect(() => {
    if (config && !form) {
      setForm(config);
      setOriginalForm(config);
    }
  }, [config]); // eslint-disable-line

  function set(key, value) {
    setForm(f => ({ ...f, [key]: value }));
    setErrors(e => ({ ...e, [key]: undefined }));
    setSettingsSaveErr("");
  }

  function validate() {
    const errs = {};
    if (!form.warn_days || form.warn_days < 1 || form.warn_days > 1095)
      errs.warn_days = "Must be between 1 and 1095 days.";
    if (form.alert_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.alert_email))
      errs.alert_email = "Enter a valid email address.";
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }

  function handleSave() {
    if (!validate()) return;
    setSettingsSaveErr("");
    save(form, {
      onSuccess: () => setOriginalForm(form),
      onError: (error) => {
        setSettingsSaveErr(getApiErrorMessage(error, "Settings save failed."));
      },
    });
  }

  function handleReset() {
    setForm(originalForm);
    setErrors({});
    setSettingsSaveErr("");
  }

  if (isError && !form) return <ErrorState onRetry={refetch} />;
  if (!form) return <Skeleton />;

  const isDirty     = JSON.stringify(form) !== JSON.stringify(originalForm);
  const enabledSet  = new Set(form.enabled_services ?? []);
  const enabledCount = SERVICES_INFO.filter(s => s.key === "RDS" ? enabledSet.has("RDS") || enabledSet.has("Aurora") : enabledSet.has(s.key)).length;

  // ── Section content ────────────────────────────────────────────────────────
  function renderSection() {
    switch (activeSection) {
      case "general":
        return (
          <div>
            <h2 className="text-lg font-bold text-slate-900 mb-1">Risk threshold</h2>
            <p className="text-sm text-slate-500 mb-6">Resources within this window are flagged as Expiring Soon.</p>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <Field label="Warning window (days)"
              hint="Resources expiring within this many days will be flagged as Expiring Soon."
              error={errors.warn_days}>
              <div className="flex flex-wrap items-center gap-3">
                <input type="number" min={1} max={1095} value={form.warn_days}
                  onChange={e => set("warn_days", parseInt(e.target.value, 10) || 1)}
                  className={`${inputClsNoW(errors.warn_days)} h-11 w-28 shrink-0 bg-white`} />
                <span className="text-sm text-slate-500 whitespace-nowrap">days before EOL</span>
              </div>
            </Field>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                {[90, 180, 365].map(v => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => set("warn_days", v)}
                    className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
                      Number(form.warn_days) === v
                        ? "border-indigo-200 bg-indigo-50 text-indigo-700"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    {v} days
                  </button>
                ))}
                <span className="ml-1 text-xs text-slate-400">Common values: 90 · 180 · 365</span>
              </div>
            </div>
          </div>
        );

      case "notify":
        return <NotifySection />;

      case "schedule": {
        const cronRaw = form.scan_schedule || "";
        const cronHuman = (() => {
          const m = cronRaw.match(/cron\((\d+)\s+(\d+)\s/);
          if (m) return `Daily at ${String(m[2]).padStart(2,"0")}:${String(m[1]).padStart(2,"0")} UTC`;
          if (cronRaw.startsWith("rate(")) return cronRaw.replace("rate(","Every ").replace(")","");
          return null;
        })();
        return (
          <div>
            <h2 className="text-lg font-bold text-slate-900 mb-1">Automated scans</h2>
            <p className="text-sm text-slate-500 mb-5">Scheduled scans are coming soon. Run scans manually from Account Scan or Connected Accounts.</p>
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 mb-5">
              <p className="text-sm font-semibold text-slate-900 mb-1">Scheduler not enabled yet</p>
              {cronHuman && (
                <p className="text-sm text-slate-700 font-medium mb-1">{cronHuman}</p>
              )}
              <p className="text-xs text-slate-400">
                Stored schedule:{" "}
                <code className="rounded bg-white px-1.5 py-0.5 font-mono">{cronRaw || "Not configured"}</code>
              </p>
            </div>
            <div className="mt-5 rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-sm font-semibold text-slate-800 mb-1">Manual scans</p>
              <p className="text-xs text-slate-500 mb-3">
                Run scans from Connected Accounts, where each workspace account uses its own scoped scan endpoint.
              </p>
              <button
                type="button"
                onClick={() => navigate("/connected-accounts")}
                className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-slate-800"
              >
                Go to Connected Accounts
                <ChevronRight size={14} strokeWidth={2.25} />
              </button>
            </div>
          </div>
        );
      }

      case "scope":
        return (
          <div>
            <h2 className="text-lg font-bold text-slate-900 mb-1">Default region scope</h2>
            <p className="text-sm text-slate-500 mb-5">Region scope can also be changed per connected account.</p>
            {connectedCount === 0 ? (
              <div className="mb-5 rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
                <p className="text-sm font-semibold text-slate-900">No AWS account connected</p>
                <p className="mt-1 text-sm leading-relaxed text-slate-600">Connect an AWS account before configuring scan scope.</p>
                {isAdminView ? (
                  <button
                    type="button"
                    onClick={() => navigate("/account-scan")}
                    className="mt-3 inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-slate-800"
                  >
                    Connect AWS Account
                  </button>
                ) : (
                  <p className="mt-2 text-xs font-medium text-slate-400">Only workspace admins can connect AWS accounts.</p>
                )}
              </div>
            ) : (
              <div className="mb-5 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-sm font-semibold text-slate-900">Connected account overrides</p>
              <p className="mt-1 text-sm leading-relaxed text-slate-600">
                {isAdminView
                  ? "Use account-specific region settings when a workload needs a narrower scan scope."
                  : "Account-specific region settings are read-only for your role."}
              </p>
              {isAdminView ? (
                <button
                  type="button"
                  onClick={() => navigate("/connected-accounts")}
                  className="mt-3 inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50"
                >
                  <Users size={14} strokeWidth={2} />
                  Manage connected accounts
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => navigate("/connected-accounts")}
                  className="mt-3 inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50"
                >
                  <Users size={14} strokeWidth={2} />
                  View connected accounts
                </button>
              )}
            </div>
            )}
            <div className="flex flex-col gap-3">
              <RadioCard
                checked={!form.scan_org}
                onChange={() => set("scan_org", false)}
                title="Connected accounts"
                desc="Scans one connected AWS account using a read-only IAM role. No cross-account permissions required."
              />
              <RadioCard
                checked={false}
                onChange={() => {}}
                disabled
                badge="Coming soon"
                title="All organization accounts"
                desc="Scans allowed organization accounts using org and member read-only roles. Requires EOLMonitorOrgReadOnly and EOLMonitorReadOnly member roles deployed via StackSet. Organization scan will be available after org role setup is enabled."
              />
            </div>
          </div>
        );

      case "services": {
        const renderServiceCard = ({ key, label, desc }, isInventoryOnly = false) => {
          const registry = SERVICE_REGISTRY[key] || {};
          const displayName = label || registry.displayName || key;
          const category = key === "RDS" ? "Database" : (registry.category || "AWS service");
          const checked = key === "RDS" ? enabledSet.has("RDS") || enabledSet.has("Aurora") : enabledSet.has(key);
          return (
            <div key={key}
              className={`rounded-xl border px-4 py-3 transition-colors ${
                checked ? "border-slate-200 bg-white" : "border-slate-100 bg-slate-50 opacity-75"
              }`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-900">{displayName}</p>
                  <p className="mt-0.5 text-xs font-medium uppercase tracking-wide text-slate-400">{category}</p>
                </div>
                <span className={`shrink-0 rounded-full px-2 py-1 text-xs font-bold ${
                  checked ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-400"
                }`}>
                  {checked ? "Enabled" : "Disabled"}
                </span>
              </div>
              <p className="mt-3 text-xs leading-relaxed text-slate-500">{desc}</p>
            </div>
          );
        };
        return (
          <div>
            <h2 className="text-lg font-bold text-slate-900 mb-1">Monitored services</h2>
            <p className="text-sm text-slate-500 mb-5">{enabledCount} of {SERVICES_INFO.length} lifecycle scanners are enabled for this workspace.</p>
            <div className="grid gap-3 md:grid-cols-2 mb-6">
              {SERVICES_INFO.map(s => renderServiceCard(s))}
            </div>

            <div className="rounded-xl border border-amber-200 bg-amber-50/50 px-4 py-3 mb-3">
              <p className="text-sm font-bold text-amber-900 mb-0.5">Inventory-only services</p>
              <p className="text-xs text-amber-700 leading-relaxed">
                These services have no published EOL lifecycle. When enabled they add inventory records
                with status <strong>Lifecycle Not Tracked</strong> — they do not count toward actionable
                EOL risk. Disabled by default to keep dashboards focused on real lifecycle signals.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2 mb-5">
              {INVENTORY_ONLY_SERVICES.map(s => renderServiceCard(s, true))}
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-sm font-semibold text-slate-900">Scanner selection</p>
              <p className="mt-1 text-sm leading-relaxed text-slate-600">
                Service enablement is shown from saved workspace config. Runtime scanner support is controlled by the backend deployment, so this UI keeps the list read-only for now.
              </p>
            </div>
          </div>
        );
      }

      case "workspace": {
        const wsId    = getWorkspaceId();
        const wsName  = getWorkspaceName();
        const isMbr   = hasMemberSession();
        const expiry  = isMbr ? fmtExpiry(getSessionExpiry()) : null;
        return (
          <WorkspaceAccessSection
            workspaceId={wsId}
            workspaceName={wsName}
            sessionExpiry={expiry}
            onRotate={() => setShowRotate(true)}
          />
        );
      }

      case "members":
        return <MembersSection isAdminView={isAdminView} />;

      default: return null;
    }
  }

  const connectedCount = loadAccounts().length;
  const { data: summaryData } = useSummary();
  const orgAccountCount = summaryData?.org_accounts ?? 0;
  const wsName = getWorkspaceName();
  const isMemberSession = hasMemberSession();
  const wsExpiry  = isMemberSession ? fmtExpiry(getSessionExpiry()) : null;
  const wsExpired = wsExpiry === "Expired";

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
      {/* Header */}
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-indigo-500 mb-2">Configuration</p>
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 mb-1.5">Settings</h1>
          <p className="text-sm text-slate-500">Configure warning windows, notifications, scan schedule, and monitored services.</p>
        </div>
        {/* Workspace summary card */}
        <div className="shrink-0 rounded-xl border border-slate-200 bg-white px-5 py-3.5 shadow-sm lg:min-w-[260px]">
          <p className="text-xs font-bold uppercase tracking-[0.15em] text-slate-400 mb-2">Workspace</p>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-4">
              <span className="text-xs text-slate-400">Name</span>
              <span className="text-sm font-semibold text-slate-800 truncate">{wsName || "—"}</span>
            </div>
            <div className="flex items-center justify-between gap-4">
              <span className="text-xs text-slate-400">Token</span>
              <span className={`text-sm font-semibold ${wsExpired ? "text-red-500" : "text-slate-800"}`}>
                {wsExpired ? "Expired" : wsExpiry ? `Expires in ${wsExpiry}` : "Workspace unlocked"}
              </span>
            </div>
            <div className="flex items-center justify-between gap-4">
              <span className="text-xs text-slate-400">Accounts</span>
              <span className="text-sm font-semibold text-slate-800">
                {connectedCount} connected
                {orgAccountCount > 0 && (
                  <span className="ml-1.5 text-xs font-medium text-violet-600">
                    · {orgAccountCount} org
                  </span>
                )}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Demo note — only in local/dev demo mode */}
      {isDemoEnabled() && !HAS_API && (
        <div className="flex items-center gap-2 text-sm text-slate-500 bg-slate-50 rounded-xl px-4 py-2.5 mb-6 ring-1 ring-slate-100">
          <Info size={15} className="shrink-0 text-slate-400" strokeWidth={1.75} />
          <span>Demo mode — settings are stored locally. Set <code className="font-mono text-xs bg-slate-100 px-1 py-0.5 rounded">REACT_APP_API_URL</code> to persist to the backend.</span>
        </div>
      )}

      {isError && (
        <div className="mb-6 flex items-center justify-between gap-4 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
          <span className="inline-flex items-center gap-2"><AlertTriangle size={15} strokeWidth={1.75} /> Unable to refresh settings. Showing local defaults or last loaded values.</span>
          <button type="button" onClick={() => refetch()} className="shrink-0 font-semibold hover:underline">Retry</button>
        </div>
      )}

      {/* Two-column layout */}
      <div className="grid gap-6 lg:grid-cols-[240px_1fr] lg:items-start">
        {/* Left nav */}
        <nav>
          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white p-2 shadow-sm">
            {visibleNav.map(({ key, label, desc, Icon }) => {
              const active = activeSection === key;
              return (
                <button key={key} onClick={() => setActiveSection(key)}
                  className={`w-full flex items-start gap-3 rounded-xl px-3 py-3 text-left transition-colors ${
                    active ? "bg-indigo-50 text-indigo-700" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"
                  }`}>
                  <Icon size={16} className={`mt-0.5 shrink-0 ${active ? "text-indigo-600" : "text-slate-400"}`} strokeWidth={1.75} />
                  <span className="min-w-0">
                    <span className={`block text-sm ${active ? "font-bold" : "font-semibold"}`}>{label}</span>
                    <span className={`mt-0.5 block text-xs ${active ? "text-indigo-500" : "text-slate-400"}`}>{desc}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </nav>

        {/* Right panel */}
        <div className="flex-1 min-w-0 flex flex-col gap-4">
          {!isAdminView && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 flex items-center gap-2">
              <Info size={14} className="text-amber-600 shrink-0" />
              <p className="text-sm text-amber-800 font-medium">
                <span className="font-bold">{memberRole}</span> role: read-only settings. Only workspace admins can change settings.
              </p>
            </div>
          )}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 min-h-[360px]">
            {renderSection()}
          </div>

          {/* Token rotate modal */}
          {showRotate && (
            <RotateTokenModal
              workspaceId={getWorkspaceId()}
              onClose={() => setShowRotate(false)}
              onRotated={(newToken) => {
                setWorkspace(getWorkspaceId(), newToken, getWorkspaceName());
              }}
            />
          )}

          {/* Actions — only on tabs with saveable state */}
          {isAdminView && ["general", "scope"].includes(activeSection) && <div className="sticky bottom-4 bg-white/95 backdrop-blur-sm rounded-2xl border border-slate-200 shadow-md px-5 py-3.5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <button onClick={handleSave} disabled={!isDirty || saving || !isAdminView}
                className="px-5 py-2 rounded-xl text-sm font-semibold text-white bg-slate-950 hover:bg-slate-800 disabled:opacity-45 disabled:cursor-not-allowed transition-colors">
                {saving ? "Saving…" : "Save Settings"}
              </button>
              <button onClick={handleReset} disabled={!isDirty || saving}
                className="px-4 py-2 rounded-xl text-sm font-medium text-slate-600 border border-slate-200 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                Reset Changes
              </button>
              {isDirty && !saved && <span className="text-xs text-amber-600 flex items-center gap-1"><AlertTriangle size={12} strokeWidth={2} /> Unsaved changes</span>}
              {settingsSaveErr && <span className="text-xs text-red-500">{settingsSaveErr}</span>}
            </div>
            {saved && (
              <span className={`text-sm font-medium flex items-center gap-1.5 ${saveResult?.isMock ? "text-amber-600" : "text-green-600"}`}>
                {saveResult?.isMock
                  ? <><Info size={14} strokeWidth={2} /> Settings saved locally in demo mode.</>
                  : <><Check size={14} strokeWidth={2.5} /> Settings saved.</>}
              </span>
            )}
          </div>}
        </div>
      </div>
    </div>
  );
}
