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
| **Clients** | The office keeps every client with contact details, contract, monthly charge, office notes, a responsible supervisor (with history) and linked GPS work sites. Clients have no login. |
| **Client issues** | The office records a problem a client reports. It goes straight to that client's supervisor (or shows SUPERVISOR NEEDED). The supervisor adds notes and marks it resolved; only the office closes or reopens it. |
| **Client messages and feedback** | Emails to clients (draft, send, try again, or record that they were told by phone), and compliments, complaints and suggestions that can be answered, sent to the Manager or turned into an issue. |
| **Invoices** | Draft, send by email with a PDF attached, print, record full or part payments, cancel. Numbers (`INV-2026-0001`) are given only when sent. Totals and VAT (only if the company is VAT-registered) are worked out by the system. Overdue invoices are flagged automatically. |
| **Payroll (confidential)** | Secretary and Manager only. Pay details per person, a monthly sheet pre-filled from them (Managers are never included), deductions typed in as amounts, Manager approval, CSV payment file and print page. Account numbers are partly hidden in lists. |
| **Items** | A library of company items with five stock counts (in store, waiting for collection, out with people, damaged, lost) and a permanent stock history. Staff and supervisors ask for items on simple, large-button pages. The Secretary approves, hands over and confirms returns. **"I have returned this item" only changes the status: stock moves only when the Secretary or Manager confirms they physically have it.** Nobody approves their own request or return. The Manager chooses which items need his approval first. Overdue reminders go out once a day. |
| **Send to Manager** | The Secretary passes a client issue, feedback, item, payroll question or any other matter to the Manager, who sees the full record and can reply, send it back or resolve it. |
| **Notifications** | An in-app bell for everyone, with links straight to the record. Clients get email. |
| **Audit log** | Every important change with who, when, and old and new values. The Manager sees the full log; entries can never be edited or deleted. |
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
| Clients: create, edit, assign supervisor, messages, feedback | yes | - | - | yes |
| Client issues | all | assigned only (note, resolve) | - | all |
| Close / reopen / reassign an issue | yes | - | - | yes |
| Invoices and payments | yes | - | - | yes |
| Payroll: prepare and submit | prepare only | - | - | yes |
| Payroll: approve / reject / reopen | yes | - | - | - |
| Item library and stock | yes | - | - | yes |
| Choose items that need Manager approval | yes | - | - | view only |
| Ask for items, "I have returned this item" | - | own | own | - |
| Approve requests, confirm handover and returns | yes (not own) | - | - | yes (not own) |
| Send a matter to the Manager | - | - | - | yes |
| Approve expenses above the limit (if switched on) | yes | - | - | - |
| Company settings, full audit log | yes | - | - | - |

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
manager, two supervisors, four staff, a secretary, reports, expenses, clients,
issues, invoices, items, item requests and a draft payroll, and
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
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | Email account for client emails and invoices. **Without `EMAIL_HOST` nothing is sent:** in development emails are printed in the console; on a live site every send stops with "Email is not set up" so nothing is wrongly marked as sent. |
| `DEFAULT_FROM_EMAIL` | Sender shown on client emails, e.g. `Resilience Security <accounts@example.co.ke>`. |
| `DJANGO_MEDIA_ROOT` | Folder for uploaded files (receipts, issue photos, logo). Defaults to `media/`. Back it up with the database. |

## Secretary operations: setup

1. The Manager opens **Company settings** and fills in the company name, phone, address, KRA PIN, logo and payment details (these appear on invoices), VAT registration and, if wanted, the expense approval limit.
2. Add clients and choose each one's supervisor. Link their GPS work sites if they have any.
3. Add items to the **Item library** with the number in the store. The Manager ticks any items that need his approval under **Items needing my approval**.
4. Add **pay details** for each person under Payroll before starting the first month.
5. Schedule `python manage.py run_daily_checks` once a day (Windows Task Scheduler or cron). It marks overdue invoices and sends overdue item reminders. It also runs by itself once a day when the Secretary or Manager opens the dashboard, so this is a backup. It is safe to run more than once.

Uploaded files (PDF, JPG, PNG up to 5 MB) are checked by their contents, stored under random names in `DJANGO_MEDIA_ROOT`, and only downloaded through a page that checks the person may see the record. Do not serve the media folder directly from the web server.

## Deploying

1. Set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and the PostgreSQL variables (SQLite is for development).
2. `pip install -r requirements.txt`, `python manage.py migrate`, `python manage.py collectstatic`.
3. Serve with a WSGI server (e.g. `gunicorn config.wsgi`) behind HTTPS, and serve `staticfiles/` with your web server (or add WhiteNoise).
4. With `DJANGO_DEBUG` off, HTTPS redirect, secure cookies and HSTS turn on automatically. Check with `python manage.py check --deploy`.
5. Back up the database and the media folder regularly.

## Project layout

```
accounts/   users, roles, login, profile, Manager's team screens, access helpers
reports/    reports, replies, workflow rules, dashboards' queries
finance/    expenses, categories, permanent history, CSV export
tracking/   GPS: sites, working hours, location updates, geofence rules, alerts, manager screens
core/       dashboards, company settings, audit log, uploads, email, workflow helpers, daily checks
clients/    clients, supervisor assignment, client issues, messages, feedback
billing/    invoices, payments, numbering, PDF
payroll/    confidential payroll
inventory/  item library, stock ledger, item requests and returns
escalations/ "Send to Manager"
notifications/ in-app notifications and the bell
templates/  HTML      static/css/app.css  styling (matches the website's brand)
```

## Not built yet (listed as "future potential" in the proposal)

Mobile app, SMS, advanced analytics, attendance tracking, tax calculation and
automated financial reports.
