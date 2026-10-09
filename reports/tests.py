from django.urls import reverse

from accounts.models import Role
from core.testing import CompanyTestCase

from .models import Report, Status


class ReportVisibilityTests(CompanyTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.r_a1 = Report.objects.create(author=cls.staff_a1, title="A1 report", body="x")
        cls.r_a2 = Report.objects.create(author=cls.staff_a2, title="A2 report", body="x")
        cls.r_b1 = Report.objects.create(author=cls.staff_b1, title="B1 report", body="x")
        cls.r_supa = Report.objects.create(author=cls.sup_a, title="SupA upward", body="x")

    def ids(self, user):
        return set(Report.objects.visible_to(user).values_list("pk", flat=True))

    def test_staff_sees_only_own(self):
        self.assertEqual(self.ids(self.staff_a1), {self.r_a1.pk})

    def test_supervisor_sees_own_and_team_only(self):
        self.assertEqual(self.ids(self.sup_a), {self.r_a1.pk, self.r_a2.pk, self.r_supa.pk})

    def test_manager_sees_everything(self):
        self.assertEqual(len(self.ids(self.manager)), 4)

    def test_secretary_sees_only_own(self):
        self.assertEqual(self.ids(self.secretary), set())
        own = Report.objects.create(author=self.secretary, title="Office", body="x")
        self.assertEqual(self.ids(self.secretary), {own.pk})

    def test_detail_of_out_of_scope_report_is_404(self):
        self.login(self.staff_a1)
        self.assertEqual(self.client.get(self.r_a2.get_absolute_url()).status_code, 404)
        self.login(self.sup_a)
        self.assertEqual(self.client.get(self.r_b1.get_absolute_url()).status_code, 404)

    def test_secretary_cannot_open_staff_reports(self):
        self.login(self.secretary)
        self.assertEqual(self.client.get(reverse("reports:list")).status_code, 200)
        self.assertEqual(self.client.get(self.r_a1.get_absolute_url()).status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("reports:list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_list_only_shows_visible_reports(self):
        self.login(self.sup_a)
        response = self.client.get(reverse("reports:list"))
        titles = {r.title for r in response.context["reports"]}
        self.assertEqual(titles, {"A1 report", "A2 report", "SupA upward"})


class ReportWorkflowTests(CompanyTestCase):
    def setUp(self):
        self.report = Report.objects.create(author=self.staff_a1, title="Night patrol", body="All quiet")

    def post_reply(self, user, report=None, **data):
        self.login(user)
        report = report or self.report
        return self.client.post(reverse("reports:reply", args=[report.pk]), {"body": "Feedback", **data})

    def test_staff_and_secretary_cannot_reply(self):
        self.assertEqual(self.post_reply(self.staff_a2).status_code, 403)
        self.assertEqual(self.post_reply(self.secretary).status_code, 403)
        self.report.refresh_from_db()
        self.assertEqual(self.report.replies.count(), 0)

    def test_author_cannot_reply_to_own_report(self):
        self.assertEqual(self.post_reply(self.staff_a1).status_code, 403)

    def test_own_supervisor_reply_marks_reviewed(self):
        self.assertEqual(self.post_reply(self.sup_a).status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Status.REVIEWED)
        self.assertEqual(self.report.reviewed_by, self.sup_a)
        self.assertIsNotNone(self.report.reviewed_at)
        self.assertEqual(self.report.replies.get().author, self.sup_a)

    def test_other_teams_supervisor_cannot_reply(self):
        self.assertEqual(self.post_reply(self.sup_b).status_code, 404)
        self.assertEqual(self.report.replies.count(), 0)

    def test_manager_reply_can_complete(self):
        self.post_reply(self.manager, complete="on")
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Status.COMPLETED)
        self.assertEqual(self.report.completed_by, self.manager)

    def test_manager_reply_without_complete_only_reviews(self):
        self.post_reply(self.manager)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Status.REVIEWED)

    def test_supervisor_can_resolve_own_team_report(self):
        self.post_reply(self.sup_a, complete="on")
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Status.COMPLETED)
        self.assertEqual(self.report.completed_by, self.sup_a)

    def test_other_supervisor_cannot_resolve(self):
        self.assertEqual(self.post_reply(self.sup_b, complete="on").status_code, 404)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Status.PENDING)

    def test_manager_replies_to_supervisor_report(self):
        upward = Report.objects.create(author=self.sup_a, title="Consolidated", body="x")
        self.assertEqual(self.post_reply(self.manager, report=upward, complete="on").status_code, 302)
        upward.refresh_from_db()
        self.assertEqual(upward.status, Status.COMPLETED)

    def test_empty_reply_is_rejected(self):
        self.login(self.sup_a)
        self.client.post(reverse("reports:reply", args=[self.report.pk]), {"body": "  "})
        self.assertEqual(self.report.replies.count(), 0)

    def test_reply_endpoint_rejects_get(self):
        self.login(self.sup_a)
        self.assertEqual(self.client.get(reverse("reports:reply", args=[self.report.pk])).status_code, 405)


class ReportSubmitEditTests(CompanyTestCase):
    def test_staff_and_supervisor_can_submit(self):
        for user in (self.staff_a1, self.sup_a):
            self.login(user)
            response = self.client.post(reverse("reports:create"), {"title": "T", "body": "Body"})
            self.assertEqual(response.status_code, 302)
            report = Report.objects.filter(author=user).get()
            self.assertEqual(report.status, Status.PENDING)

    def test_author_is_always_the_logged_in_user(self):
        self.login(self.staff_a1)
        self.client.post(reverse("reports:create"), {"title": "T", "body": "B", "author": self.manager.pk})
        self.assertEqual(Report.objects.get().author, self.staff_a1)

    def test_manager_cannot_submit(self):
        self.login(self.manager)
        self.assertEqual(self.client.get(reverse("reports:create")).status_code, 403)

    def test_secretary_uses_send_to_manager_not_reports(self):
        # One channel from the Secretary to the Manager: Escalations. Old reports stay readable.
        old = Report.objects.create(author=self.secretary, title="Fuel costs", body="Up 10%")
        self.login(self.secretary)
        self.assertEqual(self.client.get(reverse("reports:create")).status_code, 403)
        self.assertEqual(self.client.post(reverse("reports:create"), {"title": "New", "body": "x"}).status_code, 403)
        self.assertFalse(Report.objects.filter(title="New").exists())
        self.assertEqual(self.client.get(reverse("reports:detail", args=[old.pk])).status_code, 200)
        self.assertIn(old, self.client.get(reverse("reports:list")).context["reports"])

    def test_author_can_edit_only_while_pending(self):
        report = Report.objects.create(author=self.staff_a1, title="Old", body="x")
        self.login(self.staff_a1)
        url = reverse("reports:edit", args=[report.pk])
        self.assertEqual(self.client.post(url, {"title": "New", "body": "y"}).status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.title, "New")
        report.add_reply(self.sup_a, "ok")
        self.assertEqual(self.client.post(url, {"title": "Sneaky", "body": "z"}).status_code, 403)
        report.refresh_from_db()
        self.assertEqual(report.title, "New")

    def test_cannot_edit_someone_elses_report(self):
        report = Report.objects.create(author=self.staff_a1, title="Mine", body="x")
        self.login(self.staff_a2)
        self.assertEqual(self.client.post(reverse("reports:edit", args=[report.pk]), {"title": "Hacked", "body": "x"}).status_code, 404)
        self.login(self.manager)
        self.assertEqual(self.client.get(reverse("reports:edit", args=[report.pk])).status_code, 403)


class DashboardTests(CompanyTestCase):
    def test_every_role_dashboard_renders(self):
        Report.objects.create(author=self.staff_a1, title="R", body="x").add_reply(self.manager, "done", complete=True)
        for user in (self.manager, self.sup_a, self.staff_a1, self.secretary):
            self.login(user)
            response = self.client.get(reverse("core:home"))
            self.assertEqual(response.status_code, 200, user.username)

    def test_manager_dashboard_numbers(self):
        r1 = Report.objects.create(author=self.staff_a1, title="1", body="x")
        Report.objects.create(author=self.staff_b1, title="2", body="x")
        r1.add_reply(self.manager, "ok", complete=True)
        self.login(self.manager)
        ctx = self.client.get(reverse("core:home")).context
        self.assertEqual(ctx["open_count"], 1)
        self.assertEqual(ctx["completed_count"], 1)
        self.assertEqual(ctx["active_supervisors"], 2)
        self.assertEqual(ctx["feedback_sent"], 1)
        self.assertEqual(ctx["unchecked_count"], 1)
        self.assertEqual(ctx["resolved_by_manager"], 1)
        self.assertEqual(ctx["resolved_by_supervisors"], 0)
        self.assertNotIn("chart", ctx)
        groups = {g["role"]: g for g in ctx["received_groups"]}
        self.assertEqual(groups["staff"]["total"], 2)
        self.assertEqual(groups["staff"]["resolved"], 1)

    def test_home_requires_login(self):
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 302)

    def test_roles_constant(self):
        self.assertEqual(set(Role.values), {"manager", "supervisor", "staff", "secretary"})
