#!/usr/bin/env bash
# One-time setup for a fresh Ubuntu/Debian VPS. Run as root (or with sudo):
#   curl -fsSL https://raw.githubusercontent.com/shahinshabab/wiadspot/main/deploy/setup-server.sh | sudo bash -s -- <server-ip> "<deploy-public-key>"
# Re-running is safe. Needs the repo to be public, or clone it yourself first.
set -euo pipefail

SERVER_IP="${1:?usage: setup-server.sh <server-ip> \"<deploy-public-key>\"}"
PUBKEY="${2:?usage: setup-server.sh <server-ip> \"<deploy-public-key>\"}"
APP=/srv/wiadspot
REPO=https://github.com/shahinshabab/wiadspot

apt-get update -qq
apt-get install -y -qq python3-venv python3-pip nginx git

id wiadspot &>/dev/null || adduser --disabled-password --gecos "" wiadspot
usermod -aG www-data wiadspot

# Deploy key used by GitHub Actions
install -d -m 700 -o wiadspot -g wiadspot /home/wiadspot/.ssh
grep -qxF "$PUBKEY" /home/wiadspot/.ssh/authorized_keys 2>/dev/null \
  || echo "$PUBKEY" >> /home/wiadspot/.ssh/authorized_keys
chown wiadspot: /home/wiadspot/.ssh/authorized_keys
chmod 600 /home/wiadspot/.ssh/authorized_keys

# Code
mkdir -p "$APP" && chown wiadspot: "$APP"
[ -d "$APP/.git" ] || sudo -u wiadspot git clone "$REPO" "$APP"
chmod 755 "$APP"

# .env (created once, never overwritten)
if [ ! -f "$APP/.env" ]; then
  SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')
  cat > "$APP/.env" <<ENV
DEBUG=False
SECRET_KEY=$SECRET
ALLOWED_HOSTS_EXTRA=$SERVER_IP
USE_HTTPS=False
FAS_KEY=
MSG91_AUTHKEY=
MSG91_TEMPLATE_ID=
ENV
  chown wiadspot: "$APP/.env" && chmod 600 "$APP/.env"
fi

# Services
cp "$APP/deploy/wiadspot.service" /etc/systemd/system/wiadspot.service
systemctl daemon-reload && systemctl enable wiadspot
cp "$APP/deploy/nginx.conf" /etc/nginx/sites-available/wiadspot
ln -sf /etc/nginx/sites-available/wiadspot /etc/nginx/sites-enabled/wiadspot
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# Allow the deploy user to restart only this service
echo 'wiadspot ALL=(root) NOPASSWD: /bin/systemctl restart wiadspot, /usr/bin/systemctl restart wiadspot, /bin/systemctl is-active --quiet wiadspot, /usr/bin/systemctl is-active --quiet wiadspot' > /etc/sudoers.d/wiadspot
chmod 440 /etc/sudoers.d/wiadspot

# First deploy of whatever is on main
sudo -u wiadspot bash "$APP/deploy/deploy.sh"

echo
echo "Done. Open http://$SERVER_IP/ . Create an admin user with:"
echo "  sudo -u wiadspot $APP/venv/bin/python $APP/manage.py createsuperuser"
