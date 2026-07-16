import React, { useState, useMemo, useEffect } from "react";
import { useParams, useNavigate, useLocation, Link } from "react-router-dom";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { isDemoEnabled } from "../utils/config";
import { loadAccounts, updateAccount, startScanOnServer, getScanStatus, fetchWorkspaceInventory, regionScopeLabel } from "../utils/connectedAccounts";
import { MOCK_ACCOUNT_INVENTORY } from "../mocks/mockAccountScanData";
import { StatusBadge } from "../components/StatusBadge";
import { EOLTimeline } from "../components/EOLTimeline";
import { serviceLabel } from "../utils/classify";

const NON_LIFECYCLE = new Set(["NEEDS_INSPECTION", "LIFECYCLE_NOT_TRACKED"]);

const STATUS_PRIORITY = {
  EOL: 0, EXPIRING_SOON: 1, EXTENDED_SUPPORT: 2, SUPPORTED: 3,
  UNKNOWN: 4, NEEDS_INSPECTION: 5, LIFECYCLE_NOT_TRACKED: 6,
};

const EMPTY_RESULT = {
  total: 0,
  EOL: 0, EXPIRING_SOON: 0, EXTENDED_SUPPORT: 0, SUPPORTED: 0, UNKNOWN: 0,
  NEEDS_INSPECTION: 0, LIFECYCLE_NOT_TRACKED: 0,
};

const DEMO_RESULT = { total: 28, EOL: 8, EXPIRING_SOON: 8, EXTENDED_SUPPORT: 4, SUPPORTED: 7, UNKNOWN: 1 };

const SCAN_ERROR_MESSAGES = {
  ASSUME_ROLE_FAILED:    "Could not assume the IAM role. Verify the role ARN, external ID, and trust policy.",
  ACCESS_DENIED:         "Access denied. Check that the IAM role has the required permissions.",
  SERVICE_ACCESS_DENIED: "IAM role assumed, but one or more services were inaccessible. Check service-level IAM permissions.",
  SCAN_FAILED:           "Scan failed due to an unexpected error.",
};

function StatCard({ label, value, color }) {
  const c = {
    red:    { bg: "bg-red-50",     text: "text-red-800"    },
    amber:  { bg: "bg-amber-50",   text: "text-amber-800"  },
    blue:   { bg: "bg-blue-50",    text: "text-blue-800"   },
    green:  { bg: "bg-green-50",   text: "text-green-800"  },
    gray:   { bg: "bg-gray-100",   text: "text-gray-700"   },
    violet: { bg: "bg-violet-50",  text: "text-violet-700" },
    slate:  { bg: "bg-slate-100",  text: "text-slate-500"  },
  }[color] ?? { bg: "bg-gray-100", text: "text-gray-700" };
  return (
    <div className={`rounded-xl p-4 ${c.bg}`}>
      <p className={`text-2xl font-extrabold ${c.text}`}>{value}</p>
      <p className={`text-xs font-semibold uppercase tracking-wide mt-0.5 ${c.text} opacity-70`}>{label}</p>
    </div>
  );
}

export default function AccountResultsPage() {
  const { accountId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [account, setAccount]           = useState(() => loadAccounts().find(a => a.id === accountId) ?? null);
  const [statusFilter, setStatusFilter] = useState("");
  const [scanning, setScanning]         = useState(false);
  const [resources, setResources]       = useState([]);
  const [scanError, setScanError]       = useState("");
  const [loadingInventory, setLoadingInventory] = useState(false);

  // Tolerant mapper: handles both snake_case (backend) and camelCase
  function mapResource(r) {
    return {
      id:              r.resource_id         || r.resourceId,
      resourceArn:     r.resource_id         || r.resourceId,
      resourceName:    r.resource_name       || r.resourceName,
      service:         r.service_type        || r.serviceType,
      region:          r.region,
      version:         r.version,
      status:          r.eol_status          || r.eolStatus          || "UNKNOWN",
      eolDate:         r.eol_date            || r.eolDate,
      daysToEol:       r.days_to_eol         ?? r.daysToEol,
      accountId:       r.account_id          || r.accountId,
      supportEndDate:  r.support_end_date    || r.supportEndDate     || null,
      finalEolDate:    r.final_eol_date      || r.finalEolDate       || null,
      instanceType:    r.instance_type       || r.instanceType       || null,
      amiId:           r.ami_id              || r.amiId              || null,
      platformDetails: r.platform_details    || r.platformDetails    || null,
      imageName:       r.image_name          || r.imageName          || null,
      imageDescription:r.image_description   || r.imageDescription   || null,
      osSource:        r.os_source           || r.osSource           || null,
      recommendedAction:r.recommendation     || r.recommendedAction  || null,
      lifecycleApplicable: r.lifecycle_applicable ?? r.lifecycleApplicable ?? true,
      classificationType:  r.classification_type  || r.classificationType  || "EOL_TRACKED",
      statusLabel:         r.status_label         || r.statusLabel         || null,
      // Lifecycle metadata — source trust information
      lifecycleSource: r.lifecycle_source    || r.lifecycleSource    || null,
      confidence:      r.confidence                                  || null,
      officialSourceUrl: r.officialSourceUrl || r.source_url         || null,
      validatedBy:     r.validatedBy                                 || null,
      lastValidatedAt: r.lastValidatedAt                             || null,
      validationStatus: r.validationStatus                           || null,
      reason:          r.reason                                      || null,
    };
  }

  async function loadInventoryForAccount(connId) {
    if (isDemoEnabled()) return;
    setLoadingInventory(true);
    try {
      const all = await fetchWorkspaceInventory();
      const filtered = all.filter(r =>
        String(r.account_id || r.accountId || "") === String(connId)
      );
      setResources(filtered);
    } catch { /* leave resources empty */ }
    setLoadingInventory(false);
  }

  useEffect(() => {
    const found = loadAccounts().find(a => a.id === accountId);
    setAccount(found || null);
    // Always load inventory — even for org scan accounts not in localStorage
    loadInventoryForAccount(accountId);
  }, [accountId]); // eslint-disable-line

  // After inventory loads: if no connected account but resources exist,
  // create a synthetic account so the page can render org scan account results.
  useEffect(() => {
    if (!loadingInventory && !account && resources.length > 0) {
      const fromState = location.state ?? {};
      setAccount({
        id:               accountId,
        accountName:      fromState.accountName || accountId,
        accountId:        accountId,
        lastScanAt:       null,
        lastScanSummary:  null,
        _isOrgScanAccount: true,
      });
    }
  }, [loadingInventory]); // eslint-disable-line

  const inventory = isDemoEnabled()
    ? MOCK_ACCOUNT_INVENTORY
    : resources.map(mapResource);

  const inventoryTotals = useMemo(() => {
    const next = { ...EMPTY_RESULT, total: inventory.length };
    for (const item of inventory) {
      const s = item.status || "UNKNOWN";
      if (s in next) next[s] += 1;
      else next[s] = 1;
    }
    return next;
  }, [inventory]);

  const sorted = useMemo(() => {
    let rows = inventory;
    if (statusFilter) rows = rows.filter(r => r.status === statusFilter);
    return [...rows].sort((a, b) => {
      const pa = STATUS_PRIORITY[a.status] ?? 4;
      const pb = STATUS_PRIORITY[b.status] ?? 4;
      if (pa !== pb) return pa - pb;
      return (a.daysToEol ?? 99999) - (b.daysToEol ?? 99999);
    });
  }, [statusFilter, inventory]);

  // Inventory still loading — wait for synthetic account to be created
  if (!account && loadingInventory) {
    return (
      <div className="p-6 max-w-xl mx-auto text-center mt-16">
        <p className="text-gray-400 text-sm">Loading account…</p>
      </div>
    );
  }

  // Inventory done, no account found and no resources — nothing to show
  if (!account && !loadingInventory && resources.length === 0) {
    const fromState = location.state ?? {};
    const isOrgScan = fromState.scanSource === "ORG_SCAN";
    return (
      <div className="p-6 max-w-xl mx-auto text-center mt-16">
        <p className="text-gray-700 font-medium mb-2">
          {isOrgScan ? "No scan data for this account yet." : "Account not found."}
        </p>
        <p className="text-sm text-gray-400 mb-4">
          {isOrgScan
            ? "This organization member account has not been scanned yet. Run an Organization Scan to populate resource data."
            : "This connected account may have been removed or not yet scanned."}
        </p>
        <Link
          to={isOrgScan ? "/org-scan" : "/connected-accounts"}
          className="text-sm text-blue-600 hover:text-blue-800"
        >
          {isOrgScan ? "← Go to Organization Scan" : "← Back to Connected Accounts"}
        </Link>
      </div>
    );
  }

  // Should not reach here, but guard against null dereferences below
  if (!account) return null;

  const totals = inventory.length > 0
    ? inventoryTotals
    : { ...EMPTY_RESULT, ...(account.lastScanSummary ?? {}) };

  const lastScanDisplay = account.lastScanAt
    ? new Date(account.lastScanAt).toUTCString().replace("GMT", "UTC")
    : "Never";

  async function handleRescan() {
    if (isDemoEnabled()) {
      setScanning(true);
      setTimeout(() => {
        updateAccount(account.id, { lastScanAt: new Date().toISOString(), lastScanStatus: "success", lastScanSummary: DEMO_RESULT });
        setAccount(prev => ({ ...prev, lastScanAt: new Date().toISOString(), lastScanStatus: "success", lastScanSummary: DEMO_RESULT }));
        setScanning(false);
      }, 2000);
      return;
    }
    setScanning(true);
    setScanError("");

    const DONE = new Set(["SUCCESS", "FAILED", "PARTIAL_SUCCESS"]);

    function applyResult(status, summary) {
      if (status === "SUCCESS" || status === "PARTIAL_SUCCESS") {
        const s = summary ?? {};
        updateAccount(account.id, {
          lastScanAt:      new Date().toISOString(),
          lastScanStatus:  "success",
          lastScanSummary: {
            total:               s.total            ?? 0,
            EOL:                 s.eol              ?? 0,
            EXPIRING_SOON:       s.expiringSoon     ?? 0,
            EXTENDED_SUPPORT:    s.extendedSupport  ?? 0,
            SUPPORTED:           s.supported        ?? 0,
            UNKNOWN:             s.unknown          ?? 0,
            NEEDS_INSPECTION:    s.needsInspection  ?? 0,
            LIFECYCLE_NOT_TRACKED: s.lifecycleNotTracked ?? 0,
          },
        });
        setAccount(prev => ({ ...prev, lastScanAt: new Date().toISOString(), lastScanStatus: "success" }));
        // Give DynamoDB GSI ~1.5s to propagate before re-fetching
        setTimeout(() => loadInventoryForAccount(account.id), 1500);
      } else {
        setScanError("Scan completed with errors. Check server logs.");
      }
    }

    const result = await startScanOnServer(account.id);
    if (!result || result.error) {
      if (result?.errorCode === "SCAN_IN_PROGRESS") {
        // Another scan is already running — not a failure. Poll the existing scan.
        const runningScanId = result?.runningScanId;
        if (runningScanId) {
          let attempts = 0;
          const poll = setInterval(async () => {
            attempts++;
            if (attempts > 120) { clearInterval(poll); setScanError("Scan timed out."); setScanning(false); return; }
            const run = await getScanStatus(runningScanId);
            if (!run) return;
            if (DONE.has(run.status)) {
              clearInterval(poll);
              applyResult(run.status, run.summary);
              setScanning(false);
            }
          }, 2500);
        } else {
          // No scan ID — keep button disabled briefly so user can't spam clicks
          setTimeout(() => setScanning(false), 8000);
        }
        return;
      }
      setScanError(result?.error || "Scan failed. Check server logs.");
      setScanning(false);
      return;
    }

    if (DONE.has(result.status)) {
      applyResult(result.status, result.summary);
      setScanning(false);
      return;
    }

    // Async scan — poll until terminal
    const { scanId } = result;
    let attempts = 0;
    const poll = setInterval(async () => {
      attempts++;
      if (attempts > 120) {
        clearInterval(poll);
        setScanError("Scan timed out.");
        setScanning(false);
        return;
      }
      const run = await getScanStatus(scanId);
      if (!run) return;
      if (DONE.has(run.status)) {
        clearInterval(poll);
        applyResult(run.status, run.summary);
        setScanning(false);
      }
    }, 2500);
  }

  const FILTER_TABS = [
    { key: "",                    label: "All"           },
    { key: "EOL",                 label: "EOL"           },
    { key: "EXPIRING_SOON",       label: "Expiring"      },
    { key: "EXTENDED_SUPPORT",    label: "Ext. Support"  },
    { key: "SUPPORTED",           label: "Supported"     },
    { key: "UNKNOWN",             label: "Unknown"       },
    ...(totals.NEEDS_INSPECTION    > 0 ? [{ key: "NEEDS_INSPECTION",     label: "Needs Inspection"   }] : []),
    ...(totals.LIFECYCLE_NOT_TRACKED > 0 ? [{ key: "LIFECYCLE_NOT_TRACKED", label: "Not Tracked"    }] : []),
  ];

  return (
    <div className="px-4 sm:px-6 py-6 sm:py-8 max-w-7xl mx-auto">
      {/* Back navigation */}
      <div className="mb-5">
        <Link
          to={location.state?.from === "reports" ? "/reports" : "/connected-accounts"}
          className="inline-flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-600 transition-colors">
          <ArrowLeft size={14} strokeWidth={2} />
          {location.state?.from === "reports" ? "Reports" : "Connected Accounts"}
        </Link>
      </div>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full uppercase tracking-widest ${
              account._isOrgScanAccount
                ? "bg-purple-100 text-purple-700"
                : "bg-blue-100 text-blue-700"
            }`}>
              {account._isOrgScanAccount ? "Org Scan Results" : "Account Scan Results"}
            </span>
            {isDemoEnabled() && <span className="text-xs text-gray-400">Demo Mode</span>}
          </div>
          <h1 className="text-2xl font-bold text-gray-900">{account.accountName}</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {account.accountId}
            {!account._isOrgScanAccount && ` · ${regionScopeLabel(account)}`}
            {" · "}
            {lastScanDisplay === "Never" ? "Source: Organization Scan" : `Last scanned: ${lastScanDisplay}`}
          </p>
        </div>
        {!account._isOrgScanAccount && (
          <button onClick={handleRescan} disabled={scanning}
            className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-200 text-gray-600 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-60 disabled:cursor-not-allowed shrink-0 ml-4">
            <RefreshCw size={14} strokeWidth={2} className={scanning ? "animate-spin" : ""} />
            {scanning ? "Scanning…" : "Run Scan Again"}
          </button>
        )}
      </div>

      {/* Scan error */}
      {scanError && (
        <div className="mb-4 flex items-start gap-2 rounded-xl bg-red-50 ring-1 ring-red-200 px-4 py-3 text-sm text-red-700">
          <span className="font-semibold shrink-0">Scan failed:</span>
          <span className="break-all">{scanError}</span>
        </div>
      )}

      {/* Last scan failed notice */}
      {account.lastScanStatus === "failed" && !scanError && (
        <div className="mb-4 flex items-start gap-2 rounded-xl bg-amber-50 ring-1 ring-amber-200 px-4 py-3 text-sm text-amber-800">
          <span className="font-semibold shrink-0">Last scan failed:</span>
          <span>
            {SCAN_ERROR_MESSAGES[account.lastScanErrorCode] || account.lastScanError || "An unexpected error occurred."}
            {account.lastScanId && (
              <span className="ml-1.5 font-mono opacity-50">ID: {account.lastScanId}</span>
            )}
          </span>
        </div>
      )}

      {/* EOL summary cards — 5 main lifecycle statuses */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-3">
        <StatCard label="End of Life"   value={totals.EOL}              color="red"   />
        <StatCard label="Expiring Soon" value={totals.EXPIRING_SOON}    color="amber" />
        <StatCard label="Ext. Support"  value={totals.EXTENDED_SUPPORT} color="blue"  />
        <StatCard label="Supported"     value={totals.SUPPORTED}        color="green" />
        <StatCard label="Unknown"       value={totals.UNKNOWN ?? 0}     color="gray"  />
      </div>

      {/* Non-lifecycle discovery cards — shown only when present */}
      {(totals.NEEDS_INSPECTION > 0 || totals.LIFECYCLE_NOT_TRACKED > 0) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-6">
          {totals.NEEDS_INSPECTION > 0 && (
            <StatCard
              label="Needs Inspection"
              value={totals.NEEDS_INSPECTION}
              color="violet"
            />
          )}
          {totals.LIFECYCLE_NOT_TRACKED > 0 && (
            <StatCard
              label="Lifecycle Not Tracked"
              value={totals.LIFECYCLE_NOT_TRACKED}
              color="slate"
            />
          )}
        </div>
      )}
      {!(totals.NEEDS_INSPECTION > 0 || totals.LIFECYCLE_NOT_TRACKED > 0) && (
        <div className="mb-6" />
      )}

      {/* Filter tabs */}
      <div className="flex gap-2 mb-4 flex-wrap">
        {FILTER_TABS.map(({ key, label }) => (
          <button key={key} onClick={() => setStatusFilter(key)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all ${
              statusFilter === key
                ? "bg-gray-900 text-white border-gray-900"
                : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50"
            }`}>
            {label}
          </button>
        ))}
      </div>

      {/* Resource table */}
      {loadingInventory ? (
        <div className="bg-white rounded-xl border border-gray-100 p-12 text-center">
          <p className="text-gray-400 text-sm animate-pulse">Loading inventory…</p>
        </div>
      ) : inventory.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-100 p-12 text-center">
          <p className="text-gray-500 text-sm">
            {account.lastScanAt ? "No resources found for this account." : "No scan data yet — click Run Scan to start."}
          </p>
        </div>
      ) : sorted.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-100 p-12 text-center">
          <p className="text-gray-500 text-sm">No resources match this filter.</p>
          <button onClick={() => setStatusFilter("")}
            className="mt-3 text-xs text-blue-600 hover:text-blue-800 font-medium">
            Clear filter — show all {inventory.length} resources
          </button>
        </div>
      ) : (
        <div className="rounded-xl shadow-sm border border-slate-200 bg-white overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-[1020px] w-full text-sm border-collapse">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="sticky left-0 z-20 bg-slate-50 w-[220px] px-4 py-2 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">Resource</th>
                  <th className="w-[120px] px-4 py-2 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">Service</th>
                  <th className="w-[120px] px-4 py-2 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">Region</th>
                  <th className="w-[150px] px-4 py-2 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">Version</th>
                  <th className="w-[160px] px-4 py-2 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">Status</th>
                  <th className="w-[260px] px-4 py-2 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">Days</th>
                  <th className="w-[130px] px-4 py-2 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">EOL Date</th>
                  <th className="sticky right-0 z-20 bg-slate-50 w-[100px] px-4 py-2 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">Action</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(item => (
                  <tr key={item.id}
                    className="group border-b border-slate-100 hover:bg-blue-50/30 cursor-pointer transition-colors"
                    onClick={() => navigate(`/resource/${encodeURIComponent(item.resourceArn || item.id)}`)}>
                    <td className="sticky left-0 z-10 bg-white group-hover:bg-blue-50/30 transition-colors px-4 py-2 w-[220px] font-medium text-gray-900">
                      <span className="block truncate" title={item.resourceName}>{item.resourceName}</span>
                    </td>
                    <td className="px-4 py-2 text-gray-600 whitespace-nowrap">{serviceLabel(item.service)}</td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-500 whitespace-nowrap">{item.region}</td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-600 whitespace-nowrap">
                      <span className="block truncate" title={item.version || ""}>{item.version || "—"}</span>
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      <StatusBadge status={item.status} />
                    </td>
                    <td className="px-4 py-2 w-[260px]">
                      <EOLTimeline daysToEol={item.daysToEol} eolDate={item.eolDate} status={item.status}
                        eolLabel={item.service === "EC2" ? "Lifecycle end" : "EOL"} />
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">
                      {NON_LIFECYCLE.has(item.status) ? "—" : (item.supportEndDate || item.eolDate || "—")}
                    </td>
                    <td className="sticky right-0 z-10 bg-white group-hover:bg-blue-50/30 transition-colors px-4 py-2 text-xs">
                      <span className="text-blue-500 font-medium whitespace-nowrap">Details →</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-3 border-t border-slate-100 text-xs text-slate-400">
            Showing {sorted.length} of {inventory.length} resources
            {isDemoEnabled() && " · Demo data"}
          </div>
        </div>
      )}
    </div>
  );
}
