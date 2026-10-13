# Ubuntu production deployment

Application: `/srv/wiadspot`, Linux account: `wiadspot`, service: `wiadspot.service`.
Use Python 3.12 or newer. Install python3-venv, python3-pip, nginx, git, curl and util-linux.

Copy `env.example` to `.env`, generate a random SECRET_KEY, set DEBUG=False,
and restrict `.env` permissions to 600. Integration credentials are optional
and must stay out of Git. SQLite, static files, media and pre-migration database
backups live under `var/`; SQLite backups are private to wiadspot.

Install `wiadspot.service` into `/etc/systemd/system/`, run daemon-reload and
enable wiadspot. Install nginx.conf as the wiadspot site, disable the default
site, validate with nginx -t, and reload Nginx. Add wiadspot to www-data.

The sudoers entry for wiadspot must allow only:
`/bin/systemctl restart wiadspot` and `/bin/systemctl is-active --quiet wiadspot`.
Validate the entry with visudo -cf before installing it with mode 440.

First and later manual deployments: `sudo -u wiadspot bash /srv/wiadspot/deploy/deploy.sh`.
The script fast-forwards the deploy branch (`dev`, set by `WIADSPOT_DEPLOY_BRANCH`), installs dependencies, checks Django, backs up
existing SQLite data, migrates, collects static files, restarts and health-checks.
It refuses concurrent deployments or modified tracked files. It does not delete
local credentials, uploads or backups. Failed migrations require investigation;
code and database backups are not automatically rolled back.

The GitHub workflow uses the existing runner label `wiadspot-prod`, running as
ubuntu. Ubuntu must be allowed to run the deployment script as wiadspot.
Install that runner's systemd service so it survives logout/reboot. Only pushes
to dev and manual runs on dev trigger production deployment; PR jobs must not
use this production runner.

Routing: `ROUTING_MODE=path` (default) serves the site at `http://<server-ip>/`
and each workspace at `/client/`, `/owner/`, `/manager/` and `/admin/`; no DNS is
needed. When a domain exists, set `ROUTING_MODE=subdomain` in `.env` (and
`SECURE_COOKIES=True` once HTTPS is on) to use `client.<domain>` etc. again.
Path mode accepts any Host header unless `ALLOW_ANY_HOST=False`.

The supplied Nginx file provides HTTP only. Set up domain DNS and HTTPS before
using public login pages. Django keeps secure authentication cookies enabled.
External MSG91/FAS functionality requires the corresponding private credentials.

Create the admin interactively:
`sudo -u wiadspot /srv/wiadspot/venv/bin/python /srv/wiadspot/manage.py createsuperuser`.

## Billing cycle and uploads (ad marketplace)

Per-user charges, owner earnings and campaign status changes are produced by
`manage.py run_ad_cycle`. Nothing schedules it by default: install
`wiadspot-cycle.service` and `wiadspot-cycle.timer` into `/etc/systemd/system/`,
then `systemctl daemon-reload && systemctl enable --now wiadspot-cycle.timer`.
Until the timer runs, views are served and logged but not billed or credited.

The supplied `nginx.conf` raises the upload limit to 40 MB (video ads) and serves
`/media/` with `nosniff`, a sandboxing CSP, and no script or HTML types. Reinstall
it and run `nginx -t && systemctl reload nginx` after deploying. The video size
limit set in the admin workspace (default 20 MB) must stay below that.

Spot devices authenticate to `/device/v1/` with a key created in the admin
workspace (Locations, then a location). Gunicorn runs two workers and device rate
limits use per-process memory, so the real limit is looser than the numbers in
the code; put an Nginx `limit_req` in front of `/device/` if that matters.
