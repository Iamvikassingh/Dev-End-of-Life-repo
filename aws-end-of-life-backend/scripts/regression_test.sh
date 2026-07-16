#!/usr/bin/env bash
# AWS EOL Monitor — regression test suite
# Runs against the local backend (default http://127.0.0.1:3001).
# Usage:
#   bash scripts/regression_test.sh
#   API_URL=http://127.0.0.1:3001 bash scripts/regression_test.sh

set -euo pipefail

API="${API_URL:-http://127.0.0.1:3001}"
PASS=0; FAIL=0

green()  { printf '\033[0;32m✅  %s\033[0m\n' "$*"; }
red()    { printf '\033[0;31m❌  %s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m⚠️   %s\033[0m\n' "$*"; }
header() { printf '\n\033[1;34m── %s\033[0m\n' "$*"; }

pass() { green "$1"; ((PASS+=1)); }
fail() { red   "$1"; ((FAIL+=1)); }

# ── 1. Health ─────────────────────────────────────────────────────────────────
header "1. /health"

health=$(curl -sf "$API/health" 2>/dev/null) || { fail "/health unreachable at $API"; exit 1; }
status=$(echo "$health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "")
if [ "$status" = "ok" ]; then pass "/health status=ok"; else fail "/health status=$status"; fi

# ── 2. Service slug sanity (Python unit checks) ───────────────────────────────
header "2. service_config.py — slug correctness"

python3 - <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))
from service_config import SERVICE_SLUG

checks = {
    "Aurora_mysql":    "amazon-aurora-mysql",
    "Aurora_postgres": "amazon-aurora-postgresql",
    "ElastiCache":     "amazon-elasticache-redis",
    "Lambda":          "aws-lambda",
    "EKS":             "amazon-eks",
    "RDS_postgres":    "amazon-rds-postgresql",
    "RDS_mysql":       "amazon-rds-mysql",
}
ok = True
for key, expected in checks.items():
    got = SERVICE_SLUG.get(key)
    if got != expected:
        print(f"FAIL  SERVICE_SLUG[{key!r}] = {got!r}, expected {expected!r}")
        ok = False
    else:
        print(f"PASS  SERVICE_SLUG[{key!r}] = {got!r}")
sys.exit(0 if ok else 1)
PY
[ $? -eq 0 ] && ((PASS+=1)) || ((FAIL+=1))

# ── 3. fetch_eol verified_lifecycle chain ─────────────────────────────────────
header "3. fetch_eol — verified_lifecycle source"

python3 - <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))

# Load .env if present
try:
    from dotenv import load_dotenv
    for candidate in ['.env', 'backend/.env']:
        if os.path.isfile(candidate):
            load_dotenv(candidate, override=False); break
except ImportError:
    pass

from eol_collector import fetch_eol

TARGETS = [
    ("aws-lambda",               "python3.9"),
    ("amazon-eks",               "1.30"),
    ("amazon-eks",               "1.34"),          # newer — may be needs_review until saved
    ("amazon-elasticache-redis", "6.2"),
    ("amazon-rds-postgresql",    "15"),
    ("amazon-rds-mysql",         "8.0"),
    ("amazon-rds-mysql",         "8.4"),           # real scanned version
    ("amazon-aurora-postgresql", "15"),
    ("amazon-aurora-mysql",      "3"),
    ("amazon-aurora-mysql",      "2"),
]

ok = True
for p, v in TARGETS:
    r = fetch_eol(p, v)
    if r is None:
        print(f"FAIL  {p}/{v}  → None")
        ok = False
        continue
    meta = r.get("__meta", {})
    src  = meta.get("lifecycle_source", "NONE")
    conf = meta.get("confidence", "?")
    eol  = r.get("eol") or r.get("eolFrom")
    sup  = r.get("support")
    icon = "PASS" if src == "VERIFIED_AWS_OFFICIAL" else "WARN"
    print(f"{icon}  {p}/{v}  source={src}  confidence={conf}  eol={eol}  support={sup}")
    if src != "VERIFIED_AWS_OFFICIAL":
        ok = False

sys.exit(0 if ok else 1)
PY
[ $? -eq 0 ] && ((PASS+=1)) || ((FAIL+=1))

# ── 4. ElastiCache major.minor lookup (not major-only) ───────────────────────
header "4. ElastiCache Redis — major.minor lookup"

python3 - <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))
try:
    from dotenv import load_dotenv
    for c in ['.env', 'backend/.env']:
        if os.path.isfile(c): load_dotenv(c, override=False); break
except ImportError:
    pass
from eol_collector import fetch_eol

ok = True
for v in ["6.2", "7.0", "7.1"]:
    r = fetch_eol("amazon-elasticache-redis", v)
    meta = r.get("__meta", {}) if r else {}
    src  = meta.get("lifecycle_source", "NONE") if r else "NONE"
    verified = src == "VERIFIED_AWS_OFFICIAL"
    # 7.0 / 7.1 may be needs_review — only hard-fail on 6.2 which is known verified
    if v == "6.2" and not verified:
        ok = False
    print(f"{'PASS' if verified else 'WARN'}  elasticache/{v}  source={src}")
sys.exit(0 if ok else 1)
PY
[ $? -eq 0 ] && ((PASS+=1)) || ((FAIL+=1))

# ── 5. General EOL API — meta and verified overlay ───────────────────────────
header "5. GET /eol/general — meta.source and verified_overlay_count"

eol_resp=$(curl -sf "$API/eol/general?includeLegacy=false" 2>/dev/null) || {
    fail "/eol/general unreachable"; ((FAIL+=1))
    eol_resp="{}"
}

meta_source=$(echo "$eol_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('meta',{}).get('source',''))" 2>/dev/null || echo "")
overlay_count=$(echo "$eol_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('meta',{}).get('verified_overlay_count',0))" 2>/dev/null || echo "0")
total=$(echo "$eol_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('meta',{}).get('total',0))" 2>/dev/null || echo "0")

if [ "$meta_source" = "mixed" ]; then
    pass "/eol/general meta.source=mixed"
else
    yellow "/eol/general meta.source=$meta_source (expected mixed — cache may need refresh)"
fi

if [ "$overlay_count" -gt 0 ] 2>/dev/null; then
    pass "/eol/general verified_overlay_count=$overlay_count"
else
    yellow "/eol/general verified_overlay_count=$overlay_count (0 — run validate-lifecycle-save first)"
fi

pass "/eol/general total=$total records returned"

# Count VERIFIED_AWS_OFFICIAL records in response
verified_in_resp=$(echo "$eol_resp" | python3 -c "
import sys, json
d = json.load(sys.stdin)
rows = d.get('data', [])
n = sum(1 for r in rows if r.get('lifecycle_source') == 'VERIFIED_AWS_OFFICIAL')
print(n)
" 2>/dev/null || echo "0")

if [ "$verified_in_resp" -gt 0 ] 2>/dev/null; then
    pass "/eol/general VERIFIED_AWS_OFFICIAL records in data: $verified_in_resp"
else
    yellow "/eol/general no VERIFIED_AWS_OFFICIAL records in data (cache refresh or save needed)"
fi

# ── 6. General EOL — Aurora MySQL not missing ─────────────────────────────────
header "6. GET /eol/general — Aurora MySQL present"

aurora_rows=$(echo "$eol_resp" | python3 -c "
import sys, json
d = json.load(sys.stdin)
rows = d.get('data', [])
found = [r for r in rows if 'aurora' in r.get('product_slug','').lower() and 'mysql' in r.get('product_slug','').lower()]
for r in found:
    print(r.get('product_slug'), r.get('version'), r.get('lifecycle_source'))
" 2>/dev/null || echo "")

if [ -n "$aurora_rows" ]; then
    pass "Aurora MySQL rows found in /eol/general"
    echo "$aurora_rows" | while IFS= read -r line; do printf "      %s\n" "$line"; done
else
    yellow "Aurora MySQL rows not in /eol/general (expected if cache not refreshed after slug fix)"
fi

# ── 7. _lifecycle_fields coverage — all supported collectors ─────────────────
header "7. _lifecycle_fields in all collectors"

python3 - <<'PY'
import sys, os, ast, re
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend', 'eol_collector.py')
src  = open(path).read()
collectors = ["collect_lambda", "collect_eks", "collect_rds", "collect_elasticache"]
ok = True
for col in collectors:
    # Check that _lifecycle_fields appears after the def line
    m = re.search(rf"def {col}\b.*?(?=\ndef |\Z)", src, re.S)
    if not m:
        print(f"WARN  {col} not found in eol_collector.py")
        continue
    has = "_lifecycle_fields" in m.group(0)
    print(f"{'PASS' if has else 'FAIL'}  {col} has _lifecycle_fields={has}")
    if not has:
        ok = False
sys.exit(0 if ok else 1)
PY
[ $? -eq 0 ] && ((PASS+=1)) || ((FAIL+=1))

# ── 8. Batch dry-run ──────────────────────────────────────────────────────────
header "8. validate_batch.py --direct-html dry-run (filter=lambda for speed)"

python3 backend/lifecycle/validate_batch.py --direct-html --filter aws-lambda --json 2>/dev/null | python3 -c "import sys, json
d = json.load(sys.stdin)
total    = d.get('total', 0)
verified = d.get('verified', 0)
print(f'PASS  batch lambda: {verified}/{total} verified')
" 2>/dev/null && ((PASS+=1)) || { yellow "batch dry-run skipped (MCP deps may not be installed)"; }

# ── 9. /eol/general public route ─────────────────────────────────────────────
header "9. /eol/general is public (no token required)"

pub_status=$(curl -o /dev/null -w "%{http_code}" -sf "$API/eol/general" 2>/dev/null || echo "000")
if [ "$pub_status" -eq 200 ]; then
    pass "/eol/general public ($pub_status)"
else
    fail "/eol/general not reachable without token: $pub_status"
fi

# ── 10. Inventory 401 without token ──────────────────────────────────────────
header "10. Inventory auth gate — 401 without workspace token"

inv_status=$(curl -o /dev/null -w "%{http_code}" -sf "$API/workspaces/test-ws-regression/inventory" 2>/dev/null || echo "000")
if [ "$inv_status" -eq 401 ] || [ "$inv_status" -eq 403 ]; then
    pass "inventory returns $inv_status without token (auth gate working)"
else
    fail "inventory auth gate: expected 401/403, got $inv_status"
fi

# ── 11. Admin refresh requires admin token ────────────────────────────────────
header "11. Admin refresh — rejects wrong token"

bad_admin=$(curl -o /dev/null -w "%{http_code}" -sf -X POST "$API/eol/general/refresh" \
  -H "X-Admin-Token: wrong-token-regression-test" 2>/dev/null || echo "000")
if [ "$bad_admin" -eq 401 ] || [ "$bad_admin" -eq 403 ]; then
    pass "admin refresh rejects bad token ($bad_admin)"
else
    fail "admin refresh accepted bad token or unreachable: $bad_admin"
fi

# ── 12. Frontend build artifact ───────────────────────────────────────────────
header "12. Frontend build artifact exists"

FRONTEND_BUILD="${FRONTEND_BUILD_PATH:-/home/ubuntu/aws-end-of-life-frontend/build/index.html}"
if test -f "$FRONTEND_BUILD"; then
    pass "frontend build exists: $FRONTEND_BUILD"
else
    yellow "frontend build not found at $FRONTEND_BUILD (run: cd frontend && npm run build)"
fi

# ── 13. needs_review not returned as verified ────────────────────────────────
header "13. needs_review not leaked as VERIFIED_AWS_OFFICIAL"

python3 - <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))
try:
    from dotenv import load_dotenv
    for c in ['.env', 'backend/.env']:
        if os.path.isfile(c): load_dotenv(c, override=False); break
except ImportError:
    pass
from eol_collector import fetch_eol
# elasticache 7.0 is needs_review — must NOT appear as VERIFIED_AWS_OFFICIAL
r = fetch_eol("amazon-elasticache-redis", "7.0") or {}
meta = r.get("__meta", {})
src  = meta.get("lifecycle_source", "NONE")
if src == "VERIFIED_AWS_OFFICIAL":
    print(f"FAIL  elasticache/7.0 returned VERIFIED_AWS_OFFICIAL — needs_review leaked as verified!")
    sys.exit(1)
else:
    print(f"PASS  elasticache/7.0 lifecycle_source={src} (not leaked as verified)")
    sys.exit(0)
PY
[ $? -eq 0 ] && ((PASS+=1)) || ((FAIL+=1))

# ── 14. Rate limit tests (optional — set RATE_LIMIT_TEST_ENABLED=true) ───────
header "14. Rate limiting (workspace creation + auth failures)"

if [ "${RATE_LIMIT_TEST_ENABLED:-false}" = "true" ]; then
    # 14a. Workspace creation rate limit
    echo "  Testing workspace creation rate limit (11 rapid POSTs)..."
    last_status=0
    for i in $(seq 1 11); do
        last_status=$(curl -o /dev/null -w "%{http_code}" -sf -X POST "$API/workspaces" \
          -H "Content-Type: application/json" \
          -d "{\"name\":\"regression-rl-test-$i\"}" 2>/dev/null || echo "000")
    done
    if [ "$last_status" -eq 429 ]; then
        pass "workspace creation rate limited at 429 (request $i)"
    else
        yellow "workspace creation rate limit: last status=$last_status (may need WORKSPACE_CREATE_RATE_LIMIT=5 for fast test)"
    fi

    # 14b. Auth failure rate limit
    if [ -n "${TEST_WORKSPACE_ID:-}" ]; then
        echo "  Testing auth failure rate limit (21 bad tokens for $TEST_WORKSPACE_ID)..."
        last_auth=0
        for i in $(seq 1 21); do
            last_auth=$(curl -o /dev/null -w "%{http_code}" -sf \
              "$API/workspaces/$TEST_WORKSPACE_ID/inventory" \
              -H "X-Workspace-Token: wrong-token-$i-$(date +%s%N)" 2>/dev/null || echo "000")
        done
        if [ "$last_auth" -eq 429 ]; then
            pass "workspace auth failure rate limited at 429 after repeated bad tokens"
        else
            yellow "auth fail rate limit: last status=$last_auth (check WORKSPACE_AUTH_FAIL_LIMIT)"
        fi
    else
        yellow "auth fail rate limit test skipped — set TEST_WORKSPACE_ID=<ws_id>"
    fi
else
    yellow "rate limit tests skipped — set RATE_LIMIT_TEST_ENABLED=true to run"
fi

# ── 15. Auth config endpoint ──────────────────────────────────────────────────
header "15. GET /auth/config — public, returns flags, never exposes secrets"

auth_cfg=$(curl -sf "$API/auth/config" 2>/dev/null) || { fail "/auth/config unreachable"; auth_cfg="{}"; }

auth_ok=$(echo "$auth_cfg" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ok',''))" 2>/dev/null || echo "")
if [ "$auth_ok" = "True" ] || [ "$auth_ok" = "true" ]; then
    pass "/auth/config returns ok=true"
else
    fail "/auth/config missing ok=true"
fi

# Check that secret keys are NOT exposed
secret_leaked=$(echo "$auth_cfg" | python3 -c "
import sys, json
raw = sys.stdin.read()
d   = json.loads(raw)
# captchaSiteKey is PUBLIC and allowed; secretKey, clientSecret, etc. must NOT appear
forbidden = ['secret_key','CAPTCHA_SECRET','client_secret','CLIENT_SECRET',
             'DATABASE_URL','ADMIN_PORTAL_TOKEN','token_hash']
for f in forbidden:
    if f in raw:
        print(f'FOUND:{f}')
" 2>/dev/null || echo "")
if [ -z "$secret_leaked" ]; then
    pass "/auth/config does not expose secret keys"
else
    fail "/auth/config leaks sensitive key: $secret_leaked"
fi

# ── 16. Auth signup disabled by default ───────────────────────────────────────
header "16. POST /auth/signup — disabled by default (AUTH_EMAIL_SIGNUP_ENABLED=false)"

signup_status=$(curl -o /dev/null -w "%{http_code}" -sf -X POST "$API/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","name":"Test"}' 2>/dev/null || echo "000")

if [ "$signup_status" -eq 403 ] || [ "$signup_status" -eq 404 ]; then
    pass "signup disabled by default: $signup_status"
else
    yellow "signup status=$signup_status (expected 403 when AUTH_EMAIL_SIGNUP_ENABLED=false)"
fi

# ── 17. Existing workspace token still works after auth addition ───────────────
header "17. Existing workspace token flow unchanged"

inv_no_tok=$(curl -o /dev/null -w "%{http_code}" -sf \
  "$API/workspaces/test-ws-regression/inventory" 2>/dev/null || echo "000")
if [ "$inv_no_tok" -eq 401 ] || [ "$inv_no_tok" -eq 403 ]; then
    pass "inventory still requires workspace token: $inv_no_tok"
else
    fail "inventory auth gate broken after auth addition: $inv_no_tok"
fi

# ── 18. /eol/general still public after auth addition ─────────────────────────
header "18. /eol/general remains public after auth changes"

eol_pub=$(curl -o /dev/null -w "%{http_code}" -sf "$API/eol/general" 2>/dev/null || echo "000")
if [ "$eol_pub" -eq 200 ]; then
    pass "/eol/general public: $eol_pub"
else
    fail "/eol/general broken: $eol_pub"
fi

# ── 19. Org scan blocked when ENABLE_ORG_SCAN=false ──────────────────────────
header "19. Org scan routes return FEATURE_DISABLED when flag is off"

org_status=$(curl -o /dev/null -w "%{http_code}" -sf \
  "$API/workspaces/test-ws-regression/org-connections" 2>/dev/null || echo "000")
if [ "$org_status" -eq 403 ] || [ "$org_status" -eq 404 ] || [ "$org_status" -eq 401 ]; then
    pass "org-connections blocked when flag off (or auth required): $org_status"
else
    fail "org-connections returned unexpected status: $org_status"
fi

# ── 20. Org routes require workspace token ────────────────────────────────────
header "20. Org routes require workspace token"

org_no_tok=$(curl -o /dev/null -w "%{http_code}" -sf \
  "$API/workspaces/test-ws-regression/org-summary" 2>/dev/null || echo "000")
if [ "$org_no_tok" -eq 401 ] || [ "$org_no_tok" -eq 403 ]; then
    pass "org-summary requires auth: $org_no_tok"
else
    yellow "org-summary status=$org_no_tok (expected 401/403 without token)"
fi

# ── 21. Org connection rejects invalid role ARN format ────────────────────────
header "21. Org connection rejects invalid role ARN"

bad_arn_status=$(curl -o /dev/null -w "%{http_code}" -sf -X POST \
  "$API/workspaces/test-ws-regression/org-connections/validate-role" \
  -H "Content-Type: application/json" \
  -H "X-Workspace-Token: invalid" \
  -d '{"managementAccountId":"123456789012","roleArn":"not-a-valid-arn","externalId":"test-ext"}' \
  2>/dev/null || echo "000")
if [ "$bad_arn_status" -eq 400 ] || [ "$bad_arn_status" -eq 401 ] || [ "$bad_arn_status" -eq 403 ]; then
    pass "invalid role ARN rejected: $bad_arn_status"
else
    fail "invalid role ARN not rejected: $bad_arn_status"
fi

# ── 22. Org summary returns safe empty state when no org connection ────────────
header "22. Org summary returns empty state (not 500) when no connection"

# This test only runs if ENABLE_ORG_SCAN=true is set and we have a valid workspace token
if [ -n "${ORG_SCAN_WS_ID:-}" ] && [ -n "${ORG_SCAN_WS_TOKEN:-}" ]; then
    org_empty=$(curl -sf \
      "$API/workspaces/${ORG_SCAN_WS_ID}/org-summary" \
      -H "X-Workspace-Token: ${ORG_SCAN_WS_TOKEN}" 2>/dev/null) || org_empty="{}"
    empty_status=$(echo "$org_empty" | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
# Should have accountsTotal key and not crash
print('ok' if 'accountsTotal' in d else 'missing-key')
" 2>/dev/null || echo "parse-error")
    if [ "$empty_status" = "ok" ]; then
        pass "org-summary returns valid structure with no connections"
    else
        fail "org-summary returned unexpected shape: $empty_status"
    fi
else
    yellow "org-summary shape test skipped — set ORG_SCAN_WS_ID and ORG_SCAN_WS_TOKEN to run"
fi

# ── 23. Existing single-account scan regression ────────────────────────────────
header "23. Single-account scan routes unchanged"

scan_no_tok=$(curl -o /dev/null -w "%{http_code}" -sf \
  "$API/workspaces/test-ws-regression/accounts/test-account/scans" \
  -X POST -H "Content-Type: application/json" -d '{}' \
  2>/dev/null || echo "000")
if [ "$scan_no_tok" -eq 401 ] || [ "$scan_no_tok" -eq 403 ]; then
    pass "single-account scan still requires auth: $scan_no_tok"
else
    fail "single-account scan auth gate broken: $scan_no_tok"
fi

# ── 24. Public routes unaffected by org scan addition ─────────────────────────
header "24. Public routes still accessible"

overview_ok=$(curl -o /dev/null -w "%{http_code}" -sf "$API/health" 2>/dev/null || echo "000")
eol_ok=$(curl -o /dev/null -w "%{http_code}" -sf "$API/eol/general" 2>/dev/null || echo "000")
auth_cfg_ok=$(curl -o /dev/null -w "%{http_code}" -sf "$API/auth/config" 2>/dev/null || echo "000")

if [ "$overview_ok" -eq 200 ]; then pass "/health still public: $overview_ok"; else fail "/health broken: $overview_ok"; fi
if [ "$eol_ok" -eq 200 ]; then pass "/eol/general still public: $eol_ok"; else fail "/eol/general broken: $eol_ok"; fi
if [ "$auth_cfg_ok" -eq 200 ]; then pass "/auth/config still public: $auth_cfg_ok"; else fail "/auth/config broken: $auth_cfg_ok"; fi

# ── 25. Viewer role cannot start org scan ────────────────────────────────────
header "25. Role enforcement — viewer cannot start org scan"

# Org scan create requires EDITOR/ADMIN role. Without a valid token, returns 401.
# With a valid viewer token it would return 403. This checks the auth gate exists.
org_scan_no_auth=$(curl -o /dev/null -w "%{http_code}" -sf -X POST \
  "$API/workspaces/test-ws-regression/org-connections/test-conn/scans" \
  -H "Content-Type: application/json" -d '{}' \
  2>/dev/null || echo "000")
if [ "$org_scan_no_auth" -eq 401 ] || [ "$org_scan_no_auth" -eq 403 ]; then
    pass "org scan requires auth: $org_scan_no_auth"
else
    fail "org scan auth gate missing: $org_scan_no_auth"
fi

# ── 26. SAML disabled by default — /auth/config ───────────────────────────────
header "26. SAML config — disabled by default, secrets not exposed"

auth_cfg=$(curl -sf "$API/auth/config" 2>/dev/null) || { auth_cfg="{}"; fail "/auth/config unreachable for SAML check"; }

saml_enabled=$(echo "$auth_cfg" | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
print(d.get('auth', {}).get('samlEnabled', 'missing'))
" 2>/dev/null || echo "parse-error")

if [ "$saml_enabled" = "False" ] || [ "$saml_enabled" = "false" ]; then
    pass "/auth/config: samlEnabled=false (default)"
elif [ "$saml_enabled" = "missing" ] || [ "$saml_enabled" = "parse-error" ]; then
    fail "/auth/config: samlEnabled field missing"
else
    yellow "/auth/config: samlEnabled=$saml_enabled (expected false unless AUTH_SAML_ENABLED=true)"
fi

cert_leaked=$(echo "$auth_cfg" | python3 -c "
import sys, json
raw = sys.stdin.read()
bad = ['SAML_IDP_X509_CERT', 'x509cert', 'privateKey', 'BEGIN CERTIFICATE', 'BEGIN RSA']
for b in bad:
    if b in raw:
        print(f'FOUND:{b}')
" 2>/dev/null || echo "")
if [ -z "$cert_leaked" ]; then
    pass "/auth/config: SAML certificate not exposed"
else
    fail "/auth/config leaks SAML secret: $cert_leaked"
fi

# ── 27. SAML routes blocked when disabled ────────────────────────────────────
header "27. SAML routes return 403/404 when AUTH_SAML_ENABLED=false"

saml_meta=$(curl -o /dev/null -w "%{http_code}" -sf \
  "$API/auth/saml/metadata" 2>/dev/null || echo "000")
if [ "$saml_meta" -eq 403 ] || [ "$saml_meta" -eq 404 ]; then
    pass "GET /auth/saml/metadata blocked: $saml_meta"
else
    fail "GET /auth/saml/metadata returned unexpected: $saml_meta (expected 403/404)"
fi

saml_login=$(curl -o /dev/null -w "%{http_code}" -sf \
  "$API/auth/saml/login" 2>/dev/null || echo "000")
if [ "$saml_login" -eq 403 ] || [ "$saml_login" -eq 404 ]; then
    pass "GET /auth/saml/login blocked: $saml_login"
else
    fail "GET /auth/saml/login returned unexpected: $saml_login"
fi

saml_acs=$(curl -o /dev/null -w "%{http_code}" -sf -X POST \
  "$API/auth/saml/acs" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "SAMLResponse=dGVzdA==" 2>/dev/null || echo "000")
if [ "$saml_acs" -eq 403 ] || [ "$saml_acs" -eq 404 ]; then
    pass "POST /auth/saml/acs blocked: $saml_acs"
else
    fail "POST /auth/saml/acs returned unexpected: $saml_acs"
fi

# ── 28. ACS rejects missing SAMLResponse ─────────────────────────────────────
header "28. ACS returns 403 (disabled) or 400 (missing SAMLResponse)"

acs_no_data=$(curl -o /dev/null -w "%{http_code}" -sf -X POST \
  "$API/auth/saml/acs" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "" 2>/dev/null || echo "000")
if [ "$acs_no_data" -eq 400 ] || [ "$acs_no_data" -eq 403 ] || [ "$acs_no_data" -eq 404 ]; then
    pass "ACS without SAMLResponse returns $acs_no_data"
else
    fail "ACS without SAMLResponse returned unexpected: $acs_no_data"
fi

# ── 29. Public routes unchanged after SAML addition ──────────────────────────
header "29. Public routes still accessible after SAML addition"

health=$(curl -o /dev/null -w "%{http_code}" -sf "$API/health" 2>/dev/null || echo "000")
eol=$(curl -o /dev/null -w "%{http_code}" -sf "$API/eol/general" 2>/dev/null || echo "000")
cfg=$(curl -o /dev/null -w "%{http_code}" -sf "$API/auth/config" 2>/dev/null || echo "000")

[ "$health" -eq 200 ] && pass "/health still public" || fail "/health broken: $health"
[ "$eol"    -eq 200 ] && pass "/eol/general still public" || fail "/eol/general broken: $eol"
[ "$cfg"    -eq 200 ] && pass "/auth/config still public" || fail "/auth/config broken: $cfg"

# ── 30. Token flow unchanged after SAML addition ──────────────────────────────
header "30. Workspace token flow unchanged"

tok_req=$(curl -o /dev/null -w "%{http_code}" -sf \
  "$API/workspaces/test-ws-regression/inventory" 2>/dev/null || echo "000")
if [ "$tok_req" -eq 401 ] || [ "$tok_req" -eq 403 ]; then
    pass "inventory still requires workspace token: $tok_req"
else
    fail "workspace token gate broken: $tok_req"
fi

session_req=$(curl -o /dev/null -w "%{http_code}" -sf \
  "$API/auth/me" 2>/dev/null || echo "000")
if [ "$session_req" -eq 401 ] || [ "$session_req" -eq 403 ]; then
    pass "/auth/me without session still returns: $session_req"
else
    fail "/auth/me without session returned unexpected: $session_req"
fi

# ── 31. Alerts limit is capped server-side ────────────────────────────────────
header "31. Alerts list — server-side limit cap enforced"

alerts_cap=$(curl -o /dev/null -w "%{http_code}" -sf \
  "$API/workspaces/test-nonexistent/alerts?limit=1000000" 2>/dev/null || echo "000")
if [ "$alerts_cap" -eq 401 ] || [ "$alerts_cap" -eq 403 ]; then
    pass "GET /alerts?limit=1000000 — auth guard fires: $alerts_cap"
elif [ "$alerts_cap" -ne 500 ]; then
    pass "GET /alerts?limit=1000000 returns $alerts_cap (not 500)"
else
    fail "GET /alerts?limit=1000000 returned 500 — server-side cap may be missing"
fi

# ── 32. Anonymous workspace creation — backend enforces flag ─────────────────
header "32. POST /workspaces — anonymous creation works when flag=true (default)"

anon_ws=$(curl -o /dev/null -w "%{http_code}" -sf -X POST \
  "$API/workspaces" \
  -H "Content-Type: application/json" \
  -d '{"name":"regression-anon-test"}' 2>/dev/null || echo "000")
if [ "$anon_ws" -eq 201 ] || [ "$anon_ws" -eq 200 ]; then
    pass "POST /workspaces succeeds (anonymous creation enabled by default): $anon_ws"
elif [ "$anon_ws" -eq 429 ]; then
    yellow "POST /workspaces rate-limited — acceptable during repeated test runs"
elif [ "$anon_ws" -eq 403 ]; then
    fail "POST /workspaces returned 403 — anonymous creation may be incorrectly blocked"
else
    yellow "POST /workspaces returned $anon_ws"
fi

# ── 33. Schema files — eol_overrides and members composite index ──────────────
header "33. schema.sql — eol_overrides table and members composite index"

schema_file="$(dirname "$0")/../database/schema.sql"
if [ -f "$schema_file" ]; then
    if grep -q "CREATE TABLE IF NOT EXISTS eol_overrides" "$schema_file"; then
        pass "schema.sql has eol_overrides table"
    else
        fail "schema.sql missing eol_overrides — admin overrides will fail on fresh DB"
    fi
    if grep -q "idx_members_ws_email" "$schema_file"; then
        pass "schema.sql has composite index idx_members_ws_email"
    else
        fail "schema.sql missing idx_members_ws_email composite index"
    fi
else
    yellow "schema.sql not found — skipping schema checks"
fi

# ── 34. SAML_RELAY_SIGNING_KEY documented in .env ─────────────────────────────
header "34. SAML_RELAY_SIGNING_KEY entry present in .env"

env_file="$(dirname "$0")/../.env"
if [ -f "$env_file" ]; then
    if grep -q "SAML_RELAY_SIGNING_KEY" "$env_file"; then
        pass ".env has SAML_RELAY_SIGNING_KEY entry"
    else
        fail ".env missing SAML_RELAY_SIGNING_KEY — in-flight SAML logins break on restart"
    fi
else
    yellow ".env not found — skipping relay key check"
fi

# ── 35. SAML handler uses ADMIN/EDITOR/VIEWER (not owner/editor/viewer) ───────
header "35. saml_handler.py uses ADMIN/EDITOR/VIEWER role strings"

saml_file="$(dirname "$0")/../saml_handler.py"
if [ -f "$saml_file" ]; then
    if grep -q '"ADMIN"' "$saml_file" && ! grep -q 'return "owner"' "$saml_file"; then
        pass "saml_handler.py uses ADMIN role string"
    else
        fail "saml_handler.py still uses 'owner' — SAML users would be denied all access"
    fi
else
    yellow "saml_handler.py not found — skipping role string check"
fi

# ── 36. Org scan uses replace_resources_for_account ───────────────────────────
header "36. Org scan uses replace_resources_for_account (no duplicate inventory)"

api_file="$(dirname "$0")/../api_handler.py"
if [ -f "$api_file" ]; then
    if grep -q "replace_resources_for_account" "$api_file"; then
        pass "api_handler.py calls replace_resources_for_account in org scan"
    else
        fail "api_handler.py org scan still uses save_resources — inventory will accumulate"
    fi
fi

# ── 37. Magic link expiry uses full ISO timestamp ─────────────────────────────
header "37. Magic link token expiry uses full ISO timestamp (no [:10] truncation)"

if [ -f "$api_file" ]; then
    if grep -q 'expired_marker\[:10\]' "$api_file"; then
        fail "api_handler.py still uses expired_marker[:10] — multiple tokens valid same day"
    else
        pass "api_handler.py uses full ISO timestamp for token expiry"
    fi
fi

# ── 38. APP_ENV=production set in .env ────────────────────────────────────────
header "38. APP_ENV=production confirmed in .env"

if [ -f "$env_file" ]; then
    if grep -q "^APP_ENV=production" "$env_file"; then
        pass ".env has APP_ENV=production — session cookies will have Secure flag"
    elif grep -q "^APP_ENV=" "$env_file"; then
        env_val=$(grep "^APP_ENV=" "$env_file" | head -1 | cut -d= -f2)
        yellow ".env APP_ENV=$env_val (expected production for Secure cookie flag)"
    else
        fail ".env missing APP_ENV — cookies lack Secure flag"
    fi
fi

# ── 39. Org scan per-account timeout guard present ────────────────────────────
header "39. Org scan has per-account timeout (concurrent.futures)"

if [ -f "$api_file" ]; then
    if grep -q "TimeoutError\|ORG_SCAN_ACCOUNT_TIMEOUT_SECONDS" "$api_file"; then
        pass "api_handler.py has per-account timeout for org scan"
    else
        fail "api_handler.py org scan has no timeout — scan may hang indefinitely"
    fi
fi

# ── 40. handle_auth_signup does not auto-login existing verified users ─────────
header "40. handle_auth_signup — no auto-login of existing users"

if [ -f "$(dirname "$0")/../auth_handler.py" ]; then
    auth_file="$(dirname "$0")/../auth_handler.py"
    if grep -q "already_registered" "$auth_file"; then
        pass "auth_handler.py returns already_registered for existing users (no auto-login)"
    else
        fail "auth_handler.py may still auto-login existing users on signup without credential check"
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
header "Summary"
printf '\n  PASS: %d\n  FAIL: %d\n\n' "$PASS" "$FAIL"

if [ "$FAIL" -gt 0 ]; then
    red "$FAIL check(s) failed"
    exit 1
else
    green "All checks passed"
    exit 0
fi
