from django.urls import reverse

from clients.models import Feedback
from core.testing import OpsTestCase
from core.workflow import TransitionError
from notifications.models import Notification

from . import services
from .models import Escalation

E = Escalation.Status


class EscalationTests(OpsTestCase):
    def raise_for_issue(self):
        return services.raise_escalation("issue", self.issue_a, "Client threatens to leave", "Please call them", self.secretary)

    def test_note_required_and_one_open_per_record(self):
        with self.assertRaises(TransitionError):
            services.raise_escalation("issue", self.issue_a, "x", "  ", self.secretary)
        self.raise_for_issue()
        with self.assertRaisesMessage(TransitionError, "already"):
            self.raise_for_issue()
        self.assertTrue(Notification.objects.filter(recipient=self.manager, kind="escalation.new").exists())

    def test_only_secretary_raises(self):
        with self.assertRaises(TransitionError):
            services.raise_escalation("issue", self.issue_a, "x", "y", self.manager)
        self.login(self.manager)
        self.assertEqual(self.client.get(reverse("escalations:create") + f"?type=issue&id={self.issue_a.pk}").status_code, 403)

    def test_manager_sees_full_record_and_it_becomes_seen(self):
        esc = self.raise_for_issue()
        self.login(self.manager)
        page = self.client.get(reverse("escalations:detail", args=[esc.pk])).content.decode()
        self.assertIn("Light at gate B", page)
        self.assertIn("Acme Ltd", page)
        esc.refresh_from_db()
        self.assertEqual(esc.status, E.SEEN)
        self.assertTrue(Notification.objects.filter(recipient=self.secretary, kind="escalation.seen").exists())

    def test_send_back_reply_resolve(self):
        esc = self.raise_for_issue()
        with self.assertRaises(TransitionError):
            services.send_back(esc, self.manager, "")
        services.send_back(esc, self.manager, "Get the contract first")
        self.assertEqual(esc.status, E.SENT_BACK)
        services.reply(esc, self.secretary, "Contract attached to the client")
        esc.refresh_from_db()
        self.assertEqual(esc.status, E.SEEN)
        with self.assertRaises(TransitionError):
            services.resolve(esc, self.secretary, "done")
        services.resolve(esc, self.manager, "Called the client, all good")
        self.assertEqual(esc.status, E.RESOLVED)
        self.assertTrue(Notification.objects.filter(recipient=self.secretary, kind="escalation.resolved").exists())
        self.raise_for_issue()  # a resolved one no longer blocks a new one

    def test_secretary_cannot_use_manager_buttons(self):
        esc = self.raise_for_issue()
        self.login(self.secretary)
        for name in ("send_back", "resolve"):
            self.assertEqual(self.client.post(reverse(f"escalations:{name}", args=[esc.pk]), {"body": "x"}).status_code, 403)

    def test_feedback_marked_escalated(self):
        services.raise_escalation("feedback", self.feedback, "Complaint", "Serious", self.secretary)
        self.feedback.refresh_from_db()
        self.assertEqual(self.feedback.status, Feedback.Status.ESCALATED)

    def test_unknown_record_is_404(self):
        self.login(self.secretary)
        self.assertEqual(self.client.get(reverse("escalations:create") + "?type=issue&id=99999").status_code, 404)
        self.assertEqual(self.client.get(reverse("escalations:create") + "?type=bogus&id=1").status_code, 404)
