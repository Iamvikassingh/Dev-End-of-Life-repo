import React, { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, ExternalLink, ShieldCheck, Info } from "lucide-react";
import { StatusBadge } from "../components/StatusBadge";
import { EOLTimeline } from "../components/EOLTimeline";
import { GenericMetadataPanel } from "../components/GenericMetadataPanel";
import { serviceLabel, LAMBDA_UPGRADES } from "../utils/classify";
import { useResource } from "../hooks/useInventory";
import { getServiceGuide } from "../config/serviceRegistry";
import { loadAccounts, fetchAccountsFromServer } from "../utils/connectedAccounts";

// ── Detection evidence helpers ────────────────────────────────────────────────

const EC2_SERVICES = new Set(["EC2"]);
const HIGH_CONFIDENCE_SERVICES = new Set([
  "RDS", "AuroraMySQL", "AuroraPostgres", "Aurora",
  "ElastiCache", "EKS", "OpenSearch", "Lambda",
  "ElasticBeanstalk",
]);

function deriveEvidence(item) {
  const svc  = item.service_type ?? "";
  const base = svc.replace(/_.*/, "");
  const isEC2 = EC2_SERVICES.has(base);

  // Confidence: use explicit field if present, else derive
  const confidence = item.confidence
    ?? (item.eol_status === "UNKNOWN"
      ? "LOW"
      : isEC2
        ? "MEDIUM"
        : HIGH_CONFIDENCE_SERVICES.has(base) ? "HIGH" : "MEDIUM");

  // Detection source
  const detectionSource = item.detection_source
    ?? (isEC2
      ? "AWS EC2 DescribeInstances — AMI image metadata"
      : base === "Lambda"  ? "AWS Lambda ListFunctions — runtime field"
      : base === "RDS" || svc.startsWith("Aurora") ? "AWS RDS DescribeDBInstances — engine version"
      : base === "EKS"     ? "AWS EKS DescribeCluster — kubernetes version"
      : base === "ElastiCache" ? "AWS ElastiCache DescribeCacheClusters — engine version"
      : base === "OpenSearch"  ? "AWS OpenSearch DescribeDomains — engine version"
      : "AWS API — resource metadata");

  // Lifecycle data source — priority: explicit field > URL heuristic > service fallback
  const _rawSrc = item.lifecycle_source ?? item.lifecycleSource;
  const _officialUrl = item.officialSourceUrl;
  const lifecycleSource =
    _rawSrc === "VERIFIED_AWS_OFFICIAL" ? "AWS Official Verified"
    : _rawSrc === "ENDOFLIFE_DATE"      ? "endoflife.date"
    : _rawSrc === "MANUAL_OVERRIDE"     ? "Manual Override"
    : _rawSrc === "AWS_DOCS"            ? "AWS Docs"
    : _rawSrc === "AWS_API"             ? "AWS API"
    : _rawSrc
    // URL heuristic fallback when field is missing from older records
    ?? (_officialUrl?.includes("docs.aws.amazon.com") ? "AWS Official Verified"
       : _officialUrl?.includes("endoflife.date")     ? "endoflife.date"
       : null)
    // Service-level default (cosmetic — does not imply verified status)
    ?? "endoflife.date";

  // Classification reason
  const reason = item.classification_reason
    ?? (item.eol_status === "EOL"
      ? `${serviceLabel(svc)} ${item.version ?? ""}`.trim() +
        (item.eol_date ? ` reached end-of-life on ${item.eol_date}.` : " has reached end-of-life.")
      : item.eol_status === "EXPIRING_SOON"
        ? `${serviceLabel(svc)} ${item.version ?? ""}`.trim() +
          (item.eol_date ? ` reaches end-of-life on ${item.eol_date}.` : " will reach end-of-life soon.")
        : item.eol_status === "EXTENDED_SUPPORT"
          ? `${serviceLabel(svc)} ${item.version ?? ""}`.trim() + " is past standard support and in AWS Extended Support."
          : item.eol_status === "UNKNOWN"
            ? "Lifecycle data could not be matched to a known release schedule."
            : `${serviceLabel(svc)} ${item.version ?? ""}`.trim() +
              (item.eol_date ? ` is actively supported until ${item.eol_date}.` : " is currently within its support lifecycle."));

  return { confidence, detectionSource, lifecycleSource, reason, isEC2 };
}

const CONFIDENCE_CFG = {
  HIGH:   { label: "High",   cls: "bg-green-50 text-green-700 ring-1 ring-green-200"  },
  MEDIUM: { label: "Medium", cls: "bg-amber-50 text-amber-700 ring-1 ring-amber-200"  },
  LOW:    { label: "Low",    cls: "bg-red-50   text-red-700   ring-1 ring-red-200"     },
};

function EvidenceRow({ label, value, mono = false }) {
  return (
    <div className="py-2.5 border-b border-slate-100 last:border-0">
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-0.5">{label}</p>
      <p className={`text-sm text-slate-800 break-words ${mono ? "font-mono text-xs" : "font-medium"}`}>{value ?? "—"}</p>
    </div>
  );
}

function DetectionEvidence({ item }) {
  const { confidence, detectionSource, lifecycleSource, reason, isEC2 } = deriveEvidence(item);
  const cc = CONFIDENCE_CFG[confidence] ?? CONFIDENCE_CFG.MEDIUM;
  const isUnknown = item.eol_status === "UNKNOWN";

  return (
    <div className="bg-white rounded-2xl shadow-sm p-6">
      <div className="flex items-center gap-2 mb-4">
        <ShieldCheck size={15} className="text-slate-400" strokeWidth={1.75} />
        <p className="text-xs font-bold uppercase tracking-widest text-gray-400">Detection Evidence</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
        {/* Detected version */}
        <EvidenceRow label="Detected Version"  value={item.version || "Not detected"} mono />
        {/* Confidence */}
        <div className="py-2.5 border-b border-slate-100">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-0.5">Detection Confidence</p>
          <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold ${cc.cls}`}>
            {cc.label}
          </span>
        </div>
        {/* Detection source */}
        <EvidenceRow label="Detection Source"  value={detectionSource} mono />
        {/* Lifecycle source */}
        <div className="py-2.5 border-b border-slate-100">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-0.5">Lifecycle Data Source</p>
          <p className="text-sm text-slate-800 font-medium">{lifecycleSource}</p>
          {item.officialSourceUrl && (
            <a
              href={item.officialSourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 inline-flex items-center gap-1 text-xs text-blue-500 hover:text-blue-700 font-medium"
            >
              <ExternalLink size={11} />
              Official AWS documentation
            </a>
          )}
          {item.lastValidatedAt && (
            <p className="text-xs text-slate-400 mt-0.5">
              Validated {new Date(item.lastValidatedAt).toLocaleDateString()}
              {item.validatedBy ? ` by ${item.validatedBy}` : ""}
            </p>
          )}
        </div>
      </div>

      {/* Classification reason */}
      <div className="mt-3 pt-3 border-t border-slate-100">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-1">Classification Reason</p>
        <p className="text-sm text-slate-700 leading-relaxed">{reason}</p>
      </div>

      {/* EC2 medium-confidence note */}
      {isEC2 && !isUnknown && confidence !== "HIGH" && (
        <div className="mt-4 flex items-start gap-3 rounded-xl bg-amber-50 ring-1 ring-amber-100 px-4 py-3">
          <Info size={14} className="shrink-0 mt-0.5 text-amber-600" strokeWidth={1.75} />
          <div>
            <p className="text-xs font-bold text-amber-800 mb-0.5">AMI-based detection — medium confidence</p>
            <p className="text-xs text-amber-700 leading-relaxed">
              Version is derived from the AMI image name/description at launch time. It may not reflect
              in-place OS or package patches applied after launch. For higher accuracy, install the{" "}
              <strong>AWS Systems Manager (SSM) Agent</strong> and use Patch Manager to report the actual
              running kernel and package versions.
            </p>
          </div>
        </div>
      )}

      {/* Unknown status explanation */}
      {isUnknown && (
        <div className="mt-4 flex items-start gap-3 rounded-xl bg-slate-50 ring-1 ring-slate-200 px-4 py-3">
          <Info size={14} className="shrink-0 mt-0.5 text-slate-500" strokeWidth={1.75} />
          <div>
            <p className="text-xs font-bold text-slate-700 mb-0.5">Why is this unknown?</p>
            <p className="text-xs text-slate-500 leading-relaxed">
              {item.service_type === "EC2" || item.service_type?.startsWith("EC2")
                ? "The AMI name did not match a known OS/version pattern, or this is a custom or marketplace AMI. Check the instance's OS using SSM Session Manager or EC2 Instance Connect."
                : item.service_type?.startsWith("Lambda")
                  ? "This function uses a container image or a custom runtime that cannot be matched to a versioned release schedule. Verify the base image or runtime manually."
                  : "The version string returned by AWS could not be matched to a known lifecycle entry. This may indicate a custom fork, a very new minor version not yet in the lifecycle database, or a missing entry in endoflife.date."}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

const RISK_COLORS = {
  EOL:              { heroBar: "bg-red-500",   heroBg: "bg-red-50",    badge: "bg-red-100 text-red-700", actionBg: "bg-red-50 ring-1 ring-red-200"    },
  EXPIRING_SOON:    { heroBar: "bg-amber-400", heroBg: "bg-amber-50",  badge: "bg-amber-100 text-amber-700", actionBg: "bg-amber-50 ring-1 ring-amber-200" },
  EXTENDED_SUPPORT: { heroBar: "bg-blue-400",  heroBg: "bg-blue-50",   badge: "bg-blue-100 text-blue-700",   actionBg: "bg-blue-50 ring-1 ring-blue-200"   },
  SUPPORTED:        { heroBar: "bg-green-400", heroBg: "bg-green-50",  badge: "bg-green-100 text-green-700", actionBg: "bg-green-50 ring-1 ring-green-200" },
};

function DetailRow({ label, value, mono }) {
  return (
    <div className="py-2.5 border-b border-gray-100 last:border-0">
      <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-0.5">{label}</p>
      <p className={`text-sm text-gray-900 font-medium break-all ${mono ? "font-mono text-xs" : ""}`}>{value ?? "—"}</p>
    </div>
  );
}

function CkGuideSection({ ckGuide }) {
  return (
    <div className="bg-white rounded-2xl shadow-sm p-6 mt-4">
      <div className="flex items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-2">
          <ExternalLink size={15} className="text-emerald-500" strokeWidth={1.75} />
          <p className="text-xs font-bold uppercase tracking-widest text-gray-400">CK Upgrade Guide</p>
        </div>
        {ckGuide?.testedInLab && (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-bold text-emerald-700">
            ✓ Tested in lab
          </span>
        )}
      </div>

      {ckGuide ? (
        <div>
          <h3 className="text-base font-bold text-gray-900 mb-1">{ckGuide.title}</h3>
          {ckGuide.summary && (
            <p className="text-sm text-gray-600 leading-relaxed mb-3">{ckGuide.summary}</p>
          )}
          {ckGuide.targetVersion && (
            <p className="text-xs text-gray-500 mb-4">
              Target:{" "}
              <span className="font-mono font-semibold text-gray-700">{ckGuide.targetVersion}</span>
            </p>
          )}
          <a href={ckGuide.guideUrl} target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-emerald-700 transition-colors">
            <ExternalLink size={13} strokeWidth={2} />
            Open CK Guide
          </a>
        </div>
      ) : (
        <div className="py-3">
          <p className="text-sm font-semibold text-slate-500 mb-1">Coming soon</p>
          <p className="text-xs text-slate-400 leading-relaxed">
            A lab-tested CK upgrade guide is not yet available for this service/version.
            The AWS official guide is still available above.
          </p>
        </div>
      )}
    </div>
  );
}

export default function ResourceDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const decodedId = decodeURIComponent(id);
  const { data, isLoading, isError } = useResource(decodedId);
  const item    = data?.item;
  const ckGuide = data?.ckGuide ?? null;

  const [connectedAccounts, setConnectedAccounts] = useState(() => loadAccounts());
  useEffect(() => {
    fetchAccountsFromServer().then(list => { if (list) setConnectedAccounts(list); });
  }, []);
  const accountMap = useMemo(() => {
    const map = {};
    for (const a of connectedAccounts)
      map[a.id] = { name: a.accountName || a.name || a.id, awsId: a.accountId || "" };
    return map;
  }, [connectedAccounts]);

  if (isLoading) {
    return (
      <div className="px-4 sm:px-6 py-6 sm:py-8 max-w-4xl mx-auto animate-pulse space-y-4">
        <div className="h-6 bg-gray-200 rounded w-32 mb-6" />
        <div className="h-40 bg-gray-100 rounded-2xl" />
        <div className="h-64 bg-gray-100 rounded-2xl" />
      </div>
    );
  }

  if (isError || !data || !item) {
    return (
      <div className="px-4 sm:px-6 py-20 max-w-4xl mx-auto text-center">
        <p className="text-gray-500 text-lg mb-4">Resource not found.</p>
        <button onClick={() => navigate(-1)}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-600 hover:underline">
          <ArrowLeft size={14} /> Back
        </button>
      </div>
    );
  }

  const serviceBase    = item.service_type?.replace(/_.*/, "");
  const isAurora       = item.service_type?.startsWith("Aurora");
  const guide          = getServiceGuide(isAurora ? "Aurora" : (item.service_type ?? ""));
  const rc             = RISK_COLORS[item.eol_status] ?? RISK_COLORS.SUPPORTED;
  const hasRisk        = item.eol_status === "EOL" || item.eol_status === "EXPIRING_SOON";
  const isExtSupport   = item.eol_status === "EXTENDED_SUPPORT";
  const isUnknown      = item.eol_status === "UNKNOWN";
  const isRDS          = serviceBase === "RDS" || isAurora;
  const targetRuntime  = serviceBase === "Lambda" ? LAMBDA_UPGRADES[item.version] : null;
  const guideText      = (serviceBase === "Lambda" && targetRuntime)
    ? `Upgrade this function from ${item.version} to ${targetRuntime}.`
    : item.recommendation || guide?.text;

  const eolTermFull  = item.service_type === "EC2" ? "lifecycle end"   : "End-of-Life";
  const eolTermPast  = item.service_type === "EC2" ? "past its lifecycle end" : "past End-of-Life";
  const daysMsg = item.days_to_eol == null ? null
    : item.days_to_eol < 0
      ? `This resource has been ${eolTermPast} for ${Math.abs(item.days_to_eol)} days.`
      : `${item.days_to_eol} days until ${eolTermFull} on ${item.eol_date}.`;

  return (
    <div className="px-4 sm:px-6 py-6 sm:py-8 max-w-4xl mx-auto">

      {/* Back */}
      <button onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-400 hover:text-gray-700 transition-colors mb-5">
        <ArrowLeft size={14} strokeWidth={2} />
        Back to Dashboard
      </button>

      {/* Hero risk card */}
      <div className="bg-white rounded-2xl shadow-sm overflow-hidden mb-4">
        <div className={`h-1.5 ${rc.heroBar}`} />
        <div className="px-6 py-5">
          <div className="flex items-start justify-between gap-4 mb-4">
            <div className="min-w-0">
              <p className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-1">
                {serviceLabel(item.service_type)} · {item.region}
              </p>
              <h1 className="text-2xl font-extrabold text-gray-900 leading-tight break-all">
                {item.resource_name || item.resource_id}
              </h1>
              {item.version && (
                <p className="text-sm font-mono text-gray-500 mt-0.5">{item.version}</p>
              )}
            </div>
            <StatusBadge status={item.eol_status} size="md" />
          </div>

          <EOLTimeline daysToEol={item.days_to_eol} eolDate={item.eol_date} status={item.eol_status}
            eolLabel={serviceBase === "EC2" ? "Lifecycle end" : "EOL"} />
          {daysMsg && (
            <p className={`text-sm mt-2 font-medium ${
              item.eol_status === "EOL" ? "text-red-600"
              : item.eol_status === "EXPIRING_SOON" ? "text-amber-600"
              : "text-gray-500"
            }`}>{daysMsg}</p>
          )}
        </div>
      </div>

      {/* Details + Action in two-column grid on larger screens */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">

        {/* Resource details — takes 2/3 width */}
        <div className="md:col-span-2 bg-white rounded-2xl shadow-sm p-6">
          <p className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-3">Resource Details</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
            <DetailRow label="Service Type"      value={serviceLabel(item.service_type)} />
            <DetailRow label="Runtime / Version" value={item.version} mono />
            <DetailRow label="Region"            value={item.region} mono />
            <DetailRow label="Account"            value={(() => {
              const info = accountMap[item.account_id];
              return info?.name ?? (item.account_id?.startsWith("conn-") ? "Unknown account" : item.account_id);
            })()} />
            {(() => {
              const rawId = accountMap[item.account_id]?.awsId ?? "";
              if (!rawId) return null;
              const masked = rawId.length === 12 ? `${rawId.slice(0,4)}…${rawId.slice(-4)}` : rawId;
              return <DetailRow label="AWS Account" value={masked} mono />;
            })()}
            <DetailRow label="EOL Date"          value={item.eol_date} />
            <DetailRow label="Status"            value={item.eol_status} />
            <DetailRow label="Last Scanned"      value={item.scanned_at?.slice(0, 19).replace("T", " ")} />
            <GenericMetadataPanel item={item} />
          </div>
          <div className="mt-3 pt-3 border-t border-gray-100">
            <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-0.5">Resource ID</p>
            <p className="text-xs font-mono text-gray-700 break-all">{item.resource_id}</p>
          </div>
        </div>

        {/* Recommended action — takes 1/3 width */}
        {hasRisk && guide ? (
          <div className={`rounded-2xl p-5 flex flex-col ${rc.actionBg}`}>
            <p className="text-xs font-bold uppercase tracking-widest text-gray-500 mb-2">Recommended Action</p>
            <p className="text-sm font-semibold text-gray-800 mb-2">{guideText}</p>

            {guide.steps && (
              <ol className="space-y-1.5 mb-4 flex-1">
                {guide.steps.map((step, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-gray-600">
                    <span className="shrink-0 w-4 h-4 rounded-full bg-gray-200 text-gray-600 flex items-center justify-center text-[10px] font-bold mt-0.5">
                      {i + 1}
                    </span>
                    {step}
                  </li>
                ))}
              </ol>
            )}

            <a href={guide.url} target="_blank" rel="noopener noreferrer"
              className="mt-auto inline-flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl text-sm font-bold text-white transition-opacity hover:opacity-90"
              style={{ backgroundColor: "#2A85D8" }}>
              <ExternalLink size={13} strokeWidth={2} />
              View Upgrade Guide
            </a>

          </div>
        ) : isExtSupport ? (
          <div className="rounded-2xl bg-blue-50 ring-1 ring-blue-100 p-5 flex flex-col">
            <p className="text-xs font-bold uppercase tracking-widest text-blue-600 mb-2">Extended Support</p>
            <p className="text-sm text-blue-900 font-semibold mb-2">
              {guideText || "This version is in AWS Extended Support."}
            </p>
            <p className="text-xs text-blue-700 leading-relaxed mb-4">
              Standard support has ended. AWS provides critical patches at an additional charge.
              Upgrade to avoid ongoing extended support costs.
            </p>
            {guide?.url && (
              <a href={guide.url} target="_blank" rel="noopener noreferrer"
                className="mt-auto inline-flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl text-sm font-bold text-white transition-opacity hover:opacity-90"
                style={{ backgroundColor: "#2A85D8" }}>
                <ExternalLink size={13} strokeWidth={2} />
                View Upgrade Guide
              </a>
            )}
          </div>
        ) : isUnknown ? (
          <div className="rounded-2xl bg-gray-50 ring-1 ring-gray-200 p-5">
            <p className="text-xs font-bold uppercase tracking-widest text-gray-500 mb-2">Unknown Status</p>
            <p className="text-sm text-gray-700 font-semibold">
              {serviceBase === "Lambda"
                ? "Runtime lifecycle could not be matched."
                : "Lifecycle data could not be determined."}
            </p>
            <p className="text-xs text-gray-500 mt-2 leading-relaxed">
              {serviceBase === "Lambda"
                ? "Verify the runtime manually. Custom or container runtimes are not tracked."
                : "Run a scan with current permissions or check if this resource type is supported."}
            </p>
          </div>
        ) : !hasRisk ? (
          <div className="rounded-2xl bg-green-50 ring-1 ring-green-100 p-5">
            <p className="text-xs font-bold uppercase tracking-widest text-green-600 mb-2">Status</p>
            <p className="text-sm text-green-800 font-semibold">This resource is currently supported.</p>
            <p className="text-xs text-green-700 mt-2 leading-relaxed opacity-80">
              No immediate action required. Monitor for upcoming EOL changes using the General EOL library.
            </p>
          </div>
        ) : null}
      </div>

      {/* Detection evidence */}
      <DetectionEvidence item={item} />

      {/* CK Upgrade Guide */}
      <CkGuideSection ckGuide={ckGuide} />

    </div>
  );
}
