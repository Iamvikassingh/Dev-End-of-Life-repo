# AWS EOL Monitor — Production Runbook

Self-hosted deployment using Nginx + Flask backend + React frontend.
Storage backend: PostgreSQL is recommended for production and private beta; file storage is for local development or very small internal demos.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Required Environment Variables](#2-required-environment-variables)
3. [Launch Readiness Gate](#3-launch-readiness-gate)
4. [Backend Setup and Start](#4-backend-setup-and-start)
5. [Frontend Production Build](#5-frontend-production-build)
6. [Nginx Configuration](#6-nginx-configuration)
7. [HTTPS — Certbot](#7-https--certbot)
8. [Health Checks](#8-health-checks)
9. [Backup and Restore](#9-backup-and-restore)
10. [Smoke Test Checklist](#10-smoke-test-checklist)
11. [Rollback Steps](#11-rollback-steps)
12. [Known Limitations](#12-known-limitations)
13. [Security Notes](#13-security-notes)

---

## 1. Prerequisites

```bash
# System packages
sudo apt update
sudo apt install -y python3 python3-pip nginx certbot python3-certbot-nginx

# Python dependencies (backend)
cd /home/ubuntu/aws-end-of-life/backend
pip3 install -r requirements.txt flask flask-cors --break-system-packages

# Node.js 20+ (for frontend build only — not needed at runtime)
# Install via nvm: https://github.com/nvm-sh/nvm
nvm install 20 && nvm use 20

# PM2 (process manager — keeps backend alive on reboot)
npm install -g pm2
```

---

## 2. Required Environment Variables

### Backend

Set these before starting the backend process, or export them in the PM2 config below.

| Variable | Required | Example | Notes |
|---|---|---|---|
| `STORAGE_BACKEND` | Yes | `postgres` | `postgres` recommended for production; `file` only for dev/small internal demos |
| `DATABASE_URL` | Yes when using Postgres | `postgresql://eol_app:...@db-private:5432/eol_monitor` | Use private DB endpoint where possible |
| `EOL_DATA_DIR` | Only for file backend | `/home/ubuntu/eol-data` | Must be writable if `STORAGE_BACKEND=file` |
| `ALLOWED_ORIGIN` | **Yes in production** | `https://yourdomain.com` | No trailing slash. Defaults to `*` — unsafe in production |
| `APP_PUBLIC_URL` | **Yes in production** | `https://yourdomain.com` | Used for member magic-login links |
| `MEMBER_LOGIN_DEV_LINKS` | **Yes in production** | `false` | Must be `false` outside dev; true logs/returns dev login links |
| `ADMIN_PORTAL_TOKEN` | Yes | `eolm_admin_<48-hex-chars>` | Generate: `python3 -c "import secrets; print('eolm_admin_'+secrets.token_hex(24))"` |
| `GENERAL_EOL_CACHE_TTL_HOURS` | No | `24` | How long endoflife.date data is cached |
| `WARN_DAYS` | No | `180` | Days before EOL to flag as EXPIRING_SOON |
| `ENABLE_ORG_SCAN` | No | `false` | Keep false until full org-scan rollout |
| `ENABLE_REMEDIATION` | No | `false` | Future feature flag |
| `ENABLE_SSO` | No | `false` | Future feature flag |
| `ENABLE_BILLING` | No | `false` | Future feature flag |
| `ENABLE_CICD_SCAN` | No | `false` | Future feature flag |

Generate a strong admin token:
```bash
python3 -c "import secrets; print('eolm_admin_'+secrets.token_hex(24))"
```

### Frontend Build

Set these before running `npm run build`:

| Variable | Value | Notes |
|---|---|---|
| `REACT_APP_API_URL` | `/api` | Nginx proxies `/api/*` → backend. Never use `http://IP:3001` in production |
| `REACT_APP_SHOW_ADMIN_SHORTCUT` | `false` | Hides admin link from sidebar nav |
| `REACT_APP_ENABLE_DEMO_DATA` | `false` | Demo mode is runtime-controlled; compile flag not needed |
| `REACT_APP_ALLOW_INSECURE_ADMIN` | `false` | Blocks admin login over non-localhost HTTP |
| `REACT_APP_ENABLE_ORG_SCAN` | `false` | Keep Organization Scan hidden until production rollout |
| `REACT_APP_ENABLE_REMEDIATION` | `false` | Future feature flag |
| `REACT_APP_ENABLE_SSO` | `false` | Future feature flag |
| `REACT_APP_ENABLE_BILLING` | `false` | Future feature flag |
| `REACT_APP_ENABLE_CICD_SCAN` | `false` | Future feature flag |

---

## 3. Launch Readiness Gate

Feature development is frozen for launch. Do not enable unfinished modules for public/customer traffic.

### Required production env

```env
APP_PUBLIC_URL=https://yourdomain.com
ALLOWED_ORIGIN=https://yourdomain.com
MEMBER_LOGIN_DEV_LINKS=false

ENABLE_ORG_SCAN=false
ENABLE_REMEDIATION=false
ENABLE_SSO=false
ENABLE_BILLING=false
ENABLE_CICD_SCAN=false
```

Frontend build env:

```env
REACT_APP_API_URL=/api
REACT_APP_ALLOW_INSECURE_ADMIN=false
REACT_APP_ENABLE_ORG_SCAN=false
REACT_APP_ENABLE_REMEDIATION=false
REACT_APP_ENABLE_SSO=false
REACT_APP_ENABLE_BILLING=false
REACT_APP_ENABLE_CICD_SCAN=false
```

### Secret rotation before launch

Rotate all values that were used in chat, screenshots, logs, test sessions, or temporary `.env` files:

- [ ] Workspace tokens
- [ ] Member invite/login test links are expired or consumed
- [ ] Admin portal token
- [ ] Database password
- [ ] PostgreSQL app user password
- [ ] Slack, email, or SNS secrets if configured
- [ ] Any temporary AWS access keys used during testing

After rotation, verify old values fail and new values work.

### PostgreSQL security gate

- [ ] PostgreSQL port `5432` is not open to the public internet
- [ ] Security group allows DB access only from the app EC2 instance or private subnet
- [ ] Backend uses `eol_app`, not the `postgres` superuser
- [ ] `DATABASE_URL` points to the private DB endpoint where possible
- [ ] Automated `pg_dump` backup cron is configured
- [ ] Restore from backup has been tested once
- [ ] Production schema is current with `database/schema.sql`

### Public launch blockers

- [ ] Domain points to the app server
- [ ] HTTPS certificate is active
- [ ] HTTP redirects to HTTPS
- [ ] Browser DevTools shows no mixed-content warnings
- [ ] CORS is exact-domain only, not `*`
- [ ] Dev member login links are disabled
- [ ] Organization Scan remains hidden unless explicitly approved for beta testing

---

## 4. Backend Setup and Start

### Create data directory for file backend only

Skip this when `STORAGE_BACKEND=postgres`.

```bash
sudo mkdir -p /home/ubuntu/eol-data/secrets
sudo chown -R ubuntu:ubuntu /home/ubuntu/eol-data
chmod -R go-rwx /home/ubuntu/eol-data
```

### PM2 process config

Create `/home/ubuntu/eol-monitor-backend.config.js`:

```js
module.exports = {
  apps: [{
    name: "eol-monitor-backend",
    script: "python3",
    args: "scripts/run-local-backend.py",
    cwd: "/home/ubuntu/aws-end-of-life",
    interpreter: "none",
    env: {
      STORAGE_BACKEND:              "postgres",
      DATABASE_URL:                 "postgresql://eol_app:REPLACE_WITH_DB_PASSWORD@DB_PRIVATE_HOST:5432/eol_monitor",
      ALLOWED_ORIGIN:               "https://yourdomain.com",
      APP_PUBLIC_URL:               "https://yourdomain.com",
      MEMBER_LOGIN_DEV_LINKS:       "false",
      ADMIN_PORTAL_TOKEN:           "eolm_admin_REPLACE_WITH_REAL_TOKEN",
      ENABLE_ORG_SCAN:              "false",
      ENABLE_REMEDIATION:           "false",
      ENABLE_SSO:                   "false",
      ENABLE_BILLING:               "false",
      ENABLE_CICD_SCAN:             "false",
      GENERAL_EOL_CACHE_TTL_HOURS:  "24",
      WARN_DAYS:                    "180",
      PORT:                         "3001",
    },
    restart_delay: 5000,
    max_restarts:  10,
    log_date_format: "YYYY-MM-DD HH:mm:ss",
  }],
};
```

### Start, stop, restart

```bash
# First start
pm2 start /home/ubuntu/eol-monitor-backend.config.js

# Restart after code change
pm2 restart eol-monitor-backend

# Stop
pm2 stop eol-monitor-backend

# View logs (live)
pm2 logs eol-monitor-backend

# Save process list so it survives reboot
pm2 save

# Enable PM2 on system boot
pm2 startup
# Run the command it prints, e.g.:
#   sudo env PATH=$PATH:/usr/bin pm2 startup systemd -u ubuntu --hp /home/ubuntu
```

### Verify backend is running

```bash
curl -s http://127.0.0.1:3001/health | python3 -m json.tool
# Expected for production/private beta: {"status": "ok", "timestamp": "...", "storage_backend": "postgres"}
```

---

## 5. Frontend Production Build

```bash
cd /home/ubuntu/aws-end-of-life/frontend

# Set env vars for this build
export REACT_APP_API_URL=/api
export REACT_APP_SHOW_ADMIN_SHORTCUT=false
export REACT_APP_ENABLE_DEMO_DATA=false
export REACT_APP_ALLOW_INSECURE_ADMIN=false
export REACT_APP_ENABLE_ORG_SCAN=false
export REACT_APP_ENABLE_REMEDIATION=false
export REACT_APP_ENABLE_SSO=false
export REACT_APP_ENABLE_BILLING=false
export REACT_APP_ENABLE_CICD_SCAN=false

# Build
nvm use 20
npm run build

# Copy build output to Nginx serve path
sudo cp -r build /home/ubuntu/aws-end-of-life-frontend/build
# (or point Nginx root directly to frontend/build — adjust paths in Nginx config below)
```

After a new build, Nginx picks up static files immediately — no Nginx restart needed unless the config changed.

---

## 6. Nginx Configuration

> **Critical:** Always serve the React `build/` directory via Nginx. **Never run `npm start` on production** — that is the CRA dev server which serves an unminified 4 MB bundle and is not safe or performant for production use.

Create `/etc/nginx/sites-available/eol-monitor`:

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    # ── Gzip compression ──────────────────────────────────────────────────
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_min_length 1024;
    gzip_types
        text/plain text/css text/xml text/javascript
        application/json application/javascript application/xml+rss
        application/atom+xml image/svg+xml;

    # ── Backend API proxy ─────────────────────────────────────────────────
    location /api/ {
        proxy_pass         http://127.0.0.1:3001/;
        proxy_http_version 1.1;

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Increase timeout for long-running scans (boto3 can take 30–90s)
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }

    # ── Static assets — hashed filenames, cache forever ───────────────────
    # CRA build outputs /static/js/main.xxxxxxxx.js etc. with content hash.
    # Safe to cache indefinitely — a new build produces a new hash.
    location /static/ {
        root  /home/ubuntu/aws-end-of-life/frontend/build;
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    # ── React SPA — index.html must never be cached ───────────────────────
    # index.html references the current hashed JS/CSS filenames.
    # If it were cached the browser would load stale JS after a new deploy.
    location / {
        root  /home/ubuntu/aws-end-of-life/frontend/build;
        index index.html;
        try_files $uri /index.html;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        expires 0;
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/eol-monitor /etc/nginx/sites-enabled/

# Remove default site if it conflicts
sudo rm -f /etc/nginx/sites-enabled/default

# Test config
sudo nginx -t

# Apply config
sudo systemctl reload nginx
```

**Expected asset sizes after production build + gzip:**

| Asset | Raw | Gzip |
|---|---|---|
| `static/js/main.*.js` | ~700 KB | ~190 KB |
| `static/css/main.*.css` | ~50 KB | ~10 KB |

Second-visit load (cached): ~0 KB JS transferred (served from browser cache).

---

## 7. HTTPS — Certbot

```bash
# Obtain and install certificate (modifies nginx config in-place)
sudo certbot --nginx -d yourdomain.com

# Test auto-renewal
sudo certbot renew --dry-run

# Certbot installs a systemd timer; verify it is active
systemctl status certbot.timer
```

After Certbot, verify the final Nginx config has:
- `listen 443 ssl;` block with cert paths
- HTTP `listen 80` block redirecting to HTTPS

---

## 8. Health Checks

Run these after any deploy or restart to confirm the stack is healthy.

```bash
# Backend health
curl -s https://yourdomain.com/api/health | python3 -m json.tool
# Expected: {"status": "ok", "storage_backend": "postgres", ...}

# General EOL cache status
curl -s https://yourdomain.com/api/eol/general/summary | python3 -m json.tool
# Expected: {"ok": true, "data": {...}, "meta": {"total": <number>, ...}}
# If "ok": false with CACHE_EMPTY, trigger a refresh:
curl -s -X POST https://yourdomain.com/api/eol/general/refresh | python3 -m json.tool

# Admin system status (with valid admin token)
curl -s -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  https://yourdomain.com/api/admin/system | python3 -m json.tool
# Expected: {"backend": {"status": "ok", ...}, "eolCache": {...}, "scanRuns": {...}}

# Admin without token must return 401 with standard envelope
curl -i https://yourdomain.com/api/admin/system
# Expected: HTTP/2 401, body {"success":false,"error":{"code":"ADMIN_TOKEN_INVALID",...}}

# CORS header must match production domain (not "*")
curl -si https://yourdomain.com/api/health | grep -i "access-control-allow-origin"
# Expected: access-control-allow-origin: https://yourdomain.com
```

---

## 9. Backup and Restore

### Setup daily PostgreSQL backup cron

```bash
mkdir -p /home/ubuntu/eol-backups
sudo chown ubuntu:ubuntu /home/ubuntu/eol-backups
chmod go-rwx /home/ubuntu/eol-backups

# Edit crontab
crontab -e
```

Add this line (runs at 02:00 daily, keeps 30 days):

```cron
0 2 * * * pg_dump -U eol_app -d eol_monitor -F c -f /home/ubuntu/eol-backups/eol-monitor-$(date +\%F-\%H\%M).dump && find /home/ubuntu/eol-backups -name "eol-monitor-*.dump" -mtime +30 -delete
```

Verify cron is set:

```bash
crontab -l
```

### Manual backup (before deploy or risky change)

```bash
pg_dump -U eol_app -d eol_monitor -F c -f /home/ubuntu/eol-backups/eol-monitor-manual-$(date +%F-%H%M).dump
```

### Restore from backup

```bash
# Stop backend first
pm2 stop eol-monitor-backend

# Restore into the PostgreSQL database
pg_restore -U eol_app -d eol_monitor -F c --clean --if-exists /home/ubuntu/eol-backups/eol-monitor-YYYY-MM-DD-HHMM.dump

# Restart backend
pm2 restart eol-monitor-backend

# Verify
curl -s http://127.0.0.1:3001/health | python3 -m json.tool
```

---

## 10. Smoke Test Checklist

Run this checklist after every deploy. Tick each item manually in a browser.

### Public pages (no workspace required)

- [ ] `https://yourdomain.com/overview` loads — hero text "Track AWS end-of-life risks before they break production." visible
- [ ] Trust strip and CTAs visible (Browse EOL Library, Connect Account, Try Demo Workspace)
- [ ] `https://yourdomain.com/general-eol` loads and shows service list
- [ ] Filter by service name and status works on General EOL page
- [ ] Admin link is NOT visible in sidebar nav

### Demo workspace

- [ ] Click "Try Demo Workspace" on Overview page — navigates to `/dashboard`
- [ ] Amber banner "Demo workspace — sample data only." appears at top
- [ ] Dashboard shows sample scan summary (Lambda, EC2, RDS, EKS data)
- [ ] Connected Accounts shows 4 demo accounts; Delete buttons are disabled
- [ ] Account Scan shows demo account; Rotate Token is disabled
- [ ] Services page shows demo inventory; Resource detail modal opens
- [ ] Alerts page shows demo alerts
- [ ] Settings shows Demo workspace name; Rotate Token is disabled
- [ ] "Exit Demo" clears session and returns to Overview (no demo data visible after)

### Real workspace

- [ ] Create a new workspace from Overview → Connect Account
- [ ] Copy and store workspace token (shown once)
- [ ] Access workspace: token accepted, dashboard loads (empty state shown)
- [ ] Admin creates/invites a workspace member
- [ ] Member magic login email/dev link creates a member session
- [ ] Viewer role can open Dashboard, General EOL, Services, Reports, Resource Detail, and Connected Accounts
- [ ] Viewer role cannot save Settings, acknowledge/snooze alerts, edit regions, delete accounts, manage members, rotate tokens, or see API tokens
- [ ] Editor role can run scans and create reports where intended, but cannot manage workspace security/admin-only areas
- [ ] Admin role can manage members, settings, API tokens, and workspace security controls
- [ ] Onboarding checklist appears on Dashboard
- [ ] Connect an AWS account (IAM role ARN + external ID)
- [ ] Run a scan — progress message updates
- [ ] If IAM role is misconfigured: error shows friendly message (ASSUME_ROLE_FAILED / ACCESS_DENIED) + Scan ID
- [ ] Successful scan: Dashboard summary updates, Alerts generated
- [ ] Services page shows scanned resources
- [ ] Resource detail slide-out opens with correct data
- [ ] Alerts page lists active alerts; acknowledge/snooze/resolve actions work for allowed roles
- [ ] Reports page opens
- [ ] Reports "Create Snapshot" is hidden/blocked for Viewer
- [ ] CSV export works
- [ ] Print report works
- [ ] Connected Accounts count matches Dashboard, Account Results, Services, Reports, and CSV totals
- [ ] Settings → Rotate Token shows new token once and invalidates old session
- [ ] Account Scan direct URL shows an admin-only message for Viewer
- [ ] Organization Scan is hidden when `ENABLE_ORG_SCAN=false` and `REACT_APP_ENABLE_ORG_SCAN=false`

### Settings and admin

- [ ] Settings page loads without errors
- [ ] Workspace name displayed correctly
- [ ] Viewer sees read-only settings copy: "VIEWER role: read-only settings" / admin-only save message
- [ ] `https://yourdomain.com/internal-admin` — requires admin token
- [ ] Admin dashboard shows workspace list, scan run history, system status
- [ ] Admin system tab shows feature flags disabled for unfinished modules

### HTTPS and security

- [ ] All pages load over HTTPS with valid certificate
- [ ] `http://yourdomain.com` redirects to `https://yourdomain.com`
- [ ] No mixed-content warnings in browser DevTools console
- [ ] `curl -i https://yourdomain.com/api/admin/system` returns 401 (no token)
- [ ] `CORS` header is `yourdomain.com`, not `*`

---

## 11. Rollback Steps

### Code rollback (git)

```bash
# On the server
cd /home/ubuntu/aws-end-of-life

# Check recent commits
git log --oneline -10

# Roll back to previous commit
git checkout <previous-commit-sha>

# Restart backend (no rebuild needed for Python changes)
pm2 restart eol-monitor-backend

# Rebuild and redeploy frontend if JSX/JS changed
cd frontend
export REACT_APP_API_URL=/api REACT_APP_SHOW_ADMIN_SHORTCUT=false REACT_APP_ENABLE_DEMO_DATA=false
export REACT_APP_ALLOW_INSECURE_ADMIN=false REACT_APP_ENABLE_ORG_SCAN=false
nvm use 20
npm run build
sudo systemctl reload nginx
```

### Data rollback

See [Restore from backup](#restore-from-backup) above.

### Nginx rollback

```bash
# Nginx stores previous config with Certbot backup
# To revert a manual nginx config change:
sudo nano /etc/nginx/sites-available/eol-monitor  # restore previous content
sudo nginx -t && sudo systemctl reload nginx
```

---

## 12. Known Limitations

These are accurate as of the current release. Plan migrations before scaling.

| Area | Current state | When to address |
|---|---|---|
| **Organization Scan** | End-to-end async backend execution and frontend polling are implemented behind flags. Backend tests and frontend build are passing. | Ready for controlled rollout; add SQS/account fan-out later only if very large AWS Organizations require it. |
| **Remediation Tracking** | Placeholder/flag only. | Future phase. |
| **SSO/SAML** | Placeholder/flag only. | Future phase. |
| **SaaS/Billing** | Placeholder/flag only. | Future phase. |
| **CI/CD Scan-on-push** | Placeholder/flag only. | Future phase. |
| **Notification delivery** | Backend notification foundation exists, but production email/Slack/SNS credentials must be configured and tested per environment. | Before promising external notification delivery. |
| **EC2 OS detection** | Confidence depends on SSM inventory data and AMI metadata availability. Unmanaged/golden-AMI instances may show `UNKNOWN` status. | No immediate fix; expected limitation of the scanning approach. |
| **Scan execution time** | Scans run synchronously in the Flask request cycle (up to ~90s). | For large accounts or many regions, move scans to a background worker or Lambda. |
| **Backup retention** | Manual cron — no alerting on backup failure. | Add a monitoring check on backup age before critical production use. |

---

## 13. Security Notes

These are non-negotiable for production deployment.

| Area | Requirement |
|---|---|
| **HTTPS** | All traffic must be over HTTPS. `ALLOWED_ORIGIN` must be the exact production domain — never `*` in production. |
| **Public URL** | `APP_PUBLIC_URL` must be the canonical HTTPS domain. Member magic-login links use this value. |
| **Dev login links** | `MEMBER_LOGIN_DEV_LINKS=false` in production. When true, raw one-time login links may appear in logs/API responses for dev testing. |
| **Admin token** | Set via `ADMIN_PORTAL_TOKEN` env var. Must be a strong random string. Never commit to git. Token is SHA-256 hashed in memory; the plain value is never stored to disk by the backend. |
| **Admin nav visibility** | `REACT_APP_SHOW_ADMIN_SHORTCUT=false` in production build — the admin link is hidden from the sidebar. The `/internal-admin` route still works for operators with the token. |
| **Workspace token isolation** | Workspace token is stored in localStorage keyed by `eolm_ws_token`. Admin token is in sessionStorage. They are separate and non-interchangeable. |
| **Token logging** | Tokens must never appear in server logs. The backend logs role ARNs (first 50 chars) and scan IDs. Verify `pm2 logs` does not contain token values. |
| **Database access** | PostgreSQL must not be publicly reachable. Use a private endpoint/security group rule limited to the app host and connect as `eol_app`, not `postgres`. |
| **Data directory** | `EOL_DATA_DIR` must be `chmod go-rwx` (no world/group read). The `secrets/` subdirectory holds the initial admin token file at `0600`. |
| **Scan error details** | Scan failure responses include `error.details` (raw boto3 exception) only to authenticated workspace users. Details are not exposed to the public. |
| **Demo workspace** | Demo session uses `ws_demo` ID and a read-only token. All write operations (scan, delete, rotate) are disabled in the UI and short-circuit in server function guards before any real API call is made. |
