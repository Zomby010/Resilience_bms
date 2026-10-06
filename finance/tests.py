import csv
import io
from datetime import date
from decimal import Decimal

from django.urls import reverse

from core.testing import CompanyTestCase

from .models import Expense, ExpenseCategory, ExpenseLog


class FinanceAccessTests(CompanyTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cat = ExpenseCategory.objects.create(name="Fuel")
        cls.expense = Expense.objects.create(
            date=date(2026, 1, 5), category=cls.cat, description="Diesel", amount=Decimal("5000"),
            recorded_by=cls.secretary,
        )

    def status(self, user, name, *args, method="get", data=None):
        self.login(user)
        url = reverse(f"finance:{name}", args=args)
        return getattr(self.client, method)(url, data or {}).status_code

    def test_staff_and_supervisors_are_locked_out(self):
        for user in (self.staff_a1, self.sup_a):
            for name, args in (("list", ()), ("history", ()), ("detail", (self.expense.pk,)), ("create", ())):
                self.assertEqual(self.status(user, name, *args), 403, f"{user.username} {name}")

    def test_manager_is_view_only(self):
        self.assertEqual(self.status(self.manager, "list"), 200)
        self.assertEqual(self.status(self.manager, "detail", self.expense.pk), 200)
        self.assertEqual(self.status(self.manager, "history"), 200)
        self.assertEqual(self.status(self.manager, "create"), 403)
        self.assertEqual(self.status(self.manager, "edit", self.expense.pk), 403)
        self.assertEqual(self.status(self.manager, "delete", self.expense.pk, method="post"), 403)
        self.assertEqual(self.status(self.manager, "categories"), 403)
        self.assertTrue(Expense.objects.filter(pk=self.expense.pk).exists())

    def test_manager_cannot_post_a_new_expense(self):
        self.login(self.manager)
        self.client.post(reverse("finance:create"), {
            "date": "2026-02-01", "category": self.cat.pk, "description": "Sneaky", "amount": "10",
        })
        self.assertFalse(Expense.objects.filter(description="Sneaky").exists())

    def test_anonymous_redirected(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("finance:list")).status_code, 302)


class FinanceWorkflowTests(CompanyTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.fuel = ExpenseCategory.objects.create(name="Fuel")
        cls.uniforms = ExpenseCategory.objects.create(name="Uniforms")

    def create(self, **over):
        self.login(self.secretary)
        data = {"date": "2026-03-10", "category": self.fuel.pk, "description": "Diesel",
                "amount": "1500.50", "reference": "R-1", **over}
        return self.client.post(reverse("finance:create"), data)

    def test_create_records_user_and_history(self):
        self.assertEqual(self.create().status_code, 302)
        e = Expense.objects.get()
        self.assertEqual(e.recorded_by, self.secretary)
        self.assertEqual(e.amount, Decimal("1500.50"))
        log = ExpenseLog.objects.get()
        self.assertEqual((log.action, log.expense_number, log.by), ("created", e.pk, self.secretary))

    def test_rejects_zero_negative_and_missing_amounts(self):
        for bad in ("0", "-5", ""):
            self.create(amount=bad)
        self.assertEqual(Expense.objects.count(), 0)

    def test_edit_logs_before_and_after(self):
        self.create()
        e = Expense.objects.get()
        self.client.post(reverse("finance:edit", args=[e.pk]), {
            "date": "2026-03-10", "category": self.uniforms.pk, "description": "Boots",
            "amount": "999", "reference": "",
        })
        e.refresh_from_db()
        self.assertEqual(e.description, "Boots")
        entry = ExpenseLog.objects.filter(action="updated").get()
        self.assertIn("Diesel", entry.details)
        self.assertIn("Boots", entry.details)

    def test_delete_removes_expense_but_keeps_history(self):
        self.create()
        e = Expense.objects.get()
        self.client.post(reverse("finance:delete", args=[e.pk]))
        self.assertFalse(Expense.objects.exists())
        self.assertEqual(ExpenseLog.objects.filter(action="deleted", expense_number=e.pk).count(), 1)
        self.assertEqual(ExpenseLog.objects.count(), 2)  # created + deleted

    def test_search_filter_and_total(self):
        self.create(description="Diesel", amount="1000")
        self.create(description="Boots", category=self.uniforms.pk, amount="250.25", date="2026-04-01")
        self.login(self.manager)
        url = reverse("finance:list")
        r = self.client.get(url, {"q": "boots"})
        self.assertEqual(r.context["paginator"].count, 1)
        self.assertEqual(r.context["total"], Decimal("250.25"))
        r = self.client.get(url, {"category": self.fuel.pk})
        self.assertEqual(r.context["paginator"].count, 1)
        r = self.client.get(url, {"from": "2026-04-01"})
        self.assertEqual(r.context["paginator"].count, 1)
        r = self.client.get(url)
        self.assertEqual(r.context["total"], Decimal("1250.25"))

    def test_csv_export_and_formula_injection_guard(self):
        self.create(description="=HYPERLINK(\"http://evil\")", amount="10")
        self.login(self.manager)
        r = self.client.get(reverse("finance:list"), {"export": "csv"})
        self.assertEqual(r["Content-Type"], "text/csv")
        rows = list(csv.reader(io.StringIO(r.content.decode())))
        self.assertEqual(rows[0][0], "Date")
        self.assertTrue(rows[1][2].startswith("'="))

    def test_category_names_are_unique_case_insensitive(self):
        self.login(self.secretary)
        self.client.post(reverse("finance:categories"), {"name": "fuel"})
        self.assertEqual(ExpenseCategory.objects.filter(name__iexact="fuel").count(), 1)
        self.client.post(reverse("finance:categories"), {"name": "Airtime"})
        self.assertTrue(ExpenseCategory.objects.filter(name="Airtime").exists())
