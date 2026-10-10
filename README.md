# RESILIENCE Business Management System

A Django web platform that replaces paper-based management with one secure site
for Management, Supervisors, Staff and the Secretary. Built from the
*RESILIENCE - Business Management System* proposal.

## What it does

| Area | Details |
| --- | --- |
| **Roles** | Manager, Supervisor, Guard, Secretary. One account per person; role decides what they see. |
| **Menus** | One short menu per role (Guard 5 items, Supervisor 7, Secretary 6, Manager 7). Each item opens a page with tabs for its sub-pages; only the current group is open. On phones a bottom bar shows the four main items and "More", which opens the full menu as a sheet over the page. My details, payslips, password and Log out sit under the person's name. A page that is not in a role's menu is also blocked for that role. |
| **Reporting workflow** | Staff submit a report -> their supervisor reviews and gives feedback, and can resolve it -> the Manager sees everything and can resolve any report. Supervisors send reports straight to the Manager. The Secretary writes to the Manager through "Send to Manager" (their old reports stay readable). Every step is time-stamped and tied to a user. |
| **Home pages: "N things need you"** | Every role's home page starts with one action list, grouped by who it comes from (the Manager, the Secretary, supervisors, guards, clients, the system). Each row has a coloured sender chip, one verb (Approve this, Say no, Reply to this, Solve this, Complete this, Check this, Read this, Hand out) and a line on what happens next. Approving an item, an expense or a sign-in and solving a report work in one tap from the row (with a confirmation); the rest open the record. Manager: to-dos (serious incidents, matters from the Secretary, payroll, items and expenses needing approval, leave to decide (Give the days), supervisors' reports, completing the day), then a short Today's picture with a link to the full board. Supervisor: sign-ins to approve, guards' reports, incidents to review and client issues, then their own sign-in card and team today. Guard: sign-in status, location, OB buttons, Report a problem / Report in sick / Ask for leave, then unread replies and items ready to collect. Secretary: item requests, returns, sick sheets, client issues and feedback, failed emails, overdue invoices and low stock; money and latest expenses are folded away. Supervisor performance is on Company ▸ Team. |
| **Expenditure tracker** | Secretary has full access: record, edit, delete, categorise, search, filter by date/category, CSV export. Manager has view-only access. One Expenses page with three views: the list, totals by month, and who changed what (every create/edit/delete, kept permanently). The list and the change history are folded by month ("October 2026 · 2 expenses · KES 23,164 recorded"); only the current month is open. |
| **GPS tracking** | Staff and supervisors turn on location from their dashboard. The server compares each reading with their work site: ON LOCATION (inside the site radius), NEAR LOCATION (up to 50 m), OFF LOCATION (beyond 50 m), or GPS WEAK when the phone's accuracy is worse than ±50 m. The Manager's GPS Tracker shows counts, a live map, a list and alerts, refreshing every 15 seconds; each site's location and working hours are the "Location & hours" tab of its site page, and location history is under Company. Only the Manager sees locations. |
| **Clients** | The office keeps every client with contact details, contract, monthly charge, office notes, a responsible supervisor (with history) and linked GPS work sites. Clients have no login. |
| **Client issues** | The office records a problem a client reports. It goes straight to that client's supervisor (or shows SUPERVISOR NEEDED). The supervisor adds notes and marks it resolved; only the office closes or reopens it. |
| **Client messages and feedback** | Emails to clients (draft, send, try again, or record that they were told by phone), and compliments, complaints and suggestions that can be answered, sent to the Manager or turned into an issue. |
| **Invoices** | Draft, send by email with a PDF attached, print, record full or part payments, cancel. Numbers (`INV-2026-0001`) are given only when sent. Totals and VAT (only if the company is VAT-registered) are worked out by the system. Overdue invoices are flagged automatically. |
| **Payroll (confidential)** | Secretary and Manager only. Pay details per person, a monthly sheet pre-filled from them (Managers are never included), deductions typed in as amounts, Manager approval, CSV payment file and print page. Account numbers are partly hidden in lists. |
| **Items** | A library of company items with five stock counts (in store, waiting for collection, out with people, damaged, lost) and a permanent stock history. Staff and supervisors ask for items on simple, large-button pages. The Secretary approves, hands over and confirms returns. **"I have returned this item" only changes the status: stock moves only when the Secretary or Manager confirms they physically have it.** Nobody approves their own request or return. The Manager chooses which items need the Manager's OK first (Items ▸ Which items need my OK, Manager only). Overdue reminders go out once a day. |
| **Send to Manager** | The Secretary passes a client issue, feedback, item, payroll question or any other matter to the Manager, who sees the full record and can reply, send it back or resolve it. |
| **Attendance** | Each guard and supervisor signs in at their site from their phone. The server checks the distance from the site (off location and weak GPS are refused) and stamps the time. Late = more than the company's grace minutes after the shift starts. Staff sign-ins go to their supervisor to approve; approved sign-ins go to the Manager, who completes the day. Completing the day records everyone else as absent, on leave or sick. Supervisors can mark someone who could not sign in. When the phone's location fails or is refused, **Sign in without location** stamps the server time with a reason (No signal, Phone problem, GPS shows wrong place, Other): a guard's goes to their supervisor as "Approve this sign-in (no location)", a supervisor's goes to the Manager, and the 3rd in a month becomes a Manager to-do ("Check this"). **Sign out** works the same way (with location when possible, otherwise with a reason) and is recorded, never approved; completing the day does not need it. Every attendance page shows "In 06:50 · Out 18:05 · 11 h 15 m", "Not signed out yet" or "No sign-out" (never filled in). Today starts with one status card: "✔ Signed in 06:50 · ⚠ Location is off: turn it on", with the sign-out and location buttons inside it. Everyone sees their own attendance; supervisors see their team's on **My team ▸ Today | History**; the Manager uses **Today's picture ▸ Day sheet | Records | Live map**. Filterable records (including "How": signed in without location) with CSV for the office. |
| **Leave** | Four types: Annual, Maternity, Paternity and Compassionate, picked with four big buttons. The person picks the first and last day off; no numbers and no balances are shown, and nothing blocks a request. The Manager decides every request and types the **days given** (pre-filled with the working days counted, freely editable, with a quiet note below the legal minimum: annual 21, maternity 90, paternity 14). The person is told "Approved: 3 days, 9–12 Oct". The days given, counted from the first day off, decide when the person shows "On leave until 12 Oct" on Who is on duty, the day sheet and attendance. A guard's supervisor is told when leave is asked for and decided, to plan cover, but does not decide. Supervisors (for their team) and the office can record leave for someone. Old types (sick, pre-adoptive, unpaid) are switched off, not deleted, and old leave days per person stay readable for the Manager behind "▸". |
| **Sick leave and sick sheets** | "Report in sick" is its own entry (a Today button and a menu tab), separate from leave; a person's sick reports are listed on My requests. Sickness counts at once, no approval needed. The sick sheet (photo or PDF) is stored in a separate private folder, photos are re-saved to strip hidden location data, and only the person, the Secretary and the Manager can open it. Every opening is written in the audit log. Supervisors see dates only. Reminders go out when no sheet arrives, and files are deleted after the keep period set in Company settings. |
| **Sites** | One page per site with tabs: Details, Location & hours (Manager), People, OB and History (incidents and supervisor visits). The Manager edits a site's address, supervisor, guards needed, instructions and emergency contacts; the Secretary, supervisors and guards read them. Posting history (who was at which site, when) is kept automatically, folded under "Who was posted here before ▸". The Sites list has one row per site: name with its colour, supervisor, hours in one line ("Mon–Sat 07:00–18:00, Sun off"), guards posted and Open. Each site gets one of 8 colours that colour-blind people can tell apart (picked automatically, always shown with the name); the Manager can change it on the Location & hours tab. |
| **My team ▸ Today** | One page per supervisor: each guard's status in words (on duty, late, off location, on leave, sick, not signed in), shift, in and out times and the items they hold, with the buttons to approve or mark. No map and no coordinates. The Manager sees the same on the day sheet, with a "▸ Guards by site or supervisor" view. |
| **Occurrence Book (OB)** | A digital OB per site, saved in the database. One-tap entries ("Patrol done. All in order."), entries are never changed or deleted (a mistake is corrected by a new entry), filters, print and CSV. Each entry is a card under a day heading (Today, Yesterday, then the date) with the site's colour stripe and name chip, the time, an icon per kind (🟢 shift start and handover, 🔁 patrol, 🚗 visitor, 📦 delivery, 🔔 alarm, 🚨 incident with Open incident, 🧭 supervisor visit) and who wrote it. A correction sits indented under the entry it corrects. "Correct this entry" is behind "⋯": guards see it only on their own entries from the last 24 hours (others are refused), supervisors on every entry they can see. Guards and supervisors write it; the Manager reads every site's OB. The Secretary has no OB. |
| **Site visits** | Supervisors record a visit: site, time, checks done, guards seen, remarks, optional photo and a "welfare check done" tick. Each visit is also written in the OB. |
| **Incident reports** | Numbered `INC-0001`: site, date and time, type, severity, what happened, who was involved, action taken, photos, police OB number and whether the client was told. The form starts with the person's site and the time now filled in; who was involved, action taken, police, client and photos sit under "Add more details ▸" (the same on the supervisor visit form for remarks and photo). Guards and supervisors report them. High and critical incidents alert the Manager and wait on the Manager's home page; there is no Incidents page for the Manager (each site's History tab lists its incidents, with CSV) or the Secretary (who is not told about incidents). Supervisor and Manager review, the Manager closes and reopens, with a note trail. Each incident is written in the site's OB. |
| **Equipment per guard** | Returnable items still out with each person. Turning an account off tells the Secretary which items to collect. |
| **Payslips** | Everyone sees their own payslips from approved payroll months, with a print page and PDF. The office can print all payslips for a month. |
| **Lists and filters** | Every list page has one filter bar, closed by default ("Looking for something? Search or filter here"), with the main filters first and the rest under "More filters". Active filters show as chips with an ✕ to remove each one; CSV and Clear sit below the bar. Old links with filters in them still work. On phones every table turns into a stack of cards (one per row, the name or number as the card title, the status as a badge), so no page scrolls sideways at 390 px. |
| **Notifications** | The bell keeps news only ("Your leave was approved"). Anything that needs doing is on the to-do list instead, so nothing shows up twice; "Show everything" on the notifications page still lists all of them. Settings changes send no notice. Clients get email. |
| **Audit log** | Every important change with who, when, and old and new values. The Manager sees the full log, folded by month with only the current month open; entries can never be edited or deleted. |
| **Account management** | The Manager adds/edits team members, assigns staff to supervisors, resets passwords, disables accounts. Everyone can update their own details and change their password. |

### Access matrix (enforced in code and covered by tests)

| Permission | Manager | Supervisor | Guard | Secretary |
| --- | :-: | :-: | :-: | :-: |
| View own reports | yes | yes | yes | old ones only |
| View team / staff reports | all | own team only | - | - |
| Submit reports | - | yes (to management) | yes | - (uses Send to Manager) |
| Reply to and resolve reports | yes (any) | own team only | - | - |
| Sign in and sign out (with or without location) | - | yes | yes | - |
| Approve sign-ins | yes (and supervisors' sign-ins without location) | own team | - | - |
| Complete the attendance day | yes | - | - | - |
| Attendance records | all | own team | - (My attendance) | all |
| Ask for leave / report in sick | yes | yes (and for own team) | yes | yes (and for anyone) |
| Decide leave and type the days given | yes (all) | - (told about own team's) | - | - |
| List of leave requests | all | own team | - (My requests) | all |
| List of sick reports | all | own team (dates only) | - (My requests) | all |
| Set leave days per person (no longer used) | yes | - | - | - |
| Open sick sheets | yes | - (dates only) | own | yes |
| Edit site details | yes | view | view own site | view |
| Occurrence Book | read all sites | own and team sites | own site | - |
| Who is on duty (My team ▸ Today, the day sheet) | yes | own team | - | - |
| Record site visits | yes | own sites | - | - |
| Report an incident, incidents list | - | yes (own, team and own sites) | yes (own) | - |
| Open one incident, review, close | yes (from the to-do list or a site's History tab) | review | own | - |
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
| Which items need the Manager's OK | yes | - | - | - |
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
3. Add items to the **Item library** with the number in the store. The Manager ticks any items that need the Manager's OK under **Items ▸ Which items need my OK**.
4. Add **pay details** for each person under Payroll before starting the first month.
5. Fill in each site's details under **Sites**, and set the late grace minutes and sick sheet rules in **Company settings**. The Manager decides leave and types the days given on each request.
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
