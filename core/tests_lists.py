"""Date-range, search and CSV download on the office lists, and the notification date filter."""
from datetime import timedelta

from django.urls import reverse

from finance.models import Expense, ExpenseCategory, ExpenseLog
from notifications.models import Notification

from .testing import OpsTestCase


class ListFilterTests(OpsTestCase):
    def rows(self, name, params, key, user=None):
        self.login(user or self.secretary)
        resp = self.client.get(reverse(name), params)
        self.assertEqual(resp.status_code, 200)
        return list(resp.context[key])

    def assert_csv(self, name, text, params=None):
        self.login(self.secretary)
        resp = self.client.get(reverse(name), {**(params or {}), "export": "csv"})
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn(text, resp.content.decode())
        for user in (self.staff_a1, self.sup_a):
            self.login(user)
            self.assertEqual(self.client.get(reverse(name), {"export": "csv"}).status_code, 403)

    def test_escalations(self):
        yesterday = str(self.today - timedelta(days=1))
        self.assertEqual(self.rows("escalations:list", {"q": "advice"}, "escalations"), [self.escalation])
        self.assertEqual(self.rows("escalations:list", {"q": "nothing like it"}, "escalations"), [])
        self.assertEqual(self.rows("escalations:list", {"to": yesterday}, "escalations"), [])
        self.assertEqual(self.rows("escalations:list", {"kind": "other", "from": str(self.today)}, "escalations"), [self.escalation])
        self.assert_csv("escalations:list", "Need advice")

    def test_item_requests(self):
        self.assertEqual(self.rows("inventory:request_list", {"status": "all", "q": "torch"}, "reqs"), [self.req_a1])
        self.assertEqual(self.rows("inventory:request_list", {"status": "all", "q": "boots"}, "reqs"), [])
        self.assertEqual(self.rows("inventory:request_list", {"status": "all", "to": str(self.today - timedelta(days=1))}, "reqs"), [])
        self.assert_csv("inventory:request_list", "Mine broke", {"status": "all"})

    def test_feedback(self):
        self.assertEqual(self.rows("clients:feedback_list", {"q": "loud"}, "feedback"), [self.feedback])
        self.assertEqual(self.rows("clients:feedback_list", {"client": self.client_b.pk}, "feedback"), [])
        self.assertEqual(self.rows("clients:feedback_list", {"from": str(self.today + timedelta(days=1))}, "feedback"), [])
        self.assert_csv("clients:feedback_list", "Guards too loud at night")

    def test_expense_history(self):
        cat = ExpenseCategory.objects.create(name="Fuel")
        exp = Expense.objects.create(category=cat, amount=500, date=self.today, description="=Diesel for patrol",
                                     recorded_by=self.secretary)
        ExpenseLog.record(exp, ExpenseLog.Action.CREATED, self.secretary)
        self.assertEqual(len(self.rows("finance:history", {"q": str(exp.pk)}, "entries")), 1)
        self.assertEqual(self.rows("finance:history", {"action": "deleted"}, "entries"), [])
        self.assertEqual(self.rows("finance:history", {"to": str(self.today - timedelta(days=1))}, "entries"), [])
        self.assert_csv("finance:history", "Diesel")
        self.login(self.secretary)
        self.assertIn("'=Diesel", self.client.get(reverse("finance:list"), {"export": "csv"}).content.decode())

    def test_payroll_months(self):
        self.assertEqual(self.rows("payroll:list", {"from": "2026-02-01", "to": "2026-02-28"}, "runs"), [self.payroll_run])
        self.assertEqual(self.rows("payroll:list", {"from": "2026-03-01"}, "runs"), [])
        self.assert_csv("payroll:list", "February 2026")

    def test_notifications_dates_and_unread(self):
        old = Notification.objects.create(recipient=self.staff_a1, kind="x", title="Old one")
        Notification.objects.filter(pk=old.pk).update(created_at=old.created_at - timedelta(days=10))
        Notification.objects.create(recipient=self.staff_a1, kind="x", title="New one", read_at=old.created_at)

        def titles(params):
            return {n.title for n in self.rows("notifications:inbox", params, "notes", self.staff_a1)}

        self.assertEqual(titles({"from": str(self.today - timedelta(days=1))}), {"New one"})
        self.assertEqual(titles({"to": str(self.today - timedelta(days=5))}), {"Old one"})
        self.assertEqual(titles({"unread": "1"}), {"Old one"})
