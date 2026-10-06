from django.core.exceptions import ValidationError
from django.urls import reverse

from core.testing import PASSWORD, CompanyTestCase

from .models import Role, User


class TeamManagementTests(CompanyTestCase):
    def new_user_data(self, **over):
        return {
            "username": "newbie", "first_name": "New", "last_name": "Hire", "email": "",
            "phone": "", "role": Role.STAFF, "supervisor": self.sup_a.pk, "is_active": "on",
            "password1": "Sturdy-Pass-2026", "password2": "Sturdy-Pass-2026", **over,
        }

    def test_only_manager_reaches_team_pages(self):
        for user in (self.sup_a, self.staff_a1, self.secretary):
            self.login(user)
            for url in (reverse("accounts:team"), reverse("accounts:user_create"),
                        reverse("accounts:user_edit", args=[self.staff_a1.pk])):
                self.assertEqual(self.client.get(url).status_code, 403, f"{user.username} {url}")

    def test_manager_creates_user_with_hashed_password(self):
        self.login(self.manager)
        self.assertEqual(self.client.post(reverse("accounts:user_create"), self.new_user_data()).status_code, 302)
        user = User.objects.get(username="newbie")
        self.assertEqual((user.role, user.supervisor), (Role.STAFF, self.sup_a))
        self.assertTrue(user.check_password("Sturdy-Pass-2026"))
        self.assertNotIn("Sturdy", user.password)

    def test_weak_or_mismatched_passwords_are_rejected(self):
        self.login(self.manager)
        for pw1, pw2 in (("short", "short"), ("Sturdy-Pass-2026", "different-pass-2026"), ("", "")):
            self.client.post(reverse("accounts:user_create"), self.new_user_data(password1=pw1, password2=pw2))
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_only_staff_can_have_a_supervisor(self):
        self.login(self.manager)
        self.client.post(reverse("accounts:user_create"), self.new_user_data(role=Role.SECRETARY))
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_model_rejects_supervisor_on_non_staff(self):
        user = User(username="x", role=Role.SECRETARY, supervisor=self.sup_a)
        with self.assertRaises(ValidationError):
            user.full_clean(exclude=["password"])

    def test_manager_edit_keeps_password_when_blank(self):
        self.login(self.manager)
        url = reverse("accounts:user_edit", args=[self.staff_a1.pk])
        data = self.new_user_data(username="staffa1", password1="", password2="", first_name="Renamed")
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.staff_a1.refresh_from_db()
        self.assertEqual(self.staff_a1.first_name, "Renamed")
        self.assertTrue(self.staff_a1.check_password(PASSWORD))

    def test_manager_cannot_demote_or_disable_self(self):
        self.login(self.manager)
        url = reverse("accounts:user_edit", args=[self.manager.pk])
        data = self.new_user_data(username="manager", role=Role.STAFF, supervisor="", password1="", password2="")
        data.pop("is_active")  # an unticked box would normally disable the account
        self.client.post(url, data)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.role, Role.MANAGER)
        self.assertTrue(self.manager.is_active)

    def test_createsuperuser_becomes_manager(self):
        admin = User.objects.create_superuser("boss", "b@example.com", "Another-Pass-2026")
        self.assertEqual(admin.role, Role.MANAGER)


class ProfileAndAuthTests(CompanyTestCase):
    def test_login_and_logout_flow(self):
        r = self.client.post(reverse("accounts:login"), {"username": "staffa1", "password": PASSWORD})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)  # logout is POST-only
        self.client.post(reverse("accounts:logout"))
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 302)

    def test_bad_password_does_not_log_in(self):
        r = self.client.post(reverse("accounts:login"), {"username": "staffa1", "password": "nope"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 302)

    def test_user_can_update_own_details_but_not_role(self):
        self.login(self.staff_a1)
        self.client.post(reverse("accounts:profile"), {
            "first_name": "Pete", "last_name": "O", "email": "p@example.com", "phone": "0700",
            "role": Role.MANAGER, "supervisor": "",
        })
        self.staff_a1.refresh_from_db()
        self.assertEqual(self.staff_a1.first_name, "Pete")
        self.assertEqual(self.staff_a1.role, Role.STAFF)
        self.assertEqual(self.staff_a1.supervisor, self.sup_a)
