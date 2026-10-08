"""Permission matrix (Gate 3 §5), uploads, protected downloads, audit log and menus."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Attachment, AuditLog
from core.services.files import detect_type, save_attachment
from core.testing import OpsTestCase

PDF = b"%PDF-1.4\n%test\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20

O = {"manager": 200, "secretary": 200, "supervisor": 403, "staff": 403}
MGR = {"manager": 200, "secretary": 403, "supervisor": 403, "staff": 403}
REQ = {"manager": 403, "secretary": 403, "supervisor": 200, "staff": 200}
ALL = {"manager": 200, "secretary": 200, "supervisor": 200, "staff": 200}


class PermissionMatrixTests(OpsTestCase):
    def pages(self):
        c, i, inv, it = self.client_a.pk, self.issue_a.pk, self.invoice.pk, self.item.pk
        return [
            ("clients:list", (), O), ("clients:create", (), O),
            ("clients:detail", (c,), {**O, "supervisor": 200}),
            ("clients:edit", (c,), O), ("clients:supervisor", (c,), O), ("clients:sites", (c,), O),
            ("clients:message_create", (c,), O), ("clients:message_detail", (self.message.pk,), O),
            ("clients:message_edit", (self.message.pk,), O),
            ("clients:feedback_list", (), O), ("clients:feedback_create", (c,), O),
            ("clients:feedback_detail", (self.feedback.pk,), O),
            ("clients:issue_list", (), {**O, "supervisor": 200}), ("clients:issue_create", (), O),
            ("clients:issue_detail", (i,), {**O, "supervisor": 200}),
            ("notifications:inbox", (), ALL),
            ("billing:list", (), O), ("billing:create", (), O), ("billing:detail", (inv,), O),
            ("billing:edit", (inv,), O), ("billing:print", (inv,), O), ("billing:pdf", (inv,), O),
            ("payroll:list", (), O), ("payroll:profiles", (), O), ("payroll:profile_edit", (self.staff_a1.pk,), O),
            ("payroll:create", (), O), ("payroll:detail", (self.payroll_run.pk,), O), ("payroll:export", (self.payroll_run.pk,), O),
            ("payroll:print", (self.payroll_run.pk,), O),
            ("inventory:library", (), O), ("inventory:create", (), O), ("inventory:categories", (), O),
            ("inventory:detail", (it,), O), ("inventory:edit", (it,), O), ("inventory:flags", (), O),
            ("inventory:request_list", (), O), ("inventory:overdue", (), O),
            ("inventory:request_detail", (self.req_a1.pk,), O),
            ("inventory:browse", (), REQ), ("inventory:request_new", (it,), REQ), ("inventory:mine", (), REQ),
            ("escalations:list", (), O), ("escalations:detail", (self.escalation.pk,), O),
            ("escalations:create", (), {"manager": 403, "secretary": 200, "supervisor": 403, "staff": 403}),
            ("finance:approvals", (), MGR),
            ("core:company_settings", (), MGR), ("core:audit", (), MGR),
            ("core:home", (), ALL),
        ]

    def test_every_page_for_every_role(self):
        people = {"manager": self.manager, "secretary": self.secretary, "supervisor": self.sup_a, "staff": self.staff_a1}
        for name, args, expected in self.pages():
            url = reverse(name, args=args)
            for role, user in people.items():
                self.login(user)
                with self.subTest(url=url, role=role):
                    self.assertEqual(self.client.get(url).status_code, expected[role])
            self.client.logout()
            with self.subTest(url=url, role="anonymous"):
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_supervisor_only_sees_assigned_clients_and_issues(self):
        self.login(self.sup_b)
        self.assertEqual(self.client.get(reverse("clients:detail", args=[self.client_a.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("clients:issue_detail", args=[self.issue_a.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("clients:issue_detail", args=[self.issue_b.pk])).status_code, 200)
        page = self.client.get(reverse("clients:issue_list") + "?status=all").content.decode()
        self.assertIn("Late guard", page)
        self.assertNotIn("Gate light broken", page)

    def test_supervisor_client_page_hides_office_tabs(self):
        self.login(self.sup_a)
        page = self.client.get(reverse("clients:detail", args=[self.client_a.pk]) + "?tab=invoices").content.decode()
        self.assertNotIn("Monthly charge", page)
        self.assertNotIn("?tab=invoices", page)

    def test_requester_cannot_see_other_peoples_requests(self):
        url = reverse("inventory:mine_detail", args=[self.req_a1.pk])
        self.login(self.staff_a1)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.login(self.staff_a2)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.login(self.sup_a)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_menus_keep_gps_links(self):
        self.login(self.manager)
        page = self.client.get(reverse("core:home")).content.decode()
        for link in ("tracking:tracker", "tracking:sites", "tracking:people", "tracking:history"):
            self.assertIn(reverse(link), page)
        for user in (self.staff_a1, self.sup_a):
            self.login(user)
            page = self.client.get(reverse("core:home")).content.decode()
            self.assertIn(reverse("tracking:mine"), page)
            self.assertIn(reverse("inventory:browse"), page)
            self.assertNotIn(reverse("payroll:list"), page)
            self.assertNotIn(reverse("billing:list"), page)

    def test_secretary_menu(self):
        self.login(self.secretary)
        page = self.client.get(reverse("core:home")).content.decode()
        for link in ("clients:list", "billing:list", "payroll:list", "inventory:library", "escalations:list", "finance:list"):
            self.assertIn(reverse(link), page)
        self.assertNotIn(reverse("core:audit"), page)


class UploadTests(OpsTestCase):
    def test_allowed_types_pass(self):
        self.assertEqual(detect_type(SimpleUploadedFile("a.pdf", PDF)), "application/pdf")
        self.assertEqual(detect_type(SimpleUploadedFile("a.png", PNG)), "image/png")
        self.assertEqual(detect_type(SimpleUploadedFile("a.JPG", b"\xff\xd8\xff\xe0" + b"0" * 20)), "image/jpeg")

    def test_disguised_and_bad_files_fail(self):
        for name, content in (("virus.pdf", b"MZ\x90\x00binary"), ("a.exe", PDF), ("photo.png", PDF), ("x.html", b"<html>")):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                detect_type(SimpleUploadedFile(name, content))

    def test_oversize_fails(self):
        with self.assertRaises(ValidationError):
            detect_type(SimpleUploadedFile("big.pdf", PDF + b"0" * (5 * 1024 * 1024)))


@override_settings(MEDIA_ROOT="/tmp/claude-test-media")
class DownloadTests(OpsTestCase):
    def test_download_follows_parent_record_access(self):
        att = save_attachment(self.issue_a, SimpleUploadedFile("photo.pdf", PDF), self.secretary)
        url = reverse("core:file", args=[att.pk])
        self.login(self.sup_a)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp["Content-Disposition"])
        for user in (self.sup_b, self.staff_a1):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_stored_name_is_random(self):
        att = save_attachment(self.issue_a, SimpleUploadedFile("../../evil.pdf", PDF), self.secretary)
        self.assertNotIn("evil", att.file.name)
        self.assertTrue(att.file.name.startswith("attachments/"))
        self.assertEqual(Attachment.objects.count(), 1)


class AuditTests(OpsTestCase):
    def test_entries_written_and_page_filters(self):
        self.assertTrue(AuditLog.objects.filter(action="client.created", entity_id=str(self.client_a.pk)).exists())
        self.login(self.manager)
        page = self.client.get(reverse("core:audit") + "?q=Acme").content.decode()
        self.assertIn("Created client Acme Ltd", page)

    def test_admin_cannot_change_or_delete_audit(self):
        from django.contrib import admin

        model_admin = admin.site._registry[AuditLog]
        request = type("R", (), {"user": self.manager})()
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertFalse(model_admin.has_add_permission(request))


class CompanySettingsTests(OpsTestCase):
    def test_manager_saves_and_change_is_audited(self):
        self.login(self.manager)
        resp = self.client.post(reverse("core:company_settings"), {
            "company_name": "Resilience Security Ltd", "phone": "0711000000", "email": "a@example.com",
            "vat_rate": "16", "invoice_due_days": "14", "late_after_minutes": "15", "sick_note_due_days": "3",
            "sick_note_keep_days": "365",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action="settings.updated").exists())

    def test_approval_limit_needed_when_enabled(self):
        self.login(self.manager)
        resp = self.client.post(reverse("core:company_settings"), {
            "company_name": "X", "vat_rate": "16", "invoice_due_days": "14", "expense_approval_enabled": "on",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Enter the amount above which")


@override_settings(CRON_SECRET="s3cret")
class CronDailyViewTests(TestCase):
    def test_needs_the_secret(self):
        self.assertEqual(self.client.get("/cron/daily/").status_code, 404)
        self.assertEqual(self.client.get("/cron/daily/", HTTP_AUTHORIZATION="Bearer wrong").status_code, 404)

    def test_runs_the_checks(self):
        response = self.client.get("/cron/daily/", HTTP_AUTHORIZATION="Bearer s3cret")
        self.assertEqual(response.status_code, 200)
        self.assertIn("location_records_deleted", response.json())

    @override_settings(CRON_SECRET="")
    def test_off_without_a_secret(self):
        self.assertEqual(self.client.get("/cron/daily/", HTTP_AUTHORIZATION="Bearer ").status_code, 404)
