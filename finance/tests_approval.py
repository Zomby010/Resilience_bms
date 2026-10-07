"""Optional Manager approval of large expenses (D9) and receipts."""
from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from core.models import Attachment, CompanySettings
from core.testing import CompanyTestCase
from notifications.models import Notification

from .models import Expense, ExpenseCategory


@override_settings(MEDIA_ROOT="/tmp/claude-test-media")
class ExpenseApprovalTests(CompanyTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cat = ExpenseCategory.objects.create(name="Fuel")

    def record(self, amount, **extra):
        self.login(self.secretary)
        data = {"date": "2026-04-02", "category": self.cat.pk, "description": "Diesel", "amount": amount, "reference": ""}
        data.update(extra)
        self.client.post(reverse("finance:create"), data)
        return Expense.objects.latest("id")

    def enable(self, limit="10000"):
        s = CompanySettings.load()
        s.expense_approval_enabled, s.expense_approval_limit = True, Decimal(limit)
        s.save()

    def test_off_by_default(self):
        self.assertEqual(self.record("50000").status, Expense.Status.RECORDED)

    def test_above_limit_waits_and_is_left_out_of_totals(self):
        self.enable()
        small, big = self.record("5000"), self.record("20000")
        self.assertEqual((small.status, big.status), (Expense.Status.RECORDED, Expense.Status.AWAITING_APPROVAL))
        self.assertTrue(Notification.objects.filter(recipient=self.manager, kind="expense.approval").exists())
        page = self.client.get(reverse("finance:list"))
        self.assertEqual(page.context["total"], Decimal("5000"))

    def test_manager_approves_or_rejects(self):
        self.enable()
        big = self.record("20000")
        self.login(self.secretary)
        self.assertEqual(self.client.post(reverse("finance:approve", args=[big.pk])).status_code, 403)
        self.login(self.manager)
        self.assertContains(self.client.get(reverse("finance:approvals")), "Diesel")
        self.client.post(reverse("finance:reject", args=[big.pk]), {"note": ""})
        big.refresh_from_db()
        self.assertEqual(big.status, Expense.Status.AWAITING_APPROVAL)  # reason required
        self.client.post(reverse("finance:approve", args=[big.pk]))
        big.refresh_from_db()
        self.assertEqual((big.status, big.decided_by), (Expense.Status.RECORDED, self.manager))
        self.assertTrue(big.log.filter(details__startswith="Approved").exists())

    def test_receipt_upload(self):
        e = self.record("100", receipt=SimpleUploadedFile("r.pdf", b"%PDF-1.4 receipt"))
        self.assertEqual(Attachment.objects.get().parent, e)
        bad = self.record("100", receipt=SimpleUploadedFile("r.pdf", b"not a pdf"))
        self.assertEqual(bad.pk, e.pk)  # the second form was refused
        self.assertEqual(date(2026, 4, 2), e.date)
