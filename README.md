# RESILIENCE Business Management System

A Django web platform that replaces paper-based management with one secure site
for Management, Supervisors, Staff and the Secretary. Built from the
*RESILIENCE - Business Management System* proposal.

## What it does

| Area | Details |
| --- | --- |
| **Roles** | Manager, Supervisor, Staff, Secretary. One account per person; role decides what they see. |
| **Reporting workflow** | Staff submit a report -> their supervisor reviews and gives feedback -> it is visible to the Manager, who replies and marks it completed. Supervisors can also submit reports upward to the Manager. Every step is time-stamped and tied to a user. |
| **Dashboards** | Manager: pending / completed reports, active supervisors, feedback sent, 6-month pending-vs-completed chart, supervisor performance, activity feed, feedback history. Supervisor: reports to review and team overview. Staff: report status and latest feedback. Secretary: spending overview. |
| **Expenditure tracker** | Secretary has full access: record, edit, delete, categorise, search, filter by date/category, CSV export. Manager has view-only access. Every create/edit/delete is kept in a permanent history. |
| **GPS tracking** | Staff and supervisors turn on location from their dashboard. The server compares each reading with their work site: ON LOCATION (inside the site radius), NEAR LOCATION (up to 50 m), OFF LOCATION (beyond 50 m), or GPS WEAK when the phone's accuracy is worse than ±50 m. The Manager's GPS Tracker shows counts, a live map, a list and alerts, refreshing every 15 seconds; work sites, working hours (including overnight shifts) and location history are managed there. Only the Manager sees locations. |
| **Account management** | The Manager adds/edits team members, assigns staff to supervisors, resets passwords, disables accounts. Everyone can update their own details and change their password. |

### Access matrix (enforced in code and covered by tests)

| Permission | Manager | Supervisor | Staff | Secretary |
| --- | :-: | :-: | :-: | :-: |
| View own reports | yes | yes | yes | - |
| View team / staff reports | all | own team only | - | - |
| Submit reports | - | yes (to management) | yes | - |
| Reply to reports | yes (can complete) | own team only | - | - |
| Company-wide dashboard | yes | - | - | - |
| Expenditure tracker | view only | - | - | full |
| Manage user accounts | yes | - | - | - |
| Share own location | - | yes | yes | - |
| See anyone's location, sites, history | yes | - | - | - |

A report outside someone's scope returns **404** (its existence is not revealed);
a page their role can never use returns **403**.

## Run it locally

Requires Python 3.12+.

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

set DJANGO_DEBUG=1                # macOS/Linux: export DJANGO_DEBUG=1
python manage.py migrate
python manage.py createsuperuser  # becomes the Manager account
python manage.py runserver
```

Open http://127.0.0.1:8000 and sign in.

Want sample data to explore first? `python manage.py seed_demo` creates a
manager, two supervisors, four staff, a secretary, reports and expenses, and
prints a random password for each account once (development databases only).
It also creates two GPS work sites in Kisumu with Monday-Saturday hours.

## GPS tracking

**Manager setup**
1. *Work sites* -> *Add a site*: name it, click the map (or type latitude/longitude), choose the on-location radius (30 m suits most sites) and tick the working days and hours. An end time earlier than the start (18:00 to 06:00) runs past midnight.
2. *Assign sites*: press *Change* next to each staff member or supervisor and pick their site. Tick "own working hours" only if they work different hours from their site.
3. *Live tracker*: counts, alerts, map and list. It refreshes itself.
4. *Location history*: every reading, filterable by person, site, date and status. Kept for 90 days.

**Staff and supervisors**: press *Turn on location* on the dashboard (or *My location*) and allow location when the phone asks. Keep the page open with the screen on; tracking stops if the phone is locked, the page is closed or they sign out. During working hours a red reminder appears until location is on, and the Manager is alerted.

**Requirements**
- Phones only share location with sites served over **HTTPS** (`http://127.0.0.1` on the same PC also works for testing). To try it from a phone before hosting, use an HTTPS tunnel such as `cloudflared tunnel --url http://127.0.0.1:8000` and add the tunnel's address to `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`.
- Maps use OpenStreetMap tiles through Leaflet (bundled in `static/vendor/leaflet`). No API key and no cost; the map needs internet access.
- Alerts update whenever the GPS Tracker page is open. To keep alerts current and delete old history when nobody has it open, schedule `python manage.py check_tracking` every 5 minutes (cron, Windows Task Scheduler or your host's scheduled jobs).

## Tests

```bash
python manage.py test
```

## Configuration (environment variables)

See `.env.example`. Nothing secret is stored in the code.

| Variable | Purpose |
| --- | --- |
| `DJANGO_DEBUG` | `1` for local development. Leave unset in production. |
| `DJANGO_SECRET_KEY` | **Required** when `DJANGO_DEBUG` is off. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | e.g. `https://bms.example.com`. |
| `DB_ENGINE=postgresql` + `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Use PostgreSQL instead of the default SQLite. |

## Deploying

1. Set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and the PostgreSQL variables (SQLite is for development).
2. `pip install -r requirements.txt`, `python manage.py migrate`, `python manage.py collectstatic`.
3. Serve with a WSGI server (e.g. `gunicorn config.wsgi`) behind HTTPS, and serve `staticfiles/` with your web server (or add WhiteNoise).
4. With `DJANGO_DEBUG` off, HTTPS redirect, secure cookies and HSTS turn on automatically. Check with `python manage.py check --deploy`.
5. Back up the database regularly.

## Project layout

```
accounts/   users, roles, login, profile, Manager's team screens, access helpers
reports/    reports, replies, workflow rules, dashboards' queries
finance/    expenses, categories, permanent history, CSV export
tracking/   GPS: sites, working hours, location updates, geofence rules, alerts, manager screens
core/       role-based home dashboards, seed_demo command, shared test base
templates/  HTML      static/css/app.css  styling (matches the website's brand)
```

## Not built yet (listed as "future potential" in the proposal)

Mobile app, automated notifications (email/SMS), advanced analytics, payroll,
attendance tracking and automated financial reports.
