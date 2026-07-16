import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  Shield, Check, Loader2, Plus, RefreshCw, Trash2, Settings2,
  ChevronRight, Copy, CheckCircle, AlertCircle, Clock, Cloud, Lock,
  AlertTriangle, ArrowLeft, Server, X,
} from "lucide-react";
import { API_BASE_URL, isDemoEnabled } from "../utils/config";
import { isDemoWorkspace } from "../utils/workspace";
import { copyToClipboard } from "../utils/clipboard";
import {
  addAccount, loadAccounts, saveAccounts, removeAccount, updateAccount,
  regionScopeLabel, fetchAccountsFromServer, saveAccountToServer,
  updateAccountOnServer, deleteAccountFromServer, startScanOnServer,
  getScanStatus, validateRoleOnServer, normalizeScanSummary,
} from "../utils/connectedAccounts";
import { getWorkspaceId, hasMemberSession, getMemberRole, workspaceHeaders } from "../utils/workspace";
import { MOCK_CONNECTED_ACCOUNTS } from "../mocks/mockAccountScanData";
import { AppSelect } from "../components/AppSelect";

// ── Constants ──────────────────────────────────────────────────────────────────

const AWS_REGIONS = [
  { value: "us-east-1",      label: "us-east-1 (N. Virginia)"    },
  { value: "us-east-2",      label: "us-east-2 (Ohio)"           },
  { value: "us-west-1",      label: "us-west-1 (N. California)"  },
  { value: "us-west-2",      label: "us-west-2 (Oregon)"         },
  { value: "ap-south-1",     label: "ap-south-1 (Mumbai)"        },
  { value: "ap-southeast-1", label: "ap-southeast-1 (Singapore)" },
  { value: "ap-southeast-2", label: "ap-southeast-2 (Sydney)"    },
  { value: "ap-northeast-1", label: "ap-northeast-1 (Tokyo)"     },
  { value: "eu-west-1",      label: "eu-west-1 (Ireland)"        },
  { value: "eu-west-2",      label: "eu-west-2 (London)"         },
  { value: "eu-central-1",   label: "eu-central-1 (Frankfurt)"   },
  { value: "ca-central-1",   label: "ca-central-1 (Canada)"      },
  { value: "sa-east-1",      label: "sa-east-1 (São Paulo)"      },
];

const DEMO_SCAN_RESULT = { total: 24, EOL: 7, EXPIRING_SOON: 7, EXTENDED_SUPPORT: 4, SUPPORTED: 6 };
const DEMO_RESCAN      = { total: 28, EOL: 8, EXPIRING_SOON: 8, EXTENDED_SUPPORT: 4, SUPPORTED: 7, UNKNOWN: 1 };

const SCAN_ERROR_MESSAGES = {
  ASSUME_ROLE_FAILED:    "Could not assume the IAM role. Verify the role ARN, external ID, and trust policy.",
  ACCESS_DENIED:         "Access denied. Check that the IAM role has the required permissions.",
  SERVICE_ACCESS_DENIED: "IAM role assumed, but one or more services were inaccessible. Check service-level IAM permissions.",
  SCAN_FAILED:           "Scan failed due to an unexpected error.",
};

// ── Utility ────────────────────────────────────────────────────────────────────

function _cryptoRandHex(bytes) {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return Array.from(buf, b => b.toString(16).padStart(2, "0")).join("");
}

function getOrCreateExternalId() {
  const wsId = getWorkspaceId() || "default";
  const key  = `eol_ext_id_${wsId}`;
  const stored = localStorage.getItem(key);
  if (stored) return stored;
  // 20 bytes = 160 bits entropy, formatted as eolm-<8hex>-<12hex> (base-16, 20 chars)
  const hex = _cryptoRandHex(10);
  const id  = `eolm-${hex.slice(0, 8)}-${hex.slice(8)}`.toUpperCase();
  localStorage.setItem(key, id);
  return id;
}

async function fetchWorkspaceExternalId() {
  const wsId = getWorkspaceId();
  if (!wsId || isDemoEnabled()) return null;
  try {
    const r = await fetch(`${API_BASE_URL}/workspaces/${wsId}/config`, {
      headers: workspaceHeaders(),
    });
    if (!r.ok) return null;
    const data = await r.json().catch(() => null);
    return data?.external_id || null;
  } catch { return null; }
}

async function persistExternalIdToServer(externalId) {
  const wsId = getWorkspaceId();
  if (!wsId || isDemoEnabled()) return;
  try {
    await fetch(`${API_BASE_URL}/workspaces/${wsId}/config`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...workspaceHeaders() },
      body: JSON.stringify({ external_id: externalId }),
    });
  } catch { /* non-fatal — server sync is best-effort */ }
}

async function pollScanCompletion(accountId, scanId) {
  const MAX_ATTEMPTS = 24; // ~2 min at 5s intervals
  for (let i = 0; i < MAX_ATTEMPTS; i++) {
    await new Promise(r => setTimeout(r, 5000));
    const scan = await getScanStatus(scanId);
    if (!scan) continue;
    if (scan.status === "SUCCESS") {
      const patch = {
        lastScanAt: new Date().toISOString(),
        lastScanStatus: "success",
        lastScanSummary: scan.summary,
        lastScanError: null,
        lastScanErrorCode: null,
        lastScanId: scanId,
      };
      updateAccount(accountId, patch);
      await updateAccountOnServer(accountId, patch);
      return true;
    }
    if (scan.status === "FAILED") {
      const patch = {
        lastScanAt: new Date().toISOString(),
        lastScanStatus: "failed",
        lastScanError: scan.error || "Scan failed",
        lastScanErrorCode: "SCAN_FAILED",
        lastScanId: scanId,
      };
      updateAccount(accountId, patch);
      await updateAccountOnServer(accountId, patch);
      return false;
    }
  }
  updateAccount(accountId, {
    lastScanStatus: "failed",
    lastScanError: "Scan timed out. Refresh to check the latest status.",
    lastScanErrorCode: "SCAN_TIMEOUT",
  });
  return false;
}

function getAccountRegions(account) {
  if (!account) return [];
  // New canonical format
  if (account.scanAllRegions === true) return [];
  if (Array.isArray(account.regions)) return [...account.regions].sort();
  // Legacy format
  if (account.regions === "single")   return account.singleRegion ? [account.singleRegion] : [];
  if (account.regions === "selected") return [...(account.selectedRegions || [])].sort();
  return [];
}

// ── Shared primitives ──────────────────────────────────────────────────────────

function CopyBtn({ value, label }) {
  const [copied, setCopied] = useState(false);
  async function copy(e) {
    e.stopPropagation();
    const ok = await copyToClipboard(value);
    if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2000); }
  }
  return (
    <button
      onClick={copy}
      aria-label={`Copy ${label ?? "value"}`}
      className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
        copied
          ? "bg-emerald-50 text-emerald-600"
          : "bg-gray-100 text-gray-500 hover:bg-gray-200 hover:text-gray-700"
      }`}
    >
      {copied
        ? <><Check size={11} strokeWidth={2.5} /> Copied</>
        : <><Copy size={11} strokeWidth={1.75} /> Copy</>}
    </button>
  );
}

function ScanStatusPill({ status, isScanning }) {
  if (isScanning) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold text-blue-700">
        <Loader2 size={11} strokeWidth={2} className="animate-spin" />
        Scanning…
      </span>
    );
  }
  const cfg = {
    success: { cls: "bg-emerald-100 text-emerald-700", Icon: CheckCircle, label: "Connected"   },
    failed:  { cls: "bg-red-100 text-red-700",         Icon: AlertCircle, label: "Scan Failed" },
  }[status] ?? { cls: "bg-gray-100 text-gray-500", Icon: Clock, label: "Never Scanned" };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.cls}`}>
      <cfg.Icon size={11} strokeWidth={2} />
      {cfg.label}
    </span>
  );
}

function CountPill({ value, label, color }) {
  const cls = {
    red:   "bg-red-50   text-red-700",
    amber: "bg-amber-50 text-amber-700",
    blue:  "bg-blue-50  text-blue-700",
    green: "bg-green-50 text-green-700",
    gray:  "bg-gray-100 text-gray-500",
  }[color] ?? "bg-gray-100 text-gray-500";
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-bold ${cls}`}>
      <span>{value}</span>
      <span className="font-normal opacity-75">{label}</span>
    </span>
  );
}

// ── Wizard-only primitives ─────────────────────────────────────────────────────

function SecurityNote() {
  return (
    <div className="bg-slate-50 rounded-xl p-4 text-sm text-slate-600 space-y-2 ring-1 ring-slate-100">
      <p className="font-semibold text-slate-700 mb-2 flex items-center gap-1.5">
        <Shield size={15} className="text-slate-500 shrink-0" strokeWidth={1.75} />
        Built with a security-first design
      </p>
      {[
        "We never ask for AWS access keys.",
        "Connections use a read-only IAM role — no write, delete, or modify permissions.",
        "Each connection uses an ExternalId for safer cross-account access.",
        "STS sessions are short-lived and expire automatically.",
        "No access to S3 objects, SSM parameters, Secrets Manager, or KMS.",
        "You can revoke access anytime by deleting the IAM role from your account.",
      ].map(t => (
        <div key={t} className="flex gap-2">
          <Check size={13} className="text-emerald-500 shrink-0 mt-0.5" strokeWidth={2.5} />
          <span>{t}</span>
        </div>
      ))}
    </div>
  );
}

function TemplateSection({ label, value, onDownload }) {
  const [copied, setCopied] = useState(false);
  const preRef = useRef(null);
  useEffect(() => { if (preRef.current) preRef.current.scrollTop = 0; }, [value]);
  async function copy() {
    const ok = await copyToClipboard(value);
    if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2000); }
  }
  return (
    <div className="space-y-2">
      {label && <p className="text-xs font-semibold text-gray-500">{label}</p>}
      <pre ref={preRef} className="bg-gray-900 text-green-400 text-xs rounded-lg p-4 overflow-x-auto overflow-y-auto font-mono leading-relaxed max-h-80 whitespace-pre">
        {value}
      </pre>
      <div className="flex gap-2">
        <button onClick={copy}
          className={`px-3 py-1.5 text-xs rounded-lg border font-medium transition-colors ${
            copied ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
          }`}>
          {copied ? "✓ Copied" : "Copy template"}
        </button>
        <button onClick={onDownload}
          className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 font-medium transition-colors">
          ↓ Download .yaml
        </button>
      </div>
    </div>
  );
}

function CopyBox({ label, value, copyLabel = "Copy" }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    const ok = await copyToClipboard(value);
    if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2000); }
  }
  return (
    <div className="relative">
      {label && <p className="text-xs text-gray-500 mb-1">{label}</p>}
      <div className="flex items-start gap-2">
        <pre className="flex-1 bg-gray-900 text-green-400 text-xs rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-all font-mono leading-relaxed">{value}</pre>
        <button onClick={copy}
          className={`shrink-0 mt-1 px-3 py-1.5 text-xs rounded-lg border font-medium transition-colors ${
            copied
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
          }`}>
          {copied ? "✓ Copied" : copyLabel}
        </button>
      </div>
    </div>
  );
}

// ── Step indicator ─────────────────────────────────────────────────────────────

const STEP_LABELS = ["ExternalId", "Deploy Role", "Role ARN", "Review", "Connect"];

function StepIndicator({ current, total }) {
  return (
    <div className="mb-7">
      <div className="flex items-center gap-1">
        {[...Array(total)].map((_, i) => (
          <React.Fragment key={i}>
            <div className={`w-7 h-7 rounded-full text-xs font-bold flex items-center justify-center transition-all shrink-0 ${
              i + 1 < current ? "bg-emerald-500 text-white" :
              i + 1 === current ? "bg-gray-900 text-white" :
              "bg-gray-200 text-gray-400"
            }`}>
              {i + 1 < current ? "✓" : i + 1}
            </div>
            {i < total - 1 && <div className={`flex-1 h-0.5 ${i + 1 < current ? "bg-emerald-400" : "bg-gray-200"}`} />}
          </React.Fragment>
        ))}
      </div>
      <div className="flex mt-1.5" style={{ gap: 0 }}>
        {[...Array(total)].map((_, i) => (
          <div key={i} className="flex-1 text-center" style={{ minWidth: 0 }}>
            <span className={`text-xs truncate block ${
              i + 1 === current ? "text-gray-700 font-semibold" :
              i + 1 < current ? "text-emerald-600" :
              "text-gray-400"
            }`}>
              {STEP_LABELS[i]}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Wizard ─────────────────────────────────────────────────────────────────────

function WizardView({ onComplete, onCancel }) {
  const [externalId, setExternalId] = useState(getOrCreateExternalId);
  const [step, setStep]  = useState(1);
  const [deployTab, setDeployTab] = useState("cfn");
  const [extIdCopied, setExtIdCopied] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [form, setForm] = useState({
    accountName: "", accountId: "", roleArn: "",
    regions: "all", singleRegion: "ap-south-1", selectedRegions: [],
  });
  const [validating, setValidating]  = useState(false);
  const [validResult, setValidResult] = useState(null);

  // Sync ExternalId with server on mount so it survives localStorage clears.
  // Server is source of truth; localStorage is a fast-load cache.
  useEffect(() => {
    (async () => {
      const serverExtId = await fetchWorkspaceExternalId();
      const wsId = getWorkspaceId() || "default";
      const lsKey = `eol_ext_id_${wsId}`;
      if (serverExtId) {
        localStorage.setItem(lsKey, serverExtId);
        setExternalId(serverExtId);
      } else {
        // Server doesn't have one yet — persist current local value
        const localId = localStorage.getItem(lsKey) || getOrCreateExternalId();
        await persistExternalIdToServer(localId);
        setExternalId(localId);
      }
    })();
  }, []); // eslint-disable-line

  async function copyExtId() {
    const ok = await copyToClipboard(externalId);
    if (ok) { setExtIdCopied(true); setTimeout(() => setExtIdCopied(false), 2000); }
  }

  const CF_TEMPLATE = `AWSTemplateFormatVersion: "2010-09-09"
Description: AWS EOL Monitor read-only role for account scanning.

Parameters:
  ExternalId:
    Type: String
    Description: Unique ExternalId generated by AWS EOL Monitor.
    Default: "${externalId}"

Resources:
  EOLMonitorReadOnlyRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: EOLMonitorReadOnly
      Description: Read-only role used by AWS EOL Monitor to scan service versions and EOL risk.
      MaxSessionDuration: 3600
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Sid: AllowEOLMonitorBackendAssumeRole
            Effect: Allow
            Principal:
              AWS: "arn:aws:iam::495234635788:role/EOLMonitorBackendEC2Role"
            Action: sts:AssumeRole
            Condition:
              StringEquals:
                sts:ExternalId: !Ref ExternalId
      Policies:
        - PolicyName: EOLMonitorReadOnlyPolicy
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Sid: ReadOnlyVersionDiscovery
                Effect: Allow
                Action:
                  - lambda:ListFunctions
                  - eks:ListClusters
                  - eks:DescribeCluster
                  - rds:DescribeDBInstances
                  - rds:DescribeDBClusters
                  - elasticache:DescribeCacheClusters
                  - elasticache:DescribeReplicationGroups
                  - ec2:DescribeRegions
                  - ec2:DescribeInstances
                  - ec2:DescribeImages
                  - ssm:DescribeInstanceInformation
                  - ssm:GetInventory
                  - codebuild:ListProjects
                  - codebuild:BatchGetProjects
                  - elasticbeanstalk:DescribeEnvironments
                  - elasticbeanstalk:DescribePlatformVersion
                  - elasticmapreduce:ListClusters
                  - elasticmapreduce:DescribeCluster
                  - kafka:ListClusters
                  - kafka:ListClustersV2
                  - kafka:DescribeCluster
                  - kafka:DescribeClusterV2
                  - opensearch:ListDomainNames
                  - opensearch:DescribeDomain
                  - opensearch:DescribeDomains
                  - es:ListDomainNames
                  - es:DescribeDomain
                  - es:DescribeDomains
                  - es:DescribeElasticsearchDomain
                  - es:DescribeElasticsearchDomains
                  - glue:ListJobs
                  - glue:GetJobs
                  - glue:GetJob
                  - cloudfront:ListFunctions
                  - cloudfront:DescribeFunction
                  - ecr:DescribeRepositories
                  - ecr:DescribeImages
                  - ecr:BatchGetImage
                  - docdb:DescribeDBClusters
                  - neptune:DescribeDBClusters
                  - sts:GetCallerIdentity
                Resource: "*"

Outputs:
  RoleArn:
    Description: Paste this Role ARN into AWS EOL Monitor.
    Value: !GetAtt EOLMonitorReadOnlyRole.Arn

  ExternalId:
    Description: ExternalId used for this connection.
    Value: !Ref ExternalId`;

  const CLI_CMD = `aws cloudformation deploy \\
  --template-file eol-monitor-readonly-role.yaml \\
  --stack-name aws-eol-monitor-readonly-role \\
  --parameter-overrides \\
      ExternalId=${externalId} \\
  --capabilities CAPABILITY_NAMED_IAM`;

  function downloadTemplate() {
    const blob = new Blob([CF_TEMPLATE], { type: "text/yaml" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url;
    a.download = "eol-monitor-readonly-role.yaml";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function validateRole() {
    setValidating(true);
    setValidResult(null);
    const result = await validateRoleOnServer({
      roleArn:      form.roleArn,
      externalId,
      awsAccountId: form.accountId,
      accountName:  form.accountName,
    });
    setValidResult(result.ok
      ? { ok: true,  msg: `Role validated. AWS account ${result.accountId} can be scanned with read-only access.` }
      : { ok: false, msg: result.error?.message || "Unable to assume role. Check trust policy, ExternalId, and Role ARN." }
    );
    setValidating(false);
  }

  const inputCls = "w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-300/50 focus:border-indigo-300 transition-colors";

  const steps = [
    { label: "Generate ExternalId"  },
    { label: "Deploy Role Template" },
    { label: "Enter Role ARN"       },
    { label: "Validate Access"      },
    { label: "View Dashboard"       },
  ];

  return (
    <div className="p-4 sm:p-6 max-w-3xl mx-auto">
      {/* Back to accounts (only when returning from list) */}
      {onCancel && (
        <button onClick={onCancel}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-400 hover:text-gray-700 transition-colors mb-5">
          <ArrowLeft size={14} strokeWidth={2} />
          Back to accounts
        </button>
      )}

      <div className="mb-7">
        <div className="mb-2">
          <p className="text-xs font-semibold text-indigo-500 uppercase tracking-widest">Single Account Scan</p>
        </div>
        <h1 className="text-3xl font-extrabold text-gray-900 mb-2">Connect one AWS account safely</h1>
        <p className="text-sm text-gray-500 leading-relaxed max-w-xl">
          Create a read-only IAM role in your AWS account, paste the Role ARN, and review EOL risk across all
          enabled regions. No access keys required.
        </p>
      </div>

      <StepIndicator current={step} total={steps.length} />

      {/* Step 1 — ExternalId */}
      {step === 1 && (
        <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-4">
          <div>
            <h2 className="font-bold text-gray-800 mb-1">Step 1 — Your Unique ExternalId</h2>
            <p className="text-sm text-gray-500">This ExternalId is unique to your workspace and stays the same across scans. Do not regenerate it — changing it breaks the IAM role trust policy until the CloudFormation stack is redeployed.</p>
          </div>
          <CopyBox label="ExternalId — save this before continuing" value={externalId} copyLabel="Copy ExternalId" />
          <div className="flex items-start gap-2 bg-amber-50 ring-1 ring-amber-100 rounded-lg px-3 py-2.5 text-xs text-amber-700">
            <span className="shrink-0 mt-px">⚠</span>
            <span>Save this ExternalId. You will need it when deploying the read-only IAM role template.</span>
          </div>
          <SecurityNote />
          <div className="flex justify-end">
            <button onClick={() => setStep(2)} className="px-5 py-2 bg-gray-900 text-white text-sm rounded-xl font-semibold hover:bg-gray-800 transition-colors">
              Next: Deploy Role Template →
            </button>
          </div>
        </div>
      )}

      {/* Step 2 — Deploy template */}
      {step === 2 && (
        <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-4">
          <div>
            <h2 className="font-bold text-gray-800 mb-1">Step 2 — Create the read-only IAM role</h2>
            <p className="text-sm text-gray-500">
              Deploy the template in the AWS account you want to scan.
              After the stack is created, copy <strong>RoleArn</strong> from CloudFormation Outputs.
            </p>
          </div>

          <div className="flex items-start gap-2 bg-blue-50 ring-1 ring-blue-100 rounded-lg px-3 py-2.5 text-xs text-blue-800">
            <span className="shrink-0 mt-px">ℹ</span>
            <span>
              The scanner backend role is already embedded in this template. Deploy this template in the AWS account you want to scan, then copy <strong>RoleArn</strong> from CloudFormation Outputs.
            </span>
          </div>

          <div className="bg-slate-50 ring-1 ring-slate-200 rounded-lg px-3 py-2.5">
            <p className="text-xs font-semibold text-slate-600 mb-1.5">ExternalId</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 font-mono text-xs text-slate-800 truncate">{externalId}</code>
              <button
                onClick={copyExtId}
                className={`shrink-0 text-xs px-2.5 py-1 rounded-lg border font-medium transition-colors ${
                  extIdCopied
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                    : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
                }`}
              >
                {extIdCopied ? "✓ Copied" : "Copy"}
              </button>
            </div>
            <p className="text-xs text-slate-400 mt-1">Already embedded in the template and CLI command.</p>
          </div>

          <div>
            <div className="flex border-b border-gray-200 mb-3">
              {[
                { key: "cfn", label: "CloudFormation Template" },
                { key: "cli", label: "AWS CLI"                 },
              ].map(t => (
                <button
                  key={t.key}
                  onClick={() => setDeployTab(t.key)}
                  className={`px-4 py-2 text-xs font-semibold border-b-2 -mb-px transition-colors ${
                    deployTab === t.key
                      ? "border-gray-900 text-gray-900"
                      : "border-transparent text-gray-400 hover:text-gray-600"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {deployTab === "cfn" && (
              <TemplateSection value={CF_TEMPLATE} onDownload={downloadTemplate} />
            )}

            {deployTab === "cli" && (
              <div className="space-y-2">
                <CopyBox value={CLI_CMD} copyLabel="Copy command" />
              </div>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex items-start gap-2 bg-slate-50 ring-1 ring-slate-100 rounded-lg px-3 py-2.5 text-xs text-slate-600">
              <span className="shrink-0">ℹ</span>
              <span>This template only creates a read-only IAM role. It does not install agents, modify resources, or access application data.</span>
            </div>
            <div className="flex items-start gap-2 bg-emerald-50 ring-1 ring-emerald-100 rounded-lg px-3 py-2.5 text-xs text-emerald-700">
              <span className="shrink-0">✓</span>
              <span>After the stack is created, open the <strong>Outputs</strong> tab in CloudFormation and copy the <strong>RoleArn</strong> value. Paste it in the next step.</span>
            </div>
          </div>

          <div className="flex justify-between pt-1">
            <button onClick={() => setStep(1)} className="text-sm text-gray-400 hover:text-gray-700 underline">← Back</button>
            <button onClick={() => setStep(3)} className="px-5 py-2 bg-gray-900 text-white text-sm rounded-xl font-semibold hover:bg-gray-800 transition-colors">
              Next: Enter Role ARN →
            </button>
          </div>
        </div>
      )}

      {/* Step 3 — Role ARN + inline validation */}
      {step === 3 && (() => {
        const hasSpaces       = form.roleArn.includes(" ");
        const arnValid        = !hasSpaces && /^arn:aws:iam::\d{12}:role\/.+$/.test(form.roleArn);
        const idValid         = /^\d{12}$/.test(form.accountId);
        const arnAccountMatch = !form.roleArn || !form.accountId || !idValid || !arnValid
          ? true : form.roleArn.includes(`:${form.accountId}:`);
        const regionValid     = form.regions === "all" || form.regions === "single" || (form.regions === "selected" && form.selectedRegions.length > 0);
        const canValidate     = form.accountName.trim() && idValid && arnValid && arnAccountMatch && regionValid;
        const canAdvance      = canValidate && validResult?.ok === true;
        const CHEVRON = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239CA3AF' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E")`;

        function toggleRegion(r) {
          setForm(f => ({
            ...f,
            selectedRegions: f.selectedRegions.includes(r)
              ? f.selectedRegions.filter(x => x !== r)
              : [...f.selectedRegions, r],
          }));
          setValidResult(null);
        }

        return (
          <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-5">
            <div>
              <h2 className="font-bold text-gray-800 mb-1">Step 3 — Add account details and Role ARN</h2>
              <p className="text-sm text-gray-500">Enter your AWS account details and the Role ARN from the previous step.</p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Account Name</label>
                <input type="text" placeholder="prod-account" value={form.accountName}
                  onChange={e => setForm(f => ({ ...f, accountName: e.target.value }))} className={inputCls} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">AWS Account ID</label>
                <input type="text" placeholder="123456789012" maxLength={12} value={form.accountId}
                  onChange={e => { setForm(f => ({ ...f, accountId: e.target.value.replace(/\D/g, "") })); setValidResult(null); }}
                  className={`${inputCls} ${form.accountId && !idValid ? "border-red-300 focus:ring-red-300/50" : ""}`} />
                {form.accountId && !idValid && (
                  <p className="text-xs text-red-500 mt-1">Must be exactly 12 digits.</p>
                )}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Role ARN</label>
              <p className="text-xs text-gray-400 mb-1.5">
                Paste the <strong>RoleArn</strong> value from CloudFormation Outputs.
              </p>
              <input type="text" placeholder="arn:aws:iam::123456789012:role/EOLMonitorReadOnly"
                value={form.roleArn}
                onChange={e => { setForm(f => ({ ...f, roleArn: e.target.value })); setValidResult(null); }}
                className={`${inputCls} ${form.roleArn && (!arnValid || hasSpaces) ? "border-red-300 focus:ring-red-300/50" : ""}`} />
              {form.roleArn && hasSpaces ? (
                <p className="text-xs text-red-500 mt-1">Role ARN cannot contain spaces. Copy the exact RoleArn from CloudFormation Outputs.</p>
              ) : form.roleArn && !arnValid ? (
                <p className="text-xs text-red-500 mt-1">Expected: arn:aws:iam::123456789012:role/RoleName</p>
              ) : form.roleArn && arnValid && !arnAccountMatch ? (
                <p className="text-xs text-red-500 mt-1">Account ID in Role ARN does not match the AWS Account ID above.</p>
              ) : (
                <p className="text-xs text-gray-400 mt-1">Expected format: arn:aws:iam::123456789012:role/EOLMonitorReadOnly</p>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Region Scope</label>
              <div className="flex gap-2 mb-3">
                {[
                  { value: "all",      label: "All regions"    },
                  { value: "single",   label: "Single region"  },
                  { value: "selected", label: "Select regions" },
                ].map(opt => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => { setForm(f => ({ ...f, regions: opt.value, selectedRegions: [] })); setValidResult(null); }}
                    className={`flex-1 text-xs font-semibold py-2 rounded-lg border transition-all ${
                      form.regions === opt.value
                        ? "bg-gray-900 text-white border-gray-900"
                        : "bg-white text-gray-500 border-gray-200 hover:border-gray-400 hover:text-gray-700"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>

              {form.regions === "all" && (
                <p className="text-xs text-gray-400 bg-gray-50 rounded-lg px-3 py-2">
                  Scans all enabled regions in the selected account.
                </p>
              )}

              {form.regions === "single" && (
                <AppSelect
                  value={form.singleRegion}
                  options={AWS_REGIONS}
                  onChange={val => setForm(f => ({ ...f, singleRegion: val }))}
                  size="lg"
                  fullWidth
                />
              )}

              {form.regions === "selected" && (
                <>
                  <div className="border border-gray-200 rounded-xl overflow-hidden max-h-44 overflow-y-auto">
                    <div className="grid grid-cols-2">
                      {AWS_REGIONS.map((r, i) => {
                        const checked = form.selectedRegions.includes(r.value);
                        return (
                          <label key={r.value}
                            className={`flex items-center gap-2.5 px-3 py-2.5 cursor-pointer transition-colors
                              ${checked ? "bg-indigo-50" : "hover:bg-gray-50"}
                              ${i % 2 === 0 && i < AWS_REGIONS.length - 1 ? "border-r border-gray-100" : ""}
                              ${i < AWS_REGIONS.length - 2 ? "border-b border-gray-100" : ""}
                            `}>
                            <input type="checkbox"
                              checked={checked}
                              onChange={() => toggleRegion(r.value)}
                              className="w-3.5 h-3.5 accent-indigo-600 cursor-pointer shrink-0" />
                            <div>
                              <p className={`text-xs font-mono font-medium leading-tight ${checked ? "text-indigo-700" : "text-gray-700"}`}>
                                {r.value}
                              </p>
                              <p className="text-xs text-gray-400 leading-tight">
                                {r.label.split("(")[1]?.replace(")", "") ?? ""}
                              </p>
                            </div>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                  <div className="flex items-center justify-between mt-1.5">
                    {form.selectedRegions.length === 0
                      ? <p className="text-xs text-amber-600">Select at least one region.</p>
                      : <p className="text-xs text-gray-500">{form.selectedRegions.length} region{form.selectedRegions.length !== 1 ? "s" : ""} selected</p>
                    }
                    {form.selectedRegions.length > 0 && (
                      <button type="button" onClick={() => setForm(f => ({ ...f, selectedRegions: [] }))}
                        className="text-xs text-gray-400 hover:text-gray-600">
                        Clear
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>

            {/* Inline validation */}
            <div className="space-y-3">
              {!canValidate && (
                <p className="text-xs text-gray-400">Fill all fields correctly, then validate role access before continuing.</p>
              )}
              {canValidate && !validResult && (
                <div className="flex items-center gap-3">
                  <button
                    onClick={validateRole}
                    disabled={validating}
                    className="px-4 py-2 rounded-lg text-sm font-semibold text-white transition-colors disabled:opacity-60"
                    style={{ backgroundColor: "#2A85D8" }}
                  >
                    {validating
                      ? <span className="inline-flex items-center gap-1.5"><Loader2 size={14} className="animate-spin" /> Validating…</span>
                      : "Validate Access"}
                  </button>
                  {!validating && (
                    <p className="text-xs text-gray-400">Click to verify AWS role access before continuing.</p>
                  )}
                </div>
              )}
              {validating && (
                <div className="flex items-center gap-2 text-sm text-blue-600">
                  <Loader2 size={15} className="animate-spin" />
                  Validating role access…
                </div>
              )}
              {validResult && (
                <div className={`rounded-lg px-4 py-3 text-sm flex items-start gap-2 ${
                  validResult.ok
                    ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                    : "bg-red-50 text-red-700 border border-red-200"
                }`}>
                  {validResult.ok ? <CheckCircle size={16} className="shrink-0 mt-0.5" /> : <AlertCircle size={16} className="shrink-0 mt-0.5" />}
                  <div>
                    <p className="font-semibold">{validResult.ok ? "Role validated" : "Validation failed"}</p>
                    <p className="text-xs mt-0.5 opacity-80">{validResult.msg}</p>
                    {!validResult.ok && (
                      <button
                        onClick={validateRole}
                        disabled={validating}
                        className="mt-2 text-xs underline font-medium disabled:opacity-50"
                      >
                        Try again
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center justify-between gap-4 pt-1">
              <button onClick={() => setStep(2)} className="text-sm text-gray-400 hover:text-gray-700 underline shrink-0">← Back</button>
              <button onClick={() => setStep(4)} disabled={!canAdvance}
                className="px-5 py-2 bg-gray-900 text-white text-sm rounded-xl font-semibold hover:bg-gray-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0">
                Next: Review →
              </button>
            </div>
          </div>
        );
      })()}

      {/* Step 4 — Review */}
      {step === 4 && (
        <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-5">
          <div>
            <h2 className="font-bold text-gray-800 mb-1">Step 4 — Review Connection</h2>
            <p className="text-sm text-gray-500">Confirm the details before connecting this account.</p>
          </div>

          {validResult?.ok ? (
            <div className="flex items-center gap-2 rounded-lg px-4 py-3 text-sm bg-emerald-50 text-emerald-700 border border-emerald-200">
              <CheckCircle size={16} className="shrink-0" />
              <span><strong>Role validated</strong> — read-only access to AWS account <code className="font-mono">{form.accountId}</code> confirmed.</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 rounded-lg px-4 py-3 text-sm bg-red-50 text-red-700 border border-red-200">
              <AlertCircle size={16} className="shrink-0" />
              <span>Role not validated. <button onClick={() => setStep(3)} className="underline font-medium">Go back and validate role access.</button></span>
            </div>
          )}

          <div className="bg-gray-50 rounded-xl border border-gray-100 divide-y divide-gray-100 text-sm">
            {[
              { label: "Account Name",   value: form.accountName || "—" },
              { label: "AWS Account ID", value: form.accountId   || "—", mono: true },
              { label: "Role ARN",       value: form.roleArn     || "—", mono: true },
              { label: "ExternalId",     value: externalId,              mono: true },
              { label: "Region Scope",   value: regionScopeLabel(form)               },
              { label: "Validation",     value: validResult?.ok ? "✓ Verified" : "✗ Not verified",
                valueClass: validResult?.ok ? "text-emerald-600 font-semibold" : "text-red-600 font-semibold" },
            ].map(row => (
              <div key={row.label} className="flex items-center justify-between px-4 py-2.5 gap-4">
                <span className="text-gray-500 shrink-0">{row.label}</span>
                <span className={`text-right break-all ${row.mono ? "font-mono text-xs" : ""} ${row.valueClass || "text-gray-800"}`}>
                  {row.value}
                </span>
              </div>
            ))}
          </div>

          <div className="flex justify-between">
            <button onClick={() => setStep(3)} className="text-sm text-gray-500 hover:text-gray-700 underline">← Back</button>
            <button onClick={() => setStep(5)} disabled={!validResult?.ok}
              className="px-5 py-2 bg-gray-900 text-white text-sm rounded-xl font-semibold hover:bg-gray-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
              Connect Account →
            </button>
          </div>
        </div>
      )}

      {/* Step 5 — Done */}
      {step === 5 && (
        <div className="bg-white rounded-xl border border-gray-100 p-6 text-center space-y-4">
          {scanning ? (
            <>
              <div className="w-16 h-16 rounded-full bg-blue-100 flex items-center justify-center mx-auto mb-2">
                <Loader2 size={32} className="text-blue-600 animate-spin" strokeWidth={2} />
              </div>
              <h2 className="font-bold text-gray-900 text-xl">Scanning account resources…</h2>
              <p className="text-gray-500 text-sm">
                Discovering Lambda, EKS, RDS, ElastiCache, MSK, OpenSearch, and other services.
              </p>
            </>
          ) : (
            <>
              <div className="w-16 h-16 rounded-full bg-emerald-100 flex items-center justify-center mx-auto mb-2">
                <Check size={32} className="text-emerald-600" strokeWidth={2.5} />
              </div>
              <h2 className="font-bold text-gray-900 text-xl">Account Connected!</h2>
              <p className="text-gray-500 text-sm">Your account is ready. Click below to start the first scan and view your EOL dashboard.</p>
              <button
                onClick={() => { setScanning(true); setTimeout(() => onComplete(form, externalId), 2000); }}
                className="px-8 py-3 rounded-xl text-sm font-bold text-white"
                style={{ backgroundColor: "#2A85D8" }}>
                Run First Scan & View Dashboard →
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── List view components ───────────────────────────────────────────────────────

function RegionChips({ account }) {
  const regions = getAccountRegions(account);
  if (regions.length === 0) {
    return <span className="text-xs font-semibold text-slate-700">All regions</span>;
  }
  const MAX_SHOW = 4;
  const shown = regions.slice(0, MAX_SHOW);
  const rest  = regions.length - MAX_SHOW;
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="text-xs font-semibold text-slate-700 shrink-0">
        {regions.length} region{regions.length !== 1 ? "s" : ""}
      </span>
      {shown.map(r => (
        <span key={r} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-600">{r}</span>
      ))}
      {rest > 0 && (
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-400 font-medium">+{rest} more</span>
      )}
    </div>
  );
}

function SummaryCards({ accounts }) {
  const agg = accounts.reduce((acc, a) => {
    const s = normalizeScanSummary(a.lastScanSummary) || {};
    acc.EOL              += s.EOL              || 0;
    acc.EXPIRING_SOON    += s.EXPIRING_SOON    || 0;
    acc.EXTENDED_SUPPORT += s.EXTENDED_SUPPORT || 0;
    acc.SUPPORTED        += s.SUPPORTED        || 0;
    acc.UNKNOWN          += s.UNKNOWN          || 0;
    return acc;
  }, { EOL: 0, EXPIRING_SOON: 0, EXTENDED_SUPPORT: 0, SUPPORTED: 0, UNKNOWN: 0 });

  const cards = [
    {
      key: "EOL", label: "EOL",
      iconBg: "bg-red-100", iconColor: "text-red-600",
      countColor: "text-red-600",
      icon: <AlertTriangle size={15} strokeWidth={2} />,
    },
    {
      key: "EXPIRING_SOON", label: "Expiring Soon",
      iconBg: "bg-amber-100", iconColor: "text-amber-600",
      countColor: "text-amber-600",
      icon: <Clock size={15} strokeWidth={2} />,
    },
    {
      key: "EXTENDED_SUPPORT", label: "Ext. Support",
      iconBg: "bg-indigo-100", iconColor: "text-indigo-600",
      countColor: "text-indigo-600",
      icon: <Shield size={15} strokeWidth={2} />,
    },
    {
      key: "SUPPORTED", label: "Supported",
      iconBg: "bg-emerald-100", iconColor: "text-emerald-600",
      countColor: "text-emerald-600",
      icon: <CheckCircle size={15} strokeWidth={2} />,
    },
    {
      key: "UNKNOWN", label: "Unknown",
      iconBg: "bg-gray-100", iconColor: "text-gray-400",
      countColor: "text-gray-500",
      icon: <AlertCircle size={15} strokeWidth={2} />,
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-8">
      {cards.map(c => (
        <div key={c.key} className="bg-white rounded-2xl border border-slate-100 shadow-sm px-5 py-5 flex items-center gap-3">
          <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${c.iconBg}`}>
            <span className={c.iconColor}>{c.icon}</span>
          </div>
          <div className="min-w-0">
            <p className={`text-2xl font-extrabold leading-none ${c.countColor}`}>{agg[c.key]}</p>
            <p className="text-xs text-slate-400 font-medium mt-1 truncate">{c.label}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function AccountScanCard({ account, isScanning, onViewResults, onRescan, onEditRegions, onDelete }) {
  const sum   = normalizeScanSummary(account.lastScanSummary);
  const total = sum ? (sum.total || 0) : 0;

  const lastScanLabel = account.lastScanAt
    ? new Date(account.lastScanAt).toLocaleString("en-GB", {
        day: "2-digit", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit",
        timeZone: "UTC",
      }) + " UTC"
    : "Never";

  const btnLabel = isScanning ? "Scanning…" : account.lastScanAt ? "Run Scan Again" : "Run First Scan";

  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between gap-6 px-6 py-6">
        <div className="flex items-start gap-3.5 min-w-0">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-emerald-100">
            <Cloud size={20} className="text-emerald-600" strokeWidth={1.75} />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2.5 mb-1">
              <h3 className="text-lg font-extrabold text-slate-900 leading-tight truncate">{account.accountName}</h3>
              <ScanStatusPill status={account.lastScanStatus} isScanning={isScanning} />
            </div>
            <p className="text-sm font-mono text-slate-400">{account.accountId}</p>
          </div>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Last scan</p>
          <p className="mt-1 text-sm font-semibold text-slate-700">
            {isScanning ? "Scanning…" : lastScanLabel}
          </p>
        </div>
      </div>

      {/* Connection details */}
      <div className="border-t border-slate-100 px-6 py-5 space-y-3.5">
        <div className="grid items-center gap-3" style={{ gridTemplateColumns: "7rem 1fr auto" }}>
          <span className="text-xs text-slate-400 font-medium shrink-0">Role ARN</span>
          <code className="text-xs font-mono font-semibold text-slate-700 truncate min-w-0">{account.roleArn}</code>
          <CopyBtn value={account.roleArn} label="Role ARN" />
        </div>
        <div className="grid items-center gap-3" style={{ gridTemplateColumns: "7rem 1fr auto" }}>
          <span className="text-xs text-slate-400 font-medium shrink-0">ExternalId</span>
          <code className="text-xs font-mono font-semibold text-slate-700 truncate min-w-0">{account.externalId}</code>
          <CopyBtn value={account.externalId} label="ExternalId" />
        </div>
        <div className="grid items-start gap-3" style={{ gridTemplateColumns: "7rem 1fr" }}>
          <span className="text-xs text-slate-400 font-medium mt-0.5 shrink-0">Regions</span>
          <RegionChips account={account} />
        </div>
      </div>

      {/* Scan summary */}
      <div className="border-t border-slate-100 px-6 py-4">
        {sum ? (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-slate-400 font-medium mr-1">Scan Summary</span>
            {(sum.EOL || 0) > 0 && <CountPill value={sum.EOL} label="EOL" color="red" />}
            {(sum.EXPIRING_SOON || 0) > 0 && <CountPill value={sum.EXPIRING_SOON} label="Expiring" color="amber" />}
            {(sum.EXTENDED_SUPPORT || 0) > 0 && <CountPill value={sum.EXTENDED_SUPPORT} label="Ext." color="blue" />}
            {(sum.SUPPORTED || 0) > 0 && <CountPill value={sum.SUPPORTED} label="Supported" color="green" />}
            {(sum.UNKNOWN || 0) > 0 && <CountPill value={sum.UNKNOWN} label="Unknown" color="gray" />}
            {(sum.NEEDS_INSPECTION || 0) > 0 && <CountPill value={sum.NEEDS_INSPECTION} label="Needs Inspection" color="gray" />}
            {(sum.LIFECYCLE_NOT_TRACKED || 0) > 0 && <CountPill value={sum.LIFECYCLE_NOT_TRACKED} label="Not Tracked" color="gray" />}
            {total === 0 && <span className="text-xs text-slate-400 italic">No resources found</span>}
            {total > 0 && <span className="text-xs text-slate-400 ml-1">({total} total)</span>}
          </div>
        ) : (
          <p className="text-xs text-slate-400 italic">No scan data yet · Run first scan to see results</p>
        )}
      </div>

      {/* Scan error */}
      {account.lastScanStatus === "failed" && (
        <div className="mx-6 mb-3 rounded-lg bg-red-50 ring-1 ring-red-200 px-3 py-2 text-xs text-red-700">
          <span className="font-semibold">Scan failed: </span>
          {SCAN_ERROR_MESSAGES[account.lastScanErrorCode] || account.lastScanError || "An unexpected error occurred."}
          {account.lastScanId && (
            <span className="ml-1.5 font-mono opacity-50">ID: {account.lastScanId}</span>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="border-t border-slate-100 flex items-center gap-2.5 px-6 py-5 flex-wrap">
        <button
          onClick={onViewResults}
          disabled={!sum || isScanning}
          className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-2 text-xs font-bold text-white transition-colors hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          View Results <ChevronRight size={13} strokeWidth={2.5} />
        </button>
        <button
          onClick={onRescan}
          disabled={isScanning}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <RefreshCw size={12} strokeWidth={2} className={isScanning ? "animate-spin" : ""} />
          {btnLabel}
        </button>
        <button
          onClick={onEditRegions}
          disabled={isScanning}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Settings2 size={12} strokeWidth={2} />
          Edit Regions
        </button>
        <button
          onClick={onDelete}
          disabled={isScanning || isDemoWorkspace()}
          title={isDemoWorkspace() ? "Not available in demo workspace" : undefined}
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-red-100 px-3.5 py-2 text-xs font-semibold text-red-500 transition-colors hover:bg-red-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Trash2 size={12} strokeWidth={2} />
          Delete Account
        </button>
      </div>
    </div>
  );
}

function DeleteModal({ account, onConfirm, onCancel }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md space-y-4 rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-red-100">
            <Trash2 size={18} className="text-red-600" strokeWidth={2} />
          </div>
          <div className="min-w-0">
            <h3 className="font-bold text-slate-900">Delete this account connection?</h3>
            <p className="text-sm text-slate-500 truncate">
              {account.accountName} · {account.accountId}
            </p>
          </div>
        </div>
        <div className="rounded-xl bg-amber-50 px-4 py-3 text-xs text-amber-800 ring-1 ring-amber-100 space-y-1.5">
          <p className="font-semibold">This will:</p>
          <ul className="list-inside list-disc space-y-0.5 text-amber-700">
            <li>Remove the saved connection and scan history from AWS EOL Monitor.</li>
            <li>Not delete the IAM role from your AWS account.</li>
          </ul>
        </div>
        <p className="text-xs text-slate-500">
          To fully revoke access, delete the CloudFormation stack or IAM role from your AWS account.
        </p>
        <div className="flex justify-end gap-2 pt-1">
          <button
            onClick={onCancel}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 transition-colors"
          >
            Delete Connection
          </button>
        </div>
      </div>
    </div>
  );
}

function EditRegionsModal({ account, onSave, onCancel }) {
  const initMode = account.scanAllRegions === true ? "all"
    : Array.isArray(account.regions)
      ? (account.regions.length === 0 ? "all" : account.regions.length === 1 ? "single" : "selected")
      : (account.regions || "all");
  const initSingle = Array.isArray(account.regions) && account.regions.length === 1
    ? account.regions[0]
    : (account.singleRegion || "us-east-1");
  const initSelected = Array.isArray(account.regions) && account.regions.length > 1
    ? account.regions
    : (account.selectedRegions || []);

  const [regionMode, setRegionMode] = useState(initMode);
  const [single, setSingle]         = useState(initSingle);
  const [selected, setSelected]     = useState(initSelected);
  const [saving, setSaving]         = useState(false);

  function toggle(r) {
    setSelected(prev => prev.includes(r) ? prev.filter(x => x !== r) : [...prev, r]);
  }

  async function handleSave() {
    if (!canSave || saving) return;
    setSaving(true);
    const patch = regionMode === "all"
      ? { regions: [], scanAllRegions: true }
      : regionMode === "single"
      ? { regions: [single].filter(Boolean), scanAllRegions: false }
      : { regions: selected, scanAllRegions: false };
    try {
      await Promise.resolve(onSave(patch));
    } finally {
      setSaving(false);
    }
  }

  const regionName = r => r.label.split("(")[1]?.replace(")", "") ?? r.label;
  const selectedCount = regionMode === "all" ? AWS_REGIONS.length : regionMode === "single" ? (single ? 1 : 0) : selected.length;
  const canClear = regionMode !== "all" && selectedCount > 0;
  const canSave = regionMode === "all" || (regionMode === "single" ? Boolean(single) : selected.length > 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="flex max-h-[85vh] w-full max-w-xl flex-col rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 px-6 pb-4 pt-6">
          <div>
            <h3 className="text-lg font-extrabold tracking-tight text-slate-950">Edit Region Scope</h3>
            <p className="mt-1 text-sm font-medium text-slate-500">{account.accountName} · {account.accountId}</p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Close region scope modal"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-300"
          >
            <X size={18} strokeWidth={2.25} />
          </button>
        </div>

        <div className="mx-6 grid grid-cols-3 gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1">
          {[
            { v: "all",      label: "All regions"    },
            { v: "single",   label: "Single region"  },
            { v: "selected", label: "Select regions" },
          ].map(o => (
            <button key={o.v}
              type="button"
              onClick={() => { setRegionMode(o.v); setSelected([]); }}
              className={`h-11 rounded-lg px-2 text-sm font-bold transition-all focus:outline-none focus:ring-2 focus:ring-indigo-300 ${
                regionMode === o.v
                  ? "bg-slate-950 text-white shadow-sm"
                  : "bg-white text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              }`}>
              {o.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {regionMode === "all" && (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-600">
              All enabled AWS regions will be scanned. This may take longer in large accounts.
            </div>
          )}

          {regionMode === "single" && (
            <div className="space-y-3">
              <p className="text-xs font-medium text-slate-500">Only one region will be scanned.</p>
              <div className="max-h-64 space-y-2 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-2">
                {AWS_REGIONS.map(r => {
                  const checked = single === r.value;
                  return (
                    <button
                      key={r.value}
                      type="button"
                      onClick={() => setSingle(r.value)}
                      className={`flex w-full items-center gap-3 rounded-xl border px-3 py-3 text-left transition focus:outline-none focus:ring-2 focus:ring-indigo-300 ${
                        checked
                          ? "border-indigo-200 bg-indigo-50"
                          : "border-slate-200 bg-white hover:bg-slate-50"
                      }`}
                    >
                      <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                        checked ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-300 bg-white"
                      }`}>
                        {checked && <Check size={11} strokeWidth={3} />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className={`block text-sm font-semibold leading-tight ${checked ? "text-indigo-800" : "text-slate-900"}`}>
                          {r.value}
                        </span>
                        <span className="mt-0.5 block text-xs text-slate-500">{regionName(r)}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {regionMode === "selected" && (
            <div className="max-h-72 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-2">
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {AWS_REGIONS.map(r => {
                  const checked = selected.includes(r.value);
                  return (
                    <button key={r.value}
                      type="button"
                      onClick={() => toggle(r.value)}
                      className={`flex w-full items-start gap-3 rounded-xl border px-3 py-3 text-left transition focus:outline-none focus:ring-2 focus:ring-indigo-300 ${
                        checked ? "border-indigo-200 bg-indigo-50" : "border-slate-200 bg-white hover:bg-slate-50"
                      }`}>
                      <input type="checkbox" checked={checked} readOnly
                        className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer accent-indigo-600" />
                      <span className="min-w-0">
                        <span className={`block text-sm font-semibold leading-tight ${checked ? "text-indigo-800" : "text-slate-900"}`}>
                          {r.value}
                        </span>
                        <span className="mt-0.5 block text-xs text-slate-500">{regionName(r)}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-slate-100 px-6 py-3">
          <p className={`text-sm font-medium ${canSave ? "text-slate-600" : "text-amber-600"}`}>
            {canSave
              ? `${selectedCount} region${selectedCount !== 1 ? "s" : ""} selected`
              : regionMode === "single" ? "Select one region." : "Select at least one region."}
          </p>
          {canClear && (
            <button
              type="button"
              onClick={() => regionMode === "single" ? setSingle("") : setSelected([])}
              className="text-sm font-semibold text-slate-500 transition-colors hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-300"
            >
              Clear
            </button>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4">
          <button type="button" onClick={onCancel}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-indigo-300">
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!canSave || saving}
            className="rounded-lg bg-slate-950 px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-50">
            {saving ? "Saving..." : "Save Regions"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AddMoreCallout({ onAdd }) {
  return (
    <div className="mt-6 rounded-2xl border border-dashed border-slate-200 bg-white px-8 py-7 flex items-center gap-6">
      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-indigo-50">
        <Cloud size={22} className="text-indigo-500" strokeWidth={1.75} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-bold text-slate-800">Add more AWS accounts</p>
        <p className="text-xs text-slate-500 mt-0.5">
          Connect additional AWS accounts to get a unified EOL risk view across your environment.
        </p>
      </div>
      <button
        onClick={onAdd}
        className="shrink-0 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-indigo-700 transition-colors"
      >
        <Plus size={15} strokeWidth={2.5} />
        Add Another Account
      </button>
    </div>
  );
}

function AccountsSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-8">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-20 rounded-2xl bg-slate-100" />
        ))}
      </div>
      <div className="h-6 w-48 rounded-lg bg-slate-100 mb-4" />
      <div className="h-64 rounded-2xl bg-slate-100" />
    </div>
  );
}

function EmptyState({ onAdd }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center shadow-sm">
      <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-slate-100">
        <Server size={24} className="text-slate-400" strokeWidth={1.5} />
      </div>
      <h3 className="text-base font-bold text-slate-900 mb-1">No AWS accounts connected yet</h3>
      <p className="text-sm text-slate-500 max-w-xs mx-auto mb-6">
        Connect an AWS account to scan for EOL risks across your resources.
      </p>
      {onAdd ? (
        <button
          onClick={onAdd}
          className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-slate-700 transition-colors"
        >
          <Plus size={15} strokeWidth={2.5} />
          Connect AWS Account
        </button>
      ) : (
        <p className="text-xs text-slate-400">Ask your workspace admin to connect an AWS account.</p>
      )}
    </div>
  );
}

// ── Page root ──────────────────────────────────────────────────────────────────

export default function AccountScanPage() {
  const navigate = useNavigate();
  const _memberSession = hasMemberSession();
  const canAdmin = !_memberSession || getMemberRole() === "ADMIN";
  const [pageMode, setPageMode]         = useState("list");
  // Sync init from localStorage so the list is never empty on the first paint
  const [accounts, setAccounts]         = useState(() => {
    const list = loadAccounts();
    return !list.length && isDemoEnabled() ? MOCK_CONNECTED_ACCOUNTS : list;
  });
  const [bootstrapping, setBootstrapping] = useState(true);
  const [scanningIds, setScanningIds]   = useState(new Set());
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [editTarget, setEditTarget]     = useState(null);
  const [toast, setToast]               = useState(null);

  function refreshAccounts() { setAccounts(loadAccounts()); }

  useEffect(() => {
    async function init() {
      const serverList = await fetchAccountsFromServer();
      if (serverList !== null) {
        saveAccounts(serverList);
        setAccounts(serverList);
      } else {
        let list = loadAccounts();
        if (list.length === 0 && isDemoEnabled()) {
          saveAccounts(MOCK_CONNECTED_ACCOUNTS);
          list = MOCK_CONNECTED_ACCOUNTS;
        }
        setAccounts(list);
      }
      setBootstrapping(false);
    }
    init();
  }, []);

  if (!canAdmin) {
    return (
      <div className="px-4 sm:px-6 py-6 sm:py-8 max-w-4xl mx-auto">
        <div className="rounded-2xl border border-slate-200 bg-white px-4 sm:px-8 py-12 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-amber-50">
            <Lock size={22} className="text-amber-600" strokeWidth={1.75} />
          </div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-amber-600 mb-2">Admin only</p>
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">Account Scan is restricted</h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-500 max-w-xl mx-auto">
            VIEWER members can review connected accounts and scan results, but only workspace admins can connect accounts or run scans.
          </p>
          <button
            type="button"
            onClick={() => navigate("/connected-accounts")}
            className="mt-6 inline-flex items-center gap-2 rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-slate-700 transition-colors"
          >
            View Connected Accounts
            <ChevronRight size={14} strokeWidth={2.5} />
          </button>
        </div>
      </div>
    );
  }

  async function handleComplete(form, externalId) {
    const regionPayload = form.regions === "all"
      ? { regions: [], scanAllRegions: true }
      : form.regions === "single"
      ? { regions: [form.singleRegion].filter(Boolean), scanAllRegions: false }
      : { regions: form.selectedRegions, scanAllRegions: false };

    const account = addAccount({
      accountId:   form.accountId,
      accountName: form.accountName,
      roleArn:     form.roleArn,
      externalId:  externalId,
      ...regionPayload,
    });

    let finalAccount = account;
    if (isDemoEnabled()) {
      const patch = {
        lastScanAt:      new Date().toISOString(),
        lastScanStatus:  "success",
        lastScanSummary: DEMO_SCAN_RESULT,
      };
      updateAccount(account.id, patch);
      finalAccount = { ...account, ...patch };
    }

    saveAccountToServer(finalAccount);
    setAccounts(loadAccounts());
    setPageMode("list");
  }

  async function handleRescan(account) {
    setScanningIds(prev => new Set([...prev, account.id]));
    if (isDemoEnabled()) {
      setTimeout(() => {
        const patch = { lastScanAt: new Date().toISOString(), lastScanStatus: "success", lastScanSummary: DEMO_RESCAN };
        updateAccountOnServer(account.id, patch);
        updateAccount(account.id, patch);
        setScanningIds(prev => { const s = new Set(prev); s.delete(account.id); return s; });
        refreshAccounts();
      }, 2000);
      return;
    }
    const result = await startScanOnServer(account.id);
    if (!result) {
      // Network error — leave account state unchanged
    } else if (result.errorCode === "SCAN_IN_PROGRESS") {
      // Another scan is already running — don't update account status, just inform user
      setScanningIds(prev => { const s = new Set(prev); s.delete(account.id); return s; });
      setToast({ type: "info", msg: "A scan is already running for this account. Please wait for it to complete." });
      refreshAccounts();
      return;
    } else if (result.error) {
      const patch = {
        lastScanAt: new Date().toISOString(),
        lastScanStatus: "failed",
        lastScanError: result.error,
        lastScanErrorCode: result.errorCode,
      };
      updateAccount(account.id, patch);
      await updateAccountOnServer(account.id, patch);
    } else if (result.status === "SUCCESS") {
      const patch = {
        lastScanAt: new Date().toISOString(),
        lastScanStatus: "success",
        lastScanSummary: normalizeScanSummary(result.summary) ?? {},
        lastScanError: null,
        lastScanErrorCode: null,
        lastScanId: result.scanId,
      };
      updateAccount(account.id, patch);
      await updateAccountOnServer(account.id, patch);
    } else if (result.scanId) {
      // Async or in-progress scan — poll until complete
      await pollScanCompletion(account.id, result.scanId);
    }
    setScanningIds(prev => { const s = new Set(prev); s.delete(account.id); return s; });
    refreshAccounts();
  }

  async function handleDelete(id) {
    await deleteAccountFromServer(id);
    removeAccount(id);
    setDeleteTarget(null);
    refreshAccounts();
  }

  async function handleEditSave(account, patch) {
    await updateAccountOnServer(account.id, patch);
    updateAccount(account.id, patch);
    setEditTarget(null);
    refreshAccounts();
  }

  // ── Wizard mode ──────────────────────────────────────────────────────────────
  if (pageMode === "wizard") {
    if (!canAdmin) {
      // Non-ADMIN members cannot add accounts — bounce back to list
      setPageMode("list");
      return null;
    }
    return (
      <WizardView
        onComplete={handleComplete}
        onCancel={accounts.length > 0 ? () => setPageMode("list") : undefined}
      />
    );
  }

  // ── List mode ────────────────────────────────────────────────────────────────
  return (
    <div className="px-4 sm:px-6 py-6 sm:py-8 max-w-7xl mx-auto">
      {/* Page header */}
      <div className="flex items-start justify-between gap-6 mb-8">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-indigo-500 mb-2">
            Single Account Scan
          </p>
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Account Scan</h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-500 max-w-lg">
            Connect and manage AWS accounts, view EOL risk, and trigger scans across your infrastructure.
          </p>
        </div>
        {!bootstrapping && accounts.length > 0 && canAdmin && (
          <button
            onClick={() => setPageMode("wizard")}
            className="shrink-0 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-indigo-700 transition-colors"
          >
            <Plus size={15} strokeWidth={2.5} />
            Add Another Account
          </button>
        )}
      </div>

      {/* Summary cards (only when accounts are present) */}
      {accounts.length > 0 && <SummaryCards accounts={accounts} />}

      {/* Accounts section header */}
      {accounts.length > 0 && (
        <div className="mb-4">
          <h2 className="text-base font-bold text-slate-900">
            Connected AWS Accounts
            <span className="ml-2 text-sm font-semibold text-slate-400">({accounts.length})</span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Manage connections, run scans, and view results for each account.
            {isDemoEnabled() && <span className="ml-2">· Demo Mode</span>}
          </p>
        </div>
      )}

      {/* Empty state or account cards */}
      {bootstrapping && accounts.length === 0 ? (
        <AccountsSkeleton />
      ) : accounts.length === 0 ? (
        <EmptyState onAdd={canAdmin ? () => setPageMode("wizard") : null} />
      ) : (
        <>
          <div className="space-y-4">
            {accounts.map(account => (
              <AccountScanCard
                key={account.id}
                account={account}
                isScanning={scanningIds.has(account.id)}
                onViewResults={() => navigate(`/account-results/${account.id}`)}
                onRescan={() => handleRescan(account)}
                onEditRegions={() => setEditTarget(account)}
                onDelete={() => setDeleteTarget(account)}
              />
            ))}
          </div>
          {canAdmin && <AddMoreCallout onAdd={() => setPageMode("wizard")} />}
        </>
      )}

      {/* Security note */}
      <div className="mt-8 flex items-center gap-2 text-xs text-slate-500">
        <Lock size={13} strokeWidth={1.75} className="shrink-0" />
        <span>We use read-only access and never ask for AWS access keys. You can revoke access anytime by deleting the IAM role from your AWS account.</span>
      </div>

      {/* Modals */}
      {deleteTarget && (
        <DeleteModal
          account={deleteTarget}
          onConfirm={() => handleDelete(deleteTarget.id)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {editTarget && (
        <EditRegionsModal
          account={editTarget}
          onSave={patch => handleEditSave(editTarget, patch)}
          onCancel={() => setEditTarget(null)}
        />
      )}

      {toast && (
        <div className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg text-sm font-medium ring-1 ${
          toast.type === "success"
            ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
            : toast.type === "info"
            ? "bg-blue-50 text-blue-800 ring-blue-200"
            : "bg-red-50 text-red-800 ring-red-200"
        }`}>
          <span>{toast.msg}</span>
          <button onClick={() => setToast(null)} className="ml-1 opacity-60 hover:opacity-100 text-base leading-none">×</button>
        </div>
      )}
    </div>
  );
}
