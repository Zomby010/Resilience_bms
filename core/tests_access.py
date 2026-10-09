"""Every row of the role × page matrix (UX audit report, section 3).

For each page and role: the status code (200 allowed, 403 blocked) and whether the menu shows it.
A page a role cannot open is never in that role's menu, and a menu link always opens.
"""
from django.urls import reverse

from core.menu import MENUS, hrefs
from core.testing import CompanyTestCase

ROLES = ("manager", "secretary", "supervisor", "staff")


def row(name, codes, menu=""):
    """codes: four status codes in ROLES order. menu: the roles (first letters m/s/v/g) whose menu shows it."""
    return name, dict(zip(ROLES, codes)), {r for r, k in zip(ROLES, "msvg") if k in menu}


MATRIX = [
    # page                         manager secretary supervisor guard   in the menu of
    row("core:home",               (200, 200, 200, 200), "msvg"),
    row("notifications:inbox",     (200, 200, 200, 200)),            # the bell, not a menu item
    # Reports: the Secretary keeps their old reports (Manager ▸ Old reports) but sends new things through Escalations.
    row("reports:list",            (200, 200, 200, 200), "msvg"),
    row("reports:create",          (403, 403, 200, 200), "vg"),
    # Incidents happen at sites: no Incidents page for the Manager or the Secretary (Frank's rule).
    row("incidents:create",        (403, 403, 200, 200), "vg"),
    row("incidents:list",          (403, 403, 200, 200), "vg"),
    row("attendance:mine",         (403, 403, 200, 200), "vg"),
    row("attendance:team",         (403, 403, 200, 403), "v"),
    row("attendance:day",          (200, 403, 403, 403), "m"),
    row("attendance:records",      (200, 200, 200, 403), "msv"),
    row("leave:mine",              (200, 200, 200, 200), "msvg"),
    row("leave:request_list",      (200, 200, 200, 403), "msv"),
    row("leave:ask",               (200, 200, 200, 200), "vg"),     # the office asks from "My requests"
    # A guard's sick reports are on "My requests"; the list of everyone's is for the office and supervisors.
    row("leave:sick_list",         (200, 200, 200, 403), "msv"),
    row("leave:sick_report",       (200, 200, 200, 200), "vg"),
    row("leave:allowances",        (200, 403, 403, 403)),            # kept for the Manager behind "▸", not in a menu
    row("operations:sites",        (200, 200, 200, 200), "msvg"),
    row("tracking:people",         (200, 403, 403, 403), "m"),
    row("tracking:tracker",        (200, 403, 403, 403), "m"),
    row("tracking:history",        (200, 403, 403, 403), "m"),
    row("operations:team_today",   (200, 403, 200, 403), "mv"),
    row("operations:ob",           (200, 403, 200, 200), "mvg"),
    row("operations:ob_write",     (403, 403, 200, 200)),            # a button on the OB page
    row("operations:visits",       (200, 403, 200, 403), "mv"),
    row("operations:equipment",    (200, 200, 200, 403), "msv"),
    row("tracking:mine",           (403, 403, 200, 200)),            # a banner on Today, not a menu item
    row("clients:list",            (200, 200, 403, 403), "ms"),
    row("clients:issue_list",      (200, 200, 200, 403), "msv"),
    row("clients:feedback_list",   (200, 200, 403, 403), "ms"),
    row("billing:list",            (200, 200, 403, 403), "ms"),
    row("finance:list",            (200, 200, 403, 403), "ms"),
    row("finance:history",         (200, 200, 403, 403)),            # a view inside Expenses
    row("finance:approvals",       (200, 403, 403, 403), "m"),
    row("finance:categories",      (403, 200, 403, 403), "s"),
    row("payroll:list",            (200, 200, 403, 403), "ms"),
    row("inventory:library",       (200, 200, 403, 403), "ms"),
    row("inventory:request_list",  (200, 200, 403, 403), "ms"),
    row("inventory:overdue",       (200, 200, 403, 403), "ms"),
    row("inventory:flags",         (200, 403, 403, 403), "m"),
    row("inventory:browse",        (403, 403, 200, 200), "vg"),
    row("inventory:mine",          (403, 403, 200, 200), "vg"),
    row("escalations:list",        (200, 200, 403, 403), "ms"),
    row("escalations:create",      (403, 200, 403, 403), "s"),
    row("accounts:team",           (200, 403, 403, 403), "m"),
    row("core:company_settings",   (200, 403, 403, 403), "m"),
    row("core:audit",              (200, 403, 403, 403), "m"),
    # Account pages live under the person's name, not in the menu.
    row("accounts:profile",        (200, 200, 200, 200)),
    row("payslips:mine",           (200, 200, 200, 200)),
    row("accounts:password_change", (200, 200, 200, 200)),
]


class RolePageMatrixTests(CompanyTestCase):
    def people(self):
        return {"manager": self.manager, "secretary": self.secretary, "supervisor": self.sup_a, "staff": self.staff_a1}

    def test_every_row_status_code(self):
        for role, user in self.people().items():
            self.login(user)
            for name, codes, _ in MATRIX:
                with self.subTest(page=name, role=role):
                    self.assertEqual(self.client.get(reverse(name)).status_code, codes[role])

    def test_tracking_sites_is_merged_into_sites(self):
        self.login(self.manager)
        self.assertRedirects(self.client.get(reverse("tracking:sites")), reverse("operations:sites"))
        for user in (self.secretary, self.sup_a, self.staff_a1):
            self.login(user)
            self.assertEqual(self.client.get(reverse("tracking:sites")).status_code, 403)

    def test_every_row_menu_presence(self):
        for role, user in self.people().items():
            menu = hrefs(user)
            self.login(user)
            page = self.client.get(reverse("core:home")).content.decode()
            nav = page[page.index('<nav class="nav"'):page.index("</nav>", page.index('<nav class="nav"'))]
            for name, _, shown in MATRIX:
                url = reverse(name)
                with self.subTest(page=name, role=role):
                    self.assertEqual(url in menu, role in shown)
                    self.assertEqual(f'href="{url}"' in nav, role in shown)

    def test_every_menu_link_opens(self):
        for role, user in self.people().items():
            self.login(user)
            for url in hrefs(user):
                with self.subTest(url=url, role=role):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_menus_are_short(self):
        for role, items in MENUS.items():
            with self.subTest(role=role):
                self.assertLessEqual(len(items), 7)

    def test_account_links_sit_under_the_name(self):
        self.login(self.staff_a1)
        page = self.client.get(reverse("core:home")).content.decode()
        box = page[page.index('<details class="userbox">'):]
        for name in ("accounts:profile", "payslips:mine", "accounts:password_change", "accounts:logout"):
            self.assertIn(reverse(name), box)

    def test_page_tabs_show_the_group(self):
        self.login(self.manager)
        page = self.client.get(reverse("finance:list")).content.decode()
        tabs = page[page.index('<nav class="page-tabs'):]
        tabs = tabs[:tabs.index("</nav>")]
        for name in ("clients:list", "billing:list", "payroll:list", "finance:approvals"):
            self.assertIn(reverse(name), tabs)
        self.assertIn(f'href="{reverse("finance:list")}" class="on"', tabs)

    def test_phone_bar_has_four_items_and_more(self):
        for user in self.people().values():
            self.login(user)
            page = self.client.get(reverse("core:home")).content.decode()
            bar = page[page.index('<nav class="tabbar'):]
            bar = bar[:bar.index("</nav>")]
            self.assertEqual(bar.count("<a "), 4)
            self.assertIn("More", bar)
