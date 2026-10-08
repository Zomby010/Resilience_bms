# RESILIENCE Business Management System

A Django web platform that replaces paper-based management with one secure site
for Management, Supervisors, Staff and the Secretary. Built from the
*RESILIENCE - Business Management System* proposal.

## What it does

| Area | Details |
| --- | --- |
| **Roles** | Manager, Supervisor, Staff, Secretary. One account per person; role decides what they see. |
| **Reporting workflow** | Staff submit a report -> their supervisor reviews and gives feedback, and can resolve it -> the Manager sees everything and can resolve any report. Supervisors and the Secretary send reports straight to the Manager. Every step is time-stamped and tied to a user. |
| **Dashboards** | Manager: a full-width IN ATTENDANCE TODAY strip (per site: who is in, who is absent, who is on leave or sick, short-staffed sites), operations numbers (on duty, absent, on leave, sick, short-staffed sites, open high/critical incidents), reports not yet checked, reports resolved by supervisors and by the Manager, money spent today / this week / this month, Reports Received (from the Secretary, supervisors and guards, with a Resolve button and a day/week/month filter), supervisor performance, activity feed, feedback history. Supervisor: reports to review and team overview. Staff: report status and latest feedback. Secretary: spending overview. |
| **Expenditure tracker** | Secretary has full access: record, edit, delete, categorise, search, filter by date/category, CSV export. Manager has view-only access. Every create/edit/delete is kept in a permanent history. |
| **GPS tracking** | Staff and supervisors turn on location from their dashboard. The server compares each reading with their work site: ON LOCATION (inside the site radius), NEAR LOCATION (up to 50 m), OFF LOCATION (beyond 50 m), or GPS WEAK when the phone's accuracy is worse than ±50 m. The Manager's GPS Tracker shows counts, a live map, a list and alerts, refreshing every 15 seconds; work sites, working hours (including overnight shifts) and location history are managed there. Only the Manager sees locations. |
| **Clients** | The office keeps every client with contact details, contract, monthly charge, office notes, a responsible supervisor (with history) and linked GPS work sites. Clients have no login. |
| **Client issues** | The office records a problem a client reports. It goes straight to that client's supervisor (or shows SUPERVISOR NEEDED). The supervisor adds notes and marks it resolved; only the office closes or reopens it. |
| **Client messages and feedback** | Emails to clients (draft, send, try again, or record that they were told by phone), and compliments, complaints and suggestions that can be answered, sent to the Manager or turned into an issue. |
| **Invoices** | Draft, send by email with a PDF attached, print, record full or part payments, cancel. Numbers (`INV-2026-0001`) are given only when sent. Totals and VAT (only if the company is VAT-registered) are worked out by the system. Overdue invoices are flagged automatically. |
| **Payroll (confidential)** | Secretary and Manager only. Pay details per person, a monthly sheet pre-filled from them (Managers are never included), deductions typed in as amounts, Manager approval, CSV payment file and print page. Account numbers are partly hidden in lists. |
| **Items** | A library of company items with five stock counts (in store, waiting for collection, out with people, damaged, lost) and a permanent stock history. Staff and supervisors ask for items on simple, large-button pages. The Secretary approves, hands over and confirms returns. **"I have returned this item" only changes the status: stock moves only when the Secretary or Manager confirms they physically have it.** Nobody approves their own request or return. The Manager chooses which items need his approval first. Overdue reminders go out once a day. |
| **Send to Manager** | The Secretary passes a client issue, feedback, item, payroll question or any other matter to the Manager, who sees the full record and can reply, send it back or resolve it. |
| **Attendance** | Each guard and supervisor signs in at their site from their phone. The server checks the distance from the site (off location and weak GPS are refused) and stamps the time. Late = more than the company's grace minutes after the shift starts. Staff sign-ins go to their supervisor to approve; approved sign-ins go to the Manager, who completes the day. Completing the day records everyone else as absent, on leave or sick. Supervisors can mark someone who could not sign in. Everyone sees their own attendance; supervisors see their team's; filterable records with CSV for the office. |
| **Leave** | Annual, sick, maternity, paternity, pre-adoptive, compassionate and unpaid leave. Staff leave goes to their supervisor; supervisors' and the Secretary's to the Manager. Supervisors (for their team) and the office can record leave for someone. Balances in plain words ("You have 12 days of annual leave left"). The Manager sets each person's days per year; each person only sees their own. |
| **Sick leave and sick sheets** | Sickness counts at once, no approval needed. The sick sheet (photo or PDF) is stored in a separate private folder, photos are re-saved to strip hidden location data, and only the person, the Secretary and the Manager can open it. Every opening is written in the audit log. Supervisors see dates only. Reminders go out when no sheet arrives, and files are deleted after the keep period set in Company settings. |
| **Sites** | The Manager and Secretary edit each site's address, supervisor, guards needed, instructions and emergency contacts. Supervisors and staff see them read-only. Posting history (who was at which site, when) is kept automatically. |
| **My team today** | Each guard's status in words (on duty, late, off location, on leave, sick, not signed in) with the items they hold. No map and no coordinates. |
| **Occurrence Book (OB)** | A digital OB per site, saved in the database. One-tap entries ("Patrol done. All in order."), entries are never changed or deleted (a mistake is corrected by a new entry), filters, print and CSV. The Manager sees every site's OB. |
| **Site visits** | Supervisors record a visit: site, time, checks done, guards seen, remarks, optional photo and a "welfare check done" tick. Each visit is also written in the OB. |
| **Incident reports** | Numbered `INC-0001`: site, date and time, type, severity, what happened, who was involved, action taken, photos, police OB number and whether the client was told. High and critical incidents alert the Managers. Supervisor and Manager review, close and reopen, with a note trail. Each incident is written in the site's OB. |
| **Equipment per guard** | Returnable items still out with each person. Turning an account off tells the Secretary which items to collect. |
| **Payslips** | Everyone sees their own payslips from approved payroll months, with a print page and PDF. The office can print all payslips for a month. |
| **Notifications** | An in-app bell for everyone, with links straight to the record. Clients get email. |
| **Audit log** | Every important change with who, when, and old and new values. The Manager sees the full log; entries can never be edited or deleted. |
| **Account management** | The Manager adds/edits team members, assigns staff to supervisors, resets passwords, disables accounts. Everyone can update their own details and change their password. |

### Access matrix (enforced in code and covered by tests)

| Permission | Manager | Supervisor | Staff | Secretary |
| --- | :-: | :-: | :-: | :-: |
| View own reports | yes | yes | yes | - |
| View team / staff reports | all | own team only | - | - |
| Submit reports | - | yes (to management) | yes | yes (to the Manager) |
| Reply to and resolve reports | yes (any) | own team only | - | - |
| Sign in for attendance | - | yes | yes | - |
| Approve sign-ins | yes | own team | - | - |
| Complete the attendance day | yes | - | - | view |
| Ask for leave / report sick | yes | yes (and for own team) | yes | yes (and for anyone) |
| Approve leave | yes (any) | own team | - | - |
| Set leave days per person | yes | - | - | view |
| Open sick sheets | yes | - (dates only) | own | yes |
| Edit site details | yes | view | view own site | yes |
| Occurrence Book | all sites | own and team sites | own site | all sites |
| Record site visits | yes | own sites | - | view |
| Incident reports | all | own, team and own sites | own | all |
| Own payslips | yes | yes | yes | yes |
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
5. Fill in each site's details under **Sites**, and set the late grace minutes and sick sheet rules in **Company settings**. The Manager can change anyone's leave days under **Leave days per person**.
6. Schedule `python manage.py run_daily_checks` once a day (Windows Task Scheduler or cron). It marks overdue invoices, sends overdue item reminders and missing sick sheet reminders, and deletes sick sheet files past the keep period. It also runs by itself once a day when the Secretary or Manager opens the dashboard, so this is a backup. It is safe to run more than once.

Uploaded files (PDF, JPG, PNG up to 5 MB) are checked by their contents, stored under random names in `DJANGO_MEDIA_ROOT`, and only downloaded through a page that checks the person may see the record. Do not serve the media folder directly from the web server. Sick sheets live in `medical/` inside it and follow the same rule.

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
attendance/ sign-in at the site, supervisor approval, completing the day, today's board
leave/      leave types, allowances, leave requests, sick leave and private sick sheets
operations/ site details, my team today, Occurrence Book, site visits, equipment per guard
incidents/  incident reports (INC-0001), photos, review trail
escalations/ "Send to Manager"
notifications/ in-app notifications and the bell
templates/  HTML      static/css/app.css  styling (matches the website's brand)
```

## Not built yet (listed as "future potential" in the proposal)

Mobile app, SMS, advanced analytics, tax calculation and automated financial reports.
Sick sheets are protected by access checks and logging, not encrypted at rest (that would need a new package).
