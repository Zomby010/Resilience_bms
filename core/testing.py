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

    def login(self, user):
        self.client.force_login(user)
        return self.client
