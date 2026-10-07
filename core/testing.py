"""Shared test fixtures: one company with every role."""
from django.test import TestCase

from accounts.models import Role, User

PASSWORD = "Tr1cky-Test-Pass!"


class CompanyTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        def make(username, role, supervisor=None):
            return User.objects.create_user(
                username=username, password=PASSWORD, role=role, supervisor=supervisor,
                first_name=username.title(),
            )

        cls.manager = make("manager", Role.MANAGER)
        cls.sup_a = make("supa", Role.SUPERVISOR)
        cls.sup_b = make("supb", Role.SUPERVISOR)
        cls.staff_a1 = make("staffa1", Role.STAFF, cls.sup_a)
        cls.staff_a2 = make("staffa2", Role.STAFF, cls.sup_a)
        cls.staff_b1 = make("staffb1", Role.STAFF, cls.sup_b)
        cls.secretary = make("secretary", Role.SECRETARY)

    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()  # the per-user email rate limit lives in the cache

    def login(self, user):
        self.client.force_login(user)
        return self.client


class OpsTestCase(CompanyTestCase):
    """CompanyTestCase plus one record of each Secretary-operations type, for access tests."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from datetime import date, timedelta
        from decimal import Decimal

        from django.utils import timezone

        from billing.models import Invoice, InvoiceLine
        from clients import services as client_services
        from clients.models import Client, Feedback, Message
        from core.models import CompanySettings
        from escalations.models import Escalation
        from inventory.models import Category, Item, ItemRequest
        from payroll.models import PayProfile, PayrollRun

        settings = CompanySettings.load()
        settings.company_name, settings.phone, settings.email = "Resilience Security", "0711000000", "office@example.com"
        settings.save()
        cls.client_a = client_services.create_client(
            Client(name="Acme Ltd", phone="0712345678", email="acme@example.com", supervisor=cls.sup_a), cls.secretary
        )
        cls.client_b = client_services.create_client(
            Client(name="Beta Stores", phone="0722345678", email="beta@example.com", supervisor=cls.sup_b), cls.secretary
        )
        cls.issue_a = client_services.create_issue(cls.client_a, "Gate light broken", "Light at gate B", "normal", cls.secretary)
        cls.issue_b = client_services.create_issue(cls.client_b, "Late guard", "Guard late twice", "high", cls.secretary)
        cls.feedback = Feedback.objects.create(client=cls.client_a, kind="complaint", channel="phone", subject="Noise",
                                               body="Guards too loud at night", recorded_by=cls.secretary)
        cls.message = Message.objects.create(client=cls.client_a, subject="Holiday schedule", body="Hello", created_by=cls.secretary)
        cls.invoice = Invoice.objects.create(client=cls.client_a, invoice_date=date(2026, 3, 1), due_date=date(2026, 3, 15),
                                             created_by=cls.secretary, subtotal=Decimal("1000"), total=Decimal("1000"))
        InvoiceLine.objects.create(invoice=cls.invoice, description="Guarding March", quantity=1, unit_price=1000, amount=1000)
        cls.category = Category.objects.get_or_create(name="Torches")[0]
        cls.item = Item.objects.create(code="ITM-T001", name="Torch", category=cls.category, returnable=True, qty_available=5)
        cls.keep_item = Item.objects.create(code="ITM-T002", name="Boots", category=cls.category, returnable=False, qty_available=5)
        cls.req_a1 = ItemRequest.objects.create(requester=cls.staff_a1, requester_role="staff", item=cls.item,
                                                qty_requested=1, reason="Mine broke")
        PayProfile.objects.create(user=cls.staff_a1, basic_salary=Decimal("15000"))
        cls.payroll_run = PayrollRun.objects.create(period=date(2026, 2, 1), created_by=cls.secretary)
        cls.escalation = Escalation.objects.create(kind="other", subject="Need advice", note="Please advise", raised_by=cls.secretary)
        cls.today = timezone.localdate()  # the company's date (Nairobi), not the server's
        cls.later = cls.today + timedelta(days=7)
