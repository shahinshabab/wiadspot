#!/usr/bin/env bash
set -euo pipefail
umask 022
app_dir=/srv/wiadspot
cd "$app_dir"
if [ "$(id -un)" != wiadspot ]; then
    echo 'Run deployment as wiadspot.' >&2
    exit 1
fi
mkdir -p var/backups var/static var/media
chmod 700 var/backups
exec 9>var/deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
test -f .env || { echo 'Create the private .env first.' >&2; exit 1; }
if grep -q '^SECRET_KEY=CHANGE_ME$' .env; then
    echo 'Generate a private SECRET_KEY before deploying.' >&2
    exit 1
fi
test "$(git branch --show-current)" = main
git diff --quiet
git diff --cached --quiet
git fetch origin main
deploy_commit=${WIADSPOT_DEPLOY_SHA:-origin/main}
git merge-base --is-ancestor "$deploy_commit" origin/main
git merge --ff-only "$deploy_commit"
test "$(git rev-parse HEAD)" = "$(git rev-parse "$deploy_commit")"
if [ ! -x venv/bin/python ]; then python3 -m venv venv; fi
venv/bin/python -m pip install -r requirements.txt
venv/bin/python manage.py check
venv/bin/python - <<'PY'
import os, sqlite3
from datetime import datetime, timezone
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.conf import settings
config = settings.DATABASES['default']
if config['ENGINE'] == 'django.db.backends.sqlite3':
    source_path = Path(config['NAME'])
    if source_path.exists():
        backup = Path('var/backups') / ('db-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')
        with sqlite3.connect(str(source_path)) as source, sqlite3.connect(str(backup)) as target:
            source.backup(target)
        backup.chmod(0o600)
        print('SQLite database backup created:', backup)
PY
umask 077
venv/bin/python manage.py migrate --noinput
umask 022
venv/bin/python manage.py collectstatic --noinput
sudo -n /bin/systemctl restart wiadspot
sudo -n /bin/systemctl is-active --quiet wiadspot
probe() {
    curl --fail --silent --show-error --retry 8 --retry-connrefused --retry-delay 2 --max-time 10 -H "Host: $1" "http://127.0.0.1:8000$2" >/dev/null
}
if [ "$(venv/bin/python manage.py shell -c 'from django.conf import settings; print(settings.ROUTING_MODE)')" = "path" ]; then
    for workspace_path in / /client/ /owner/ /manager/ /admin/; do
        probe 127.0.0.1 "$workspace_path"
    done
else
    for portal_host in wiadspot.com www.wiadspot.com client.wiadspot.com owner.wiadspot.com manager.wiadspot.com admin.wiadspot.com partner.wiadspot.com clients.wiadspot.com ads.wiadspot.com; do
        probe "$portal_host" /
    done
fi
echo "Deployment healthy at $(git rev-parse --short HEAD)."
