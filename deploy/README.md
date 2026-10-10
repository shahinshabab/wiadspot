# Deployment

Merging into `main` runs `.github/workflows/deploy.yml`: tests, then an SSH
deploy that runs `deploy/deploy.sh` on the server (pull `main`, install,
migrate, collectstatic, restart gunicorn).

## One-time server setup (Ubuntu/Debian)

Easiest: copy `deploy/setup-server.sh` to the server and run
`sudo bash setup-server.sh <server-ip> "<contents of deploy_key.pub>"`
(it needs `main` to contain `deploy/`, so merge `dev` into `main` first, or
clone the repo yourself and check out `dev`). Manual steps:

```bash
sudo apt install python3-venv python3-pip nginx git
sudo adduser --disabled-password wiadspot && sudo usermod -aG www-data wiadspot
sudo mkdir -p /srv/wiadspot && sudo chown wiadspot: /srv/wiadspot
sudo -u wiadspot git clone https://github.com/shahinshabab/wiadspot /srv/wiadspot
sudo -u wiadspot cp /srv/wiadspot/deploy/env.example /srv/wiadspot/.env   # then edit it
sudo cp /srv/wiadspot/deploy/wiadspot.service /etc/systemd/system/ && sudo systemctl enable wiadspot
sudo cp /srv/wiadspot/deploy/nginx.conf /etc/nginx/sites-available/wiadspot
sudo ln -sf /etc/nginx/sites-available/wiadspot /etc/nginx/sites-enabled/wiadspot
sudo rm -f /etc/nginx/sites-enabled/default && sudo nginx -t && sudo systemctl reload nginx
echo 'wiadspot ALL=(root) NOPASSWD: /bin/systemctl restart wiadspot, /bin/systemctl is-active --quiet wiadspot' | sudo tee /etc/sudoers.d/wiadspot
sudo -u wiadspot bash /srv/wiadspot/deploy/deploy.sh   # first deploy
sudo -u wiadspot /srv/wiadspot/venv/bin/python /srv/wiadspot/manage.py createsuperuser
```

Make `/srv/wiadspot` traversable by nginx (`chmod 755 /srv/wiadspot`).

## GitHub secrets (repo → Settings → Secrets → Actions, environment `production`)

`SSH_HOST` (server IP), `SSH_USER` (`wiadspot`), `SSH_PRIVATE_KEY` (deploy key
whose public half is in the server user's `~/.ssh/authorized_keys`),
`APP_DIR` (`/srv/wiadspot`), optional `SSH_PORT`.

## Reaching the workspaces

| | Now (IP only, `USE_HTTPS=False`) | Later (domain) |
|---|---|---|
| Public site | `http://<ip>/` | `https://wiadspot.com` |
| Client | `http://<ip>/client/` | `https://client.wiadspot.com` |
| Owner | `http://<ip>/owner/` | `https://owner.wiadspot.com` |
| Manager | `http://<ip>/manager/` | `https://manager.wiadspot.com` |
| Admin | `http://<ip>/admin/` | `https://admin.wiadspot.com` |
| FAS | `http://<ip>/fas/<assetid>/` | same path on the domain |

No code change is needed when the domain arrives: point DNS (`@`, `www`, `client`,
`owner`, `manager`, `admin`) at the server, get a certificate
(`certbot --nginx -d wiadspot.com -d www... -d client... `), then set
`USE_HTTPS=True` in the server `.env`. On an IP all four workspaces share one
browser cookie, so use one workspace sign-in at a time; separate sessions per
workspace return with the subdomains.
