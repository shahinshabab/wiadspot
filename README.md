# WiadSpot

WiadSpot connects poster advertisers to Wi-Fi locations. This development version provides a responsive public website, four account workspaces, and image-poster submission using Bootstrap **5.3.8** and Bootstrap Icons **1.13.1**. Frontend dependencies are vendored with their MIT licenses; the new pages work without a CDN.

## Run locally

Use Python 3.12 or later. From your existing project folder, preserve any local changes before switching branches:

```bash
git fetch origin
git switch dev
git pull --ff-only origin dev
python -m venv venv
source venv/bin/activate
export PYTHONDONTWRITEBYTECODE=1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

On Windows, activate with `venv\Scripts\activate` and set `$env:PYTHONDONTWRITEBYTECODE = "1"` in PowerShell. The repository currently tracks historical bytecode files, so disabling bytecode generation avoids dirtying them locally.

SQLite, Django's local cache and the development server are sufficient. The `.env` file and `db.sqlite3` are ignored. Do not copy production credentials or data into development. Uploaded posters are stored in the ignored `media/` directory and are served by Django only when `DEBUG` is enabled. Production requires separate media hosting. No FAS logic, SMS calls, runtime ad-serving logic or billing tasks were changed by the website work.

## Accounts and pages

| Account | Existing Django group | Workspace |
| --- | --- | --- |
| Administrator | `Admin` | `admin.wiadspot.com` → `/portal/admin/` |
| Ad manager | `Manager` | `manager.wiadspot.com` → `/portal/manager/` |
| Advertising customer | `Client` | `client.wiadspot.com` → `/portal/customer/` |
| Customer-owned location account | `Partner` | `owner.wiadspot.com` → `/portal/owner/` |

The public website at `wiadspot.com` and `www.wiadspot.com` provides Home, About, Contact, Articles and Careers. Its Sign in menu offers **Client · Advertiser** and **Location owner**, linking to their respective subdomains. Managers and administrators use their workspace addresses directly. Each workspace root opens its dashboard or sends anonymous visitors to sign in. The hostname fixes the account type; changing a role in the URL or form cannot switch workspaces. Public private-page bookmarks redirect to the corresponding workspace; public sign-in pages do not accept passwords. Existing `clients`, `partner` and `ads` subdomains remain aliases.

Sessions and CSRF cookies are host-only, with secure cookies when `DEBUG=False`. Successful ERP sign-ins bind the session to its workspace role. A browser can keep four independent sessions; signing out of one leaves the others signed in. Cross-subdomain CSRF origins are not trusted. Workspace views also check group membership and ownership on the server. Accounts must already exist and belong to the matching group. An administrator can create users and groups using Django admin at `admin.wiadspot.com/secure-django-admin/` (or `/secure-django-admin/` on the development loopback host); create a development superuser with `python manage.py createsuperuser`. Django admin uses Django's staff/permission checks, separately from the four workspace groups. No demo credentials or automatic privilege grants ship with the website.

Customers can submit posters to active, bookable locations; location owners can submit to their own active, bookable locations. Each successful submission creates a draft campaign with pending review, a pending image ad and a pending placement with serving disabled. The manager dashboard links to the existing review tools, also exposed at `/management/reviews/`. Campaigns, ads and placements require their respective approval steps. The new website does not approve or deliver ads automatically.

Customers see their own campaigns and metrics. Owners see their own locations and campaigns placed there, plus campaigns they created. Admins and managers see platform activity. Metrics are month-to-date database aggregates, not illustrative numbers. Campaign search filters the eight recent campaigns displayed on the page.

## Local subdomain preview and deployment

Pull `dev`, install dependencies and run the existing Django project. With `DEBUG=True`, `localhost` or `127.0.0.1` provides all workspace screens on one host for quick local development. To test the full subdomain behavior, add these names to your **local computer's hosts file**:

```text
127.0.0.1 wiadspot.local www.wiadspot.local client.wiadspot.local owner.wiadspot.local manager.wiadspot.local admin.wiadspot.local
```

Run `python manage.py runserver 127.0.0.1:8000`, then open `http://wiadspot.local:8000` on that computer. The sign-in menu keeps the current port when opening `client.wiadspot.local:8000` or `owner.wiadspot.local:8000`. Accounts and matching groups must exist in your local database. Never use preview screenshots as evidence of live billing or live network delivery.

For production, configure DNS for the main site and all four subdomains, HTTPS certificates and reverse-proxy routing to this Django service; serve static/media files separately and set `DEBUG=False` and a private `SECRET_KEY`. These code changes do not provision DNS, certificates or a production server. The public website and workspaces have separate URLconfs and authentication boundaries in one Django project; they still share the process and database. Operational isolation would require separate services.

## FAS and the advertisement pool

`/fas/<assetid>/` and `/wiadspot/fas/<assetid>/` both invoke the **unchanged** `ads.views.fas` handler before ERP host routing, on the public domain or any supported workspace domain. `/fas/` and `/wiadspot/fas/` also reach that handler for gateways that supply their location via gateway parameters. Keep the gateway token/encrypted parameters required by the existing protocol. AuthMon polling should use the explicit asset-ID route. Both `/ad-click/<session-id>/` and `/wiadspot/ad-click/<session-id>/` invoke the existing click logger.

FAS remains anonymous with respect to ERP: ERP sessions do not select ads, authenticate Wi-Fi visitors, change gateway parameters or bypass OTP. The existing pool determines eligibility from campaign/ad/placement approval, availability, subscription and wallet rules. ERP browsing and FAS requests do not sign each other out. FAS source files, templates, SMS services and runtime pool code were not edited.

**Existing FAS issue found during validation:** `handle_authmon_common` in `ads/utils.py` queries `Asset.is_active`, but `Asset` has `status` and no `is_active` field; a real AuthMon poll currently returns 500. This also affects the original route. It remains unchanged under the instruction to preserve FAS code and requires a separate FAS fix before relying on gateway authentication in production. Ad-pool impression and click tests pass; they do not validate the entire OTP/gateway exchange.

## Billing feasibility and remaining work

The requested business models are feasible:

- **WiadSpot-hosted locations:** a charge per user, billed monthly.
- **Customer-owned locations:** a monthly subscription. SMS charges, if required, need a separate rate and usage definition.

Existing `Asset` records distinguish `ADMIN` (WiadSpot hosted) from `PARTNER` (customer owned). Campaigns, image ads, placements, subscriptions, audience identities/sessions and delivery metrics already have models. The website displays these concepts and an assigned subscription's status.

**Monthly invoicing and payment collection are not implemented.** The existing billing job uses prepaid wallets and event-based deductions; it must not be treated as a monthly per-user invoice engine. Currency, per-user rate, subscription prices, tax treatment and the definition of a billable user remain to be agreed. For example, a unique verified visitor per location per month differs from charging for every login or every served ad. The owner dashboard's unique verified visitor count is a reporting metric, not an invoice total. SMS sessions do not reliably count sends or retries; provider delivery/usage records are needed for SMS billing.

A follow-up billing implementation should add effective-dated rates, immutable monthly usage and invoice line items, idempotent month closing, account/location allocation rules, SMS usage reconciliation if applicable, and a payment integration. It must reconcile or replace the prepaid charging path to prevent double charging. No financial totals or payment success are invented in this version.

## Validation and development workflow

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test core.test_portals core.test_channels --noinput
```

The 32 tests cover public pages and articles, host and role isolation, independent sign-in/logout, CSRF protection and production cookie flags, customer/owner data isolation, pending poster submission, review actions, contact validation, and real pool impressions/clicks. The pool test serves an approved poster anonymously and under every ERP role, on the public host and all four workspace hosts, through both FAS prefixes. AuthMon routing delegation is checked separately; it is not a live gateway/SMS test. Browser checks cover the five landing pages, two public sign-in choices, four simultaneous host-only sessions, poster/review screens and mobile navigation.

## Screenshots

The dashboard captures use an isolated preview database and are labelled **sample data**. They do not show live invoices or customer activity.

- [Public homepage](docs/screenshots/homepage.png) and [mobile homepage](docs/screenshots/homepage-mobile.png)
- [Administrator workspace](docs/screenshots/admin-dashboard.png)
- [Ad manager workspace](docs/screenshots/manager-dashboard.png) and [review queue](docs/screenshots/manager-review-queue.png)
- [Advertising customer workspace](docs/screenshots/customer-dashboard.png)
- [Location-owner workspace](docs/screenshots/owner-dashboard.png) and [mobile view](docs/screenshots/owner-dashboard-mobile.png)
- [Client sign-in](docs/screenshots/sign-in.png), [public sign-in menu](docs/screenshots/homepage-sign-in-menu.png), [workspace choices](docs/screenshots/workspace-options.png) and [poster submission](docs/screenshots/poster-submission.png)
- [About](docs/screenshots/about.png), [Contact](docs/screenshots/contact.png), [Articles](docs/screenshots/articles.png) and [Careers](docs/screenshots/careers.png)

`main` is reserved for production. Start work on a task branch from the latest `dev`, validate it, then merge into `dev`. Pull `dev` locally to receive changes. Do not merge development work into `main` without an explicit production promotion request.
