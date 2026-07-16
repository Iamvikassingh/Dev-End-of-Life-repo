import React, { useMemo, useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Shield, Check, RefreshCw, Play, AlertTriangle, Loader2, CheckCircle2, XCircle, Trash2, Unplug, ScanLine, BellOff, FileText, ShieldAlert, ChevronUp, ChevronDown, Globe2, X, ArrowRight, Info } from "lucide-react";
import { StatusBadge } from "../components/StatusBadge";
import { serviceLabel } from "../utils/classify";
import { copyToClipboard } from "../utils/clipboard";
import { API_BASE_URL } from "../utils/config";
import { getWorkspaceId, workspaceHeaders } from "../utils/workspace";

// ── Shared primitives ─────────────────────────────────────────────────────────

function TemplateSection({ label, value, filename }) {
  const [copied, setCopied] = useState(false);
  async function copy() { const ok = await copyToClipboard(value); if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2000); } }
  function download() {
    const blob = new Blob([value], { type: "text/yaml" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
  }
  return (
    <div className="space-y-2">
      {label && <p className="text-xs font-semibold text-gray-500">{label}</p>}
      <pre className="bg-gray-900 text-green-400 text-xs rounded-lg p-4 overflow-x-auto overflow-y-auto font-mono leading-relaxed max-h-56 whitespace-pre">
        {value}
      </pre>
      <div className="flex gap-2">
        <button onClick={download} className="px-3 py-1.5 text-xs rounded-lg bg-gray-900 text-white font-medium hover:bg-gray-800 transition-colors">
          ↓ Download .yaml
        </button>
        <button onClick={copy} className={`px-3 py-1.5 text-xs rounded-lg border font-medium transition-colors ${
          copied ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
        }`}>
          {copied ? "✓ Copied" : "Copy template"}
        </button>
      </div>
    </div>
  );
}

function CopyBox({ label, value, copyLabel = "Copy command" }) {
  const [copied, setCopied] = useState(false);
  async function copy() { const ok = await copyToClipboard(value); if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2000); } }
  return (
    <div>
      {label && <p className="text-xs font-semibold text-gray-500 mb-1">{label}</p>}
      <div className="flex items-start gap-2">
        <pre className="flex-1 bg-gray-900 text-green-400 text-xs rounded-lg p-3 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">{value}</pre>
        <button onClick={copy} className={`shrink-0 mt-1 px-3 py-1.5 text-xs rounded-lg border font-medium transition-colors ${
          copied ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
        }`}>
          {copied ? "✓ Copied" : copyLabel}
        </button>
      </div>
    </div>
  );
}

function CollapsibleCli({ label, value }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button onClick={() => setOpen(o => !o)}
        className="text-xs text-indigo-600 font-medium underline underline-offset-2 hover:text-indigo-800 transition-colors">
        {open ? "Hide AWS CLI command" : "Show AWS CLI command"}
      </button>
      {open && <div className="mt-2"><CopyBox label={label} value={value} /></div>}
    </div>
  );
}

const ORG_STEP_LABELS = ["Admin Account", "ExternalId", "Org Role", "StackSet", "Details", "Review"];

function StepIndicator({ current, total }) {
  return (
    <div className="mb-7">
      <div className="flex items-center gap-1">
        {[...Array(total)].map((_, i) => (
          <React.Fragment key={i}>
            <div className={`w-7 h-7 rounded-full text-xs font-bold flex items-center justify-center transition-all shrink-0 ${
              i+1 < current ? "bg-emerald-500 text-white" : i+1 === current ? "bg-gray-900 text-white" : "bg-gray-200 text-gray-400"
            }`}>
              {i+1 < current ? "✓" : i+1}
            </div>
            {i < total-1 && <div className={`flex-1 h-0.5 ${i+1 < current ? "bg-emerald-400" : "bg-gray-200"}`} />}
          </React.Fragment>
        ))}
      </div>
      <div className="flex mt-1.5" style={{ gap: 0 }}>
        {[...Array(total)].map((_, i) => (
          <div key={i} className="flex-1 text-center" style={{ minWidth: 0 }}>
            <span className={`text-xs truncate block ${
              i+1 === current ? "text-gray-700 font-semibold" :
              i+1 < current  ? "text-emerald-600" : "text-gray-400"
            }`}>
              {ORG_STEP_LABELS[i]}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SecurityNote() {
  return (
    <div className="bg-slate-50 rounded-xl p-4 text-sm text-slate-600 space-y-2 ring-1 ring-slate-100">
      <p className="font-semibold text-slate-700 mb-2 flex items-center gap-1.5">
        <Shield size={15} className="text-slate-500 shrink-0" strokeWidth={1.75} />
        Built with a security-first design
      </p>
      {[
        "Organizations read-only API access only — list accounts, describe OUs.",
        "Member accounts use separate read-only roles — no single role has org-wide write access.",
        "Each member role uses an ExternalId for safer cross-account access.",
        "STS sessions are short-lived and expire automatically.",
        "No access to S3 objects, SSM parameters, Secrets Manager, or KMS.",
        "Supports account and OU allowlist — scan only what you specify.",
        "Revoke access anytime by deleting roles or disabling the StackSet.",
      ].map(t => (
        <div key={t} className="flex gap-2">
          <Check size={13} className="text-emerald-500 shrink-0 mt-0.5" strokeWidth={2.5} />
          <span>{t}</span>
        </div>
      ))}
    </div>
  );
}

// ── Risk bar ──────────────────────────────────────────────────────────────────

function RiskBar({ totals }) {
  const total = (totals?.EOL ?? 0) + (totals?.EXPIRING_SOON ?? 0) + (totals?.EXTENDED_SUPPORT ?? 0) + (totals?.SUPPORTED ?? 0);
  if (total === 0) return <span className="text-xs text-gray-300">—</span>;
  const segments = [
    { key:"EOL",              color:"#922B21" },
    { key:"EXPIRING_SOON",    color:"#B7770D" },
    { key:"EXTENDED_SUPPORT", color:"#1A6EBD" },
    { key:"SUPPORTED",        color:"#0D6E56" },
  ];
  return (
    <div className="flex h-2 rounded-full overflow-hidden w-full min-w-[80px]">
      {segments.filter(s => (totals[s.key] ?? 0) > 0).map(s => (
        <div key={s.key} style={{ width:`${((totals[s.key]??0)/total)*100}%`, backgroundColor:s.color }} />
      ))}
    </div>
  );
}

// ── API helpers ───────────────────────────────────────────────────────────────

function orgApi(path, opts = {}) {
  const wsId = getWorkspaceId();
  return fetch(`${API_BASE_URL}/workspaces/${wsId}${path}`, {
    headers: { "Content-Type": "application/json", ...workspaceHeaders() },
    ...opts,
  }).then(async r => {
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(data?.error?.message || "Request failed"), {
      code: data?.error?.code,
      status: r.status,
      data,
    });
    return data;
  });
}

// ── Wizard ────────────────────────────────────────────────────────────────────

const inputCls = "w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-300/50 focus:border-indigo-300 transition-colors";

const ADMIN_OPTIONS = [
  { value: "delegated",  title: "Delegated Admin Account", badge: "Recommended", desc: "Recommended for separation of duties. Use a member account delegated for AWS Organizations access." },
  { value: "management", title: "Management Account",      badge: "Advanced",    desc: "Use this if you want to scan directly from the AWS Organizations management account." },
];

const SCANNER_ROLE_ARN = "arn:aws:iam::495234635788:role/EOLMonitorBackendEC2Role";

function OrgWizard({ externalId, onConnected }) {
  const [step, setStep]           = useState(1);
  const [adminType, setAdminType] = useState("delegated");
  const [form, setForm]           = useState({ name: "AWS Organization", mgmtAccountId: "", orgRoleArn: "", regions: "us-east-1" });
  const [loading, setLoading]     = useState(false);
  const [result, setResult]       = useState(null); // { ok, msg, conn, accounts }

  const ORG_ROLE_TEMPLATE = `AWSTemplateFormatVersion: "2010-09-09"
Description: AWS EOL Monitor org management role for Organizations read access.

Parameters:
  ScannerRoleArn:
    Type: String
    Default: "${SCANNER_ROLE_ARN}"
    Description: IAM role ARN used by the AWS EOL Monitor backend scanner.
    AllowedPattern: "^arn:aws:iam::[0-9]{12}:role/.+$"

  ExternalId:
    Type: String
    Description: Unique ExternalId generated by AWS EOL Monitor.
    Default: "${externalId}"

Resources:
  EOLMonitorOrgRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: EOLMonitorOrgReadOnly
      MaxSessionDuration: 3600
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal:
              AWS: !Ref ScannerRoleArn
            Action: "sts:AssumeRole"
            Condition:
              StringEquals:
                sts:ExternalId: !Ref ExternalId
      Policies:
        - PolicyName: OrgReadOnly
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action:
                  - organizations:ListAccounts
                  - organizations:ListAccountsForParent
                  - organizations:ListOrganizationalUnitsForParent
                  - organizations:ListRoots
                  - organizations:DescribeOrganization
                  - organizations:DescribeOrganizationalUnit
                Resource: "*"

Outputs:
  RoleArn:
    Description: Paste this Role ARN into AWS EOL Monitor.
    Value: !GetAtt EOLMonitorOrgRole.Arn`;

  const ORG_CLI_CMD = `aws cloudformation deploy \\
  --template-file eol-monitor-org-role.yaml \\
  --stack-name aws-eol-monitor-org-role \\
  --parameter-overrides \\
      ScannerRoleArn=${SCANNER_ROLE_ARN} \\
      ExternalId=${externalId} \\
  --capabilities CAPABILITY_NAMED_IAM`;

  const MEMBER_TEMPLATE = `AWSTemplateFormatVersion: "2010-09-09"
Description: AWS EOL Monitor member account read-only role for cross-account scanning.

Parameters:
  ScannerRoleArn:
    Type: String
    Default: "${SCANNER_ROLE_ARN}"
    Description: IAM role ARN used by the AWS EOL Monitor backend scanner.
    AllowedPattern: "^arn:aws:iam::[0-9]{12}:role/.+$"

  ExternalId:
    Type: String
    Default: "${externalId}"

Resources:
  EOLMonitorMemberRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: EOLMonitorReadOnly
      MaxSessionDuration: 3600
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal:
              AWS: !Ref ScannerRoleArn
            Action: "sts:AssumeRole"
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
                  - es:ListDomainNames
                  - es:DescribeElasticsearchDomain
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
                  - ecs:ListClusters
                  - ecs:DescribeClusters
                  - ecs:ListServices
                  - ecs:DescribeServices
                  - mq:ListBrokers
                  - mq:DescribeBroker
                  - dms:DescribeReplicationInstances
                  - dms:DescribeReplicationTasks
                  - airflow:ListEnvironments
                  - airflow:GetEnvironment
                  - batch:DescribeComputeEnvironments
                  - batch:DescribeJobQueues
                  - sagemaker:ListNotebookInstances
                  - sagemaker:DescribeNotebookInstance
                  - sts:GetCallerIdentity
                Resource: "*"

Outputs:
  RoleArn:
    Description: Member account read-only role ARN.
    Value: !GetAtt EOLMonitorMemberRole.Arn`;

  const STACKSET_CMD = `# Step 1 — Create the StackSet definition
aws cloudformation create-stack-set \\
  --stack-set-name aws-eol-monitor-member-roles \\
  --template-body file://eol-monitor-member-role.yaml \\
  --parameters ParameterKey=ScannerRoleArn,ParameterValue=${SCANNER_ROLE_ARN} \\
               ParameterKey=ExternalId,ParameterValue=${externalId} \\
  --capabilities CAPABILITY_NAMED_IAM \\
  --permission-model SERVICE_MANAGED \\
  --auto-deployment Enabled=true,RetainStacksOnAccountRemoval=false

# Step 2 — Deploy to all accounts in your organization root
# Replace r-xxxx with your root OU ID (from AWS Console → Organizations → Root)
aws cloudformation create-stack-instances \\
  --stack-set-name aws-eol-monitor-member-roles \\
  --deployment-targets OrganizationalUnitIds=r-xxxx \\
  --regions us-east-1 \\
  --operation-preferences FailureTolerancePercentage=100,MaxConcurrentPercentage=50`;

  async function createAndDiscover() {
    setLoading(true);
    setResult(null);
    try {
      const regions = form.regions.split(",").map(r => r.trim()).filter(Boolean);
      const conn = await orgApi("/org-connections", {
        method: "POST",
        body: JSON.stringify({
          name:                form.name || "AWS Organization",
          managementAccountId: form.mgmtAccountId,
          roleArn:             form.orgRoleArn,
          externalId,
          regions,
        }),
      });
      const connId = conn.connection?.id;
      let accounts = [];
      try {
        const disc = await orgApi(`/org-connections/${connId}/discover`, { method: "POST" });
        accounts = disc.accounts || [];
      } catch (_discErr) {
        // connection saved, discovery failed — non-fatal
      }
      setResult({ ok: true, conn: conn.connection, accounts, accountCount: accounts.length });
    } catch (err) {
      const msg = err.message || "Validation failed. Check the Role ARN and ExternalId.";
      setResult({ ok: false, msg });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="px-4 sm:px-6 py-6 sm:py-8 max-w-3xl mx-auto">
      <div className="mb-7">
        <p className="text-xs font-semibold text-indigo-500 uppercase tracking-widest mb-2">Organization Scan</p>
        <h1 className="text-3xl font-extrabold text-gray-900 mb-2">See EOL risk across every AWS account</h1>
        <p className="text-sm text-gray-500 leading-relaxed max-w-xl">
          Use an org read-only role and member account roles to build a cross-account lifecycle view across
          production, development, and shared services — all in one dashboard.
        </p>
      </div>

      <StepIndicator current={step} total={6} />

      {/* Step 1 — Choose admin account */}
      {step === 1 && (
        <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-4">
          <div>
            <h2 className="font-bold text-gray-800 mb-1">Step 1 — Choose admin account</h2>
            <p className="text-sm text-gray-500">Select the AWS account you will use to connect your organization.</p>
          </div>
          <div className="grid gap-3">
            {ADMIN_OPTIONS.map(opt => {
              const selected = adminType === opt.value;
              return (
                <label key={opt.value}
                  className={`flex items-start gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all ${
                    selected ? "border-indigo-400 bg-indigo-50/60" : "border-gray-200 hover:border-indigo-200 bg-white"
                  }`}>
                  <input type="radio" name="adminType" value={opt.value} checked={selected}
                    onChange={() => setAdminType(opt.value)} className="mt-0.5 accent-indigo-500 shrink-0" />
                  <div>
                    <p className={`text-sm font-semibold flex items-center gap-2 ${selected ? "text-indigo-800" : "text-gray-800"}`}>
                      {opt.title}
                      {opt.badge && (
                        <span className={`text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-full ${
                          opt.badge === "Recommended" ? "bg-indigo-600 text-white" : "bg-gray-200 text-gray-500"
                        }`}>{opt.badge}</span>
                      )}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">{opt.desc}</p>
                  </div>
                </label>
              );
            })}
          </div>
          <SecurityNote />
          <div className="flex justify-end">
            <button onClick={() => setStep(2)} className="px-5 py-2 bg-gray-900 text-white text-sm rounded-xl font-semibold hover:bg-gray-800 transition-colors">
              Next: Generate ExternalId →
            </button>
          </div>
        </div>
      )}

      {/* Step 2 — ExternalId */}
      {step === 2 && (
        <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-4">
          <div>
            <h2 className="font-bold text-gray-800 mb-1">Step 2 — Organization ExternalId</h2>
            <p className="text-sm text-gray-500">This ExternalId must be used in both the org management role and every member StackSet deployment.</p>
          </div>
          <CopyBox label="Organization ExternalId — save this before continuing" value={externalId} copyLabel="Copy ExternalId" />
          <div className="flex items-start gap-2 bg-amber-50 ring-1 ring-amber-100 rounded-lg px-3 py-2.5 text-xs text-amber-700">
            <span className="shrink-0 mt-px">⚠</span>
            <span>Use this same ExternalId in both the org management role (Step 3) and the member StackSet (Step 4).</span>
          </div>
          <div className="flex justify-between">
            <button onClick={() => setStep(1)} className="text-sm text-gray-400 hover:text-gray-700 underline">← Back</button>
            <button onClick={() => setStep(3)} className="px-5 py-2 bg-gray-900 text-white text-sm rounded-xl font-semibold hover:bg-gray-800 transition-colors">
              Next: Deploy Org Role →
            </button>
          </div>
        </div>
      )}

      {/* Step 3 — Org role */}
      {step === 3 && (
        <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-5">
          <div>
            <h2 className="font-bold text-gray-800 mb-1">
              {adminType === "delegated" ? "Step 3 — Deploy delegated admin org role" : "Step 3 — Deploy org management role"}
            </h2>
            <p className="text-sm text-gray-500">
              {adminType === "delegated"
                ? "Deploy this template in your delegated admin account."
                : "Deploy this template in your management account."}
            </p>
          </div>
          <div className="flex items-start gap-2.5 bg-indigo-50 ring-1 ring-indigo-100 rounded-lg px-3 py-2.5 text-xs text-indigo-700">
            <Shield size={13} className="shrink-0 mt-0.5" />
            <span>
              This template trusts only the exact backend scanner role —{" "}
              <span className="font-mono font-semibold">{SCANNER_ROLE_ARN}</span>
              {" "}— not the entire AWS account root.
            </span>
          </div>
          <TemplateSection value={ORG_ROLE_TEMPLATE} filename="eol-monitor-org-role.yaml" />
          <CollapsibleCli value={ORG_CLI_CMD} />
          <div className="flex items-start gap-2 bg-emerald-50 ring-1 ring-emerald-100 rounded-lg px-3 py-2.5 text-xs text-emerald-700">
            <span className="shrink-0">✓</span>
            <span>After the stack is created, copy the <strong>RoleArn</strong> from CloudFormation Outputs — you will paste it in Step 5.</span>
          </div>
          <div className="flex justify-between">
            <button onClick={() => setStep(2)} className="text-sm text-gray-400 hover:text-gray-700 underline">← Back</button>
            <button onClick={() => setStep(4)} className="px-5 py-2 bg-gray-900 text-white text-sm rounded-xl font-semibold hover:bg-gray-800 transition-colors">
              Next: Deploy Member Roles →
            </button>
          </div>
        </div>
      )}

      {/* Step 4 — StackSet */}
      {step === 4 && (
        <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-5">
          <div>
            <h2 className="font-bold text-gray-800 mb-1">Step 4 — Deploy member account roles via StackSet</h2>
            <p className="text-sm text-gray-500">
              This StackSet creates <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">EOLMonitorReadOnly</code> in every member account in your organization automatically.
            </p>
          </div>
          <div className="flex items-start gap-2.5 bg-indigo-50 ring-1 ring-indigo-100 rounded-lg px-3 py-2.5 text-xs text-indigo-700">
            <Shield size={13} className="shrink-0 mt-0.5" />
            <span>
              Member roles trust only{" "}
              <span className="font-mono font-semibold">{SCANNER_ROLE_ARN}</span>.
              No other principal can assume these roles.
            </span>
          </div>
          <TemplateSection value={MEMBER_TEMPLATE} filename="eol-monitor-member-role.yaml" />
          <CollapsibleCli value={STACKSET_CMD} />
          <div className="space-y-2">
            <div className="flex items-start gap-2 bg-slate-50 ring-1 ring-slate-100 rounded-lg px-3 py-2.5 text-xs text-slate-600">
              <span className="shrink-0">ℹ</span>
              <span>SERVICE_MANAGED StackSets auto-deploy to new accounts that join the organization. The <code>create-stack-instances</code> command is still required to deploy to existing accounts.</span>
            </div>
            <div className="flex items-start gap-2 bg-amber-50 ring-1 ring-amber-100 rounded-lg px-3 py-2.5 text-xs text-amber-700">
              <span className="shrink-0 mt-0.5">⚠</span>
              <span>
                <strong>Management account not included:</strong> AWS SERVICE_MANAGED StackSets do not deploy to the management (or delegated admin) account by default.
                If you want to scan resources in the management account, deploy the same template there separately via CloudFormation — not StackSet.
              </span>
            </div>
          </div>
          <div className="flex justify-between">
            <button onClick={() => setStep(3)} className="text-sm text-gray-400 hover:text-gray-700 underline">← Back</button>
            <button onClick={() => setStep(5)} className="px-5 py-2 bg-gray-900 text-white text-sm rounded-xl font-semibold hover:bg-gray-800 transition-colors">
              Next: Enter Details →
            </button>
          </div>
        </div>
      )}

      {/* Step 5 — Enter details */}
      {step === 5 && (() => {
        const acctIdValid = /^\d{12}$/.test(form.mgmtAccountId);
        const arnValid    = /^arn:aws:iam::\d{12}:role\/.+$/.test(form.orgRoleArn);
        const arnMatch    = !form.orgRoleArn || !form.mgmtAccountId || !acctIdValid || !arnValid
          ? true : form.orgRoleArn.includes(`:${form.mgmtAccountId}:`);
        const canAdvance  = acctIdValid && arnValid && arnMatch;
        return (
          <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-5">
            <div>
              <h2 className="font-bold text-gray-800 mb-1">Step 5 — Enter organization details</h2>
              <p className="text-sm text-gray-500">Enter the role details from the previous deployment steps.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Connection Name <span className="text-gray-400 font-normal">(optional)</span></label>
              <input type="text" placeholder="AWS Organization" value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                className={inputCls} />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {adminType === "delegated" ? "Delegated Admin Account ID" : "Management Account ID"}
                </label>
                <input type="text" placeholder="123456789012" maxLength={12} value={form.mgmtAccountId}
                  onChange={e => setForm(f => ({ ...f, mgmtAccountId: e.target.value.replace(/\D/g, "") }))}
                  className={`${inputCls} ${form.mgmtAccountId && !acctIdValid ? "border-red-300" : ""}`} />
                {form.mgmtAccountId && !acctIdValid
                  ? <p className="text-xs text-red-500 mt-1">Must be exactly 12 digits.</p>
                  : <p className="text-xs text-gray-400 mt-1">
                      {adminType === "delegated" ? "12-digit delegated admin AWS account ID." : "12-digit management AWS account ID."}
                    </p>}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Scan Regions</label>
                <input type="text" placeholder="us-east-1, ap-south-1" value={form.regions}
                  onChange={e => setForm(f => ({ ...f, regions: e.target.value }))}
                  className={inputCls} />
                <p className="text-xs text-gray-400 mt-1">Comma-separated AWS region codes.</p>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Org Management Role ARN</label>
              <p className="text-xs text-gray-400 mb-1.5">Paste the RoleArn from your CloudFormation stack output (Step 3).</p>
              <input type="text" placeholder="arn:aws:iam::123456789012:role/EOLMonitorOrgReadOnly"
                value={form.orgRoleArn}
                onChange={e => setForm(f => ({ ...f, orgRoleArn: e.target.value.trim() }))}
                className={`${inputCls} ${form.orgRoleArn && !arnValid ? "border-red-300" : ""}`} />
              {form.orgRoleArn && !arnValid
                ? <p className="text-xs text-red-500 mt-1">Expected: arn:aws:iam::123456789012:role/RoleName</p>
                : form.orgRoleArn && arnValid && !arnMatch
                  ? <p className="text-xs text-red-500 mt-1">Account ID in Role ARN does not match Management Account ID above.</p>
                  : <p className="text-xs text-gray-400 mt-1">Expected format: arn:aws:iam::123456789012:role/EOLMonitorOrgReadOnly</p>}
            </div>
            <div className="flex items-center justify-between gap-4">
              <button onClick={() => setStep(4)} className="text-sm text-gray-400 hover:text-gray-700 underline shrink-0">← Back</button>
              <div className="flex items-center gap-3">
                {!canAdvance && <p className="text-xs text-gray-400 text-right">Enter a valid Account ID and Role ARN to continue.</p>}
                <button onClick={() => setStep(6)} disabled={!canAdvance}
                  className="px-5 py-2 bg-gray-900 text-white text-sm rounded-xl font-semibold hover:bg-gray-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0">
                  Next: Review →
                </button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Step 6 — Review & Connect */}
      {step === 6 && (
        <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-5">
          <div>
            <h2 className="font-bold text-gray-800 mb-1">Step 6 — Review and connect</h2>
            <p className="text-sm text-gray-500">Confirm the details below, then connect your organization.</p>
          </div>
          <div className="bg-gray-50 rounded-xl p-4 space-y-3 text-sm">
            {[
              { label: "Connection Name",   value: form.name || "AWS Organization" },
              { label: adminType === "delegated" ? "Delegated Admin Account" : "Management Account", value: form.mgmtAccountId },
              { label: "Org Role ARN",       value: form.orgRoleArn },
              { label: "ExternalId",         value: externalId },
              { label: "Regions",            value: form.regions },
            ].map(({ label, value }) => (
              <div key={label} className="flex justify-between gap-4 py-1 border-b border-gray-100 last:border-0">
                <span className="text-gray-500 shrink-0">{label}</span>
                <span className="font-mono text-xs text-gray-700 text-right break-all">{value || "—"}</span>
              </div>
            ))}
          </div>
          <button onClick={createAndDiscover} disabled={loading}
            className="w-full py-2.5 rounded-xl text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-60 transition-colors flex items-center justify-center gap-2">
            {loading && <Loader2 size={15} className="animate-spin" />}
            {loading ? "Connecting and discovering accounts…" : "Validate & Connect Organization"}
          </button>
          {result && !result.ok && (
            <div className="flex items-start gap-2 rounded-xl px-4 py-3 text-sm bg-red-50 text-red-700 ring-1 ring-red-200">
              <XCircle size={15} className="shrink-0 mt-0.5" />
              <span>{result.msg}</span>
            </div>
          )}
          {result?.ok && (
            <div className="space-y-3">
              <div className="flex items-start gap-2 rounded-xl px-4 py-3 text-sm bg-green-50 text-green-700 ring-1 ring-green-200">
                <CheckCircle2 size={15} className="shrink-0 mt-0.5" />
                <span>
                  Organization connected. {result.accountCount > 0
                    ? `${result.accountCount} account${result.accountCount !== 1 ? "s" : ""} discovered.`
                    : "Run a discovery to find member accounts."}
                </span>
              </div>
              <button onClick={() => onConnected(result.conn)}
                className="w-full py-2.5 rounded-xl text-sm font-bold text-white bg-gray-900 hover:bg-gray-800 transition-colors">
                View Organization Dashboard →
              </button>
            </div>
          )}
          <button onClick={() => setStep(5)} className="text-sm text-gray-400 hover:text-gray-700 underline">← Back</button>
        </div>
      )}
    </div>
  );
}

// ── Org Dashboard ──────────────────────────────────────────────────────────────

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

function orgRegionLabel(conn) {
  const regions = conn?.regions;
  if (!regions || regions.length === 0) return "All enabled regions";
  if (regions.length === 1) return regions[0];
  return `${regions.length} regions`;
}

const STATUS_PRIORITY = { EOL:0, EXPIRING_SOON:1, EXTENDED_SUPPORT:2, SUPPORTED:3, UNKNOWN:4, LIFECYCLE_NOT_TRACKED:5, NEEDS_INSPECTION:6 };
const ORG_SCAN_TERMINAL = new Set(["SUCCESS", "PARTIAL_SUCCESS", "FAILED", "CANCELLED"]);

function scanStatusClasses(status) {
  if (status === "SUCCESS") return "bg-green-50 text-green-700 ring-green-200";
  if (status === "PARTIAL_SUCCESS") return "bg-amber-50 text-amber-700 ring-amber-200";
  if (status === "FAILED") return "bg-red-50 text-red-700 ring-red-200";
  return "bg-indigo-50 text-indigo-700 ring-indigo-200";
}

function memberScanErrorLabel(code) {
  switch (code) {
    case "ASSUME_ROLE_ACCESS_DENIED":   return "Cannot assume role — check trust policy / ExternalId";
    case "MEMBER_ROLE_NOT_FOUND":       return "Role not found — deploy StackSet to this account";
    case "MANAGEMENT_ROLE_MISSING":     return "Scan role missing — StackSets don't deploy here automatically";
    case "MEMBER_SCAN_TIMEOUT":         return "Scan timed out";
    case "ORG_DISCOVERY_ACCESS_DENIED": return "Organizations access denied";
    case "MEMBER_SCAN_FAILED":          return "Scan failed";
    default: return code || "Scan failed";
  }
}

function memberScanErrorShort(code) {
  switch (code) {
    case "ASSUME_ROLE_ACCESS_DENIED":   return "Cannot assume role";
    case "MEMBER_ROLE_NOT_FOUND":       return "Role not found";
    case "MANAGEMENT_ROLE_MISSING":     return "Role missing";
    case "MEMBER_SCAN_TIMEOUT":         return "Timed out";
    case "ORG_DISCOVERY_ACCESS_DENIED": return "Access denied";
    default: return "Scan failed";
  }
}

function IssueCell({ acct }) {
  const [tip, setTip]       = useState(false);
  const [copied, setCopied] = useState(false);
  if (acct.lastScanStatus !== "FAILED") return null;

  const short     = memberScanErrorShort(acct.lastErrorCode);
  const hasDetail = acct.lastRoleArn || acct.lastErrorCode === "MANAGEMENT_ROLE_MISSING";

  async function copyArn() {
    const ok = await copyToClipboard(acct.lastRoleArn);
    if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2000); }
  }

  return (
    <div className="relative" onMouseLeave={() => setTip(false)}>
      <div className="flex items-center gap-1">
        <span className="text-xs font-medium text-red-600 leading-tight">{short}</span>
        {hasDetail && (
          <button
            type="button"
            onMouseEnter={() => setTip(true)}
            onClick={() => setTip(t => !t)}
            className="text-gray-300 hover:text-gray-500 flex-shrink-0 transition-colors"
          >
            <Info size={11} />
          </button>
        )}
      </div>
      {tip && (
        <div className="absolute left-0 top-5 z-50 w-72 bg-white rounded-lg shadow-xl ring-1 ring-gray-200 p-3 space-y-2">
          {acct.lastErrorCode === "MANAGEMENT_ROLE_MISSING" && (
            <p className="text-xs text-amber-700">Deploy the member role template via CloudFormation directly to this account — StackSets cannot deploy to the management account automatically.</p>
          )}
          {acct.lastErrorCode === "ASSUME_ROLE_ACCESS_DENIED" && (
            <p className="text-xs text-gray-700">Cannot assume the scan role. Check the IAM trust policy allows the management account principal, and that the ExternalId matches exactly (case-sensitive).</p>
          )}
          {acct.lastErrorCode === "MEMBER_ROLE_NOT_FOUND" && (
            <p className="text-xs text-gray-700">Role <code className="font-mono text-[11px]">EOLMonitorReadOnly</code> not found. Deploy the StackSet to this account via CloudFormation → StackSets in the management account.</p>
          )}
          {acct.lastRoleArn && (
            <div className={acct.lastErrorCode !== "MANAGEMENT_ROLE_MISSING" ? "pt-1.5 border-t border-gray-100" : ""}>
              <p className="text-[10px] font-semibold text-gray-500 mb-1">Expected role ARN</p>
              <div className="flex items-start gap-1.5">
                <code className="text-[10px] text-gray-600 font-mono break-all flex-1 leading-relaxed">{acct.lastRoleArn}</code>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); copyArn(); }}
                  className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors ${
                    copied ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-gray-200 text-gray-500 hover:bg-gray-50"
                  }`}
                >
                  {copied ? "✓" : "Copy"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const FIX_STEPS = {
  MANAGEMENT_ROLE_MISSING: [
    "Download the member role CloudFormation template from the org setup wizard.",
    "In the member account, go to CloudFormation → Create Stack.",
    "Use the downloaded template — do NOT use StackSets (they skip the management account).",
  ],
  MEMBER_ROLE_NOT_FOUND: [
    "The StackSet deployment to this account may have failed or not yet started.",
    "In the management account, go to CloudFormation → StackSets.",
    "Check the instance status for this account and redeploy if FAILED or OUTDATED.",
  ],
  ASSUME_ROLE_ACCESS_DENIED: [
    "The scan role exists but AWS denied the AssumeRole call.",
    "Open IAM in the member account → Roles → EOLMonitorReadOnly → Trust relationships.",
    "Confirm the trust policy allows the management account scanner principal.",
    "Verify the ExternalId in the trust policy exactly matches the value shown in the setup wizard — it is case-sensitive.",
  ],
};

function FixRoleButton({ acct }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    function close(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const steps = FIX_STEPS[acct.lastErrorCode] || [
    "Verify the member account CloudFormation stack is in CREATE_COMPLETE status.",
    "Retry the scan after confirming the role is deployed.",
  ];

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
        className="inline-flex items-center gap-1 rounded-lg border border-orange-200 bg-orange-50 px-2.5 py-1 text-xs font-semibold text-orange-700 hover:bg-orange-100 transition-colors"
      >
        <AlertTriangle size={10} /> Fix Role Setup
      </button>
      {open && (
        <div className="absolute right-0 top-8 z-50 w-72 bg-white rounded-xl shadow-xl ring-1 ring-gray-200 p-4 space-y-3">
          <p className="text-xs font-semibold text-gray-800">
            How to fix — <span className="text-red-600">{memberScanErrorShort(acct.lastErrorCode)}</span>
          </p>
          <ol className="space-y-2">
            {steps.map((step, i) => (
              <li key={i} className="flex gap-2 text-xs text-gray-600">
                <span className="flex-shrink-0 w-4 h-4 rounded-full bg-orange-100 text-orange-700 text-[10px] font-bold flex items-center justify-center mt-0.5">{i + 1}</span>
                <span className="leading-relaxed">{step}</span>
              </li>
            ))}
          </ol>
          {acct.lastRoleArn && (
            <ArnRow label="Role ARN" value={acct.lastRoleArn} />
          )}
        </div>
      )}
    </div>
  );
}

function ArnRow({ label, value }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    const ok = await copyToClipboard(value);
    if (ok) { setCopied(true); setTimeout(() => setCopied(false), 2000); }
  }
  return (
    <div className="pt-1 border-t border-gray-100">
      <p className="text-[10px] font-semibold text-gray-500 mb-1">{label}</p>
      <div className="flex items-start gap-1.5">
        <code className="text-[10px] text-gray-600 font-mono break-all flex-1 leading-relaxed">{value}</code>
        <button
          type="button"
          onClick={copy}
          className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors ${
            copied ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-gray-200 text-gray-500 hover:bg-gray-50"
          }`}
        >
          {copied ? "✓" : "Copy"}
        </button>
      </div>
    </div>
  );
}

function AccountActionCell({ acct, onViewResources, onRetryScan, scanRunning }) {
  const status = acct.lastScanStatus;

  if (status === "SUCCESS") {
    return (
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onViewResources(); }}
        className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-indigo-50 hover:border-indigo-200 hover:text-indigo-700 transition-colors"
      >
        View Resources <ArrowRight size={11} />
      </button>
    );
  }

  if (status === "RUNNING") {
    return (
      <span className="inline-flex items-center gap-1 rounded-lg border border-indigo-100 bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-400">
        <Loader2 size={10} className="animate-spin" /> Scanning…
      </span>
    );
  }

  if (status === "FAILED") {
    if (acct.lastScanAt) {
      return (
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onViewResources(); }}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-500 hover:bg-slate-50 hover:text-slate-700 transition-colors"
          >
            View Previous
          </button>
          <button
            type="button"
            disabled={scanRunning}
            onClick={(e) => { e.stopPropagation(); onRetryScan(); }}
            className="inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <RefreshCw size={10} /> Retry
          </button>
        </div>
      );
    }
    return (
      <div className="flex items-center gap-1.5">
        <FixRoleButton acct={acct} />
        <button
          type="button"
          disabled={scanRunning}
          onClick={(e) => { e.stopPropagation(); onRetryScan(); }}
          className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <RefreshCw size={10} /> Retry
        </button>
      </div>
    );
  }

  return <span className="text-xs text-gray-300">—</span>;
}

function EditOrgRegionsModal({ conn, onSave, onCancel }) {
  const initRegions = Array.isArray(conn?.regions) ? conn.regions : [];
  const initMode = initRegions.length === 0 ? "all"
    : initRegions.length === 1 ? "single" : "selected";
  const initSingle   = initRegions.length === 1 ? initRegions[0] : "us-east-1";
  const initSelected = initRegions.length > 1   ? initRegions : [];

  const [regionMode, setRegionMode] = useState(initMode);
  const [single, setSingle]         = useState(initSingle);
  const [selected, setSelected]     = useState(initSelected);
  const [saving, setSaving]         = useState(false);
  const [saveError, setSaveError]   = useState("");

  function toggle(r) {
    setSelected(prev => prev.includes(r) ? prev.filter(x => x !== r) : [...prev, r]);
  }

  async function handleSave() {
    if (!canSave || saving) return;
    setSaving(true);
    const newRegions = regionMode === "all" ? []
      : regionMode === "single" ? [single].filter(Boolean)
      : selected;
    try {
      const connId = conn?.id;
      await orgApi(`/org-connections/${connId}`, {
        method: "PATCH",
        body: JSON.stringify({ regions: newRegions }),
      });
      onSave(newRegions);
    } catch (e) {
      setSaveError(e?.message || "Failed to save regions. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  const regionName = r => r.label.split("(")[1]?.replace(")", "") ?? r.label;
  const selectedCount = regionMode === "all" ? AWS_REGIONS.length : regionMode === "single" ? (single ? 1 : 0) : selected.length;
  const canClear = regionMode !== "all" && selectedCount > 0;
  const canSave  = regionMode === "all" || (regionMode === "single" ? Boolean(single) : selected.length > 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="flex max-h-[85vh] w-full max-w-xl flex-col rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 px-6 pb-4 pt-6">
          <div>
            <h3 className="text-lg font-extrabold tracking-tight text-slate-950">Edit Region Scope</h3>
            <p className="mt-1 text-sm font-medium text-slate-500">Applies to all member accounts in the next org scan.</p>
          </div>
          <button type="button" onClick={onCancel} aria-label="Close"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-300">
            <X size={18} strokeWidth={2.25} />
          </button>
        </div>

        <div className="mx-6 grid grid-cols-3 gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1">
          {[
            { v: "all",      label: "All regions"    },
            { v: "single",   label: "Single region"  },
            { v: "selected", label: "Select regions" },
          ].map(o => (
            <button key={o.v} type="button"
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
              All enabled AWS regions will be scanned across member accounts. This may take longer for large organizations.
            </div>
          )}

          {regionMode === "single" && (
            <div className="space-y-3">
              <p className="text-xs font-medium text-slate-500">Only one region will be scanned across all member accounts.</p>
              <div className="max-h-64 space-y-2 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-2">
                {AWS_REGIONS.map(r => {
                  const checked = single === r.value;
                  return (
                    <button key={r.value} type="button" onClick={() => setSingle(r.value)}
                      className={`flex w-full items-center gap-3 rounded-xl border px-3 py-3 text-left transition focus:outline-none focus:ring-2 focus:ring-indigo-300 ${
                        checked ? "border-indigo-200 bg-indigo-50" : "border-slate-200 bg-white hover:bg-slate-50"
                      }`}>
                      <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                        checked ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-300 bg-white"
                      }`}>
                        {checked && <Check size={11} strokeWidth={3} />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className={`block text-sm font-semibold leading-tight ${checked ? "text-indigo-800" : "text-slate-900"}`}>{r.value}</span>
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
                    <button key={r.value} type="button" onClick={() => toggle(r.value)}
                      className={`flex w-full items-start gap-3 rounded-xl border px-3 py-3 text-left transition focus:outline-none focus:ring-2 focus:ring-indigo-300 ${
                        checked ? "border-indigo-200 bg-indigo-50" : "border-slate-200 bg-white hover:bg-slate-50"
                      }`}>
                      <input type="checkbox" checked={checked} readOnly
                        className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer accent-indigo-600" />
                      <span className="min-w-0">
                        <span className={`block text-sm font-semibold leading-tight ${checked ? "text-indigo-800" : "text-slate-900"}`}>{r.value}</span>
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
              ? regionMode === "all"
                ? "All enabled regions selected"
                : `${selectedCount} region${selectedCount !== 1 ? "s" : ""} selected`
              : regionMode === "single" ? "Select one region." : "Select at least one region."}
          </p>
          {canClear && (
            <button type="button"
              onClick={() => regionMode === "single" ? setSingle("") : setSelected([])}
              className="text-sm font-semibold text-slate-500 transition-colors hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-300">
              Clear
            </button>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4">
          {saveError && (
            <p className="text-xs text-red-600 mr-auto">{saveError}</p>
          )}
          <button type="button" onClick={onCancel}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-indigo-300">
            Cancel
          </button>
          <button type="button" onClick={handleSave} disabled={!canSave || saving}
            className="rounded-lg bg-slate-950 px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-50">
            {saving ? "Saving…" : "Save Regions"}
          </button>
        </div>
      </div>
    </div>
  );
}

const PERM_DETAILS = {
  ECS_ACCESS_DENIED:       { label: "ECS Fargate",         actions: ["ecs:ListClusters", "ecs:DescribeClusters", "ecs:ListServices", "ecs:DescribeServices"] },
  AMAZON_MQ_ACCESS_DENIED: { label: "Amazon MQ",           actions: ["mq:ListBrokers", "mq:DescribeBroker"] },
  DMS_ACCESS_DENIED:       { label: "AWS DMS",             actions: ["dms:DescribeReplicationInstances", "dms:DescribeReplicationTasks"] },
  MWAA_ACCESS_DENIED:      { label: "Amazon MWAA",         actions: ["airflow:ListEnvironments", "airflow:GetEnvironment"] },
  BATCH_ACCESS_DENIED:     { label: "AWS Batch",           actions: ["batch:DescribeComputeEnvironments", "batch:DescribeJobQueues"] },
  SAGEMAKER_ACCESS_DENIED: { label: "SageMaker Notebook",  actions: ["sagemaker:ListNotebookInstances", "sagemaker:DescribeNotebookInstance"] },
  CODEBUILD_ACCESS_DENIED: { label: "CodeBuild",           actions: ["codebuild:ListProjects", "codebuild:BatchGetProjects"] },
  GLUE_ACCESS_DENIED:      { label: "Glue",                actions: ["glue:ListJobs", "glue:GetJobs"] },
  MSK_ACCESS_DENIED:       { label: "MSK (Kafka)",         actions: ["kafka:ListClusters", "kafka:DescribeCluster"] },
  OPENSEARCH_ACCESS_DENIED:{ label: "OpenSearch",          actions: ["opensearch:ListDomainNames", "opensearch:DescribeDomain"] },
};

function OrgDashboard({ conn, onDisconnect }) {
  const navigate = useNavigate();
  const [summary, setSummary]     = useState(null);
  const [accounts, setAccounts]   = useState([]);
  const [inventory, setInventory] = useState([]);
  const [tab, setTab]             = useState("accounts");
  const [statusFilter, setStatusFilter] = useState("");
  const [acctStatusFilter, setAcctStatusFilter] = useState("all");
  const [acctSearch, setAcctSearch]             = useState("");
  const [scanState, setScanState]           = useState("idle"); // idle | running | stopping | done | error
  const [scanRun, setScanRun]               = useState(null);
  const [currentScanId, setCurrentScanId]   = useState(null);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const [rediscoverState, setRediscoverState] = useState("idle"); // idle | loading | done | error
  const [rediscoverMsg, setRediscoverMsg]     = useState("");
  const [showPermDetails, setShowPermDetails] = useState(false);
  const [showEditRegions, setShowEditRegions] = useState(false);
  const [dashLoading, setDashLoading]       = useState(true);
  const [loadErr, setLoadErr]               = useState(null);
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const pollRef = useRef(null);
  const pollInFlightRef = useRef(false);
  const mountedRef = useRef(true);

  const fetchSummary = useCallback(async () => {
    try {
      const data = await orgApi("/org-summary");
      if (!mountedRef.current) return;
      setSummary(data);
      if (data.connections?.[0]) {
        const accts = await orgApi(`/org-connections/${data.connections[0].id}/accounts`);
        if (!mountedRef.current) return;
        setAccounts(accts.accounts || []);
      }
    } catch (err) {
      if (!mountedRef.current) return;
      setLoadErr(err.message || "Failed to load organization summary.");
    } finally {
      if (mountedRef.current) setDashLoading(false);
    }
  }, []);

  const fetchInventory = useCallback(async () => {
    try {
      const wsId = getWorkspaceId();
      const r = await fetch(`${API_BASE_URL}/workspaces/${wsId}/inventory?limit=500`, {
        headers: workspaceHeaders(),
      });
      const data = await r.json();
      if (!mountedRef.current) return;
      setInventory((data.resources || data.items || []).filter(item => {
        const acctId = String(item.account_id || item.payload?.account_id || "");
        return !acctId.startsWith("conn-");
      }).map(item => {
        const p = item.payload || item;
        return {
          id:              item.resource_id || p.resourceId || item.id,
          accountName:     p.accountName || p.account_name || item.account_id || "—",
          ou:              p.ouPath || "/Root",
          resourceName:    p.resourceName || p.name || p.resource_id || "—",
          service:         item.service_type || p.serviceType || "—",
          region:          item.region || p.region || "—",
          version:         p.version || "—",
          status:          item.eol_status || p.eolStatus || "UNKNOWN",
          eolDate:         p.eolDate || p.eol_date || "—",
          recommendedAction: p.recommendedAction || "",
        };
      }));
    } catch (_) {}
  }, []);

  useEffect(() => {
    fetchSummary();
    fetchInventory();
  }, [fetchSummary, fetchInventory]);

  const clearScanPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const applyPolledScan = useCallback((data) => {
    const run = data?.run || null;
    if (!run) return null;
    setScanRun(run);
    if (Array.isArray(data.accounts)) setAccounts(data.accounts);
    setSummary(prev => prev ? {
      ...prev,
      accountsScanned: run.accountsScanned ?? prev.accountsScanned,
      accountsFailed:  run.accountsFailed  ?? prev.accountsFailed,
      summary:         run.summary         || prev.summary,
      latestRun:       run,
    } : prev);
    return run;
  }, []);

  const pollScan = useCallback(async (scanId) => {
    if (!scanId || pollInFlightRef.current) return;
    pollInFlightRef.current = true;
    try {
      const data = await orgApi(`/org-scans/${scanId}`);
      if (!mountedRef.current) return;
      const run = applyPolledScan(data);
      if (run && ORG_SCAN_TERMINAL.has(run.status)) {
        clearScanPoll();
        setScanState(run.status === "FAILED" ? "error" : "done");
        await fetchSummary();
        await fetchInventory();
      }
    } catch (err) {
      if (!mountedRef.current) return;
      clearScanPoll();
      setScanState("error");
      setScanRun(prev => ({ ...(prev || {}), error: err.message || "Failed to poll organization scan." }));
    } finally {
      pollInFlightRef.current = false;
    }
  }, [applyPolledScan, clearScanPoll, fetchSummary, fetchInventory]);

  const startScanPolling = useCallback((scanId) => {
    clearScanPoll();
    if (!scanId) {
      setScanState("error");
      setScanRun({ error: "Organization scan started, but no scan ID was returned." });
      return;
    }
    pollScan(scanId);
    pollRef.current = setInterval(() => pollScan(scanId), 2500);
  }, [clearScanPoll, pollScan]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearScanPoll();
    };
  }, [clearScanPoll]);

  async function startScan() {
    const connId = summary?.connections?.[0]?.id || conn?.id;
    if (!connId) return;
    clearScanPoll();
    setScanState("running");
    setScanRun(null);
    try {
      const data = await orgApi(`/org-connections/${connId}/scans`, { method: "POST" });
      const run = data.run || null;
      const scanId = data.orgScanId || run?.id;
      setScanRun(run || { id: scanId, status: data.status });
      setCurrentScanId(scanId);
      startScanPolling(scanId);
    } catch (err) {
      const runningScanId = err.data?.runningScan?.orgScanId || err.data?.runningScan?.scanId;
      if (err.status === 409 && err.code === "ORG_SCAN_IN_PROGRESS") {
        setScanRun({
          id: runningScanId,
          status: "RUNNING",
          error: "An organization scan is already running.",
        });
        if (runningScanId) {
          setCurrentScanId(runningScanId);
          setScanState("running");
          startScanPolling(runningScanId);
        } else {
          setScanState("error");
          await fetchSummary();
        }
        return;
      }
      setScanState("error");
      setScanRun({ error: err.message });
    }
  }

  async function cancelScan() {
    if (!currentScanId || scanState !== "running") return;
    setShowCancelConfirm(false);
    setScanState("stopping");
    try {
      await orgApi(`/org-scans/${currentScanId}/cancel`, { method: "POST" });
      // Worker will set status to CANCELLED; poll picks it up as terminal
    } catch {
      // If cancel failed (scan already finished), polling will detect terminal state
      if (mountedRef.current) setScanState("running");
    }
  }

  async function rediscover() {
    const connId = summary?.connections?.[0]?.id || conn?.id;
    if (!connId || rediscoverState === "loading") return;
    setRediscoverState("loading");
    setRediscoverMsg("");
    try {
      const data = await orgApi(`/org-connections/${connId}/discover`, { method: "POST" });
      await fetchSummary();
      if (!mountedRef.current) return;
      setRediscoverState("done");
      setRediscoverMsg(`${data.count ?? 0} accounts discovered`);
      setTimeout(() => { if (mountedRef.current) setRediscoverState("idle"); }, 4000);
    } catch (err) {
      if (!mountedRef.current) return;
      setRediscoverState("error");
      const code = err.code || "";
      const msg = code === "ORG_DISCOVERY_ACCESS_DENIED" || code === "ASSUME_ROLE_ACCESS_DENIED"
        ? "Cannot assume role — check trust policy and ExternalId"
        : code === "ORG_DISCOVERY_FAILED"
        ? "Could not reach AWS Organizations — check IAM permissions"
        : err.message || "Rediscovery failed";
      setRediscoverMsg(msg);
      setTimeout(() => { if (mountedRef.current) setRediscoverState("idle"); }, 6000);
    }
  }

  const totals = summary?.summary || {};
  const activeConn = summary?.connections?.[0] || conn;

  if (loadErr) {
    return (
      <div className="p-10 text-center">
        <AlertTriangle size={36} className="mx-auto mb-3 text-red-400" strokeWidth={1.5} />
        <p className="text-gray-600 mb-4">{loadErr}</p>
        <button onClick={fetchSummary} className="px-4 py-2 bg-gray-900 text-white rounded-xl text-sm font-semibold">Retry</button>
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="p-10 text-center">
        <Loader2 size={32} className="mx-auto mb-3 text-indigo-400 animate-spin" strokeWidth={1.5} />
        <p className="text-sm text-gray-400">Loading organization data…</p>
      </div>
    );
  }

  return (
    <div className="px-4 sm:px-6 py-6 sm:py-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-5 flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="text-xs font-semibold px-2 py-0.5 bg-purple-100 text-purple-700 rounded-full">Organization Scan</span>
            {activeConn && <span className="text-xs text-gray-400">{activeConn.name || "AWS Organization"}</span>}
          </div>
          <h1 className="text-2xl font-bold text-gray-900">{activeConn?.name || "AWS Organization"}</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {dashLoading
              ? "Loading…"
              : <>
                  {accounts.length} accounts discovered
                  {totals.totalResources > 0 && ` · ${totals.totalResources} resources`}
                  {` · Regions: ${orgRegionLabel(activeConn)}`}
                  {activeConn?.lastScanAt && ` · Last scanned ${new Date(activeConn.lastScanAt).toLocaleDateString()}`}
                </>
            }
          </p>
          {activeConn?.regions?.length > 0 && (
            <p className="text-xs text-amber-600 mt-0.5">
              Resources outside selected regions will not be scanned.
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={() => setShowEditRegions(true)} className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50">
            <Globe2 size={13} strokeWidth={2} />
            Edit Regions
          </button>
          <div className="flex flex-col items-end gap-0.5">
            <button
              onClick={rediscover}
              disabled={rediscoverState === "loading"}
              className={`flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border transition-colors ${
                rediscoverState === "loading"
                  ? "border-gray-200 bg-gray-50 text-gray-400 cursor-not-allowed"
                  : "border-gray-200 text-gray-500 hover:bg-gray-50"
              }`}>
              <RefreshCw size={13} strokeWidth={2} className={rediscoverState === "loading" ? "animate-spin" : ""} />
              {rediscoverState === "loading" ? "Rediscovering…" : "Rediscover Accounts"}
            </button>
            {rediscoverMsg && (
              <p className={`text-[11px] font-medium ${rediscoverState === "error" ? "text-red-600" : "text-emerald-600"}`}>
                {rediscoverState === "error" ? "⚠ " : "✓ "}{rediscoverMsg}
              </p>
            )}
          </div>
          {scanState === "running" ? (
            <button
              onClick={() => setShowCancelConfirm(true)}
              className="flex items-center gap-1.5 text-sm px-4 py-1.5 rounded-lg font-semibold transition-colors bg-red-600 text-white hover:bg-red-700">
              <X size={13} strokeWidth={2.5} /> Stop Scan
            </button>
          ) : scanState === "stopping" ? (
            <button disabled
              className="flex items-center gap-1.5 text-sm px-4 py-1.5 rounded-lg font-semibold bg-red-100 text-red-400 cursor-not-allowed">
              <Loader2 size={13} className="animate-spin" /> Stopping…
            </button>
          ) : (
            <button onClick={startScan}
              className="flex items-center gap-1.5 text-sm px-4 py-1.5 rounded-lg font-semibold transition-colors bg-indigo-600 text-white hover:bg-indigo-700">
              <Play size={13} strokeWidth={2.5} /> Scan All Accounts
            </button>
          )}
          <button onClick={() => setShowDisconnectModal(true)} className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50">
            <Unplug size={13} strokeWidth={2} /> Disconnect
          </button>
        </div>
      </div>

      {/* Stopping banner */}
      {scanState === "stopping" && (
        <div className="mb-4 flex items-center gap-3 px-4 py-3 rounded-xl text-sm ring-1 bg-amber-50 text-amber-700 ring-amber-200">
          <Loader2 size={15} className="animate-spin shrink-0" />
          <span className="font-semibold">Stopping scan…</span>
          <span className="text-amber-600">Waiting for the current account to finish, then stopping safely.</span>
        </div>
      )}

      {/* Scan result banner */}
      {scanState === "running" && scanRun && (() => {
        const inProgress = accounts.filter(a => a.lastScanStatus === "RUNNING").length;
        const scannedSoFar = scanRun.accountsScanned ?? 0;
        const failedSoFar  = scanRun.accountsFailed  ?? 0;
        const parts = [
          `${scannedSoFar} scanned`,
          ...(inProgress > 0 ? [`${inProgress} running`] : []),
          ...(failedSoFar > 0 ? [`${failedSoFar} need attention`] : []),
        ];
        return (
          <div className="mb-4 flex items-center justify-between gap-3 px-4 py-3 rounded-xl text-sm ring-1 bg-indigo-50 text-indigo-700 ring-indigo-200">
            <div className="flex items-center gap-2 min-w-0">
              <Loader2 size={15} className="animate-spin shrink-0" />
              <span className="font-semibold shrink-0">Organization scan in progress</span>
            </div>
            <span className="shrink-0 text-indigo-600 font-medium">{parts.join(" · ")}</span>
          </div>
        );
      })()}
      {scanState === "done" && scanRun && (() => {
        if (scanRun.status === "CANCELLED") {
          const completedNow  = accounts.filter(a => a.lastScanStatus === "SUCCESS").length;
          const failedNow     = accounts.filter(a => a.lastScanStatus === "FAILED").length;
          const cancelledNow  = accounts.filter(a => a.lastScanStatus === "CANCELLED").length;
          const parts = [
            ...(completedNow  > 0 ? [`${completedNow} scanned`]     : []),
            ...(failedNow     > 0 ? [`${failedNow} failed`]         : []),
            ...(cancelledNow  > 0 ? [`${cancelledNow} stopped mid-scan`] : []),
          ];
          return (
            <div className="mb-4 flex items-center gap-2 px-4 py-3 rounded-xl text-sm ring-1 bg-slate-50 text-slate-700 ring-slate-200">
              <X size={15} className="shrink-0" />
              <span className="font-semibold">Scan stopped.</span>
              <span>
                {parts.length > 0 ? parts.join(" · ") + "." : "No accounts were scanned."}
                {completedNow > 0 && " Completed results were kept."}
              </span>
            </div>
          );
        }
        const permWarns     = (scanRun.warnings ?? []).filter(w => w.type === "COLLECTOR_PERMISSION");
        const hasPermWarns  = permWarns.length > 0;
        if (!hasPermWarns) {
          return (
            <div className={`mb-4 flex items-center gap-2 px-4 py-3 rounded-xl text-sm ring-1 ${scanStatusClasses(scanRun.status)}`}>
              {scanRun.status === "SUCCESS" ? <CheckCircle2 size={15} className="shrink-0" /> : <AlertTriangle size={15} className="shrink-0" />}
              <span className="font-semibold">{scanRun.status}</span>
              <span>
                {scanRun.accountsScanned ?? 0}/{scanRun.accountsTotal ?? 0} accounts scanned
                {scanRun.accountsFailed > 0 && `, ${scanRun.accountsFailed} failed`}.
                {totals.totalResources > 0 && ` ${totals.totalResources} resources found.`}
              </span>
            </div>
          );
        }
        // Group by service code, count unique accounts
        const grouped = {};
        for (const w of permWarns) {
          if (!grouped[w.code]) grouped[w.code] = new Set();
          if (w.awsAccountId) grouped[w.code].add(w.awsAccountId);
        }
        const serviceCount = Object.keys(grouped).length;
        return (
          <div className="mb-4 rounded-xl text-sm ring-1 bg-amber-50 text-amber-800 ring-amber-200 overflow-hidden">
            <div className="flex items-center justify-between gap-2 px-4 py-3">
              <div className="flex items-center gap-2 min-w-0">
                <AlertTriangle size={15} className="shrink-0" />
                <span className="font-semibold shrink-0">COMPLETED WITH WARNINGS</span>
                <span className="truncate">
                  {scanRun.accountsScanned ?? 0}/{scanRun.accountsTotal ?? 0} accounts scanned
                  {scanRun.accountsFailed > 0 && `, ${scanRun.accountsFailed} failed`}.
                  {totals.totalResources > 0 && ` ${totals.totalResources} resources found.`}
                </span>
              </div>
              <button onClick={() => setShowPermDetails(v => !v)}
                className="shrink-0 flex items-center gap-1 text-xs font-semibold text-amber-700 hover:text-amber-900 underline underline-offset-2 whitespace-nowrap">
                {showPermDetails ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                {showPermDetails ? "Hide" : `View missing permissions (${serviceCount})`}
              </button>
            </div>
            {showPermDetails && (
              <div className="border-t border-amber-200 px-4 py-3 bg-amber-50/60">
                <p className="text-xs font-semibold text-amber-700 mb-2">
                  Add these actions to <span className="font-mono">EOLMonitorReadOnly</span> member role (via StackSet update):
                </p>
                <div className="space-y-2">
                  {Object.entries(grouped).map(([code, accts]) => {
                    const info = PERM_DETAILS[code];
                    if (!info) return null;
                    return (
                      <div key={code} className="flex items-start gap-3 text-xs">
                        <span className="w-36 shrink-0 font-medium text-amber-800">{info.label}</span>
                        <span className="flex-1 font-mono text-amber-700 break-all">{info.actions.join(", ")}</span>
                        <span className="shrink-0 text-amber-500">{accts.size} acct{accts.size === 1 ? "" : "s"}</span>
                      </div>
                    );
                  })}
                </div>
                <p className="text-[10px] text-amber-500 mt-3">
                  Re-deploy the StackSet template from the setup wizard to push these permissions to all member accounts.
                </p>
              </div>
            )}
          </div>
        );
      })()}
      {scanState === "error" && (
        <div className="mb-4 flex items-center gap-2 px-4 py-3 rounded-xl text-sm bg-amber-50 text-amber-700 ring-1 ring-amber-200">
          <AlertTriangle size={15} className="shrink-0" />
          <span>
            {(scanRun?.accountsFailed ?? 0) > 0
              ? `${scanRun.accountsFailed} account${scanRun.accountsFailed === 1 ? "" : "s"} need attention — check the role setup below.`
              : scanRun?.error || "Scan completed with issues. Check organization connection."}
          </span>
        </div>
      )}

      {/* Summary stat cards — skeleton while loading, real data once ready */}
      {dashLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-5 animate-pulse">
          {[...Array(7)].map((_, i) => (
            <div key={i} className="rounded-xl bg-gray-100 h-16" />
          ))}
        </div>
      ) : null}
      {!dashLoading && (() => {
        const total          = accounts.length;
        const scanned        = accounts.filter(a => a.lastScanStatus === "SUCCESS").length;
        const running        = accounts.filter(a => a.lastScanStatus === "RUNNING").length;
        const failed         = accounts.filter(a => a.lastScanStatus === "FAILED").length;
        const notStarted     = accounts.filter(a => !a.lastScanStatus || a.lastScanStatus === "NOT_SCANNED").length;
        const NOT_TRACKED_ST = new Set(["LIFECYCLE_NOT_TRACKED", "NEEDS_INSPECTION", "UNKNOWN"]);
        const notTrackedCt   = inventory.filter(i => NOT_TRACKED_ST.has(i.status)).length;
        const failedAcctsWithNoInventory = accounts.filter(a => a.lastScanStatus === "FAILED" && !a.lastScanAt).length;

        const scanStateCards = [
          { label:"Accounts",        value: total,   bg:"bg-gray-100",  text:"text-gray-700"   },
          { label:"Scanned",         value: scanned, bg:"bg-indigo-50", text:"text-indigo-800" },
          ...(running > 0    ? [{ label:"Running",     value: running,    bg:"bg-indigo-50", text:"text-indigo-600" }] : []),
          ...(failed > 0     ? [{ label:"Failed",      value: failed,     bg:"bg-red-50",    text:"text-red-700"   }] : []),
          ...(notStarted > 0 ? [{ label:"Not Started", value: notStarted, bg:"bg-gray-50",   text:"text-gray-400"  }] : []),
        ];
        const lifecycleCards = [
          { label:"EOL",           value: totals.eol ?? 0,             bg:"bg-red-50",   text:"text-red-800"   },
          { label:"Expiring Soon", value: totals.expiringSoon ?? 0,    bg:"bg-amber-50", text:"text-amber-800" },
          { label:"Ext. Support",  value: totals.extendedSupport ?? 0, bg:"bg-blue-50",  text:"text-blue-800"  },
          { label:"Supported",     value: totals.supported ?? 0,       bg:"bg-green-50", text:"text-green-800" },
        ];

        return (
          <>
            {/* Account state cards */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-3">
              {scanStateCards.map(s => (
                <div key={s.label} className={`rounded-xl px-4 py-3 ${s.bg}`}>
                  <p className={`text-2xl font-extrabold ${s.text}`}>{s.value}</p>
                  <p className={`text-xs font-semibold uppercase tracking-wide mt-0.5 ${s.text} opacity-70`}>{s.label}</p>
                </div>
              ))}
            </div>

            {/* Lifecycle risk cards — only meaningful when accounts have been scanned */}
            {scanned > 0 && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
                {lifecycleCards.map(s => (
                  <div key={s.label} className={`rounded-xl px-4 py-3 ${s.bg}`}>
                    <p className={`text-2xl font-extrabold ${s.text}`}>{s.value}</p>
                    <p className={`text-xs font-semibold uppercase tracking-wide mt-0.5 ${s.text} opacity-70`}>{s.label}</p>
                  </div>
                ))}
              </div>
            )}

            {notTrackedCt > 0 && scanned > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-3">
                <div className="rounded-xl px-4 py-3 bg-slate-100">
                  <p className="text-2xl font-extrabold text-slate-600">{notTrackedCt}</p>
                  <p className="text-xs font-semibold uppercase tracking-wide mt-0.5 text-slate-500 opacity-70">Not Tracked</p>
                </div>
              </div>
            )}

            {/* Helper text when failed accounts have no inventory at all */}
            {failedAcctsWithNoInventory > 0 && scanned === 0 && (
              <p className="text-xs text-amber-600 mb-3">
                {failedAcctsWithNoInventory} account{failedAcctsWithNoInventory !== 1 ? "s" : ""} could not be evaluated — fix the role setup and re-scan to collect inventory.
              </p>
            )}

            <div className="mb-2" />
          </>
        );
      })()}

      {/* Action banner — separate not-started and failed states */}
      {scanState !== "running" && scanState !== "stopping" && (() => {
        const notStarted  = accounts.filter(a => !a.lastScanStatus || a.lastScanStatus === "NOT_SCANNED" || a.lastScanStatus === "CANCELLED").length;
        const failedAccts = accounts.filter(a => a.lastScanStatus === "FAILED").length;
        if (notStarted === 0 && failedAccts === 0) return null;
        return (
          <div className="mb-5 space-y-2">
            {notStarted > 0 && (
              <div className="flex items-center justify-between gap-4 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm">
                <div className="flex items-center gap-2 text-amber-700">
                  <AlertTriangle size={15} className="shrink-0" />
                  <span>
                    {notStarted} account{notStarted !== 1 ? "s" : ""} {failedAccts > 0 ? "not yet scanned." : "have not been scanned yet."}
                  </span>
                </div>
                <button onClick={startScan} className="shrink-0 text-xs font-semibold text-amber-700 underline hover:text-amber-900">
                  Scan all accounts →
                </button>
              </div>
            )}
            {failedAccts > 0 && (
              <div className="flex items-center justify-between gap-4 bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm">
                <div className="flex items-center gap-2 text-red-700">
                  <XCircle size={15} className="shrink-0" />
                  <span>
                    {failedAccts} account{failedAccts !== 1 ? "s" : ""} failed — scan role could not be assumed. Fix the IAM role and retry.
                  </span>
                </div>
                <button onClick={startScan} className="shrink-0 text-xs font-semibold text-red-700 underline hover:text-red-900">
                  Retry all →
                </button>
              </div>
            )}
          </div>
        );
      })()}

      {/* Management account setup callout */}
      {accounts.some(a => a.accountType === "MANAGEMENT" && a.lastErrorCode === "MANAGEMENT_ROLE_MISSING") && (
        <div className="mb-5 rounded-xl border border-purple-200 bg-purple-50 px-4 py-3 text-sm">
          <div className="flex items-start gap-2 text-purple-800">
            <ShieldAlert size={15} className="shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold mb-0.5">Management account scan role not found</p>
              <p className="text-purple-700 text-xs leading-relaxed">
                AWS StackSets do not deploy to the management account by default.
                To scan management account resources, deploy the <strong>EOLMonitorReadOnly</strong> CloudFormation template
                (from Step 4 of the setup wizard) directly in the management account — not via StackSet.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 mb-5">
        {[
          { key:"accounts",  label:"Account Summary"   },
          { key:"inventory", label:"Resource Inventory" },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-lg text-sm font-semibold border transition-all ${
              tab === t.key ? "bg-gray-900 text-white border-gray-900" : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50"}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Account Summary tab */}
      {tab === "accounts" && (() => {
        if (dashLoading) return (
          <div className="bg-white rounded-xl border border-gray-100 p-10 animate-pulse space-y-3">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-10 rounded-lg bg-gray-100" />
            ))}
          </div>
        );

        const acctFiltered = accounts.filter(a => {
          const matchStatus =
            acctStatusFilter === "all"         ? true :
            acctStatusFilter === "scanned"     ? a.lastScanStatus === "SUCCESS" :
            acctStatusFilter === "running"     ? a.lastScanStatus === "RUNNING" :
            acctStatusFilter === "failed"      ? a.lastScanStatus === "FAILED" :
            /* not_started */                   !a.lastScanStatus || a.lastScanStatus === "NOT_SCANNED";
          const matchSearch = !acctSearch || (a.name || "").toLowerCase().includes(acctSearch.toLowerCase()) ||
            (a.awsAccountId || "").includes(acctSearch);
          return matchStatus && matchSearch;
        });

        if (accounts.length === 0) return (
          <div className="bg-white rounded-xl border border-gray-100 p-12 text-center">
            <AlertTriangle size={32} className="mx-auto mb-3 text-amber-400" strokeWidth={1.5} />
            <p className="text-gray-600 mb-2">No accounts discovered yet.</p>
            <p className="text-sm text-gray-400 mb-4">Click "Rediscover Accounts" to fetch member accounts from AWS Organizations.</p>
            <button onClick={rediscover} className="px-4 py-2 bg-gray-900 text-white rounded-xl text-sm font-semibold">
              Discover Accounts Now
            </button>
          </div>
        );

        return (
          <div className="bg-white rounded-xl shadow-sm overflow-hidden">
            {/* Table toolbar */}
            <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-gray-100">
              <input value={acctSearch} onChange={e => setAcctSearch(e.target.value)}
                placeholder="Search account name or ID…"
                className="flex-1 min-w-[180px] text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-300/50" />
              <div className="flex gap-1.5 flex-wrap">
                {[
                  { key:"all",         label:"All"         },
                  { key:"scanned",     label:"Scanned"     },
                  { key:"running",     label:"Running"     },
                  { key:"failed",      label:"Failed"      },
                  { key:"not_started", label:"Not Started" },
                ].map(f => (
                  <button key={f.key} onClick={() => setAcctStatusFilter(f.key)}
                    className={`px-3 py-1 text-xs font-semibold rounded-lg border transition-all ${
                      acctStatusFilter === f.key ? "bg-gray-900 text-white border-gray-900" : "bg-white border-gray-200 text-gray-500 hover:bg-gray-50"}`}>
                    {f.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    {["Account","Account ID","EOL","Expiring","Ext. Support","Supported","Risk","Last Scanned","Status","Issue","Action"].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {acctFiltered.length === 0 ? (
                    <tr><td colSpan={11} className="px-4 py-10 text-center text-sm text-gray-400">No accounts match this filter.</td></tr>
                  ) : acctFiltered.map(acct => {
                    const s = acct.lastScanSummary || {};
                    const totRow = { EOL: s.EOL||0, EXPIRING_SOON: s.EXPIRING_SOON||0, EXTENDED_SUPPORT: s.EXTENDED_SUPPORT||0, SUPPORTED: s.SUPPORTED||0 };
                    const masked = acct.awsAccountId ? `****${acct.awsAccountId.slice(-4)}` : "—";
                    return (
                      <tr key={acct.id} className="border-b border-gray-100 hover:bg-gray-50/60 transition-colors">
                        <td className="px-4 py-3 font-medium text-gray-900">
                          <span>{acct.name}</span>
                          {acct.accountType === "MANAGEMENT" && (
                            <span className="ml-1.5 text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-purple-100 text-purple-700 uppercase tracking-wide align-middle">MGMT</span>
                          )}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-gray-500">{masked}</td>
                        <td className="px-4 py-3 font-bold" style={{ color: totRow.EOL > 0 ? "#922B21" : "#9CA3AF" }}>{totRow.EOL}</td>
                        <td className="px-4 py-3 font-bold" style={{ color: totRow.EXPIRING_SOON > 0 ? "#B7770D" : "#9CA3AF" }}>{totRow.EXPIRING_SOON}</td>
                        <td className="px-4 py-3 font-bold" style={{ color: totRow.EXTENDED_SUPPORT > 0 ? "#1A6EBD" : "#9CA3AF" }}>{totRow.EXTENDED_SUPPORT}</td>
                        <td className="px-4 py-3 text-gray-600">{totRow.SUPPORTED}</td>
                        <td className="px-4 py-3 min-w-[100px]"><RiskBar totals={totRow} /></td>
                        <td className="px-4 py-3 text-xs text-gray-400 whitespace-nowrap">
                          {acct.lastScanAt ? new Date(acct.lastScanAt).toLocaleDateString() : "—"}
                        </td>
                        <td className="px-4 py-3">
                          {acct.lastScanStatus === "SUCCESS"
                            ? <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">Scanned</span>
                            : acct.lastScanStatus === "FAILED"
                              ? <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium">Failed</span>
                              : acct.lastScanStatus === "RUNNING"
                                ? <span className="inline-flex items-center gap-1 text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-medium"><Loader2 size={10} className="animate-spin" /> Running</span>
                                : <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full font-medium">Not scanned</span>}
                        </td>
                        <td className="px-4 py-3 max-w-[200px]">
                          {acct.lastScanStatus === "FAILED" ? (
                            <IssueCell acct={acct} />
                          ) : acct.lastScanStatus === "RUNNING" ? (
                            <span className="text-xs text-indigo-500 font-medium">Scanning…</span>
                          ) : null}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <AccountActionCell
                            acct={acct}
                            onViewResources={() => navigate(`/dashboard?source=ORG_SCAN&account_id=${encodeURIComponent(acct.awsAccountId)}`)}
                            onRetryScan={startScan}
                            scanRunning={scanState === "running" || scanState === "stopping"}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="px-4 py-3 border-t border-gray-100 text-xs text-gray-400">
              Showing {acctFiltered.length} of {accounts.length} accounts
            </div>
          </div>
        );
      })()}

      {/* Resource Inventory tab */}
      {tab === "inventory" && (() => {
        const NOT_TRACKED = new Set(["LIFECYCLE_NOT_TRACKED", "NEEDS_INSPECTION"]);
        const notTrackedCount = inventory.filter(i => NOT_TRACKED.has(i.status)).length;
        const acctMap = new Map(accounts.map(a => [a.awsAccountId, a]));

        const filteredInv = statusFilter
          ? inventory.filter(i => i.status === statusFilter)
          : inventory;
        const sortedInv = [...filteredInv].sort((a, b) => {
          const d = (STATUS_PRIORITY[a.status] ?? 9) - (STATUS_PRIORITY[b.status] ?? 9);
          return d !== 0 ? d : (a.daysToEol ?? 0) - (b.daysToEol ?? 0);
        });

        const FILTER_TABS = [
          { key: "",                    label: "All"         },
          { key: "EOL",                 label: "EOL"         },
          { key: "EXPIRING_SOON",       label: "Expiring"    },
          { key: "EXTENDED_SUPPORT",    label: "Ext. Support"},
          { key: "SUPPORTED",           label: "Supported"   },
          ...(notTrackedCount > 0 ? [{ key: "LIFECYCLE_NOT_TRACKED", label: `Not Tracked (${notTrackedCount})` }] : []),
        ];

        function shortId(raw) {
          if (!raw || raw === "—") return raw;
          if (raw.startsWith("arn:")) {
            const parts = raw.split(":");
            const last = parts[parts.length - 1] || raw;
            return last.length > 36 ? `…${last.slice(-36)}` : last;
          }
          return raw.length > 40 ? `${raw.slice(0, 38)}…` : raw;
        }

        return (
          <>
            <div className="flex flex-wrap items-center gap-2 mb-3">
              {FILTER_TABS.map(({ key, label }) => (
                <button key={key} onClick={() => setStatusFilter(key)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all ${
                    statusFilter === key ? "bg-gray-900 text-white border-gray-900" : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50"}`}>
                  {label}
                </button>
              ))}
            </div>
            {sortedInv.length === 0 ? (
              <div className="bg-white rounded-xl border border-gray-100 p-12 text-center">
                {inventory.length === 0 ? (
                  <>
                    <p className="text-gray-500 mb-2">No resources found yet.</p>
                    {failedAcctsWithNoInventory > 0 ? (
                      <p className="text-sm text-amber-600">
                        {failedAcctsWithNoInventory} account{failedAcctsWithNoInventory !== 1 ? "s" : ""} need role setup before inventory can be collected — fix the role and re-scan.
                      </p>
                    ) : (
                      <p className="text-sm text-gray-400">Run a scan to populate the inventory.</p>
                    )}
                  </>
                ) : statusFilter === "EOL" ? (
                  <>
                    <p className="text-gray-500 mb-2">No EOL resources in this inventory.</p>
                    {notTrackedCount > 0 && (
                      <p className="text-sm text-gray-400">
                        {notTrackedCount} resource{notTrackedCount === 1 ? "" : "s"} found with no lifecycle data — click <strong>Not Tracked</strong> to inspect them.
                      </p>
                    )}
                  </>
                ) : statusFilter ? (
                  <>
                    <p className="text-gray-500 mb-2">No resources with this status.</p>
                    <p className="text-sm text-gray-400">Try a different filter or clear to see all.</p>
                  </>
                ) : (
                  <>
                    <p className="text-gray-500 mb-2">No resources found.</p>
                    <p className="text-sm text-gray-400">Run a scan to populate the inventory.</p>
                  </>
                )}
              </div>
            ) : (
              <div className="bg-white rounded-xl shadow-sm overflow-hidden">
                <table className="w-full text-sm table-fixed">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200">
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide w-32">Account</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide w-24">Service</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Resource</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide w-24">Region</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide w-28">Version</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide w-36">Status</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide w-24">EOL Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedInv.map(item => {
                      const rawId      = String(item.accountName || "");
                      const acct       = acctMap.get(rawId);
                      const acctName   = acct?.name;
                      const displayName = acctName && acctName !== rawId ? acctName : null;
                      const maskedId   = rawId.length >= 4 ? `****${rawId.slice(-4)}` : rawId;
                      const isUntracked = NOT_TRACKED.has(item.status);
                      return (
                        <tr key={item.id} className="border-b border-gray-100 hover:bg-blue-50/30 transition-colors">
                          <td className="px-4 py-3 min-w-0">
                            {displayName && <p className="text-xs font-medium text-gray-800 truncate" title={displayName}>{displayName}</p>}
                            <p className="font-mono text-[10px] text-gray-400">{maskedId}</p>
                          </td>
                          <td className="px-4 py-3 text-gray-600 whitespace-nowrap text-xs">{serviceLabel(item.service)}</td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-1.5 min-w-0">
                              <span className="font-mono text-xs text-gray-700 truncate" title={item.resourceName}>
                                {shortId(item.resourceName)}
                              </span>
                              {item.resourceName && item.resourceName !== "—" && (
                                <button onClick={() => copyToClipboard(item.resourceName)}
                                  className="shrink-0 text-gray-300 hover:text-gray-600 transition-colors" title="Copy full ID">
                                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                                </button>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-3 font-mono text-xs text-gray-500 whitespace-nowrap">{item.region}</td>
                          <td className="px-4 py-3 font-mono text-xs text-gray-600 truncate" title={item.version}>{item.version}</td>
                          <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
                          <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap"
                            title={isUntracked ? "No published EOL schedule" : undefined}>
                            {isUntracked ? <span className="text-gray-300">—</span> : item.eolDate}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <div className="px-4 py-3 border-t border-gray-100 text-xs text-gray-400">
                  Showing {sortedInv.length} of {inventory.length} resources
                </div>
              </div>
            )}
          </>
        );
      })()}

      {/* Edit regions modal */}
      {showEditRegions && (
        <EditOrgRegionsModal
          conn={activeConn}
          onSave={async () => {
            setShowEditRegions(false);
            await fetchSummary();
          }}
          onCancel={() => setShowEditRegions(false)}
        />
      )}

      {/* Disconnect confirmation modal */}
      {showCancelConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl p-8 max-w-md w-full mx-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                <X size={18} className="text-red-600" />
              </div>
              <h2 className="text-lg font-bold text-gray-900">Stop organization scan?</h2>
            </div>
            <p className="text-sm text-gray-600 mb-2">
              The scan will finish the current account, then stop. Accounts scanned so far will keep their results.
            </p>
            <p className="text-sm text-gray-500 mb-6">
              Pending accounts will remain as <strong>Not Scanned</strong>. You can restart the scan anytime.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setShowCancelConfirm(false)}
                className="px-4 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">
                Keep scanning
              </button>
              <button onClick={cancelScan}
                className="px-4 py-2 text-sm rounded-lg bg-red-600 text-white font-semibold hover:bg-red-700">
                Stop scan
              </button>
            </div>
          </div>
        </div>
      )}

      {showDisconnectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl p-8 max-w-md w-full mx-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center shrink-0">
                <Unplug size={18} className="text-amber-600" />
              </div>
              <h2 className="text-lg font-bold text-gray-900">Disconnect AWS Organization?</h2>
            </div>
            <p className="text-sm text-gray-600 mb-2">
              This will pause scanning for this connection. Your connection details and scan history will be preserved.
            </p>
            <p className="text-sm text-gray-500 mb-6">
              IAM roles and StackSets in your AWS accounts will <strong>not</strong> be deleted.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setShowDisconnectModal(false)}
                className="px-4 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">
                Cancel
              </button>
              <button disabled={disconnecting} onClick={async () => {
                setDisconnecting(true);
                try {
                  const updated = await orgApi(`/org-connections/${conn.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({ status: "DISCONNECTED" }),
                  });
                  onDisconnect(updated.connection || { ...conn, status: "DISCONNECTED" });
                } catch {
                  setDisconnecting(false);
                  setShowDisconnectModal(false);
                }
              }} className="px-4 py-2 text-sm rounded-lg bg-amber-600 text-white font-semibold hover:bg-amber-700 disabled:opacity-60">
                {disconnecting ? "Disconnecting…" : "Disconnect"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Disconnected profile page ──────────────────────────────────────────────────

const RECONNECT_STEPS = [
  "Validating IAM access",
  "Rediscovering accounts",
  "Resuming scanning",
];

function OrgDisconnectedPage({ conn, onReconnect, onDelete }) {
  const [reconnectStep, setReconnectStep] = useState(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showSetup, setShowSetup]           = useState(false);
  const [deleteInput, setDeleteInput]       = useState("");
  const [deleting, setDeleting]             = useState(false);
  const [reconnectErr, setReconnectErr]     = useState(null);
  const [copiedKey, setCopiedKey]           = useState(null);

  function copyField(key, value) {
    copyToClipboard(value).then(() => {
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 1500);
    });
  }

  async function handleReconnect() {
    setReconnectErr(null);
    try {
      setReconnectStep(0);
      await orgApi("/org-connections/validate-role", {
        method: "POST",
        body: JSON.stringify({
          managementAccountId: conn.managementAccountId,
          roleArn:             conn.roleArn,
          externalId:          conn.externalId,
          regions:             conn.regions,
        }),
      });
      setReconnectStep(1);
      const patchRes = await orgApi(`/org-connections/${conn.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "CONNECTED" }),
      });
      await orgApi(`/org-connections/${conn.id}/discover`, { method: "POST" });
      setReconnectStep(2);
      await new Promise(r => setTimeout(r, 600));
      onReconnect(patchRes.connection || { ...conn, status: "CONNECTED" });
    } catch (err) {
      setReconnectErr(err.message || `Reconnect failed. Ensure the org role trust policy allows ${SCANNER_ROLE_ARN} and ExternalId matches.`);
      setReconnectStep(null);
    }
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await orgApi(`/org-connections/${conn.id}`, { method: "DELETE" });
      onDelete();
    } catch {
      setDeleting(false);
    }
  }

  const fields = [
    { key: "name",   label: "Connection Name",  value: conn.name || "AWS Organization", copy: false },
    { key: "acct",   label: "Admin Account ID", value: conn.managementAccountId || "—", copy: false },
    { key: "arn",    label: "Org Role ARN",      value: conn.roleArn || "—",            copy: true  },
    { key: "extId",  label: "ExternalId",        value: conn.externalId || "—",         copy: true  },
    { key: "member", label: "Member Role Name",  value: "EOLMonitorReadOnly",            copy: true  },
    { key: "region", label: "Regions",           value: (conn.regions || []).join(", ") || "—", copy: false },
  ];

  const reconnecting = reconnectStep !== null;
  const lastScanDate = conn.lastScanAt ? new Date(conn.lastScanAt).toLocaleDateString() : null;

  return (
    <div className="px-4 sm:px-6 py-6 sm:py-8 max-w-7xl mx-auto">

      {/* Status header strip */}
      <div className="bg-white border border-amber-200 rounded-2xl p-6 mb-6 flex flex-col sm:flex-row sm:items-center gap-5">
        <div className="flex items-center gap-4 flex-1 min-w-0">
          <div className="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center shrink-0">
            <Unplug size={22} className="text-amber-600" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-0.5">
              <h1 className="text-xl font-bold text-gray-900">{conn.name || "AWS Organization"}</h1>
              <span className="text-xs font-bold bg-amber-100 text-amber-700 px-2.5 py-0.5 rounded-full uppercase tracking-wide">Paused</span>
            </div>
            <p className="text-sm text-gray-500">
              Scanning disabled{lastScanDate && ` · Last scan ${lastScanDate}`}
              {conn.managementAccountId && ` · Admin account ${conn.managementAccountId}`}
            </p>
            <p className="text-xs text-gray-400 mt-1">Reconnect to resume account discovery, scans, and alert updates.</p>
          </div>
        </div>
        <button onClick={handleReconnect} disabled={reconnecting}
          className="shrink-0 flex items-center gap-2 px-5 py-2.5 bg-indigo-600 text-white text-sm font-semibold rounded-xl hover:bg-indigo-700 disabled:opacity-60 transition-colors">
          {reconnecting ? <><Loader2 size={14} className="animate-spin" /> Reconnecting…</> : "Reconnect Organization"}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">

        {/* Impact summary */}
        <div className="lg:col-span-2 bg-white rounded-2xl border border-gray-200 p-6">
          <h2 className="text-sm font-bold text-gray-700 uppercase tracking-wide mb-4">Impact while paused</h2>
          <div className="space-y-3">
            {[
              { Icon: ScanLine,       text: "Member accounts will not be scanned",                          color: "text-red-400"    },
              { Icon: BellOff,        text: "EOL alerts and notifications will not be sent",                color: "text-amber-400"  },
              { Icon: FileText,       text: "Existing scan reports may become stale",                      color: "text-gray-400"   },
              { Icon: ShieldAlert,    text: "IAM roles and StackSets in AWS are still active until manually deleted", color: "text-gray-400" },
            ].map(({ Icon, text, color }) => (
              <div key={text} className="flex items-start gap-3 text-sm text-gray-600">
                <Icon size={15} className={`shrink-0 mt-0.5 ${color}`} />
                <span>{text}</span>
              </div>
            ))}
          </div>

          {/* Reconnect progress */}
          {reconnecting && (
            <div className="mt-5 bg-indigo-50 border border-indigo-200 rounded-xl px-5 py-4">
              <div className="flex flex-col gap-2">
                {RECONNECT_STEPS.map((label, i) => (
                  <div key={i} className={`flex items-center gap-2.5 text-sm ${i < reconnectStep ? "text-green-600" : i === reconnectStep ? "text-indigo-700 font-medium" : "text-gray-400"}`}>
                    {i < reconnectStep
                      ? <Check size={14} className="shrink-0" />
                      : i === reconnectStep
                        ? <Loader2 size={14} className="animate-spin shrink-0" />
                        : <span className="w-3.5 h-3.5 rounded-full border border-gray-300 inline-block shrink-0" />}
                    {label}
                  </div>
                ))}
              </div>
            </div>
          )}

          {reconnectErr && (
            <div className="mt-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
              {reconnectErr}
            </div>
          )}
        </div>

        {/* Setup details card */}
        <div className="bg-white rounded-2xl border border-gray-200 p-6">
          <button onClick={() => setShowSetup(v => !v)}
            className="w-full flex items-center justify-between text-sm font-bold text-gray-700 uppercase tracking-wide mb-3">
            <span>Setup Details</span>
            <span className="flex items-center gap-1 text-xs font-semibold text-indigo-500 normal-case tracking-normal">
              {showSetup ? <><ChevronUp size={13} /> Hide details</> : <><ChevronDown size={13} /> Show details</>}
            </span>
          </button>
          {!showSetup && (
            <div className="space-y-2 mb-1">
              {[
                { label: "Org role",     value: conn.roleArn     ? "Configured" : "Not set", ok: !!conn.roleArn     },
                { label: "Member role",  value: "EOLMonitorReadOnly",                         ok: true               },
                { label: "Regions",      value: (conn.regions?.length ?? 0) > 0 ? `${conn.regions.length} region${conn.regions.length === 1 ? "" : "s"} selected` : "All enabled regions", ok: true },
              ].map(({ label, value, ok }) => (
                <div key={label} className="flex items-center gap-2 text-xs text-gray-500">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${ok ? "bg-green-400" : "bg-gray-300"}`} />
                  <span className="font-medium text-gray-500 w-24 shrink-0">{label}</span>
                  <span className="text-gray-400 truncate">{value}</span>
                </div>
              ))}
              <p className="text-[10px] text-gray-300 pt-1">Expand to copy ARN, ExternalId, and role name.</p>
            </div>
          )}
          {showSetup && (
            <div className="divide-y divide-gray-100">
              {fields.map(f => (
                <div key={f.key} className="flex items-start gap-2 py-2.5">
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-0.5">{f.label}</p>
                    <p className="font-mono text-xs text-gray-800 break-all">{f.value}</p>
                  </div>
                  {f.copy && f.value !== "—" && (
                    <button onClick={() => copyField(f.key, f.value)}
                      className="shrink-0 mt-1 text-[10px] font-semibold px-1.5 py-0.5 rounded border border-gray-200 text-gray-400 hover:text-indigo-600 hover:border-indigo-300 transition-colors">
                      {copiedKey === f.key ? "✓" : "Copy"}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Danger zone */}
      <div className="bg-white rounded-2xl border border-red-100 p-6">
        <h2 className="text-sm font-bold text-red-600 uppercase tracking-wide mb-2">Danger Zone</h2>
        <p className="text-sm text-gray-500 mb-4">
          Permanently removes this connection and scan history from AWS EOL Monitor.
          IAM roles and StackSets in your AWS accounts will <strong>remain active</strong> until you delete them manually.
        </p>
        <button onClick={() => { setShowDeleteModal(true); setDeleteInput(""); }}
          disabled={reconnecting}
          className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-xl border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-40">
          <Trash2 size={13} /> Delete Connection
        </button>
      </div>

      {/* Delete modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl p-8 max-w-md w-full mx-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                <Trash2 size={18} className="text-red-600" />
              </div>
              <h2 className="text-lg font-bold text-gray-900">Delete Organization Connection?</h2>
            </div>
            <p className="text-sm text-gray-600 mb-3">
              This removes this connection and scan history from AWS EOL Monitor.
              IAM roles and StackSets in AWS will <strong>remain active</strong> until you delete them manually.
            </p>
            <div className="bg-gray-50 rounded-lg px-4 py-3 mb-4 text-xs text-gray-500 space-y-1">
              <p className="font-semibold text-gray-600 mb-1.5">To revoke AWS access, delete:</p>
              <p>• IAM role: <span className="font-mono">EOLMonitorOrgReadOnly</span> (in admin account)</p>
              <p>• StackSet: <span className="font-mono">aws-eol-monitor-member-roles</span> (and its stack instances)</p>
              <p>• Member role: <span className="font-mono">EOLMonitorReadOnly</span> (auto-removed when StackSet is deleted)</p>
            </div>
            <div className="mb-6">
              <label className="block text-xs font-semibold text-gray-600 mb-1.5">Type DELETE to confirm</label>
              <input value={deleteInput} onChange={e => setDeleteInput(e.target.value)}
                placeholder="DELETE"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-red-300" />
            </div>
            <div className="flex justify-end gap-3">
              <button onClick={() => setShowDeleteModal(false)}
                className="px-4 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">
                Cancel
              </button>
              <button disabled={deleteInput !== "DELETE" || deleting} onClick={handleDelete}
                className="px-4 py-2 text-sm rounded-lg bg-red-600 text-white font-semibold hover:bg-red-700 disabled:opacity-40">
                {deleting ? "Deleting…" : "Delete Connection"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Page root ──────────────────────────────────────────────────────────────────

function getOrCreateExternalId() {
  const wsId = getWorkspaceId() || "default";
  const key  = `org_ext_id_${wsId}`;
  let id = localStorage.getItem(key);
  if (!id) {
    id = `org-eolm-${Math.random().toString(36).substring(2,6).toUpperCase()}-${Math.random().toString(36).substring(2,8).toUpperCase()}`;
    localStorage.setItem(key, id);
  }
  return id;
}

export default function OrgScanPage() {
  const [pageState, setPageState] = useState("loading"); // loading | wizard | dashboard | disconnected
  const [activeConn, setActiveConn] = useState(null);
  const externalId = useMemo(() => getOrCreateExternalId(), []);

  useEffect(() => {
    const wsId = getWorkspaceId();
    if (!wsId) { setPageState("wizard"); return; }
    fetch(`${API_BASE_URL}/workspaces/${wsId}/org-connections`, { headers: workspaceHeaders() })
      .then(r => r.json())
      .then(data => {
        const conns = data.connections || [];
        if (conns.length > 0) {
          const conn = conns[0];
          setActiveConn(conn);
          setPageState(conn.status === "DISCONNECTED" ? "disconnected" : "dashboard");
        } else {
          setPageState("wizard");
        }
      })
      .catch(() => setPageState("wizard"));
  }, []);

  if (pageState === "loading") {
    return (
      <div className="p-10 text-center">
        <Loader2 size={32} className="mx-auto mb-3 text-indigo-400 animate-spin" strokeWidth={1.5} />
        <p className="text-sm text-gray-400">Loading…</p>
      </div>
    );
  }

  if (pageState === "dashboard") {
    return (
      <OrgDashboard
        conn={activeConn}
        onDisconnect={updatedConn => {
          setActiveConn(updatedConn);
          setPageState("disconnected");
        }}
      />
    );
  }

  if (pageState === "disconnected") {
    return (
      <OrgDisconnectedPage
        conn={activeConn}
        onReconnect={updatedConn => { setActiveConn(updatedConn); setPageState("dashboard"); }}
        onDelete={() => { setActiveConn(null); setPageState("wizard"); }}
      />
    );
  }

  return (
    <OrgWizard
      externalId={externalId}
      onConnected={conn => { setActiveConn(conn); setPageState("dashboard"); }}
    />
  );
}
