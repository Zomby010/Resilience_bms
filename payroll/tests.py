from datetime import date
from decimal import Decimal

from django.urls import reverse

from accounts.models import Role
from core.models import AuditLog
from core.testing import OpsTestCase
from core.workflow import TransitionError
from notifications.models import Notification

from . import services
from .models import PayProfile, PayrollLine, PayrollRun

S = PayrollRun.Status


class PayrollTests(OpsTestCase):
    def new_run(self, period=date(2026, 5, 1)):
        return services.create_run(period, self.secretary)

    def test_run_prefilled_and_managers_excluded(self):
        run = self.new_run()
        people = set(run.lines.values_list("employee__username", flat=True))
        self.assertNotIn("manager", people)
        self.assertIn("staffa1", people)
        line = run.lines.get(employee=self.staff_a1)
        self.assertEqual((line.basic, line.gross, line.net), (Decimal("15000.00"), Decimal("15000.00"), Decimal("15000.00")))

    def test_one_active_payroll_per_month(self):
        self.new_run()
        with self.assertRaises(TransitionError):
            self.new_run()
        self.assertEqual(PayrollRun.objects.filter(period=date(2026, 5, 1)).count(), 1)

    def test_rejected_month_can_be_started_again(self):
        run = self.new_run()
        services.submit(run, self.secretary)
        services.reject(run, self.manager, "Wrong figures")
        self.new_run()

    def test_maths_and_negative_net_blocks_submit(self):
        run = self.new_run()
        line = run.lines.get(employee=self.staff_a1)
        before = {}
        line.overtime, line.bonus, line.paye, line.nssf, line.advance = Decimal("2000"), Decimal("500"), Decimal("1200"), Decimal("1080"), Decimal("20000")
        services.save_line(line, self.secretary, before)
        self.assertEqual((line.gross, line.total_deductions, line.net), (Decimal("17500"), Decimal("22280"), Decimal("-4780")))
        with self.assertRaisesMessage(TransitionError, "below zero"):
            services.submit(run, self.secretary)
        line.advance = Decimal("0")
        services.save_line(line, self.secretary, before)
        run.refresh_from_db()
        services.submit(run, self.secretary)
        self.assertEqual(run.status, S.SUBMITTED)

    def test_full_approval_cycle_and_lock(self):
        run = self.new_run()
        services.submit(run, self.secretary)
        self.assertTrue(Notification.objects.filter(recipient=self.manager, kind="payroll.submitted").exists())
        self.login(self.manager)
        self.client.get(run.get_absolute_url())
        run.refresh_from_db()
        self.assertEqual(run.status, S.UNDER_REVIEW)
        with self.assertRaises(TransitionError):
            services.request_changes(run, self.manager, "")
        services.request_changes(run, self.manager, "Check overtime")
        self.assertEqual(run.status, S.REVISION_REQUIRED)
        services.submit(run, self.secretary)
        services.approve(run, self.manager)
        self.assertEqual(run.status, S.APPROVED)
        line = run.lines.first()
        with self.assertRaises(TransitionError):
            services.save_line(line, self.secretary, {})
        with self.assertRaises(TransitionError):
            services.add_person(run, self.staff_b1, self.secretary)
        with self.assertRaises(TransitionError):
            services.reopen(run, self.manager, "")
        services.reopen(run, self.manager, "Bonus missing")
        self.assertEqual(run.status, S.REVISION_REQUIRED)

    def test_only_manager_decides_and_only_secretary_submits(self):
        run = self.new_run()
        self.login(self.manager)
        self.assertEqual(self.client.post(reverse("payroll:submit", args=[run.pk])).status_code, 403)
        services.submit(run, self.secretary)
        self.login(self.secretary)
        for name in ("approve", "reject", "request_changes", "reopen"):
            self.assertEqual(self.client.post(reverse(f"payroll:{name}", args=[run.pk]), {"note": "x"}).status_code, 403)
        with self.assertRaises(TransitionError):
            services.approve(run, self.secretary)

    def test_supervisors_and_staff_blocked_everywhere(self):
        run = self.new_run()
        line = run.lines.first()
        urls = [reverse("payroll:list"), reverse("payroll:profiles"), reverse("payroll:create"),
                reverse("payroll:detail", args=[run.pk]), reverse("payroll:export", args=[run.pk]),
                reverse("payroll:print", args=[run.pk]), reverse("payroll:profile_edit", args=[self.staff_a1.pk]),
                reverse("payroll:line_edit", args=[run.pk, line.pk])]
        for user in (self.sup_a, self.staff_a1):
            self.login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403, url)
            for name in ("submit", "approve", "add_person"):
                self.assertEqual(self.client.post(reverse(f"payroll:{name}", args=[run.pk])).status_code, 403)

    def test_no_pay_leaks_into_other_pages(self):
        self.new_run()
        for user, url in ((self.manager, reverse("accounts:team")), (self.sup_a, reverse("core:home")),
                          (self.staff_a1, reverse("core:home")), (self.staff_a1, reverse("accounts:profile"))):
            self.login(user)
            page = self.client.get(url).content.decode()
            self.assertNotIn("15,000", page)
            self.assertNotIn("15000", page)

    def test_manager_cannot_get_a_pay_profile(self):
        self.login(self.secretary)
        self.assertEqual(self.client.get(reverse("payroll:profile_edit", args=[self.manager.pk])).status_code, 404)
        with self.assertRaises(TransitionError):
            services.add_person(self.new_run(), self.manager, self.secretary)

    def test_profile_validation_and_masking(self):
        self.login(self.secretary)
        url = reverse("payroll:profile_edit", args=[self.staff_a2.pk])
        resp = self.client.post(url, {"basic_salary": "12000", "regular_allowances": "0", "payment_method": "mpesa",
                                      "mpesa_number": "12345", "is_active": "on"})
        self.assertEqual(resp.status_code, 200)
        self.client.post(url, {"basic_salary": "12000", "regular_allowances": "0", "payment_method": "mpesa",
                               "mpesa_number": "0712345678", "is_active": "on"})
        self.assertTrue(PayProfile.objects.filter(user=self.staff_a2).exists())
        page = self.client.get(reverse("payroll:profiles")).content.decode()
        self.assertNotIn("0712345678", page)
        self.assertIn("678", page)
        entry = AuditLog.objects.filter(action="payroll.profile_saved").latest("id")
        self.assertTrue(entry.confidential)
        self.assertNotIn("0712345678", str(entry.changes))

    def test_export_is_audited_as_confidential(self):
        run = self.new_run()
        self.login(self.secretary)
        resp = self.client.get(reverse("payroll:export", args=[run.pk]))
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("Net pay", resp.content.decode())
        self.assertTrue(AuditLog.objects.filter(action="payroll.exported", confidential=True).exists())

    def test_payroll_audit_hidden_from_client_history(self):
        self.new_run()
        self.assertFalse(AuditLog.objects.filter(action__startswith="payroll.", confidential=False).exists())

    def test_line_edit_page_recalculates(self):
        run = self.new_run()
        line = run.lines.get(employee=self.staff_a1)
        self.login(self.secretary)
        data = {f: "0" for f in services.EARNINGS + services.DEDUCTIONS}
        data.update(basic="15000", paye="1000", other_note="")
        self.client.post(reverse("payroll:line_edit", args=[run.pk, line.pk]), data)
        line.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(line.net, Decimal("14000.00"))
        self.assertEqual(run.total_net, sum(PayrollLine.objects.filter(run=run).values_list("net", flat=True)))
        self.assertEqual(self.manager.role, Role.MANAGER)
