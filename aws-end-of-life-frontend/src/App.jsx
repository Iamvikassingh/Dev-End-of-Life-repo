import React, { useState, useEffect, useRef, lazy, Suspense, Component } from "react";
import {
  BrowserRouter, Routes, Route, NavLink, Navigate, Link,
  Outlet, useLocation, useNavigate, useParams,
} from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { hasWorkspace, getWorkspaceId, clearWorkspace, getWorkspaceName, getSessionExpiry, getWorkspaceExpiresAt, isWorkspaceExpired, isDemoWorkspace, hasMemberSession, getMemberRole, workspaceHeaders } from "./utils/workspace";
import { SHOW_ADMIN_SHORTCUT } from "./utils/config";
import { useAuthConfig } from "./hooks/useAuthConfig";
import {
  Home, CalendarClock, ShieldCheck, Network,
  BarChart3, Cloud, Bell, Settings,
  CloudCog, ChevronLeft, ChevronRight, Server, FileText, Menu, AlertTriangle,
} from "lucide-react";

import WorkspaceAccessPanel   from "./components/WorkspaceAccessPanel";
import DemoWorkspaceBanner    from "./components/DemoWorkspaceBanner";
// Public pages — eager: they are the first thing a visitor sees.
import OverviewPage           from "./pages/OverviewPage";
import GeneralEolPage         from "./pages/GeneralEolPage";
// Workspace-gated and admin pages — lazy: only loaded after workspace auth.
// Each becomes its own JS chunk, keeping the initial bundle small.
const AccountScanPage        = lazy(() => import("./pages/AccountScanPage"));
const ConnectedAccountsPage  = lazy(() => import("./pages/ConnectedAccountsPage"));
const AccountResultsPage     = lazy(() => import("./pages/AccountResultsPage"));
const OrgScanPage            = lazy(() => import("./pages/OrgScanPage"));
const DashboardPage          = lazy(() => import("./pages/DashboardPage"));
const ResourceDetailPage     = lazy(() => import("./pages/ResourceDetailPage"));
const ServicesPage           = lazy(() => import("./pages/ServicesPage"));
const AlertsPage             = lazy(() => import("./pages/AlertsPage"));
const SettingsPage           = lazy(() => import("./pages/SettingsPage"));
const ReportsPage            = lazy(() => import("./pages/ReportsPage"));
const InternalAdminPage      = lazy(() => import("./pages/InternalAdminPage"));
const AcceptInvitePage           = lazy(() => import("./pages/AcceptInvitePage"));
const MemberLoginPage            = lazy(() => import("./pages/MemberLoginPage"));
const MemberLoginCompletePage    = lazy(() => import("./pages/MemberLoginCompletePage"));
const EmailVerificationPage      = lazy(() => import("./pages/EmailVerificationPage"));

// ── Inline SAML pages (lightweight, no lazy needed) ─────────────────────────

function SamlCompletePage() {
  const navigate = React.useRef(null);
  const loc      = window.location;
  const next     = new URLSearchParams(loc.search).get("next") || "/overview";
  const safePath = next.startsWith("/") ? next : "/overview";
  React.useEffect(() => { window.location.replace(safePath); }, [safePath]);
  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: "#F0F4F8" }}>
      <p className="text-sm text-slate-500">Signing you in…</p>
    </div>
  );
}

const SAML_ERROR_MESSAGES = {
  SAML_DOMAIN_NOT_ALLOWED:  "Your email domain is not permitted for SSO login. Contact your admin.",
  SSO_USER_NOT_PROVISIONED: "No account found for your SSO identity. Ask your workspace admin to invite you first.",
  SAML_ACCOUNT_DISABLED:    "Your account has been disabled. Contact your admin.",
  SAML_NO_EMAIL:            "SSO response did not include a valid email address.",
  SAML_VALIDATION_FAILED:   "SSO response validation failed. Please try again.",
  SAML_PROCESSING_ERROR:    "Could not process the SSO response. Please try again.",
  SAML_PROVISIONING_ERROR:  "Account setup failed. Please contact your admin.",
  SAML_NOT_CONFIGURED:      "SSO is not fully configured. Contact your admin.",
};

function SamlErrorPage() {
  const code = new URLSearchParams(window.location.search).get("error") || "SAML_PROCESSING_ERROR";
  const msg  = SAML_ERROR_MESSAGES[code] || "SSO login failed. Please try again or use workspace token access.";
  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ background: "#F0F4F8" }}>
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-10 max-w-md w-full text-center">
        <div className="text-4xl mb-4">🔐</div>
        <h1 className="text-xl font-bold text-slate-900 mb-2">SSO Login Failed</h1>
        <p className="text-sm text-slate-600 mb-6 leading-relaxed">{msg}</p>
        <a href="/overview"
           className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-slate-900 text-white text-sm font-semibold hover:bg-slate-700 transition-colors">
          Back to home
        </a>
      </div>
    </div>
  );
}

const SCAN_MODES_BASE = [
  { to: "/general-eol",        label: "General EOL",       Icon: CalendarClock },
  { to: "/account-scan",       label: "Account Scan",       Icon: ShieldCheck   },
  { to: "/connected-accounts", label: "Connected Accounts", Icon: Server        },
];

const TOOLS = [
  { to: "/dashboard", label: "Dashboard", Icon: BarChart3 },
  { to: "/services",  label: "Services",  Icon: Cloud     },
  { to: "/alerts",    label: "Alerts",    Icon: Bell      },
  { to: "/reports",   label: "Reports",   Icon: FileText  },
  { to: "/settings",  label: "Settings",  Icon: Settings  },
];

// ── Page context shown above the workspace panel for each protected route ──────

const PAGE_CONTEXT = {
  "/account-scan": {
    eyebrow:      "SINGLE ACCOUNT SCAN",
    title:        "Connect one AWS account safely",
    description:  "Create a read-only IAM role, validate access, and scan EOL risk across all regions.",
    panelTitle:   "Access a workspace to connect AWS accounts",
    panelSubtitle: "Workspace keeps IAM role setup, scan results, alerts, and settings isolated.",
  },
  "/connected-accounts": {
    eyebrow:      "SINGLE ACCOUNT SCAN",
    title:        "Connected Accounts",
    description:  "View and manage connected AWS accounts and their scan results.",
    panelTitle:   "Access a workspace to view connected accounts",
    panelSubtitle: "Connected AWS accounts and scan history are stored per workspace.",
  },
  "/org-scan": {
    eyebrow:      "ORGANIZATION SCAN",
    title:        "Scan AWS Organizations",
    description:  "Discover lifecycle risk across multiple accounts in your AWS Organization.",
  },
  "/dashboard": {
    eyebrow:      "ACCOUNT INVENTORY",
    title:        "Dashboard",
    description:  "View scanned resources and EOL risk across your connected accounts.",
  },
  "/services": {
    eyebrow:      "SERVICE RISK",
    title:        "Services",
    description:  "View service-level EOL distribution and risk breakdown.",
  },
  "/alerts": {
    eyebrow:      "ALERT HISTORY",
    title:        "Alerts",
    description:  "View EOL alerts and acknowledgements for your connected accounts.",
  },
  "/reports": {
    eyebrow:      "COMPLIANCE REPORTING",
    title:        "Reports",
    description:  "Create CSV and print-ready evidence reports for lifecycle risk reviews.",
  },
  "/settings": {
    eyebrow:      "SETTINGS",
    title:        "Workspace Settings",
    description:  "Configure alerts, scan scope, and notification channels.",
    panelTitle:   "Access a workspace to manage settings",
    panelSubtitle: "Warning windows, scan scope, tokens, and alerts are workspace-scoped.",
  },
};

const DEFAULT_CTX = {
  eyebrow:     "AWS EOL MONITOR",
  title:       "Workspace required",
  description: "Access your workspace to continue.",
};

// ── Workspace guard — inline panel, no redirect, sidebar stays visible ────────

function WorkspaceGuard() {
  const [tick, setTick]           = useState(0); // forces re-render after workspace set
  const [showExpiredMsg, setShowExpiredMsg] = useState(false);
  const queryClient               = useQueryClient();
  const prevWsId                  = useRef(getWorkspaceId());
  const location                  = useLocation();

  // Detect expiry and clear stale credentials AFTER render so that
  // the first render with !hasWorkspace() can read isWorkspaceExpired()
  // before the token is wiped — this is what lets us show the right message.
  useEffect(() => {
    if (isWorkspaceExpired()) {
      setShowExpiredMsg(true);
      clearWorkspace(); // wipe stale token; same token re-enters on next login
    }
  });

  // When the active workspace changes, remove all cached query data so that
  // newly mounted page components see isLoading=true (loading skeletons)
  // instead of stale data from the previous workspace session.
  // removeQueries() clears the cache but does NOT cancel in-flight requests —
  // safer than clear() which was causing blank-screen on first login.
  useEffect(() => {
    const current = getWorkspaceId();
    if (prevWsId.current !== current) {
      prevWsId.current = current;
      if (current) queryClient.removeQueries();
    }
  }, [tick, queryClient]);

  if (!hasWorkspace()) {
    // Match on base path (ignore dynamic segments like /account-results/:id)
    const base = "/" + location.pathname.split("/")[1];
    const ctx  = PAGE_CONTEXT[base] || DEFAULT_CTX;

    return (
      <div className="px-6 py-8 min-h-full">
        <div className="max-w-lg mx-auto">
          {/* Session expired banner — shown when the 24-hour browser session expired */}
          {showExpiredMsg && (
            <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 flex items-center gap-2.5">
              <AlertTriangle size={15} className="text-amber-600 shrink-0" strokeWidth={2} />
              <p className="text-sm font-semibold text-amber-800">
                Session expired. Please login again.
              </p>
            </div>
          )}
          {/* Page-specific context header */}
          <div className="mb-4">
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-indigo-500 mb-2">
              {ctx.eyebrow}
            </p>
            <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 mb-1.5">
              {ctx.title}
            </h1>
            <p className="text-sm text-slate-500 leading-relaxed">{ctx.description}</p>
          </div>
          {/* Workspace access/create panel — full width within the column */}
          <WorkspaceAccessPanel
            onSuccess={() => {
              setShowExpiredMsg(false);
              // Remove any empty/error queries cached while workspace was absent,
              // then tick so WorkspaceGuard re-renders and shows the protected page.
              queryClient.removeQueries();
              setTick(t => t + 1);
            }}
            title={ctx.panelTitle}
            subtitle={ctx.panelSubtitle}
          />
          <p className="text-center text-sm text-slate-400 mt-4">
            Invited as a member?{" "}
            <Link to="/member-login" className="text-blue-600 hover:underline font-medium">
              Sign in with email →
            </Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <>
      {isDemoWorkspace() && <DemoWorkspaceBanner />}
      <Outlet />
    </>
  );
}

// ── Route-keyed wrappers ──────────────────────────────────────────────────────
// Keying by route param forces a clean remount when the param changes,
// preventing stale state from a previous resource/account from flashing.

function KeyedAccountResults() {
  const { accountId } = useParams();
  return <AccountResultsPage key={accountId} />;
}

function KeyedResourceDetail() {
  const { id } = useParams();
  return <ResourceDetailPage key={id} />;
}

// ── Sidebar workspace badge ───────────────────────────────────────────────────

function fmtMemberExpiry(ms) {
  const diff = ms - Date.now();
  if (diff <= 0) return "Session expired";
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor((diff % 3_600_000) / 60_000);
  return h > 0 ? `Expires in ${h}h ${m}m` : `Expires in ${m}m`;
}

function WorkspaceBadge({ collapsed }) {
  const navigate   = useNavigate();
  if (collapsed) return null;
  const isMember   = hasMemberSession();
  const role       = isMember ? getMemberRole() : null;
  const ROLE_COLOR = { VIEWER: "text-blue-300", EDITOR: "text-amber-300", ADMIN: "text-purple-300" };
  const wsExpiry   = getWorkspaceExpiresAt();
  // Both member sessions and workspace-owner sessions now have a 24h expiry.
  const statusLine = isMember
    ? fmtMemberExpiry(getSessionExpiry())
    : wsExpiry > 0
      ? fmtMemberExpiry(wsExpiry)
      : "Workspace unlocked";
  return (
    <div className="px-3 pb-3 pt-1 border-t border-white/10">
      <div className="px-2 py-2 rounded-lg" style={{ background: "rgba(255,255,255,0.07)" }}>
        <div className="flex items-center gap-2 mb-0.5">
          <div className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
          <span className="text-white/70 text-xs font-medium truncate flex-1">{getWorkspaceName()}</span>
          <button
            onClick={() => { clearWorkspace(); navigate("/overview", { replace: true }); }}
            title="Remove workspace from this browser"
            aria-label="Remove workspace from this browser"
            className="text-white/30 hover:text-red-400 text-xs transition-colors shrink-0"
          >
            ✕
          </button>
        </div>
        {role && (
          <p className={`text-[11px] pl-4 leading-none font-semibold ${ROLE_COLOR[role] || "text-white/50"}`}>{role}</p>
        )}
        <p className="text-white/35 text-[11px] pl-4 leading-none mt-0.5">{statusLine}</p>
      </div>
    </div>
  );
}

// ── Nav item ──────────────────────────────────────────────────────────────────

function NavItem({ to, label, Icon, collapsed }) {
  return (
    <NavLink
      to={to}
      title={label}
      className={({ isActive }) =>
        `flex items-center gap-3 px-3 py-2 mx-2 rounded-lg text-sm transition-colors ${
          isActive
            ? "bg-white/15 text-white font-semibold"
            : "text-white/55 hover:bg-white/10 hover:text-white"
        }`
      }
    >
      {({ isActive }) => (
        <>
          <Icon size={16} className={`shrink-0 ${isActive ? "text-white" : "text-white/55"}`}
            strokeWidth={isActive ? 2 : 1.5} />
          {!collapsed && <span className="truncate">{label}</span>}
        </>
      )}
    </NavLink>
  );
}

function ComingSoonNavItem({ label, Icon, collapsed }) {
  return (
    <div
      title="Org-wide scanning with StackSets is coming soon."
      className="flex items-center gap-3 px-3 py-2 mx-2 rounded-lg text-sm opacity-40 cursor-not-allowed select-none"
    >
      <Icon size={16} className="shrink-0 text-white/55" strokeWidth={1.5} />
      {!collapsed && (
        <div className="flex-1 min-w-0">
          <span className="block truncate text-white/55">{label}</span>
          <span className="text-white/35 text-[10px] leading-none">Coming soon</span>
        </div>
      )}
    </div>
  );
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

function Sidebar({ collapsed, onToggle, mobileOpen, orgScanEnabled }) {
  const navigate = useNavigate();
  const scanModes = orgScanEnabled
    ? [...SCAN_MODES_BASE, { to: "/org-scan", label: "Organization Scan", Icon: Network }]
    : SCAN_MODES_BASE;
  return (
    <aside
      className={`flex flex-col overflow-hidden shrink-0 transition-all duration-300
        fixed inset-y-0 left-0 z-50
        md:sticky md:top-0 md:bottom-auto md:h-screen md:z-auto
        ${mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}`}
      style={{ width: collapsed ? 56 : 240, background: "#0F1E35" }}
    >
      {/* Logo */}
      <div className="flex items-center gap-2 px-3 py-4 border-b border-white/10 shrink-0">
        <CloudCog size={22} className="text-sky-400 shrink-0" strokeWidth={1.5} />
        {!collapsed && (
          <div className="min-w-0">
            <p className="text-white font-bold text-sm leading-tight">AWS EOL</p>
            <p className="text-white/50 text-xs leading-tight">Monitor</p>
          </div>
        )}
      </div>

      <nav className="flex-1 py-3 overflow-y-auto overflow-x-hidden space-y-1">
        <NavItem to="/overview" label="Overview" Icon={Home} collapsed={collapsed} />

        {!collapsed && (
          <p className="text-white/30 text-xs uppercase tracking-widest px-5 pt-3 pb-1">Scan Modes</p>
        )}
        {collapsed && <div className="border-t border-white/10 mx-3 my-2" />}
        {scanModes.map(m => m.comingSoon
          ? <ComingSoonNavItem key={m.to} label={m.label} Icon={m.Icon} collapsed={collapsed} />
          : <NavItem key={m.to} to={m.to} label={m.label} Icon={m.Icon} collapsed={collapsed} />
        )}

        {!collapsed && (
          <p className="text-white/30 text-xs uppercase tracking-widest px-5 pt-4 pb-1">Tools</p>
        )}
        {collapsed && <div className="border-t border-white/10 mx-3 my-2" />}
        {TOOLS.map(t => (
          <NavItem key={t.to} to={t.to} label={t.label} Icon={t.Icon} collapsed={collapsed} />
        ))}
      </nav>

      {hasWorkspace() && <WorkspaceBadge collapsed={collapsed} />}

      <button
        onClick={onToggle}
        className="flex items-center gap-2 text-white/35 hover:text-white/70 text-xs py-3 px-3 border-t border-white/10 transition-colors shrink-0"
      >
        {collapsed
          ? <ChevronRight size={14} />
          : <><ChevronLeft size={14} /><span>Collapse</span></>
        }
      </button>

      {SHOW_ADMIN_SHORTCUT && (
        <button
          onClick={() => navigate("/admin")}
          title="Internal admin"
          className="text-white/[0.12] hover:text-white/35 text-[10px] py-2 px-3 w-full text-left transition-colors shrink-0"
        >
          {!collapsed && "admin"}
        </button>
      )}
    </aside>
  );
}

function FeatureDisabledPage() {
  const navigate = useNavigate();
  return (
    <div className="p-8 max-w-xl mx-auto text-center mt-20">
      <Network size={52} className="text-slate-200 mx-auto mb-5" strokeWidth={1} />
      <h1 className="text-2xl font-extrabold text-slate-900 mb-2">Feature disabled</h1>
      <p className="text-slate-500 leading-relaxed mb-8">
        Organization Scan is not enabled in this deployment.
      </p>
      <button
        onClick={() => navigate("/dashboard")}
        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-slate-900 text-white text-sm font-bold hover:bg-slate-700 transition-colors"
      >
        Back to Dashboard
      </button>
    </div>
  );
}

// Guard component for /org-scan — waits for auth config before deciding.
// Without this, DEFAULT_AUTH_CONFIG.orgScanEnabled=false causes FeatureDisabledPage
// to flash briefly on every refresh before the /auth/config response arrives.
function OrgScanGate() {
  const { authConfig, isLoading } = useAuthConfig();
  if (isLoading) return <PageLoadingFallback />;
  if (!authConfig.orgScanEnabled) return <FeatureDisabledPage />;
  return <OrgScanPage />;
}

// ── AppLayout — sidebar + page content via Outlet ─────────────────────────────
// Keeps collapsed state internally so it persists within a route group.

const PROTECTED_PREFIXES = [
  "/account-scan", "/connected-accounts", "/account-results",
  "/org-scan", "/dashboard", "/resource", "/services", "/alerts", "/reports", "/settings",
];

function AppLayout() {
  const [collapsed,  setCollapsed]  = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const navigate   = useNavigate();
  const location   = useLocation();
  const { authConfig } = useAuthConfig();
  const locRef     = useRef(location);
  useEffect(() => { locRef.current = location; }, [location]);

  // Close mobile sidebar on navigation
  useEffect(() => { setMobileOpen(false); }, [location.pathname]);

  // Background session-expiry watchdog — runs every 60 s
  useEffect(() => {
    const timer = setInterval(() => {
      const path = locRef.current.pathname;
      const onProtected = PROTECTED_PREFIXES.some(p => path.startsWith(p));
      if (onProtected && !hasWorkspace()) {
        navigate("/overview", { replace: true, state: { sessionExpired: true } });
      }
    }, 60_000);
    return () => clearInterval(timer);
  }, [navigate]);

  // 401/403 from backend → clear stale session and redirect to overview.
  // Only trigger on workspace-specific error codes; other 403s (e.g. AWS AccessDenied)
  // should propagate normally without wiping the session.
  const navigateRef = useRef(navigate);
  useEffect(() => { navigateRef.current = navigate; }, [navigate]);
  useEffect(() => {
    const SESSION_ERROR_CODES = new Set([
      "WORKSPACE_TOKEN_MISSING",
      "WORKSPACE_TOKEN_INVALID",
      "WORKSPACE_TOKEN_EXPIRED",
      "WORKSPACE_NOT_FOUND",
      "MEMBER_SESSION_INVALID",
      "MEMBER_SESSION_REVOKED",
      "MEMBER_SESSION_EXPIRED",
    ]);
    const id = axios.interceptors.response.use(null, (error) => {
      const status  = error?.response?.status;
      const errCode = error?.response?.data?.error?.code ?? "";
      const isSessionError =
        (status === 401 || status === 403) &&
        SESSION_ERROR_CODES.has(errCode);
      if (isSessionError && hasWorkspace()) {
        clearWorkspace();
        navigateRef.current("/overview", { replace: true, state: { sessionExpired: true } });
      }
      return Promise.reject(error);
    });
    return () => axios.interceptors.response.eject(id);
  }, []);

  // Dev/internal shortcut. The visible sidebar shortcut is gated separately.
  useEffect(() => {
    function onKey(e) {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "a") {
        e.preventDefault();
        if (SHOW_ADMIN_SHORTCUT) navigate("/admin");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "#F0F4F8" }}>
      {/* Mobile overlay backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed(c => !c)}
        mobileOpen={mobileOpen}
        orgScanEnabled={authConfig.orgScanEnabled}
      />

      <main className="flex-1 overflow-x-hidden overflow-y-auto min-w-0">
        {/* Mobile top bar — hamburger + logo, only on small screens */}
        <div className="sticky top-0 z-30 flex items-center gap-3 px-4 py-3 bg-white border-b border-slate-100 shadow-sm md:hidden shrink-0">
          <button
            onClick={() => setMobileOpen(true)}
            className="p-1.5 rounded-lg text-slate-600 hover:bg-slate-100 transition-colors"
            aria-label="Open navigation menu"
          >
            <Menu size={18} strokeWidth={2} />
          </button>
          <CloudCog size={18} className="text-sky-400 shrink-0" strokeWidth={1.5} />
          <span className="text-sm font-bold text-slate-800">AWS EOL Monitor</span>
        </div>

        <RouteErrorBoundary>
          <Suspense fallback={<PageLoadingFallback />}>
            <Outlet />
          </Suspense>
        </RouteErrorBoundary>
      </main>
    </div>
  );
}

// ── Suspense fallback — shown while a lazy page chunk is downloading ──────────
// Sidebar is already visible; only the content area shows a shimmer.

function PageLoadingFallback() {
  return (
    <div className="px-6 py-8 max-w-7xl mx-auto animate-pulse">
      <div className="h-3 w-20 rounded bg-slate-200 mb-2" />
      <div className="h-8 w-64 rounded bg-slate-200 mb-2" />
      <div className="h-4 w-80 rounded bg-slate-100 mb-8" />
      <div className="h-28 rounded-2xl bg-white shadow-sm mb-4" />
      <div className="h-64 rounded-2xl bg-white shadow-sm" />
    </div>
  );
}

// ── Route-level error boundary ────────────────────────────────────────────────

class RouteErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="px-6 py-16 max-w-xl mx-auto text-center">
          <p className="text-2xl font-extrabold text-slate-800 mb-2">Something went wrong</p>
          <p className="text-sm text-slate-500 mb-6 leading-relaxed">
            This page encountered an error. Your workspace session is still active.
          </p>
          <button
            onClick={() => { this.setState({ hasError: false }); window.location.reload(); }}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-slate-900 text-white text-sm font-bold hover:bg-slate-700 transition-colors"
          >
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const { authConfig } = useAuthConfig();

  // Attach workspace token to every outgoing axios request automatically
  useEffect(() => {
    const id = axios.interceptors.request.use(cfg => {
      cfg.headers = { ...(cfg.headers || {}), ...workspaceHeaders() };
      return cfg;
    });
    return () => axios.interceptors.request.eject(id);
  }, []);

  return (
    <BrowserRouter>
      <Suspense fallback={
        <div className="min-h-screen flex items-center justify-center" style={{ background: "#F0F4F8" }}>
          <div className="flex gap-1.5">
            <span className="h-2 w-2 rounded-full bg-slate-300 animate-pulse" style={{ animationDelay: "0ms" }} />
            <span className="h-2 w-2 rounded-full bg-slate-300 animate-pulse" style={{ animationDelay: "150ms" }} />
            <span className="h-2 w-2 rounded-full bg-slate-300 animate-pulse" style={{ animationDelay: "300ms" }} />
          </div>
        </div>
      }>
      <Routes>
        <Route path="/admin"                  element={<InternalAdminPage />} />
        <Route path="/accept-invite"          element={<AcceptInvitePage />} />
        <Route path="/member-login"           element={<MemberLoginPage />} />
        <Route path="/member-login/complete"  element={<MemberLoginCompletePage />} />
        {/* Auth routes — rendered outside AppLayout (no sidebar needed) */}
        <Route path="/auth/verify-email"      element={<EmailVerificationPage />} />
        <Route path="/auth/google/complete"   element={<Navigate to="/overview" replace />} />
        <Route path="/auth/saml/complete"     element={<SamlCompletePage />} />
        <Route path="/auth/saml/error"        element={<SamlErrorPage />} />
        <Route path="/auth/error"             element={<Navigate to="/overview" replace />} />

        {/* Standalone access page — redirect to overview; inline panel handles access */}
        <Route path="/workspace-access" element={<Navigate to="/overview" replace />} />

        {/* All remaining routes share the same AppLayout (sidebar always visible) */}
        <Route element={<AppLayout />}>
          {/* Public — no workspace required */}
          <Route path="/"            element={<Navigate to="/overview" replace />} />
          <Route path="/overview"    element={<OverviewPage orgScanEnabled={authConfig.orgScanEnabled} />} />
          <Route path="/general-eol" element={<GeneralEolPage />} />

          {/* Protected — WorkspaceGuard renders inline panel if no workspace */}
          <Route element={<WorkspaceGuard />}>
            <Route path="/account-scan"               element={<AccountScanPage />} />
            <Route path="/connected-accounts"         element={<ConnectedAccountsPage />} />
            <Route path="/account-results/:accountId" element={<KeyedAccountResults />} />
            <Route path="/org-scan"                   element={<OrgScanGate />} />
            <Route path="/dashboard"                  element={<DashboardPage />} />
            <Route path="/resource/:id"               element={<KeyedResourceDetail />} />
            <Route path="/services"                   element={<ServicesPage />} />
            <Route path="/alerts"                     element={<AlertsPage />} />
            <Route path="/reports"                    element={<ReportsPage />} />
            <Route path="/settings"                   element={<SettingsPage />} />
          </Route>
        </Route>
      </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
