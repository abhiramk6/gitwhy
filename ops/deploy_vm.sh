#!/usr/bin/env bash
# Deploy Gitwhy on this VM: code -> /opt/gitwhy, systemd service (user gitwhy), Caddy for HTTPS on <ip>.sslip.io.
# Idempotent: rerun after code changes. Secrets are read from ~/.config/gitwhy/*.env and written to /etc/gitwhy/app.env (mode 640, root:gitwhy).
# Usage (as root): ops/deploy_vm.sh [hostname]      default hostname: <public-ip-with-dashes>.sslip.io
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"; APP=/opt/gitwhy
IP=$(curl -4 -s --max-time 10 https://api.ipify.org); HOST="${1:-${IP//./-}.sslip.io}"
id gitwhy >/dev/null 2>&1 || useradd -r -m -d /var/lib/gitwhy -s /usr/sbin/nologin gitwhy
mkdir -p "$APP/frontend" /etc/gitwhy /var/lib/gitwhy/org-secrets
rsync -a --delete --exclude .venv --exclude __pycache__ --exclude '*.pyc' "$SRC/backend/" "$APP/backend/"
rsync -a --delete "$SRC/migrations/" "$APP/migrations/"; rsync -a --delete "$SRC/fixtures/" "$APP/fixtures/"
rsync -a --delete "$SRC/frontend/dist/" "$APP/frontend/dist/"; cp "$SRC/product.json" "$APP/product.json"
[ -d "$APP/venv" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q fastapi 'uvicorn[standard]' 'psycopg[binary]' pydantic-settings google-genai httpx
chown -R root:root "$APP"; chmod -R a+rX "$APP"; chown -R gitwhy:gitwhy /var/lib/gitwhy; chmod 700 /var/lib/gitwhy/org-secrets

if [ ! -f /etc/gitwhy/app.env ]; then
  set -a; . ~/.config/gitwhy/db.env; . ~/.config/gitwhy/gemini.env; . ~/.config/gitwhy/voyage.env; set +a
  umask 027
  cat > /etc/gitwhy/app.env <<ENV
DATABASE_URL=${DATABASE_URL}
GEMINI_API_KEY=${GEMINI_API_KEY}
GEMINI_API_KEY_BACKUP=${GEMINI_API_KEY_BACKUP:-}
VOYAGE_API_KEY=${VOYAGE_API_KEY}
PROVIDER=gemini
EMBED_PROVIDER=voyage
ENVIRONMENT=production
AUTH_REQUIRED=1
ORG_SLUG=northwind
DEMO_TOKEN=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)
GITWHY_SESSION_SECRET=$(head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 64)
SECRETS_DIR=/var/lib/gitwhy/org-secrets
SYNC_EMBED=0
ENV
  chown root:gitwhy /etc/gitwhy/app.env; chmod 640 /etc/gitwhy/app.env
  umask 022
fi

cat > /etc/systemd/system/gitwhy.service <<UNIT
[Unit]
Description=Gitwhy
After=network-online.target postgresql.service
Wants=network-online.target
[Service]
User=gitwhy
Group=gitwhy
WorkingDirectory=$APP/backend
EnvironmentFile=/etc/gitwhy/app.env
ExecStartPre=$APP/venv/bin/python -c "from app.db import migrate; migrate()"
ExecStart=$APP/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=/var/lib/gitwhy
[Install]
WantedBy=multi-user.target
UNIT

if ! command -v caddy >/dev/null; then
  curl -fsSL "https://caddyserver.com/api/download?os=linux&arch=amd64" -o /usr/local/bin/caddy
  chmod 755 /usr/local/bin/caddy; setcap cap_net_bind_service=+ep /usr/local/bin/caddy
fi
id caddy >/dev/null 2>&1 || useradd -r -m -d /var/lib/caddy -s /usr/sbin/nologin caddy
mkdir -p /etc/caddy
cat > /etc/caddy/Caddyfile <<CADDY
$HOST {
    encode gzip
    header {
        Strict-Transport-Security "max-age=31536000"
        X-Content-Type-Options nosniff
        Referrer-Policy no-referrer
        X-Frame-Options DENY
    }
    request_body {
        max_size 2MB
    }
    reverse_proxy 127.0.0.1:8080
}
CADDY
cat > /etc/systemd/system/caddy.service <<UNIT
[Unit]
Description=Caddy
After=network-online.target
[Service]
User=caddy
Group=caddy
ExecStart=/usr/local/bin/caddy run --environ --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile
Restart=on-failure
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now gitwhy caddy >/dev/null 2>&1
systemctl restart gitwhy; systemctl reload caddy 2>/dev/null || systemctl restart caddy
echo "deployed: https://$HOST"
