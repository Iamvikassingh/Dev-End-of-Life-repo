# Regression Test Checklist — Phase 1

Run this checklist after every deploy before marking the release stable.

---

## Prerequisites

```bash
API="http://127.0.0.1:3001"
WS_ID="<your-workspace-id>"
TOKEN="<your-workspace-token>"
ACCT_ID="<a-connected-account-id>"
```

---

## 1. Health Check

- [ ] `GET /health` returns `200`

```bash
curl -s $API/health | python3 -m json.tool
```

Expected: `{ "status": "ok" }`

---

## 2. Auth / Security

- [ ] No-token request returns `401`

```bash
STATUS=$(curl -s -o /dev/null -w "%{http_code}" $API/workspaces/$WS_ID/inventory)
[ "$STATUS" = "401" ] && echo "PASS" || echo "FAIL: expected 401, got $STATUS"
```

- [ ] Wrong-token request returns `401`

```bash
STATUS=$(curl -s -o /dev/null -w "%{http_code}" $API/workspaces/$WS_ID/inventory \
  -H "X-Workspace-Token: eolm_live_wrong_token_here")
[ "$STATUS" = "401" ] && echo "PASS" || echo "FAIL: expected 401, got $STATUS"
```

- [ ] Valid token returns `200`

```bash
STATUS=$(curl -s -o /dev/null -w "%{http_code}" $API/workspaces/$WS_ID/inventory \
  -H "X-Workspace-Token: $TOKEN")
[ "$STATUS" = "200" ] && echo "PASS" || echo "FAIL: expected 200, got $STATUS"
```

- [ ] Token A cannot access Workspace B (different workspace ID)

```bash
FAKE_WS="ws_000000000000"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" $API/workspaces/$FAKE_WS/inventory \
  -H "X-Workspace-Token: $TOKEN")
[ "$STATUS" = "401" ] && echo "PASS" || echo "FAIL: expected 401, got $STATUS"
```

- [ ] Legacy route returns `410`

```bash
STATUS=$(curl -s -o /dev/null -w "%{http_code}" $API/eol/inventory)
[ "$STATUS" = "410" ] && echo "PASS" || echo "FAIL: expected 410, got $STATUS"
```

---

## 3. Accounts

- [ ] List accounts returns `200` with accounts array

```bash
curl -s $API/workspaces/$WS_ID/accounts \
  -H "X-Workspace-Token: $TOKEN" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Accounts: {len(d.get(\"accounts\", []))}')
"
```

- [ ] Cross-account access blocked: account from another workspace returns `404`

```bash
FAKE_ACCT="conn_000000000000"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST $API/workspaces/$WS_ID/accounts/$FAKE_ACCT/scans \
  -H "X-Workspace-Token: $TOKEN")
[ "$STATUS" = "404" ] && echo "PASS" || echo "FAIL: expected 404, got $STATUS"
```

---

## 4. Scan

- [ ] Start scan returns `202` with `scanId` and `status: running`

```bash
curl -s -X POST $API/workspaces/$WS_ID/accounts/$ACCT_ID/scans \
  -H "X-Workspace-Token: $TOKEN" | python3 -m json.tool
```

- [ ] Scan completes with `status: completed` (poll)

```bash
SCAN_ID="<scan-id-from-above>"
curl -s $API/workspaces/$WS_ID/accounts/$ACCT_ID/scans/$SCAN_ID \
  -H "X-Workspace-Token: $TOKEN" | python3 -m json.tool
```

- [ ] Completed scan summary has all 7 keys

```bash
curl -s $API/workspaces/$WS_ID/accounts/$ACCT_ID/scans/$SCAN_ID \
  -H "X-Workspace-Token: $TOKEN" | python3 -c "
import json, sys
d = json.load(sys.stdin)
s = d.get('summary', {})
expected = ['total','eol','expiringSoon','extendedSupport','supported','unknown','needsInspection','lifecycleNotTracked']
missing = [k for k in expected if k not in s]
if missing: print(f'FAIL: missing keys {missing}')
else: print('PASS: all summary keys present')
print(json.dumps(s, indent=2))
"
```

---

## 5. Inventory

- [ ] Inventory returns items with correct fields

```bash
curl -s $API/workspaces/$WS_ID/inventory \
  -H "X-Workspace-Token: $TOKEN" | python3 -c "
import json, sys
d = json.load(sys.stdin)
items = d.get('items', [])
print(f'Total items: {len(items)}')
if items:
    sample = items[0]
    required_fields = ['resource_name', 'service_type', 'version', 'eol_status', 'region']
    missing = [f for f in required_fields if f not in sample]
    if missing: print(f'FAIL: sample item missing fields: {missing}')
    else: print('PASS: sample item has required fields')
"
```

- [ ] No `"unknown"` string in `eol_date` field

```bash
curl -s $API/workspaces/$WS_ID/inventory \
  -H "X-Workspace-Token: $TOKEN" | python3 -c "
import json, sys
items = json.load(sys.stdin).get('items', [])
bad = [r for r in items if r.get('eol_date') == 'unknown']
if bad:
    print(f'FAIL: {len(bad)} items have eol_date=\"unknown\"')
    for r in bad[:3]: print(f'  {r.get(\"service_type\")} {r.get(\"resource_name\")}')
else:
    print('PASS: no \"unknown\" date strings')
"
```

- [ ] NEEDS_INSPECTION / LIFECYCLE_NOT_TRACKED have null eol_date

```bash
curl -s $API/workspaces/$WS_ID/inventory \
  -H "X-Workspace-Token: $TOKEN" | python3 -c "
import json, sys
items = json.load(sys.stdin).get('items', [])
non_lc = [r for r in items if r.get('eol_status') in ('NEEDS_INSPECTION','LIFECYCLE_NOT_TRACKED')]
bad = [r for r in non_lc if r.get('eol_date') is not None]
if bad:
    print(f'FAIL: {len(bad)} non-lifecycle items have eol_date set')
else:
    print(f'PASS: {len(non_lc)} non-lifecycle items, all have null eol_date')
"
```

---

## 6. OpenSearch Classification

- [ ] OpenSearch resources are NOT classified as UNKNOWN (if OpenSearch exists in the account)

```bash
curl -s $API/workspaces/$WS_ID/inventory \
  -H "X-Workspace-Token: $TOKEN" | python3 -c "
import json, sys
items = json.load(sys.stdin).get('items', [])
os_items = [r for r in items if r.get('service_type') == 'OpenSearch']
print(f'OpenSearch resources: {len(os_items)}')
for r in os_items:
    status = r.get('eol_status')
    version = r.get('version')
    print(f'  {r.get(\"resource_name\")} | v{version} | {status}')
    if status == 'UNKNOWN':
        print(f'  WARN: OpenSearch {version} still showing UNKNOWN — check version key format')
"
```

---

## 7. Summary

- [ ] Summary returns correct 7-key structure

```bash
curl -s $API/workspaces/$WS_ID/summary \
  -H "X-Workspace-Token: $TOKEN" | python3 -c "
import json, sys
d = json.load(sys.stdin)
r = d.get('resources', {})
expected = ['total','eol','expiringSoon','extendedSupport','supported','unknown','needsInspection','lifecycleNotTracked']
missing = [k for k in expected if k not in r]
if missing: print(f'FAIL: missing keys: {missing}')
else: print('PASS: all summary keys present')
print(f'  Total:                 {r.get(\"total\",0)}')
print(f'  EOL:                   {r.get(\"eol\",0)}')
print(f'  Expiring Soon:         {r.get(\"expiringSoon\",0)}')
print(f'  Extended Support:      {r.get(\"extendedSupport\",0)}')
print(f'  Supported:             {r.get(\"supported\",0)}')
print(f'  Unknown:               {r.get(\"unknown\",0)}')
print(f'  Needs Inspection:      {r.get(\"needsInspection\",0)}')
print(f'  Lifecycle Not Tracked: {r.get(\"lifecycleNotTracked\",0)}')
"
```

- [ ] `needsInspection + lifecycleNotTracked` NOT included in `eol + expiringSoon + extendedSupport + supported + unknown`

```bash
curl -s $API/workspaces/$WS_ID/summary \
  -H "X-Workspace-Token: $TOKEN" | python3 -c "
import json, sys
r = json.load(sys.stdin).get('resources', {})
lifecycle = r.get('eol',0) + r.get('expiringSoon',0) + r.get('extendedSupport',0) + r.get('supported',0) + r.get('unknown',0)
nonlc = r.get('needsInspection',0) + r.get('lifecycleNotTracked',0)
total = r.get('total', 0)
if lifecycle + nonlc == total:
    print(f'PASS: lifecycle({lifecycle}) + non-lifecycle({nonlc}) = total({total})')
else:
    print(f'WARN: lifecycle({lifecycle}) + non-lifecycle({nonlc}) != total({total})')
"
```

---

## 8. UI Smoke Tests (manual)

After opening the dashboard in a browser:

- [ ] Dashboard shows 7 status tiles (5 main + 2 non-lifecycle if applicable)
- [ ] Account Results page shows correct per-account summary cards
- [ ] Status badges display on one line (no wrapping for "Lifecycle Not Tracked")
- [ ] EOL Date column shows `—` for NEEDS_INSPECTION and LIFECYCLE_NOT_TRACKED rows
- [ ] EOL Timeline bar shows correct color (red = EOL, orange = expiring, green = supported)
- [ ] EOL Timeline shows date only if date is not null/unknown
- [ ] Filter chips exist for all statuses with count > 0
- [ ] Run Scan completes and results refresh automatically (within ~5s)
- [ ] Tooltip appears on hover for NEEDS_INSPECTION and LIFECYCLE_NOT_TRACKED badges

---

## 9. Member Role Enforcement (if member accounts available)

- [ ] VIEWER token cannot start scan (expect 403)

```bash
VIEWER_TOKEN="eolm_member_xxxx"  # token with VIEWER role
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST $API/workspaces/$WS_ID/accounts/$ACCT_ID/scans \
  -H "X-Workspace-Token: $VIEWER_TOKEN")
[ "$STATUS" = "403" ] && echo "PASS" || echo "FAIL: expected 403, got $STATUS"
```

- [ ] VIEWER token can read inventory (expect 200)

```bash
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  $API/workspaces/$WS_ID/inventory \
  -H "X-Workspace-Token: $VIEWER_TOKEN")
[ "$STATUS" = "200" ] && echo "PASS" || echo "FAIL: expected 200, got $STATUS"
```

---

## 10. CORS Production Guard (if APP_ENV=production)

- [ ] Backend started successfully (no RuntimeError)
- [ ] `ALLOWED_ORIGIN` is NOT `*`
- [ ] Browser requests to API return correct `Access-Control-Allow-Origin` header

```bash
ORIGIN_HEADER=$(curl -sI -H "Origin: http://localhost:5173" $API/health \
  | grep -i "access-control-allow-origin" | tr -d '\r')
echo "CORS header: $ORIGIN_HEADER"
```

---

## Quick Test Summary Script

```bash
#!/bin/bash
API="http://127.0.0.1:3001"
WS_ID="$1"
TOKEN="$2"
PASS=0; FAIL=0

check() {
  local label="$1" expected="$2" actual="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  PASS: $label"
    ((PASS++))
  else
    echo "  FAIL: $label (expected $expected, got $actual)"
    ((FAIL++))
  fi
}

check "Health" "200" "$(curl -s -o /dev/null -w "%{http_code}" $API/health)"
check "No-token 401" "401" "$(curl -s -o /dev/null -w "%{http_code}" $API/workspaces/$WS_ID/inventory)"
check "Wrong-token 401" "401" "$(curl -s -o /dev/null -w "%{http_code}" $API/workspaces/$WS_ID/inventory -H "X-Workspace-Token: wrong")"
check "Valid-token 200" "200" "$(curl -s -o /dev/null -w "%{http_code}" $API/workspaces/$WS_ID/inventory -H "X-Workspace-Token: $TOKEN")"
check "Legacy 410" "410" "$(curl -s -o /dev/null -w "%{http_code}" $API/eol/inventory)"

echo ""
echo "Results: $PASS passed, $FAIL failed"
```

Usage: `bash quick-test.sh <WS_ID> <TOKEN>`
