"""The "N things need you" lists (DASH-01..04, DASH-08, CLUT-04, NOTE-01, PERF-01)."""
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.testing import OpsTestCase
from core.todo import grouped, todos_for
from inventory import services as inventory
from inventory.models import ItemRequest
from notifications.models import Notification
from notifications.services import notify, unread_count
from reports.models import Report


class TodoTests(OpsTestCase):
    def test_manager_item_approval_is_one_tap(self):
        self.item.needs_manager_approval = True
        self.item.save()
        req = inventory.create_request(self.item, 1, "Night patrol", self.sup_a)
        self.assertEqual(req.status, ItemRequest.Status.AWAITING_MANAGER)
        self.login(self.manager)
        page = self.client.get(reverse("core:home")).content.decode()
        self.assertIn("SUPERVISOR</b> · Supa", page)  # who sent it
        self.assertIn("Approve this", page)
        post = reverse("inventory:manager_approve", args=[req.pk])
        self.assertIn(post, page)
        r = self.client.post(post, {"next": reverse("core:home")})
        self.assertRedirects(r, reverse("core:home"), fetch_redirect_response=False)
        req.refresh_from_db()
        self.assertEqual(req.status, ItemRequest.Status.PENDING)

    def test_one_tap_ignores_outside_next(self):
        self.item.needs_manager_approval = True
        self.item.save()
        req = inventory.create_request(self.item, 1, "x", self.sup_a)
        self.login(self.manager)
        r = self.client.post(reverse("inventory:manager_approve", args=[req.pk]), {"next": "https://evil.example/"})
        self.assertEqual(r["Location"], req.get_absolute_url())

    def test_secretary_groups_by_sender(self):
        groups = dict(grouped(todos_for(self.secretary)))
        self.assertIn("From guards", groups)        # the staff item request
        self.assertIn("From clients", groups)       # new feedback
        labels = [label for label, _ in grouped(todos_for(self.secretary))]
        order = ["From the Manager", "From the Secretary", "From supervisors", "From guards", "From clients", "From the system"]
        self.assertEqual(labels, [x for x in order if x in labels])

    def test_supervisor_sees_guard_reports_and_issues(self):
        Report.objects.create(author=self.staff_a1, title="Gate lock broken", body="x")
        summaries = [t.summary for t in todos_for(self.sup_a)]
        self.assertIn("Gate lock broken", summaries)
        self.assertTrue(any("Gate light broken" in s for s in summaries))  # issue_a is sup_a's client
        self.assertFalse(any("Late guard" in s for s in summaries))        # issue_b belongs to sup_b

    def test_guard_feedback_is_a_read_this_until_opened(self):
        report = Report.objects.create(author=self.staff_a1, title="Torch", body="x")
        report.add_reply(self.sup_a, "Collect a new one")
        todos = todos_for(self.staff_a1)
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].actions[0].label, "Read this")
        self.assertEqual(unread_count(self.staff_a1), 0)  # not in the bell as well
        self.login(self.staff_a1)
        page = self.client.get(reverse("core:home")).content.decode()
        for gone in ("Latest feedback", "My recent reports", ">Pending<"):
            self.assertNotIn(gone, page)
        self.client.get(todos[0].url)  # opening it marks it read
        self.assertEqual(todos_for(self.staff_a1), [])

    def test_bell_keeps_news_only(self):
        notify(self.staff_a1, "leave.decided", "Your leave was approved")
        notify(self.staff_a1, "report.reply", "Supa replied")
        self.assertEqual(unread_count(self.staff_a1), 1)
        self.login(self.staff_a1)
        notes = self.client.get(reverse("notifications:inbox")).context["notes"]
        self.assertEqual([n.kind for n in notes], ["leave.decided"])
        notes = self.client.get(reverse("notifications:inbox") + "?all=1").context["notes"]
        self.assertEqual(len(notes), 2)  # nothing is lost
        self.assertEqual(Notification.objects.filter(recipient=self.staff_a1).count(), 2)

    def test_manager_home_query_ceiling(self):
        for i in range(5):
            Report.objects.create(author=self.sup_a, title=f"Report {i}", body="x")
        self.login(self.manager)
        self.client.get(reverse("core:home"))
        with CaptureQueriesContext(connection) as q:
            self.assertEqual(self.client.get(reverse("core:home")).status_code, 200)
        self.assertLess(len(q.captured_queries), 30)
