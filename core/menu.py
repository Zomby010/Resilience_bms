"""The main menu for each role: at most seven items, each opening a page with tabs for its sub-pages.

One definition drives the sidebar (desktop), the bottom bar and "More" sheet (phones) and the tab strip
at the top of each page, so they can never disagree. A page that is not in a role's menu is also blocked
for that role by the view itself; `core/tests_access.py` checks both together.
"""
from django.urls import reverse

# (label, url name, extra path prefixes that also belong to this tab). A tab whose label is None only
# claims pages for its group (so the group opens) without showing a tab of its own.
T = tuple

MENUS = {
    "staff": [
        ("🏠", "Today", [
            T(("Today", "core:home", ())),
            T(("My attendance", "attendance:mine", ())),
            T((None, "tracking:mine", ("/notifications/", "/accounts/", "/payslips/"))),
        ]),
        ("📒", "Occurrence Book", [
            T(("Occurrence Book", "operations:ob", ())),
            T(("My site", "operations:sites", ())),
        ]),
        ("⚠️", "Report a problem", [
            T(("Report an incident", "incidents:create", ())),
            T(("Tell my supervisor", "reports:create", ())),
            T(("What I reported", "reports:list", ())),
            T(("My incidents", "incidents:list", ())),
        ]),
        ("🗓️", "Leave & sick", [
            T(("My leave", "leave:mine", ("/leave/requests/",))),
            T(("Report in sick", "leave:sick_report", ())),
            T(("My sick reports", "leave:sick_list", ())),
        ]),
        ("🎒", "Items", [
            T(("Ask for an item", "inventory:browse", ())),
            T(("My items", "inventory:mine", ())),
        ]),
    ],
    "supervisor": [
        ("🏠", "Today", [
            T(("Today", "core:home", ())),
            T(("My attendance", "attendance:mine", ())),
            T((None, "tracking:mine", ("/notifications/", "/accounts/", "/payslips/"))),
        ]),
        ("👥", "My team", [
            T(("Who is on duty", "operations:team_today", ())),
            T(("Sign-ins", "attendance:team", ())),
            T(("Attendance records", "attendance:records", ())),
            T(("Sick", "leave:sick_list", ())),
            T(("Leave", "leave:request_list", ())),
            T(("Equipment", "operations:equipment", ())),
        ]),
        ("📍", "My sites", [
            T(("Sites", "operations:sites", ())),
            T(("Occurrence Book", "operations:ob", ())),
            T(("Site visits", "operations:visits", ())),
        ]),
        ("📨", "Inbox", [
            T(("From my guards", "reports:list", ())),
            T(("Incidents", "incidents:list", ())),
            T(("Client issues", "clients:issue_list", ())),
        ]),
        ("⚠️", "Report a problem", [
            T(("Report an incident", "incidents:create", ())),
            T(("Send a report", "reports:create", ())),
        ]),
        ("🗓️", "My leave", [
            T(("My leave", "leave:mine", ())),
            T(("Report in sick", "leave:sick_report", ())),
        ]),
        ("🎒", "Items", [
            T(("Ask for an item", "inventory:browse", ())),
            T(("My items", "inventory:mine", ())),
        ]),
    ],
    "secretary": [
        ("🏠", "To do", [
            T(("To do", "core:home", ())),
            T((None, "notifications:inbox", ("/accounts/", "/payslips/"))),
        ]),
        ("👤", "Clients", [
            T(("Clients", "clients:list", ())),
            T(("Client issues", "clients:issue_list", ())),
            T(("Feedback", "clients:feedback_list", ())),
            T(("Sites", "operations:sites", ())),
        ]),
        ("💰", "Money", [
            T(("Invoices", "billing:list", ())),
            T(("Expenses", "finance:list", ())),
            T(("Expense categories", "finance:categories", ())),
            T(("Payroll", "payroll:list", ())),
        ]),
        ("🎒", "Items", [
            T(("Requests", "inventory:request_list", ())),
            T(("Stock", "inventory:library", ())),
            T(("Overdue", "inventory:overdue", ())),
            T(("Equipment per guard", "operations:equipment", ())),
        ]),
        ("👥", "People", [
            T(("Attendance records", "attendance:records", ())),
            T(("Leave requests", "leave:request_list", ())),
            T(("Sick", "leave:sick_list", ())),
            T(("My leave", "leave:mine", ())),
        ]),
        ("✉️", "Manager", [
            T(("Send to Manager", "escalations:create", ())),
            T(("Sent and answered", "escalations:list", ())),
            T(("Old reports", "reports:list", ())),
        ]),
    ],
    "manager": [
        ("🏠", "To do", [
            T(("To do", "core:home", ())),
            T(("Sent to me", "escalations:list", ())),
            T(("Reports", "reports:list", ())),
            T((None, "notifications:inbox", ("/accounts/profile/", "/accounts/password", "/payslips/", "/incidents/"))),
        ]),
        ("📊", "Today's picture", [
            T(("Day sheet", "attendance:day", ())),
            T(("Who is on duty", "operations:team_today", ())),
            T(("Live map", "tracking:tracker", ())),
            T(("Attendance records", "attendance:records", ())),
        ]),
        ("🗓️", "Leave & sick", [
            T(("Requests to decide", "leave:request_list", ())),
            T(("Sick", "leave:sick_list", ())),
            T(("My leave", "leave:mine", ())),
        ]),
        ("📍", "Sites", [
            T(("Sites", "operations:sites", ("/location/sites/",))),
            T(("Assign people", "tracking:people", ())),
            T(("Visits", "operations:visits", ())),
            T(("Occurrence Book", "operations:ob", ())),
            T(("Equipment", "operations:equipment", ())),
        ]),
        ("👤", "Clients & money", [
            T(("Clients", "clients:list", ())),
            T(("Client issues", "clients:issue_list", ())),
            T(("Feedback", "clients:feedback_list", ())),
            T(("Invoices", "billing:list", ())),
            T(("Expenses", "finance:list", ())),
            T(("Expense approvals", "finance:approvals", ())),
            T(("Payroll", "payroll:list", ())),
        ]),
        ("🎒", "Items", [
            T(("Requests", "inventory:request_list", ())),
            T(("Stock", "inventory:library", ())),
            T(("Overdue", "inventory:overdue", ())),
            T(("Which items need my OK", "inventory:flags", ())),
        ]),
        ("⚙️", "Company", [
            T(("Team & accounts", "accounts:team", ())),
            T(("Settings", "core:company_settings", ())),
            T(("Audit log", "core:audit", ())),
            T(("Location history", "tracking:history", ())),
        ]),
    ],
}

# How many items the phone bottom bar shows before "More".
BAR_ITEMS = 4


def _build(role):
    groups = []
    for icon, label, tabs in MENUS.get(role, []):
        built = []
        for tab_label, name, extra in tabs:
            href = reverse(name)
            built.append({"label": tab_label, "href": href, "prefixes": (href, *extra), "name": name})
        groups.append({"icon": icon, "label": label, "tabs": built,
                       "visible": [t for t in built if t["label"]], "href": built[0]["href"]})
    return groups


def _owner(groups, path):
    """The tab that owns a path: the longest matching prefix wins. The home page only matches itself."""
    best, best_len = None, -1
    for g in groups:
        for t in g["tabs"]:
            for prefix in t["prefixes"]:
                hit = path == prefix if prefix == "/" else path.startswith(prefix)
                if hit and len(prefix) > best_len:
                    best, best_len = (g, t), len(prefix)
    return best


def menu_for(user, path):
    if not user.is_authenticated:
        return None
    groups = _build(user.role)
    owner = _owner(groups, path)
    for g in groups:
        g["current"] = owner is not None and owner[0] is g
        for t in g["tabs"]:
            t["current"] = owner is not None and owner[1] is t
    current = owner[0] if owner else None
    # No tab strip on a page that only belongs to a group through a hidden entry (notifications, account pages).
    tabs = current["visible"] if current and owner[1]["label"] and len(current["visible"]) > 1 else []
    return {"groups": groups, "bar": groups[:BAR_ITEMS], "more": groups[BAR_ITEMS:], "tabs": tabs}


def hrefs(user):
    """Every link a role's menu shows (used by the access test)."""
    return {t["href"] for g in _build(user.role) for t in g["visible"]}


def main_menu(request):
    """Context processor."""
    user = getattr(request, "user", None)
    if user is None:
        return {}
    return {"menu": menu_for(user, request.path)}
