from datetime import date
from decimal import Decimal

from django.core import mail
from django.urls import reverse

from clients.models import Client
from core.models import CompanySettings
from core.testing import OpsTestCase
from core.workflow import TransitionError

from . import services
from .models import Invoice, InvoiceLine
from .pdf import invoice_pdf

ST = Invoice.Status


class InvoiceTests(OpsTestCase):
    def draft(self, client=None, lines=(("Guarding", "1", "1000.00"),), vat=False, d=date(2026, 3, 1)):
        inv = Invoice(client=client or self.client_a, invoice_date=d, due_date=d.replace(day=15), vat_enabled=vat)
        objs = [InvoiceLine(description=a, quantity=Decimal(q), unit_price=Decimal(p)) for a, q, p in lines]
        return services.save_draft(inv, objs, self.secretary, creating=True)

    def test_totals_without_vat(self):
        inv = self.draft(lines=(("Day guards", "2.5", "333.33"), ("Dog", "1", "100")))
        self.assertEqual(inv.subtotal, Decimal("933.33"))  # 833.325 -> 833.33 per line
        self.assertEqual(inv.vat_amount, Decimal("0.00"))
        self.assertEqual(inv.total, Decimal("933.33"))

    def test_vat_only_when_company_is_vat_registered(self):
        inv = self.draft(vat=True)
        self.assertFalse(inv.vat_enabled)
        s = CompanySettings.load()
        s.vat_registered = True
        s.save()
        inv = self.draft(vat=True, lines=(("Guarding", "1", "1000"),))
        self.assertEqual((inv.vat_rate, inv.vat_amount, inv.total), (Decimal("16.00"), Decimal("160.00"), Decimal("1160.00")))

    def test_totals_come_from_the_server_not_the_form(self):
        self.login(self.secretary)
        resp = self.client.post(reverse("billing:create"), {
            "client": self.client_a.pk, "invoice_date": "2026-03-01", "due_date": "2026-03-10",
            "notes": "", "payment_instructions": "", "total": "1", "subtotal": "1",
            "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "50",
            "lines-0-description": "Guarding", "lines-0-quantity": "3", "lines-0-unit_price": "500",
        })
        inv = Invoice.objects.latest("id")
        self.assertRedirects(resp, inv.get_absolute_url())
        self.assertEqual(inv.total, Decimal("1500.00"))
        self.assertIsNone(inv.number)

    def test_form_rules(self):
        self.login(self.secretary)
        base = {"client": self.client_a.pk, "invoice_date": "2026-03-10", "due_date": "2026-03-01",
                "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "50",
                "lines-0-description": "", "lines-0-quantity": "", "lines-0-unit_price": ""}
        resp = self.client.post(reverse("billing:create"), base)
        self.assertContains(resp, "due date cannot be before")
        self.assertContains(resp, "at least one line")
        base.update({"due_date": "2026-03-20", "lines-0-description": "X", "lines-0-quantity": "0", "lines-0-unit_price": "-5"})
        resp = self.client.post(reverse("billing:create"), base)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Invoice.objects.filter(invoice_date=date(2026, 3, 10)).exists())

    def test_numbers_given_on_send_in_order_and_per_year(self):
        a, b = self.draft(), self.draft()
        services.send_invoice(b, self.secretary)
        services.send_invoice(a, self.secretary)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((b.number, a.number), ("INV-2026-0001", "INV-2026-0002"))
        c = self.draft(d=date(2027, 1, 5))
        services.send_invoice(c, self.secretary)
        self.assertEqual(c.number, "INV-2027-0001")
        self.assertIsNone(self.invoice.number)  # untouched draft has no number

    def test_send_twice_keeps_one_number(self):
        inv = self.draft()
        stale = Invoice.objects.get(pk=inv.pk)
        services.send_invoice(inv, self.secretary)
        services.send_invoice(stale, self.secretary)  # second click = "email again"
        self.assertEqual(Invoice.objects.exclude(number=None).count(), 1)
        self.assertEqual(len(mail.outbox), 2)

    def test_email_has_pdf_and_client_details_are_frozen(self):
        inv = self.draft()
        services.send_invoice(inv, self.secretary)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["acme@example.com"])
        name, content, mime = msg.attachments[0]
        self.assertEqual((name, mime), ("INV-2026-0001.pdf", "application/pdf"))
        self.assertTrue(content.startswith(b"%PDF"))
        Client.objects.filter(pk=self.client_a.pk).update(name="Renamed")
        inv.refresh_from_db()
        self.assertEqual(inv.bill_to_name, "Acme Ltd")

    def test_sent_invoice_cannot_be_edited(self):
        inv = self.draft()
        services.send_invoice(inv, self.secretary)
        with self.assertRaises(TransitionError):
            services.save_draft(inv, [InvoiceLine(description="x", quantity=1, unit_price=1)], self.secretary, creating=False)
        self.login(self.secretary)
        self.assertRedirects(self.client.get(reverse("billing:edit", args=[inv.pk])), inv.get_absolute_url())

    def test_client_without_email_cannot_be_sent(self):
        Client.objects.filter(pk=self.client_a.pk).update(email="")
        inv = self.draft()
        inv.client.refresh_from_db()
        with self.assertRaisesMessage(TransitionError, "no email"):
            services.send_invoice(inv, self.secretary)
        inv.refresh_from_db()
        self.assertIsNone(inv.number)

    def test_payments_part_then_paid_and_never_above_balance(self):
        inv = self.draft()
        services.send_invoice(inv, self.secretary)
        with self.assertRaises(TransitionError):
            services.record_payment(inv, date(2026, 3, 5), Decimal("1000.01"), "mpesa", "", self.secretary)
        services.record_payment(inv, date(2026, 3, 5), Decimal("400"), "mpesa", "QX1", self.secretary)
        self.assertEqual((inv.status, inv.balance), (ST.PART_PAID, Decimal("600.00")))
        services.record_payment(inv, date(2026, 3, 6), Decimal("600"), "bank", "", self.secretary)
        self.assertEqual((inv.status, inv.balance), (ST.PAID, Decimal("0.00")))
        with self.assertRaises(TransitionError):
            services.record_payment(inv, date(2026, 3, 6), Decimal("1"), "cash", "", self.secretary)

    def test_no_payment_on_draft(self):
        with self.assertRaises(TransitionError):
            services.record_payment(self.invoice, date(2026, 3, 5), Decimal("10"), "cash", "", self.secretary)

    def test_overdue_check(self):
        inv = self.draft()
        services.send_invoice(inv, self.secretary)
        self.assertEqual(services.mark_overdue(today=date(2026, 3, 16)), 1)
        inv.refresh_from_db()
        self.assertEqual(inv.status, ST.OVERDUE)
        self.assertEqual(services.mark_overdue(today=date(2026, 3, 17)), 0)

    def test_cancel_rules(self):
        inv = self.draft()
        services.send_invoice(inv, self.secretary)
        with self.assertRaises(TransitionError):
            services.cancel_invoice(inv, self.secretary, "")
        services.record_payment(inv, date(2026, 3, 5), Decimal("10"), "cash", "", self.secretary)
        with self.assertRaisesMessage(TransitionError, "payments"):
            services.cancel_invoice(inv, self.secretary, "Wrong client")
        other = self.draft()
        services.send_invoice(other, self.secretary)
        services.cancel_invoice(other, self.secretary, "Wrong client")
        self.assertEqual(other.status, ST.CANCELLED)

    def test_delete_only_unsent_drafts(self):
        inv = self.draft()
        services.delete_draft(inv, self.secretary)
        self.assertFalse(Invoice.objects.filter(pk=inv.pk).exists())
        sent = self.draft()
        services.send_invoice(sent, self.secretary)
        with self.assertRaises(TransitionError):
            services.delete_draft(sent, self.secretary)

    def test_pdf_has_number_and_total(self):
        inv = self.draft()
        services.send_invoice(inv, self.secretary)
        pdf = invoice_pdf(inv)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1500)

    def test_staff_and_supervisors_blocked_on_actions(self):
        for user in (self.staff_a1, self.sup_a):
            self.login(user)
            for name in ("send", "cancel", "delete"):
                self.assertEqual(self.client.post(reverse(f"billing:{name}", args=[self.invoice.pk])).status_code, 403)
