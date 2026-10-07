from django.core import mail
from django.test import override_settings
from django.urls import reverse

from core.models import AuditLog
from core.testing import OpsTestCase
from core.workflow import TransitionError
from notifications.models import Notification

from . import services
from .models import Client, Feedback, Issue, Message, SupervisorAssignment

S = Issue.Status


class ClientTests(OpsTestCase):
    def post_client(self, **extra):
        data = {"name": "Gamma Hotel", "phone": "0733111222", "email": "", "contact_person": "Jane"}
        data.update(extra)
        self.login(self.secretary)
        return self.client.post(reverse("clients:create"), data)

    def test_create_with_audit_and_supervisor_history(self):
        resp = self.post_client(supervisor=self.sup_a.pk)
        c = Client.objects.get(name="Gamma Hotel")
        self.assertRedirects(resp, c.get_absolute_url())
        self.assertEqual(c.supervisor, self.sup_a)
        self.assertEqual(SupervisorAssignment.objects.filter(client=c, ended_at__isnull=True).count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="client.created", entity_id=str(c.pk)).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.sup_a, kind="client.assigned").exists())

    def test_phone_and_email_validation(self):
        resp = self.post_client(phone="12345")
        self.assertContains(resp, "Kenyan phone number")
        resp = self.post_client(phone="", email="")
        self.assertContains(resp, "at least a phone number or an email")

    def test_duplicate_warning_needs_confirmation(self):
        resp = self.post_client(name="acme ltd", phone="0799000000")
        self.assertContains(resp, "Possible duplicate")
        self.assertEqual(Client.objects.filter(name__iexact="acme ltd").count(), 1)
        self.post_client(name="acme ltd", phone="0799000000", confirm_duplicate="on")
        self.assertEqual(Client.objects.filter(name__iexact="acme ltd").count(), 2)

    def test_edit_is_audited_with_old_and_new_values(self):
        self.login(self.secretary)
        self.client.post(reverse("clients:edit", args=[self.client_a.pk]), {
            "name": "Acme Limited", "phone": "0712345678", "email": "acme@example.com",
        })
        entry = AuditLog.objects.filter(action="client.updated").latest("id")
        self.assertEqual(entry.changes["name"], ["Acme Ltd", "Acme Limited"])

    def test_deactivate_and_reactivate(self):
        self.login(self.secretary)
        self.client.post(reverse("clients:deactivate", args=[self.client_a.pk]))
        self.client_a.refresh_from_db()
        self.assertFalse(self.client_a.is_active)
        self.assertTrue(Notification.objects.filter(recipient=self.sup_a, kind="client.deactivated").exists())
        self.client.post(reverse("clients:reactivate", args=[self.client_a.pk]))
        self.client_a.refresh_from_db()
        self.assertTrue(self.client_a.is_active)

    def test_change_supervisor_keeps_history_and_moves_open_issues(self):
        self.login(self.manager)
        self.client.post(reverse("clients:supervisor", args=[self.client_a.pk]), {"supervisor": self.sup_b.pk, "move_open_issues": "on"})
        self.client_a.refresh_from_db()
        self.issue_a.refresh_from_db()
        self.assertEqual(self.client_a.supervisor, self.sup_b)
        self.assertEqual(self.issue_a.supervisor, self.sup_b)
        self.assertEqual(self.client_a.assignments.count(), 2)
        self.assertEqual(self.client_a.assignments.filter(ended_at__isnull=True).get().supervisor, self.sup_b)
        self.assertTrue(Notification.objects.filter(recipient=self.sup_b, kind="client.assigned").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.sup_a, kind="client.unassigned").exists())

    def test_staff_cannot_be_made_supervisor(self):
        with self.assertRaises(TransitionError):
            services.assign_supervisor(self.client_a, self.staff_a1, self.secretary)

    def test_gps_site_links_to_one_client_only(self):
        from tracking.models import Site

        site = Site.objects.create(name="Kondele", latitude=-0.08, longitude=34.77)
        services.set_client_sites(self.client_a, [site], self.secretary)
        with self.assertRaises(TransitionError):
            services.set_client_sites(self.client_b, [site], self.secretary)
        self.login(self.secretary)
        page = self.client.get(reverse("clients:sites", args=[self.client_b.pk])).content.decode()
        self.assertNotIn("Kondele", page)


class IssueTests(OpsTestCase):
    def test_new_issue_goes_to_clients_supervisor(self):
        self.assertEqual(self.issue_a.supervisor, self.sup_a)
        self.assertEqual(self.issue_a.status, S.ASSIGNED)
        self.assertTrue(Notification.objects.filter(recipient=self.sup_a, kind="issue.assigned").exists())

    def test_no_supervisor_means_supervisor_needed(self):
        c = services.create_client(Client(name="Delta", phone="0744000000"), self.secretary)
        issue = services.create_issue(c, "Broken gate", "x", "normal", self.secretary)
        self.assertEqual(issue.status, S.SUPERVISOR_NEEDED)
        self.assertIsNone(issue.supervisor)
        self.assertTrue(Notification.objects.filter(recipient=self.secretary, kind="issue.supervisor_needed").exists())
        services.assign_issue(issue, self.sup_b, self.secretary)
        self.assertEqual((issue.status, issue.supervisor), (S.ASSIGNED, self.sup_b))

    def test_supervisor_transitions(self):
        services.change_issue_status(self.issue_a, S.IN_PROGRESS, self.sup_a)
        services.change_issue_status(self.issue_a, S.WAITING_FEEDBACK, self.sup_a)
        with self.assertRaisesMessage(TransitionError, "note"):
            services.change_issue_status(self.issue_a, S.RESOLVED, self.sup_a, "")
        services.change_issue_status(self.issue_a, S.RESOLVED, self.sup_a, "Bulb replaced")
        with self.assertRaises(TransitionError):  # supervisors never close
            services.change_issue_status(self.issue_a, S.CLOSED, self.sup_a)
        with self.assertRaises(TransitionError):  # nor reopen
            services.change_issue_status(self.issue_a, S.IN_PROGRESS, self.sup_a, "again")
        self.assertTrue(Notification.objects.filter(recipient=self.secretary, kind="issue.progress").exists())

    def test_office_closes_and_reopens_with_reason(self):
        services.change_issue_status(self.issue_a, S.RESOLVED, self.secretary, "Fixed")
        services.change_issue_status(self.issue_a, S.CLOSED, self.secretary)
        with self.assertRaises(TransitionError):
            services.change_issue_status(self.issue_a, S.IN_PROGRESS, self.secretary, "")
        services.change_issue_status(self.issue_a, S.IN_PROGRESS, self.manager, "Client says it broke again")
        self.assertEqual(self.issue_a.status, S.IN_PROGRESS)
        self.assertIsNone(self.issue_a.closed_at)

    def test_other_supervisor_cannot_act(self):
        with self.assertRaises(TransitionError):
            services.change_issue_status(self.issue_a, S.IN_PROGRESS, self.sup_b)
        self.login(self.sup_b)
        resp = self.client.post(reverse("clients:issue_status", args=[self.issue_a.pk]), {"to": S.IN_PROGRESS})
        self.assertEqual(resp.status_code, 404)
        resp = self.client.post(reverse("clients:issue_note", args=[self.issue_a.pk]), {"body": "hi"})
        self.assertEqual(resp.status_code, 404)

    def test_supervisor_cannot_reassign(self):
        self.login(self.sup_a)
        resp = self.client.post(reverse("clients:issue_assign", args=[self.issue_a.pk]), {"supervisor": self.sup_b.pk})
        self.assertEqual(resp.status_code, 403)

    def test_note_through_page(self):
        self.login(self.sup_a)
        self.client.post(reverse("clients:issue_note", args=[self.issue_a.pk]), {"body": "On my way"})
        self.assertTrue(self.issue_a.notes.filter(body="On my way", author=self.sup_a).exists())

    def test_stale_double_submit_applied_once(self):
        stale = Issue.objects.get(pk=self.issue_a.pk)
        services.change_issue_status(self.issue_a, S.IN_PROGRESS, self.sup_a)
        with self.assertRaises(TransitionError):
            services.change_issue_status(stale, S.IN_PROGRESS, self.sup_a)
        self.assertEqual(self.issue_a.notes.filter(status_to=S.IN_PROGRESS).count(), 1)


class MessageAndFeedbackTests(OpsTestCase):
    def test_send_message_by_email(self):
        ok, err = services.send_message(self.message, self.secretary)
        self.assertTrue(ok, err)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["acme@example.com"])
        self.assertIn("Resilience Security", mail.outbox[0].body)
        self.message.refresh_from_db()
        self.assertEqual(self.message.status, Message.Status.SENT)
        ok, err = services.send_message(self.message, self.secretary)
        self.assertFalse(ok)  # never sent twice
        self.assertEqual(len(mail.outbox), 1)

    def test_internal_notes_never_in_email(self):
        Client.objects.filter(pk=self.client_a.pk).update(notes="SECRET: slow payer")
        self.message.client.refresh_from_db()
        services.send_message(self.message, self.secretary)
        self.assertNotIn("SECRET", mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND="core.tests_helpers.BrokenEmailBackend")
    def test_failure_is_recorded_and_retry_works(self):
        ok, err = services.send_message(self.message, self.secretary)
        self.assertFalse(ok)
        self.message.refresh_from_db()
        self.assertEqual(self.message.status, Message.Status.FAILED)
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            ok, err = services.send_message(self.message, self.secretary)
        self.assertTrue(ok)

    def test_client_without_email(self):
        c = services.create_client(Client(name="NoMail", phone="0755000000"), self.secretary)
        msg = Message.objects.create(client=c, subject="Hi", body="x", created_by=self.secretary)
        ok, err = services.send_message(msg, self.secretary)
        self.assertFalse(ok)
        self.assertIn("no email", err)
        services.record_offline(msg, self.secretary)
        self.assertEqual(msg.status, Message.Status.RECORDED_OFFLINE)

    def test_send_from_page(self):
        self.login(self.secretary)
        self.client.post(reverse("clients:message_create", args=[self.client_a.pk]),
                         {"subject": "Notice", "body": "New guard from Monday", "priority": "normal", "action": "send"})
        self.assertEqual(len(mail.outbox), 1)

    def test_feedback_flow(self):
        services.review_feedback(self.feedback, self.secretary)
        services.respond_to_feedback(self.feedback, self.secretary, "We have spoken to the guards.", Feedback.Channel.EMAIL)
        self.feedback.refresh_from_db()
        self.assertEqual(self.feedback.status, Feedback.Status.RESPONDED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(Message.objects.filter(kind=Message.Kind.FEEDBACK_RESPONSE, client=self.client_a).exists())
        issue = services.feedback_to_issue(self.feedback, self.secretary)
        self.assertEqual(issue.supervisor, self.sup_a)
        self.assertEqual(issue.source_feedback, self.feedback)
        services.close_feedback(self.feedback, self.secretary)
        self.assertEqual(self.feedback.status, Feedback.Status.CLOSED)

    def test_phone_response_sends_no_email(self):
        services.respond_to_feedback(self.feedback, self.secretary, "Called them.", Feedback.Channel.PHONE)
        self.assertEqual(len(mail.outbox), 0)
