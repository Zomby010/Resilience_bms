from datetime import date
from decimal import Decimal

from django.urls import reverse

from core.models import AuditLog
from core.testing import OpsTestCase
from notifications.models import Notification

from . import services
from .models import PayProfile


class PayslipTests(OpsTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        PayProfile.objects.filter(user=cls.staff_a1).update(mpesa_number="0712345678")
        cls.approved = services.create_run(date(2026, 5, 1), cls.secretary)
        cls.line = cls.approved.lines.get(employee=cls.staff_a1)
        cls.line.paye, cls.line.nssf, cls.line.housing_levy = Decimal("1200"), Decimal("1080"), Decimal("225")
        services.save_line(cls.line, cls.secretary, {})
        cls.other_line = cls.approved.lines.get(employee=cls.staff_a2)
        services.submit(cls.approved, cls.secretary)
        services.approve(cls.approved, cls.manager)
        cls.draft = services.create_run(date(2026, 6, 1), cls.secretary)
        cls.draft_line = cls.draft.lines.get(employee=cls.staff_a1)

    def test_own_payslips_listed_and_shown(self):
        self.login(self.staff_a1)
        page = self.client.get(reverse("payslips:mine")).content.decode()
        self.assertIn("May 2026", page)
        self.assertNotIn("June 2026", page)  # not approved yet
        resp = self.client.get(reverse("payslips:detail", args=[self.line.pk]))
        self.assertEqual(resp.status_code, 200)
        page = resp.content.decode()
        for text in ("Resilience Security", "PAYE", "NSSF", "SHIF", "Housing levy", "15,000.00", "12,495.00"):
            self.assertIn(text, page)
        self.assertTrue(AuditLog.objects.filter(action="payroll.payslip_viewed", confidential=True).exists())

    def test_someone_elses_or_unapproved_payslip_is_404(self):
        self.login(self.staff_a1)
        self.assertEqual(self.client.get(reverse("payslips:detail", args=[self.other_line.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("payslips:pdf", args=[self.other_line.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("payslips:detail", args=[self.draft_line.pk])).status_code, 404)

    def test_pdf_download(self):
        self.login(self.staff_a1)
        resp = self.client.get(reverse("payslips:pdf", args=[self.line.pk]))
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))
        self.assertTrue(AuditLog.objects.filter(action="payroll.payslip_downloaded", confidential=True).exists())

    def test_account_number_masked(self):
        self.login(self.staff_a1)
        page = self.client.get(reverse("payslips:detail", args=[self.line.pk])).content.decode()
        self.assertNotIn("0712345678", page)
        self.assertIn("678", page)

    def test_employees_told_when_approved(self):
        note = Notification.objects.get(recipient=self.staff_a1, kind="payroll.payslip_ready")
        self.assertEqual(note.link_url, reverse("payslips:detail", args=[self.line.pk]))
        self.assertNotIn("12,495", note.title + note.message)

    def test_office_print_all_and_single(self):
        self.login(self.secretary)
        page = self.client.get(reverse("payroll:payslips", args=[self.approved.pk])).content.decode()
        self.assertEqual(page.count('class="payslip-page"'), self.approved.lines.count())
        self.assertIn("Staffa2", page)
        self.assertEqual(self.client.get(reverse("payroll:payslip", args=[self.approved.pk, self.line.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("payroll:payslip_pdf", args=[self.approved.pk, self.line.pk]))["Content-Type"],
                         "application/pdf")
        self.assertEqual(self.client.get(reverse("payroll:payslips", args=[self.draft.pk])).status_code, 404)
        self.assertIn(reverse("payroll:payslips", args=[self.approved.pk]),
                      self.client.get(self.approved.get_absolute_url()).content.decode())

    def test_staff_and_supervisor_blocked_from_office_payslips(self):
        for user in (self.staff_a1, self.sup_a):
            self.login(user)
            for url in (reverse("payroll:payslips", args=[self.approved.pk]),
                        reverse("payroll:payslip", args=[self.approved.pk, self.line.pk]),
                        reverse("payroll:payslip_pdf", args=[self.approved.pk, self.line.pk])):
                self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_menu_link_for_every_role(self):
        for user in (self.staff_a1, self.sup_a, self.secretary, self.manager):
            self.login(user)
            self.assertIn(reverse("payslips:mine"), self.client.get(reverse("core:home")).content.decode())
