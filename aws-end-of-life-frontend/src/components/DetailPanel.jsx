import React from "react";
import { useNavigate } from "react-router-dom";
import { X, ExternalLink, ShieldCheck } from "lucide-react";
import { StatusBadge } from "./StatusBadge";
import { EOLTimeline } from "./EOLTimeline";
import { serviceLabel, LAMBDA_UPGRADES } from "../utils/classify";
import { getAwsGuideUrl } from "../config/serviceRegistry";
import { GenericMetadataPanel } from "./GenericMetadataPanel";
import { useResource } from "../hooks/useInventory";

const RISK_COLORS = {
  EOL:              { bar: "bg-red-500",   bg: "bg-red-50",    ring: "ring-red-100",   text: "text-red-800",   sub: "text-red-500"   },
  EXPIRING_SOON:    { bar: "bg-amber-400", bg: "bg-amber-50",  ring: "ring-amber-100", text: "text-amber-800", sub: "text-amber-500" },
  EXTENDED_SUPPORT: { bar: "bg-blue-400",  bg: "bg-blue-50",   ring: "ring-blue-100",  text: "text-blue-800",  sub: "text-blue-500"  },
  SUPPORTED:        { bar: "bg-green-400", bg: "bg-green-50",  ring: "ring-green-100", text: "text-green-800", sub: "text-green-500" },
};

function MetaRow({ label, value, mono }) {
  if (!value && value !== 0) return null;
  return (
    <div className="flex items-start justify-between gap-4 py-2.5 border-b border-gray-100 last:border-0">
      <span className="text-xs font-medium text-gray-400 uppercase tracking-wide shrink-0 w-28">{label}</span>
      <span className={`text-xs text-right text-gray-800 break-all ${mono ? "font-mono" : "font-medium"}`}>{value}</span>
    </div>
  );
}

function isRealResource(item) {
  return item?.resource_id?.startsWith("arn:");
}

export function DetailPanel({ item, onClose, accountMap = {} }) {
  const navigate = useNavigate();
  const { data: resourceData } = useResource(item?.resource_id);
  const ckGuide = resourceData?.ckGuide ?? null;

  if (!item) return null;

  const acctInfo    = accountMap[item.account_id];
  const acctName    = acctInfo?.name
    ?? (item.account_id?.startsWith("conn-") ? null : item.account_id)
    ?? "Unknown account";
  const rawAwsId    = acctInfo?.awsId ?? "";
  const maskedAwsId = rawAwsId.length === 12
    ? `${rawAwsId.slice(0, 4)}…${rawAwsId.slice(-4)}`
    : rawAwsId;

  const serviceBase    = item.service_type?.replace(/_.*/, "");
  const guideUrl       = getAwsGuideUrl(item.service_type);
  const rc             = RISK_COLORS[item.eol_status] ?? RISK_COLORS.SUPPORTED;
  const hasRisk        = item.eol_status === "EOL" || item.eol_status === "EXPIRING_SOON";
  const isUnknown      = item.eol_status === "UNKNOWN";
  const targetRuntime  = serviceBase === "Lambda" ? LAMBDA_UPGRADES[item.version] : null;

  const isExtSupport   = item.eol_status === "EXTENDED_SUPPORT";
  const isAurora       = item.service_type?.startsWith("Aurora");
  const isRDS          = serviceBase === "RDS" || isAurora;
  const daysLabel = item.days_to_eol == null
    ? null
    : item.days_to_eol < 0
      ? `${Math.abs(item.days_to_eol)} days past EOL`
      : `${item.days_to_eol} days remaining`;
  const eolLabel = serviceBase === "EC2" ? "Lifecycle end" : "EOL";

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/15 backdrop-blur-[1px] z-20" onClick={onClose} />

      {/* Panel */}
      <div className="fixed right-0 top-0 h-full w-full sm:w-[420px] bg-white shadow-2xl z-30 flex flex-col border-l border-gray-100">

        {/* Status accent bar */}
        <div className={`h-1 shrink-0 ${rc.bar}`} />

        {/* Header */}
        <div className="flex items-start justify-between px-6 py-4 border-b border-gray-100 bg-white shrink-0">
          <div className="min-w-0">
            <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-0.5">
              {serviceLabel(item.service_type)}
            </p>
            <h2 className="text-base font-extrabold text-gray-900 leading-snug truncate" title={item.resource_name || item.resource_id}>
              {item.resource_name || item.resource_id}
            </h2>
          </div>
          <button onClick={onClose}
            className="ml-3 mt-0.5 shrink-0 p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors">
            <X size={16} strokeWidth={2} />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">

          {/* Risk summary card */}
          <div className={`rounded-2xl ring-1 p-4 space-y-3 ${rc.bg} ${rc.ring}`}>
            <div className="flex items-center justify-between gap-3">
              <StatusBadge status={item.eol_status} size="md" />
              {daysLabel && (
                <span className={`text-sm font-bold ${rc.text}`}>{daysLabel}</span>
              )}
            </div>
            <EOLTimeline daysToEol={item.days_to_eol} eolDate={item.eol_date} status={item.eol_status} eolLabel={eolLabel} />
            {item.eol_date && item.eol_date !== "unknown" && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-500">
                  {item.eol_status === "EOL" ? "EOL since" : "EOL date"}
                </span>
                <span className={`font-semibold ${rc.sub}`}>{item.eol_date}</span>
              </div>
            )}
          </div>

          {/* Resource metadata */}
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-2">Resource Details</p>
            <div className="bg-gray-50 rounded-xl px-4 py-1">
              <MetaRow label="Service"      value={serviceLabel(item.service_type)} />
              <MetaRow label="Region"       value={item.region}      mono />
              <MetaRow label="Version"      value={item.version}     mono />
              <MetaRow label="Account"      value={acctName} />
              {maskedAwsId && <MetaRow label="AWS Account" value={maskedAwsId} mono />}
              <MetaRow label="Resource ID"  value={item.resource_id} mono />
              <MetaRow label="Last Scanned" value={item.scanned_at?.slice(0, 19).replace("T", " ")} />
              <GenericMetadataPanel item={item} compact />
            </div>
          </div>

          {/* Lifecycle data source */}
          {(() => {
            const rawSrc = item.lifecycle_source ?? item.lifecycleSource;
            const officialUrl = item.officialSourceUrl;
            const srcLabel =
              rawSrc === "VERIFIED_AWS_OFFICIAL" ? "AWS Official Verified"
              : rawSrc === "ENDOFLIFE_DATE"      ? "endoflife.date"
              : rawSrc === "MANUAL_OVERRIDE"     ? "Manual Override"
              : rawSrc === "AWS_DOCS"            ? "AWS Docs"
              : rawSrc
              ?? (officialUrl?.includes("docs.aws.amazon.com") ? "AWS Official Verified" : null)
              ?? null;
            if (!srcLabel && !item.confidence) return null;
            return (
              <div>
                <p className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-2">Lifecycle Data Source</p>
                <div className="bg-gray-50 rounded-xl px-4 py-1">
                  <MetaRow label="Source"       value={srcLabel} />
                  <MetaRow label="Confidence"   value={item.confidence} />
                  <MetaRow label="Validated"    value={
                    item.lastValidatedAt
                      ? new Date(item.lastValidatedAt).toLocaleDateString()
                      : null
                  } />
                  <MetaRow label="Validated By" value={item.validatedBy} />
                </div>
                {officialUrl && (
                  <a
                    href={officialUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-2 flex items-center gap-1.5 text-xs text-blue-500 hover:text-blue-700 font-medium"
                  >
                    <ShieldCheck size={12} />
                    Official AWS documentation
                    <ExternalLink size={11} />
                  </a>
                )}
              </div>
            );
          })()}

          {/* Recommended action */}
          {hasRisk && (
            <div>
              <p className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-2">Recommended Action</p>
              <div className={`rounded-xl p-4 ring-1 ${
                item.eol_status === "EOL"
                  ? "bg-red-50 ring-red-100 text-red-800"
                  : "bg-amber-50 ring-amber-100 text-amber-800"
              }`}>
                <p className="text-sm font-semibold mb-1">
                  {item.eol_status === "EOL"
                    ? (targetRuntime ? `Upgrade from ${item.version} to ${targetRuntime}` : "Upgrade immediately")
                    : (targetRuntime
                        ? `Upgrade from ${item.version} to ${targetRuntime} within ${item.days_to_eol} days`
                        : `Upgrade within ${item.days_to_eol} days`)}
                </p>
                <p className="text-xs leading-relaxed opacity-80">
                  {item.eol_status === "EOL"
                    ? "This resource is past End-of-Life and no longer receives security patches."
                    : "Schedule an upgrade to avoid EOL and maintain security coverage."}
                </p>
              </div>
            </div>
          )}

          {/* Extended Support action */}
          {isExtSupport && (
            <div>
              <p className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-2">Extended Support</p>
              <div className="rounded-xl p-4 ring-1 bg-blue-50 ring-blue-100 text-blue-800">
                <p className="text-sm font-semibold mb-1">
                  {item.recommendation || "Upgrade to avoid extended support charges."}
                </p>
                <p className="text-xs leading-relaxed opacity-80">
                  Standard support has ended. AWS provides critical patches at additional cost until the extended support date.
                </p>
              </div>
            </div>
          )}

          {/* Unknown lifecycle note */}
          {isUnknown && (
            <div>
              <p className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-2">Lifecycle Status</p>
              <div className="rounded-xl p-4 ring-1 bg-gray-50 ring-gray-200 text-gray-600">
                <p className="text-sm font-semibold mb-1">
                  {item.reason === "version_not_detected"
                    ? "Version not detected"
                    : serviceBase === "Lambda"
                      ? "Runtime not recognized"
                      : "Lifecycle data unavailable"}
                </p>
                <p className="text-xs leading-relaxed opacity-80">
                  {item.reason === "version_not_detected"
                    ? "The resource version could not be determined at scan time. Check the resource directly in the AWS console."
                    : "Lifecycle dates for this version could not be found in any source. The version may be too new, too old, or not yet tracked."}
                </p>
                {item.reason && item.reason !== "version_not_detected" && (
                  <p className="text-xs mt-1.5 font-mono text-gray-400">{item.reason}</p>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Sticky footer */}
        <div className="shrink-0 px-6 py-4 border-t border-gray-100 bg-white space-y-2.5">
          {guideUrl && (hasRisk || isExtSupport) && (
            <a href={guideUrl} target="_blank" rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 w-full py-2.5 px-4 rounded-xl text-sm font-bold text-white transition-opacity hover:opacity-90"
              style={{ backgroundColor: "#2A85D8" }}>
              <ExternalLink size={14} strokeWidth={2} />
              View Upgrade Guide
            </a>
          )}
          {(hasRisk || isExtSupport) && (
            ckGuide ? (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold uppercase tracking-widest text-emerald-700">CK Upgrade Guide</span>
                  {ckGuide.testedInLab && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-bold text-emerald-700">
                      ✓ Tested in lab
                    </span>
                  )}
                </div>
                <p className="text-sm font-bold text-gray-900 mb-1 leading-snug">{ckGuide.title}</p>
                {ckGuide.summary && (
                  <p className="text-xs text-gray-600 leading-relaxed mb-2">{ckGuide.summary}</p>
                )}
                {ckGuide.targetVersion && (
                  <p className="text-xs text-gray-500 mb-2.5">
                    Target: <span className="font-mono font-semibold text-gray-700">{ckGuide.targetVersion}</span>
                  </p>
                )}
                <a href={ckGuide.guideUrl} target="_blank" rel="noopener noreferrer"
                  className="flex items-center justify-center gap-2 w-full rounded-lg bg-emerald-600 px-4 py-2 text-sm font-bold text-white hover:bg-emerald-700 transition-colors">
                  <ExternalLink size={13} strokeWidth={2} />
                  Open CK Guide
                </a>
              </div>
            ) : (
              <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-bold uppercase tracking-widest text-gray-400">CK Upgrade Guide</span>
                  <span className="text-xs font-semibold text-gray-400 bg-gray-200 rounded-full px-2 py-0.5">Coming soon</span>
                </div>
                <p className="text-xs text-gray-400 leading-relaxed">
                  A lab-tested CK upgrade guide is not yet available for this service/version.
                </p>
              </div>
            )
          )}
          {isRealResource(item) ? (
            <button
              onClick={() => navigate(`/resource/${encodeURIComponent(item.resource_id)}`)}
              className="w-full py-2 px-4 rounded-xl border border-gray-200 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors">
              Full Detail View
            </button>
          ) : (
            <p className="text-xs text-gray-400 text-center leading-relaxed">
              Reference lifecycle data — run <strong className="text-gray-500">Account Scan</strong> to find impacted resources.
            </p>
          )}
        </div>
      </div>
    </>
  );
}
