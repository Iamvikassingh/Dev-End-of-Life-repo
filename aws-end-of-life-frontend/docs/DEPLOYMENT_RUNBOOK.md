# Deployment Runbook — AWS EOL Monitor

---

## Prerequisites

- EC2 instance (Ubuntu 22.04 recommended, t3.small or larger)
- Python 3.11+ installed
- Node.js 20+ installed
- PM2 installed globally: `npm install -g pm2`
- SSH access to EC2 instance
- Domain or EC2 public IP for frontend access

---

## Directory Structure (on EC2)

```
/home/ubuntu/
  ├─ aws-end-of-life-backend/
  │    ├─ api_handler.py
  │    ├─ eol_collector.py
  │    ├─ general_eol.py
  │    ├─ requirements.txt
  │    └─ ...
  ├─ aws-end-of-life-frontend/
  │    ├─ src/
  │    ├─ dist/                   ← built output, served as static files
  │    ├─ package.json
  │    └─ ...
  └─ eol-data/                    ← data directory (or set EOL_DATA_DIR)
       ├─ workspaces.json
       ├─ inventory/
       └─ scans/
```

---

## Environment Variables

Set these in `/home/ubuntu/.env` or in your PM2 ecosystem file.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `APP_ENV` | Yes | `development` | Set to `production` for prod |
| `ALLOWED_ORIGIN` | Yes in prod | `*` | Frontend URL; `*` blocked in production |
| `PORT` | No | `3001` | Backend listen port |
| `ADMIN_TOKEN` | Yes | auto-generated | System admin token |
| `EOL_DATA_DIR` | No | `/var/lib/eol-data` | Persistent storage directory |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## First-Time Setup

### 1. Install Python dependencies

```bash
cd /home/ubuntu/aws-end-of-life-backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Install Node dependencies and build frontend

```bash
cd /home/ubuntu/aws-end-of-life-frontend
npm install
npm run build
```

### 3. Create data directory

```bash
sudo mkdir -p /var/lib/eol-data
sudo chown ubuntu:ubuntu /var/lib/eol-data
```

### 4. Create PM2 ecosystem file

```bash
cat > /home/ubuntu/ecosystem.config.js << 'EOF'
module.exports = {
  apps: [
    {
      name: "eol-backend",
      cwd: "/home/ubuntu/aws-end-of-life-backend",
      script: "python3",
      args: "api_handler.py",
      interpreter: "none",
      env: {
        APP_ENV: "production",
        ALLOWED_ORIGIN: "http://YOUR_EC2_IP_OR_DOMAIN",
        PORT: "3001",
        EOL_DATA_DIR: "/var/lib/eol-data",
        LOG_LEVEL: "INFO"
      }
    }
  ]
};
EOF
```

### 5. Start backend with PM2

```bash
cd /home/ubuntu
pm2 start ecosystem.config.js
pm2 save
pm2 startup    # follow the printed command to enable auto-start on reboot
```

### 6. Serve frontend

Option A — nginx (recommended for production):

```nginx
server {
    listen 80;
    server_name _;
    root /home/ubuntu/aws-end-of-life-frontend/dist;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:3001/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo apt install nginx -y
sudo cp eol-nginx.conf /etc/nginx/sites-available/eol
sudo ln -s /etc/nginx/sites-available/eol /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Option B — PM2 serve (simpler for demo):

```bash
pm2 serve /home/ubuntu/aws-end-of-life-frontend/dist 8080 --name eol-frontend --spa
pm2 save
```

---

## Deploy Script (automated)

Use `deploy-ec2.sh` from the repo root for all subsequent deploys:

```bash
# From local machine — syncs code + restarts + validates
./deploy-ec2.sh ubuntu@<EC2_IP>

# With workspace token for full validation
WORKSPACE_TOKEN=eolm_live_xxxx ./deploy-ec2.sh ubuntu@<EC2_IP>
```

The script:
1. rsyncs backend (excluding `__pycache__`, `.pyc`, `.git`)
2. rsyncs frontend (excluding `node_modules`, `build`, `dist`)
3. SSHs into EC2 and runs remote steps
4. Restarts PM2 process (`eol-backend` or `eol-api`)
5. Health check: `GET /health`
6. Rebuilds frontend
7. If `WORKSPACE_TOKEN` is set: runs regression checks

---

## PM2 Commands

```bash
pm2 list                        # show all processes
pm2 status eol-backend          # check process status
pm2 logs eol-backend            # tail live logs
pm2 logs eol-backend --lines 200  # view last 200 log lines
pm2 restart eol-backend         # restart without code change
pm2 reload eol-backend          # zero-downtime reload (if supported)
pm2 stop eol-backend            # stop
pm2 delete eol-backend          # remove from PM2
pm2 save                        # persist current process list
pm2 resurrect                   # restore saved process list after reboot
```

---

## After Every Deploy

1. `pm2 restart eol-backend`
2. Verify: `curl http://127.0.0.1:3001/health`
3. Rebuild frontend: `cd /home/ubuntu/aws-end-of-life-frontend && npm run build`
4. If using nginx: reload if nginx config changed (`sudo systemctl reload nginx`)
5. Run a fresh scan from the dashboard to verify classification changes

---

## Checking Logs

```bash
# Live tail
pm2 logs eol-backend

# Last 500 lines
pm2 logs eol-backend --lines 500

# PM2 log files
ls ~/.pm2/logs/
cat ~/.pm2/logs/eol-backend-out.log    # stdout
cat ~/.pm2/logs/eol-backend-error.log  # stderr

# Filter for errors
pm2 logs eol-backend --lines 200 | grep -i error
```

---

## Updating the endoflife.date Cache

The general EOL library caches responses in memory. Cache is cleared on restart. To force fresh data:

```bash
pm2 restart eol-backend
```

If you need a file-based cache (survives restarts), set `EOL_CACHE_FILE=/var/lib/eol-data/eol-cache.json` (feature available in Phase 2).

---

## Data Backup

The data directory (`/var/lib/eol-data`) contains all workspace and inventory data. Back it up before deploying breaking changes:

```bash
tar -czf eol-data-backup-$(date +%Y%m%d).tar.gz /var/lib/eol-data
```

---

## Security Hardening Checklist (before public exposure)

- [ ] `APP_ENV=production` set
- [ ] `ALLOWED_ORIGIN` set to specific frontend URL (not `*`)
- [ ] EC2 security group: port 3001 not exposed publicly (only nginx proxy on 80/443)
- [ ] EC2 security group: SSH limited to your IP only
- [ ] HTTPS configured (Let's Encrypt / ACM) if using a domain
- [ ] Admin token changed from default
- [ ] PM2 log rotation configured: `pm2 install pm2-logrotate`

---

## Rollback

If a deploy breaks the backend:

```bash
# On EC2: restore previous code from git or backup
cd /home/ubuntu/aws-end-of-life-backend
git stash          # or git checkout HEAD~1

pm2 restart eol-backend
curl http://127.0.0.1:3001/health
```

For data directory corruption:

```bash
pm2 stop eol-backend
cp -r /var/lib/eol-data /var/lib/eol-data-broken
cp -r eol-data-backup/ /var/lib/eol-data
pm2 start eol-backend
```

---

## Common Issues

| Issue | Cause | Fix |
|---|---|---|
| `pm2 restart eol-backend` — process not found | Wrong process name | Run `pm2 list` to find actual name |
| Backend starts but health check fails | Wrong port / Python error on startup | `pm2 logs eol-backend --lines 50` to see error |
| Frontend shows blank page | Old `dist` build | Run `npm run build` again |
| CORS error in browser | `ALLOWED_ORIGIN` mismatch | Set `ALLOWED_ORIGIN` to exact frontend URL |
| `RuntimeError: FATAL: CORS wildcard not allowed in production` | `ALLOWED_ORIGIN=*` with `APP_ENV=production` | Set correct `ALLOWED_ORIGIN` |
| Inventory not refreshing after scan | DynamoDB GSI delay (if using DynamoDB) | 1.5s delay built into frontend; wait 3s and refresh |
| Python `ModuleNotFoundError` | venv not activated or deps not installed | `source venv/bin/activate && pip install -r requirements.txt` |
