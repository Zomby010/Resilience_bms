"""The shared design-system building blocks (UX batch 1)."""
from django.template import Context, Template
from django.test import RequestFactory
from django.urls import reverse

from accounts.models import ROLE_CHOICES
from core.filters import F, filter_bar
from reports.models import Report, Status

from .testing import CompanyTestCase


class SenderChipTests(CompanyTestCase):
    def render(self, sender):
        return Template("{% sender_chip who %}").render(Context({"who": sender}))

    def test_each_role_gets_its_own_colour_and_word(self):
        self.assertIn("s-guard", self.render(self.staff_a1))
        self.assertIn("GUARD", self.render(self.staff_a1))
        self.assertIn("Staffa1", self.render(self.staff_a1))
        self.assertIn("s-supervisor", self.render(self.sup_a))
        self.assertIn("s-secretary", self.render(self.secretary))
        self.assertIn("s-manager", self.render(self.manager))
        self.assertIn("SYSTEM", self.render(None))


class WordingTests(CompanyTestCase):
    def test_staff_is_called_guard(self):
        self.assertEqual(self.staff_a1.get_role_display(), "Guard")
        self.assertIn(("staff", "Guard"), ROLE_CHOICES)

    def test_report_completed_reads_solved(self):
        report = Report.objects.create(author=self.staff_a1, title="Gate", body="x", status=Status.COMPLETED)
        self.assertEqual(report.get_status_display(), "Solved")

    def test_log_out_button(self):
        html = self.login(self.staff_a1).get(reverse("core:home")).content.decode()
        self.assertIn(">Log out</button>", html)
        self.assertNotIn(">Sign out</button>", html)


class FilterBarTests(CompanyTestCase):
    def test_active_filters_become_removable_chips_and_other_params_are_kept(self):
        request = RequestFactory().get("/x/", {"q": "gate", "status": "pending", "scope": "team", "page": "2"})
        fb = filter_bar(request, [F("q", "Search", main=True), F("status", "Status", "select", [("pending", "Pending")])])
        self.assertEqual([a["label"] for a in fb["active"]], ["Search", "Status"])
        self.assertEqual(fb["active"][1]["value"], "Pending")
        self.assertNotIn("status=", fb["active"][1]["remove"])
        self.assertIn("scope=team", fb["active"][1]["remove"])
        self.assertEqual(fb["keep"], [("scope", "team")])
        html = Template('{% include "partials/filter_bar.html" %}').render(Context({"fb": fb}))
        self.assertIn("Looking for something? Search or filter here", html)
        self.assertIn('<details class="filterbar', html)
        self.assertNotIn("filterbar no-print\" open", html)  # closed by default


class ManagerCountTests(CompanyTestCase):
    def test_waiting_total_counts_more_than_five(self):
        from escalations.models import Escalation

        for i in range(7):
            Escalation.objects.create(kind=Escalation.Kind.OTHER, subject=f"Matter {i}", note="x", raised_by=self.secretary)
        from core.todo import todos_for

        self.assertGreaterEqual(len(todos_for(self.manager)), 7)


class PhoneListAndFilterTests(CompanyTestCase):
    """MOB-01 and FILT-01/02: every list is a phone card list and has one closed filter bar."""

    LISTS = ["reports:list", "attendance:records", "leave:request_list", "leave:sick_list", "billing:list", "finance:list",
             "finance:history", "payroll:list", "inventory:request_list", "inventory:library", "escalations:list",
             "core:audit", "accounts:team", "operations:visits", "operations:equipment", "operations:sites", "operations:ob",
             "clients:list", "clients:feedback_list", "clients:issue_list", "clients:issue_history", "tracking:history",
             "tracking:people"]

    def test_lists_use_cards_and_one_closed_filter_bar(self):
        self.login(self.manager)
        for name in self.LISTS:
            with self.subTest(page=name):
                page = self.client.get(reverse(name)).content.decode()
                self.assertNotIn('class="filters"', page)
                self.assertEqual(page.count('<details class="filterbar no-print"'), 1)
                if "<table" in page:  # empty lists and the library's tiles have no table
                    self.assertIn('<table class="cards', page)

    def test_old_query_strings_still_work_and_show_as_chips(self):
        from reports.models import Report

        Report.objects.create(author=self.sup_a, title="Gate lock", body="x")
        Report.objects.create(author=self.staff_a1, title="Torch", body="x")
        self.login(self.manager)
        page = self.client.get(reverse("reports:list") + "?from_role=supervisor&status=pending").content.decode()
        self.assertIn("Gate lock", page)
        self.assertNotIn(">Torch<", page)
        self.assertIn("From: Supervisors", page)
        self.assertIn("Status: Pending", page)
        r = self.client.get(reverse("finance:list") + "?view=month&export=csv")
        self.assertEqual(r["Content-Type"], "text/csv")

    def test_kept_parameters_ride_along(self):
        self.login(self.manager)
        page = self.client.get(reverse("finance:list") + "?view=month&category=").content.decode()
        self.assertIn('<input type="hidden" name="view" value="month">', page)
