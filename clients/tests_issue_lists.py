from datetime import timedelta

from django.urls import reverse

from core.testing import OpsTestCase

from . import services
from .models import Issue


class IssueListTests(OpsTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # The owner's case: issues sent to a supervisor and then resolved used to vanish from the default list.
        Issue.objects.filter(pk=cls.issue_a.pk).update(status=Issue.Status.RESOLVED)
        services.add_issue_note(cls.issue_a, cls.sup_a, "Fixed the gate light")
        services.add_issue_note(cls.issue_b, cls.sup_b, "Spoke to the guard")

    def numbers(self, params=None, user=None):
        self.login(user or self.secretary)
        resp = self.client.get(reverse("clients:issue_list"), params or {})
        return {i.number for i in resp.context["issues"]}

    def test_default_shows_every_issue_with_status_counts(self):
        self.assertEqual(self.numbers(), {self.issue_a.number, self.issue_b.number})
        chips = {v: n for v, _label, n in self.client.get(reverse("clients:issue_list")).context["chips"]}
        self.assertEqual((chips["all"], chips["resolved"], chips["open"]), (2, 1, 1))
        self.assertEqual(self.numbers({"status": "open"}), {self.issue_b.number})
        self.assertIn("Last update", self.client.get(reverse("clients:issue_list")).content.decode())

    def test_filters(self):
        a, b = self.issue_a.number, self.issue_b.number
        self.assertEqual(self.numbers({"q": a}), {a})
        self.assertEqual(self.numbers({"q": "late guard"}), {b})
        self.assertEqual(self.numbers({"client": self.client_b.pk}), {b})
        self.assertEqual(self.numbers({"priority": "high"}), {b})
        self.assertEqual(self.numbers({"supervisor": self.sup_a.pk}), {a})
        self.assertEqual(self.numbers({"to": str(self.today - timedelta(days=1))}), set())
        self.assertEqual(self.numbers({"from": str(self.today)}), {a, b})

    def test_supervisor_sees_only_own_and_cannot_filter_by_supervisor(self):
        self.assertEqual(self.numbers(user=self.sup_a), {self.issue_a.number})
        self.assertEqual(self.numbers({"supervisor": self.sup_b.pk}, user=self.sup_a), {self.issue_a.number})

    def test_csv_office_only(self):
        self.login(self.secretary)
        resp = self.client.get(reverse("clients:issue_list"), {"export": "csv"})
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn(self.issue_a.number, resp.content.decode())
        self.login(self.sup_a)
        self.assertEqual(self.client.get(reverse("clients:issue_list"), {"export": "csv"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("clients:issue_history"), {"export": "csv"}).status_code, 403)

    def test_history_scoped_and_filtered(self):
        self.login(self.sup_a)
        entries = self.client.get(reverse("clients:issue_history")).context["entries"]
        self.assertTrue(entries)
        self.assertEqual({n.issue_id for n in entries}, {self.issue_a.pk})
        self.login(self.secretary)
        url = reverse("clients:issue_history")
        self.assertEqual({n.issue_id for n in self.client.get(url).context["entries"]}, {self.issue_a.pk, self.issue_b.pk})
        notes = self.client.get(url, {"kind": "note"}).context["entries"]
        self.assertEqual({n.body for n in notes}, {"Fixed the gate light", "Spoke to the guard"})
        self.assertTrue(all(n.status_to for n in self.client.get(url, {"kind": "status"}).context["entries"]))
        self.assertEqual({n.issue_id for n in self.client.get(url, {"author": self.sup_b.pk}).context["entries"]}, {self.issue_b.pk})
        self.assertEqual({n.issue_id for n in self.client.get(url, {"client": self.client_a.pk}).context["entries"]}, {self.issue_a.pk})
        self.assertFalse(self.client.get(url, {"to": str(self.today - timedelta(days=1))}).context["entries"])
        resp = self.client.get(url, {"export": "csv"})
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("Fixed the gate light", resp.content.decode())
        self.login(self.staff_a1)
        self.assertEqual(self.client.get(url).status_code, 403)
