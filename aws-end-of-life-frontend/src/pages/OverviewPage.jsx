import React, { useMemo, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  CalendarClock, ShieldCheck, Network,
  Shield, KeyRound, Eye, Clock, Ban,
  Target, Check, Plug, ScanSearch, GitCompareArrows, ArrowRight,
  FlaskConical,
} from "lucide-react";
import { useGeneralEol } from "../hooks/useGeneralEol";
import { setDemoWorkspace } from "../utils/workspace";

/* ─── Static Data ───────────────────────────────────────────────────────── */

const MODES = [
  {
    to: "/general-eol", Icon: CalendarClock,
    iconBg: "bg-emerald-100", iconCl: "text-emerald-700",
    badge: "No AWS access required", badgeCs: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
    title: "General EOL Library",
    summary: "Explore AWS lifecycle timelines and upcoming end-of-life milestones.",
    bestFor: "Researching service lifecycle changes and planning upgrades.",
    covers: ["Lambda", "EKS", "RDS", "ElastiCache", "MSK", "Amazon Linux"],
    cta: "Browse Library", ctaCs: "bg-emerald-600 hover:bg-emerald-700",
    ring: "hover:ring-2 hover:ring-emerald-300",
  },
  {
    to: "/account-scan", Icon: ShieldCheck,
    iconBg: "bg-blue-100", iconCl: "text-blue-700",
    badge: "Read-only IAM role", badgeCs: "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
    recommended: true,
    title: "Account Level Scan",
    summary: "Scan one AWS account and surface expiring runtimes, engines, and cluster versions.",
    bestFor: "Workload-level visibility for a single AWS environment.",
    covers: ["All 13 services", "All regions", "Urgency sorted"],
    cta: "Connect Account", ctaCs: "bg-blue-600 hover:bg-blue-700",
    ring: "hover:ring-2 hover:ring-blue-300",
  },
  {
    to: "/org-scan", Icon: Network,
    iconBg: "bg-violet-100", iconCl: "text-violet-700",
    badge: "Org read-only + StackSet", badgeCs: "bg-violet-50 text-violet-700 ring-1 ring-violet-200",
    title: "Organization Scan",
    summary: "Monitor end-of-life risk across accounts, OUs, and shared platforms.",
    bestFor: "Enterprise-wide lifecycle governance.",
    covers: ["All accounts", "OU grouping", "Cross-account alerts"],
    cta: "Connect Organization", ctaCs: "bg-violet-600 hover:bg-violet-700",
    ring: "hover:ring-2 hover:ring-violet-300",
  },
];

const TRUST_STATS = [
  { value: "13",             label: "AWS Services"     },
  { value: "50+",            label: "Known Lifecycles" },
  { value: "All",            label: "Regions Supported"},
  { value: "endoflife.date", label: "Data Source"      },
];

const TRUST_STRIP = [
  { Icon: Eye,      text: "Read-only IAM roles"           },
  { Icon: Shield,   text: "No AWS access keys"            },
  { Icon: Clock,    text: "Short-lived STS sessions"      },
  { Icon: Ban,      text: "No access to secrets or data"  },
  { Icon: KeyRound, text: "External ID for cross-account"  },
];

const HOW_STEPS = [
  { Icon: Plug,             title: "Connect",  body: "Choose a mode and connect only what you need."               },
  { Icon: ScanSearch,       title: "Discover", body: "Identify deployed runtimes, engines, and service versions."  },
  { Icon: GitCompareArrows, title: "Compare",  body: "Match discovered versions against trusted lifecycle data."   },
  { Icon: Target,           title: "Act",      body: "Prioritize upgrades before EOL becomes a risk."             },
];

const WHY_POINTS = [
  "Catch risky runtimes before audits do",
  "See what's expiring across accounts and regions",
  "Keep security, platform, and operations teams aligned",
  "Plan upgrades with less guesswork",
];

/* ─── ModeCard ──────────────────────────────────────────────────────────── */

function ModeCard({ mode }) {
  const navigate = useNavigate();
  const { Icon } = mode;
  return (
    <div
      onClick={!mode.comingSoon ? () => navigate(mode.to) : undefined}
      className={`group bg-white rounded-2xl p-5 flex flex-col h-full
        shadow-sm transition-all duration-200 ring-1 ring-gray-100
        ${mode.comingSoon ? "opacity-60 cursor-default" : `cursor-pointer ${mode.ring}`}
        ${mode.recommended ? "ring-2 ring-blue-200 shadow-md" : ""}`}
    >
      {mode.recommended && (
        <div className="mb-3">
          <span className="text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full bg-blue-600 text-white">
            Recommended
          </span>
        </div>
      )}
      <div className="flex items-center justify-between mb-4">
        <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${mode.iconBg}`}>
          <Icon size={18} className={mode.iconCl} strokeWidth={1.75} />
        </div>
        <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${mode.badgeCs}`}>
          {mode.badge}
        </span>
      </div>
      <h3 className="text-base font-bold text-gray-900 mb-1">{mode.title}</h3>
      <p className="text-sm text-gray-500 leading-relaxed mb-3">{mode.summary}</p>
      <div className="flex-1 space-y-2.5 mb-4">
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Best for</p>
          <p className="text-sm text-gray-600">{mode.bestFor}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {mode.covers.map(c => (
            <span key={c} className="text-xs bg-gray-50 text-gray-500 px-2 py-0.5 rounded-md border border-gray-100">
              {c}
            </span>
          ))}
        </div>
      </div>
      {mode.comingSoon ? (
        <div className="mt-auto w-full py-2.5 rounded-xl text-sm font-semibold text-center
                        text-violet-400 bg-violet-50 border border-violet-100 cursor-not-allowed select-none">
          Coming soon
        </div>
      ) : (
        <button
          onClick={e => { e.stopPropagation(); navigate(mode.to); }}
          className={`mt-auto w-full py-2.5 rounded-xl text-sm font-semibold text-white transition-colors ${mode.ctaCs}`}
        >
          {mode.cta} →
        </button>
      )}
    </div>
  );
}

/* ─── EOL Watchlist ─────────────────────────────────────────────────────── */

function EolWatchlist() {
  const navigate = useNavigate();
  const { data: records, loading } = useGeneralEol();

  const watchlist = useMemo(() => {
    const map = {};
    for (const r of records) {
      if (r.status !== "EOL" && r.status !== "EXPIRING_SOON") continue;
      if (!map[r.service]) {
        map[r.service] = { service: r.service, eolCount: 0, expiringSoon: 0, nearestDays: Infinity, nearestEolDate: "" };
      }
      const svc = map[r.service];
      if (r.status === "EOL")           svc.eolCount++;
      if (r.status === "EXPIRING_SOON") svc.expiringSoon++;
      if ((r.daysToEol ?? 99999) < svc.nearestDays) {
        svc.nearestDays    = r.daysToEol ?? 99999;
        svc.nearestEolDate = r.eolDate ?? "";
      }
    }
    return Object.values(map)
      .sort((a, b) => {
        const aEs = a.expiringSoon > 0;
        const bEs = b.expiringSoon > 0;
        if (aEs !== bEs) return aEs ? -1 : 1;
        return a.nearestDays - b.nearestDays;
      })
      .slice(0, 6);
  }, [records]);

  const handleRowClick = (entry) => {
    const status = entry.expiringSoon > 0 ? "EXPIRING_SOON" : "EOL";
    navigate(`/dashboard?status=${status}&service=${encodeURIComponent(entry.service)}`);
  };

  if (loading) {
    return (
      <section className="bg-white rounded-2xl ring-1 ring-gray-100 shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <div className="h-4 w-40 bg-gray-100 animate-pulse rounded" />
        </div>
        {[...Array(4)].map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-5 py-3.5 border-b border-gray-100 last:border-0">
            <div className="w-2 h-2 rounded-full bg-gray-100" />
            <div className="h-3 w-24 bg-gray-100 animate-pulse rounded" />
            <div className="h-3 w-32 bg-gray-100 animate-pulse rounded ml-2" />
          </div>
        ))}
      </section>
    );
  }

  if (watchlist.length === 0) {
    return (
      <section className="bg-white rounded-2xl px-6 py-6 ring-1 ring-gray-100 shadow-sm text-center text-sm text-gray-400">
        All tracked lifecycle versions are currently supported.
      </section>
    );
  }

  return (
    <section className="bg-white rounded-2xl ring-1 ring-gray-100 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
        <div>
          <p className="text-xs font-bold text-gray-500 uppercase tracking-widest">
            Upcoming EOL Watchlist
          </p>
          <p className="text-xs text-slate-500 mt-0.5">
            Public AWS lifecycle risks.
            <span className="text-slate-400 ml-1">Run Account Scan to find impacted resources in your environment.</span>
          </p>
        </div>
        <button
          onClick={() => navigate("/general-eol")}
          className="inline-flex items-center gap-1 text-xs font-bold text-indigo-600 hover:text-indigo-800 transition-colors shrink-0 border border-indigo-100 bg-indigo-50 hover:bg-indigo-100 rounded-lg px-3 py-1.5"
        >
          View all <ArrowRight size={11} strokeWidth={2.5} />
        </button>
      </div>

      {/* Rows */}
      {watchlist.map((entry, idx) => {
        const isExpiring = entry.expiringSoon > 0;
        const isPast     = entry.nearestDays < 0;
        const isLast     = idx === watchlist.length - 1;
        const riskLabel  = entry.nearestEolDate
          ? (isPast
            ? `${Math.abs(entry.nearestDays)} days past EOL`
            : `${entry.nearestDays} days remaining`)
          : null;
        const dateLabel  = entry.nearestEolDate ?? null;

        return (
          <button
            key={entry.service}
            onClick={() => handleRowClick(entry)}
            className={`group w-full grid items-center gap-x-4 px-5 py-3 text-left
              hover:bg-slate-50 transition-colors
              grid-cols-[160px_1fr_auto_16px] sm:grid-cols-[160px_1fr_260px_16px]
              ${!isLast ? "border-b border-gray-100" : ""}`}
          >
            {/* col 1 — dot + service name */}
            <div className="flex items-center gap-2.5 min-w-0">
              <div className={`w-2 h-2 rounded-full shrink-0 ${isExpiring ? "bg-amber-400" : "bg-red-500"}`} />
              <span className="text-sm font-semibold text-gray-800 truncate">{entry.service}</span>
            </div>

            {/* col 2 — badges (left-anchored inside the flexible column) */}
            <div className="flex gap-1.5 flex-wrap items-center">
              {entry.expiringSoon > 0 && (
                <span className="text-xs px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 font-medium whitespace-nowrap">
                  {entry.expiringSoon} expiring soon
                </span>
              )}
              {entry.eolCount > 0 && (
                <span className="text-xs px-2.5 py-1 rounded-full bg-red-50 text-red-700 font-medium whitespace-nowrap">
                  {entry.eolCount} already EOL
                </span>
              )}
            </div>

            {/* col 3 — risk label + date, right-aligned */}
            <div className="text-right whitespace-nowrap">
              {riskLabel ? (
                <span className="text-xs">
                  <span className={`font-medium ${isPast ? "text-red-500" : "text-amber-600"}`}>
                    {riskLabel}
                  </span>
                  {dateLabel && (
                    <span className="text-gray-400"> · EOL: {dateLabel}</span>
                  )}
                </span>
              ) : null}
            </div>

            {/* col 4 — arrow */}
            <ArrowRight size={13} className="text-gray-300 group-hover:text-indigo-400 transition-colors justify-self-end" />
          </button>
        );
      })}
    </section>
  );
}

/* ─── Page ──────────────────────────────────────────────────────────────── */

export default function OverviewPage({ orgScanEnabled = false }) {
  const navigate  = useNavigate();
  const location  = useLocation();
  const [expired, setExpired] = useState(!!location.state?.sessionExpired);

  function tryDemo() {
    setDemoWorkspace();
    navigate("/dashboard");
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">

      {expired && (
        <div className="flex items-center justify-between gap-3 rounded-xl bg-amber-50 ring-1 ring-amber-200 px-4 py-3 text-sm text-amber-800">
          <span>Workspace session expired. Access your workspace again to continue.</span>
          <button
            onClick={() => setExpired(false)}
            className="text-amber-500 hover:text-amber-700 font-bold leading-none shrink-0"
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      )}

      {/* 1 · Hero */}
      <section className="text-center max-w-2xl mx-auto pt-2 pb-0">
        <p className="text-xs font-bold text-indigo-500 uppercase tracking-[0.22em] mb-3">
          AWS Lifecycle Visibility
        </p>
        <h1 className="text-4xl font-extrabold text-gray-900 leading-tight tracking-tight mb-3">
          Track AWS end-of-life risks before they break production
        </h1>
        <p className="text-gray-500 text-base leading-relaxed max-w-xl mx-auto mb-6">
          Surface expiring runtimes, engine versions, and service lifecycles before they become
          security or compliance incidents.
        </p>
        {/* CTA row */}
        <div className="flex flex-wrap items-center justify-center gap-3">
          <button
            onClick={() => navigate("/general-eol")}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold transition-colors"
          >
            <CalendarClock size={15} strokeWidth={1.75} />
            Browse EOL Library
          </button>
          <button
            onClick={() => navigate("/account-scan")}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold transition-colors"
          >
            <ShieldCheck size={15} strokeWidth={1.75} />
            Connect Account
          </button>
          <button
            onClick={tryDemo}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-indigo-200 bg-white hover:bg-indigo-50 text-indigo-700 text-sm font-semibold transition-colors"
          >
            <FlaskConical size={15} strokeWidth={1.75} />
            Try Demo Workspace
          </button>
        </div>
      </section>

      {/* 2 · Stats mini cards */}
      <section className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {TRUST_STATS.map(s => (
          <div key={s.label}
            className="rounded-2xl border border-slate-200 bg-white px-5 py-4 text-center shadow-sm">
            <p className="text-2xl font-extrabold text-slate-900">{s.value}</p>
            <p className="text-xs font-medium text-slate-500 mt-1">{s.label}</p>
          </div>
        ))}
      </section>

      {/* 3 · Trust strip */}
      <section className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 px-6 py-3.5
                          bg-slate-50 rounded-xl ring-1 ring-slate-200">
        {TRUST_STRIP.map(p => (
          <div key={p.text} className="flex items-center gap-1.5">
            <p.Icon size={13} className="shrink-0 text-slate-500" strokeWidth={1.75} />
            <span className="text-xs text-slate-600 font-medium">{p.text}</span>
          </div>
        ))}
      </section>

      {/* 4 · EOL Watchlist — primary actionable section */}
      <EolWatchlist />

      {/* 5 · Scan mode cards */}
      <section>
        <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4">
          Choose a scan mode
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 items-stretch">
          {MODES.map(m => {
            const effective = m.to === "/org-scan"
              ? { ...m, comingSoon: !orgScanEnabled }
              : m;
            return <ModeCard key={m.to} mode={effective} />;
          })}
        </div>
      </section>

      {/* 6 · How it works */}
      <section className="bg-white rounded-2xl px-6 py-6 ring-1 ring-gray-100 shadow-sm">
        <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-6">
          How it works
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
          {HOW_STEPS.map((step, i) => (
            <div key={step.title} className="flex flex-col items-start">
              <div className="w-9 h-9 rounded-xl bg-slate-800 flex items-center justify-center mb-3">
                <step.Icon size={17} className="text-white" strokeWidth={1.75} />
              </div>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-bold text-gray-300">{String(i + 1).padStart(2, "0")}</span>
                <span className="text-sm font-bold text-gray-800">{step.title}</span>
              </div>
              <p className="text-xs text-gray-500 leading-relaxed">{step.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* 7 · Why teams use this */}
      <section className="pb-4">
        <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-1">
          Why teams use AWS EOL Monitor
        </p>
        <p className="text-xs text-gray-400 mb-4">Make lifecycle risk visible before it becomes urgent.</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          {WHY_POINTS.map(pt => (
            <div key={pt} className="flex items-start gap-3 bg-white rounded-xl px-4 py-3 ring-1 ring-gray-100 shadow-sm">
              <Check size={13} className="text-emerald-500 mt-0.5 shrink-0" strokeWidth={2.5} />
              <span className="text-sm text-gray-600">{pt}</span>
            </div>
          ))}
        </div>
      </section>

    </div>
  );
}
