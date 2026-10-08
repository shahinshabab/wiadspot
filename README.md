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
| Administrator | `Admin` | `/portal/admin/` |
| Ad manager | `Manager` | `/portal/manager/` |
| Advertising customer | `Client` | `/portal/customer/` |
| Customer-owned location account | `Partner` | `/portal/owner/` |

Sign in at `/accounts/login/` and select the account type. Accounts must already exist and belong to the matching group. An administrator can create users and groups using Django admin at `/secure-django-admin/`; create a development superuser with `python manage.py createsuperuser`. Django admin uses Django's staff/permission checks, separately from the four workspace groups. No demo credentials or automatic privilege grants ship with the website.

Customers can submit posters to active, bookable locations; location owners can submit to their own active, bookable locations. Each successful submission creates a draft campaign with pending review, a pending image ad and a pending placement with serving disabled. The manager dashboard links to the existing review tools, also exposed at `/management/reviews/`. Campaigns, ads and placements require their respective approval steps. The new website does not approve or deliver ads automatically.

Customers see their own campaigns and metrics. Owners see their own locations and campaigns placed there, plus campaigns they created. Admins and managers see platform activity. Metrics are month-to-date database aggregates, not illustrative numbers. Campaign search filters the eight recent campaigns displayed on the page.

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
python manage.py test core.test_portals --noinput
```

The portal tests cover all four access boundaries, successful/wrong-role login, logout, customer/owner data isolation, pending poster submission, image validation, unavailable locations and duplicate campaign names.

## Screenshots

The dashboard captures use an isolated preview database and are labelled **sample data**. They do not show live invoices or customer activity.

- [Public homepage](docs/screenshots/homepage.png) and [mobile homepage](docs/screenshots/homepage-mobile.png)
- [Administrator workspace](docs/screenshots/admin-dashboard.png)
- [Ad manager workspace](docs/screenshots/manager-dashboard.png) and [review queue](docs/screenshots/manager-review-queue.png)
- [Advertising customer workspace](docs/screenshots/customer-dashboard.png)
- [Location-owner workspace](docs/screenshots/owner-dashboard.png) and [mobile view](docs/screenshots/owner-dashboard-mobile.png)
- [Account sign-in](docs/screenshots/sign-in.png) and [poster submission](docs/screenshots/poster-submission.png)

`main` is reserved for production. Start work on a task branch from the latest `dev`, validate it, then merge into `dev`. Pull `dev` locally to receive changes. Do not merge development work into `main` without an explicit production promotion request.
