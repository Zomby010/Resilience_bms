from datetime import datetime, time, timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from core.testing import CompanyTestCase
from core.workflow import TransitionError
from leave.models import LeaveType
from leave.services import ask_for_leave, report_sick
from tracking.models import Site, TrackingProfile, WorkHours

from . import services
from .models import AttendanceDay, AttendanceRecord

O = AttendanceRecord.Outcome
S = AttendanceRecord.Status
LAT, LNG = -0.0917, 34.7680  # Kisumu
ON_SITE = {"latitude": LAT + 0.0001, "longitude": LNG, "accuracy": 10}       # about 11 m away
FAR_AWAY = {"latitude": LAT + 0.01, "longitude": LNG, "accuracy": 10}        # about 1.1 km away
WEAK = {"latitude": LAT, "longitude": LNG, "accuracy": 300}


def at(day, hh, mm=0):
    return timezone.make_aware(datetime.combine(day, time(hh, mm)))


class AttendanceBase(CompanyTestCase):
    def setUp(self):
        super().setUp()
        self.site = Site.objects.create(name="Kondele Site", latitude=LAT, longitude=LNG, radius_m=30, guards_needed=2,
                                        supervisor=self.sup_a)
        self.site_b = Site.objects.create(name="Milimani Site", latitude=LAT + 0.05, longitude=LNG, radius_m=30)
        for wd in range(7):
            WorkHours.objects.create(site=self.site, weekday=wd, start=time(6), end=time(18))
            WorkHours.objects.create(site=self.site_b, weekday=wd, start=time(18), end=time(6))
        for user in (self.staff_a1, self.staff_a2, self.sup_a):
            TrackingProfile.objects.create(user=user, site=self.site)
        TrackingProfile.objects.create(user=self.staff_b1, site=self.site_b)
        self.day = timezone.localdate()


class SignInTests(AttendanceBase):
    def test_on_time_sign_in_goes_to_supervisor(self):
        rec = services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 5))
        self.assertEqual((rec.outcome, rec.status, rec.supervisor), (O.PRESENT, S.WAITING_SUPERVISOR, self.sup_a))
        self.assertEqual(rec.location_status, "on")
        self.assertEqual(rec.date, self.day)

    def test_late_after_grace_minutes(self):
        rec = services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 40))
        self.assertEqual((rec.outcome, rec.late_minutes), (O.LATE, 40))
        self.assertTrue(self.sup_a.notifications.filter(kind="attendance.late").exists())

    def test_off_location_and_weak_gps_refused(self):
        with self.assertRaisesMessage(ValidationError, "You must be at the site"):
            services.sign_in(self.staff_a1, FAR_AWAY, now=at(self.day, 6, 5))
        with self.assertRaisesMessage(ValidationError, "not accurate enough"):
            services.sign_in(self.staff_a1, WEAK, now=at(self.day, 6, 5))
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_sign_in_window(self):
        with self.assertRaisesMessage(ValidationError, "You can sign in from 05:00"):
            services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 4, 30))
        services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 5, 10))
        with self.assertRaisesMessage(ValidationError, "already recorded"):
            services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 0))

    def test_overnight_shift_counts_for_the_start_day(self):
        night = {"latitude": LAT + 0.05, "longitude": LNG, "accuracy": 10}
        rec = services.sign_in(self.staff_b1, night, now=at(self.day, 2, 0))  # 02:00 belongs to yesterday's 18:00 shift
        self.assertEqual(rec.date, self.day - timedelta(days=1))
        self.assertEqual(rec.outcome, O.LATE)

    def test_supervisor_sign_in_goes_straight_to_manager(self):
        rec = services.sign_in(self.sup_a, ON_SITE, now=at(self.day, 6, 0))
        self.assertEqual(rec.status, S.WAITING_MANAGER)

    def test_office_cannot_sign_in(self):
        with self.assertRaises(ValidationError):
            services.sign_in(self.secretary, ON_SITE, now=at(self.day, 6, 0))

    def test_api_returns_plain_message_and_never_trusts_user_field(self):
        self.login(self.staff_a1)
        # Fix the clock inside the shift: otherwise this test fails when run after 18:00.
        with mock.patch("attendance.services.timezone.now", return_value=at(self.day, 6, 5)):
                r = self.client.post(reverse("attendance:api_sign_in"), {**FAR_AWAY, "user": self.staff_a2.pk},
                                 content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("must be at the site", r.json()["error"])
        self.login(self.secretary)
        self.assertEqual(self.client.post(reverse("attendance:api_sign_in"), ON_SITE,
                                          content_type="application/json").status_code, 403)


class ApprovalTests(AttendanceBase):
    def setUp(self):
        super().setUp()
        self.rec = services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 0))

    def test_only_own_supervisor_or_manager_approves(self):
        with self.assertRaises(TransitionError):
            services.approve(self.rec, self.sup_b)
        services.approve(self.rec, self.sup_a)
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.status, S.WAITING_MANAGER)
        with self.assertRaises(TransitionError):
            services.approve(self.rec, self.sup_a)  # double click

    def test_reject_needs_reason_and_tells_guard(self):
        with self.assertRaises(ValidationError):
            services.reject(self.rec, self.sup_a, "")
        services.reject(self.rec, self.sup_a, "Was not at the gate")
        self.assertTrue(self.staff_a1.notifications.filter(kind="attendance.rejected").exists())

    def test_mark_present_for_team_member(self):
        rec = services.mark(self.staff_a2, self.day, O.PRESENT, "Phone broken", self.sup_a)
        self.assertEqual((rec.method, rec.status), (AttendanceRecord.Method.SUPERVISOR, S.WAITING_MANAGER))
        with self.assertRaises(TransitionError):
            services.mark(self.staff_b1, self.day, O.PRESENT, "x", self.sup_a)
        with self.assertRaises(TransitionError):
            services.mark(self.sup_a, self.day, O.PRESENT, "x", self.sup_a)  # not for yourself

    def test_complete_day_records_absent_leave_and_sick(self):
        annual = LeaveType.objects.get(code="annual")
        ask_for_leave(self.staff_a2, annual, self.day, self.day, "", self.manager)
        report_sick(self.staff_b1, self.day, self.day, "", self.staff_b1)
        services.approve(self.rec, self.sup_a)
        summary = services.complete_day(self.day, self.manager)
        outcomes = dict(AttendanceRecord.objects.filter(date=self.day).values_list("user__username", "outcome"))
        self.assertEqual(outcomes, {"staffa1": O.PRESENT, "staffa2": O.ON_LEAVE, "staffb1": O.SICK, "supa": O.ABSENT})
        self.assertEqual((summary.present, summary.on_leave, summary.sick, summary.absent), (1, 1, 1, 1))
        self.assertFalse(AttendanceRecord.objects.filter(date=self.day).exclude(status=S.COMPLETED).exists())
        with self.assertRaises(TransitionError):
            services.complete_day(self.day, self.manager)
        with self.assertRaises(TransitionError):
            services.mark(self.staff_a2, self.day, O.PRESENT, "x", self.sup_a)

    def test_only_manager_completes_and_reopens(self):
        with self.assertRaises(TransitionError):
            services.complete_day(self.day, self.secretary)
        services.complete_day(self.day, self.manager)
        services.reopen_day(self.day, self.manager)
        self.assertFalse(AttendanceDay.objects.exists())
        self.assertEqual(AttendanceRecord.objects.get(pk=self.rec.pk).status, S.WAITING_MANAGER)


class PageTests(AttendanceBase):
    def test_board_shows_sites_and_counts(self):
        services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 0))
        data = services.board(self.day, now=at(self.day, 9, 0))
        box = next(b for b in data["boxes"] if b["site"] == self.site)
        self.assertEqual([r["person"] for r in box["in"]], [self.staff_a1])
        self.assertEqual({r["person"] for r in box["absent"]}, {self.staff_a2, self.sup_a})
        self.assertTrue(box["short"])

    def test_people_rows_have_no_coordinates(self):
        services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 0))
        self.login(self.sup_a)
        # ATT-03: the supervisor's one "My team ▸ Today" page (the old team-today address redirects here).
        r = self.client.get(reverse("operations:team_today"), follow=True)
        self.assertEqual(r.redirect_chain[-1][0], reverse("attendance:team"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, str(ON_SITE["latitude"]))
        self.assertNotContains(r, "34.768")

    def test_pages_by_role(self):
        cases = [
            ("attendance:mine", {self.staff_a1: 200, self.sup_a: 200, self.secretary: 403, self.manager: 403}),
            ("attendance:team", {self.sup_a: 200, self.staff_a1: 403, self.manager: 403}),
            # Only the Manager completes the day; guards see their days on "My attendance" (Frank's matrix).
            ("attendance:day", {self.manager: 200, self.secretary: 403, self.sup_a: 403, self.staff_a1: 403}),
            ("attendance:records", {self.manager: 200, self.secretary: 200, self.sup_a: 200, self.staff_a1: 403}),
        ]
        for name, expected in cases:
            for user, code in expected.items():
                self.login(user)
                self.assertEqual(self.client.get(reverse(name)).status_code, code, f"{name} {user}")

    def test_records_are_scoped_and_csv_is_office_only(self):
        services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 0))
        services.mark(self.staff_b1, self.day, O.ABSENT, "No show", self.manager)
        self.login(self.sup_a)
        r = self.client.get(reverse("attendance:records"))
        self.assertEqual({rec.user for rec in r.context["records"]}, {self.staff_a1})
        self.assertNotEqual(self.client.get(reverse("attendance:records") + "?export=csv").get("Content-Type"), "text/csv")
        self.login(self.manager)
        r = self.client.get(reverse("attendance:records") + "?export=csv")
        self.assertEqual(r["Content-Type"], "text/csv")

    def test_supervisor_cannot_approve_other_team_through_url(self):
        rec = services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 0))
        self.login(self.sup_b)
        self.assertEqual(self.client.post(reverse("attendance:approve", args=[rec.pk])).status_code, 404)
        self.assertEqual(AttendanceRecord.objects.get().status, S.WAITING_SUPERVISOR)

    def test_manager_dashboard_shows_attendance_first(self):
        self.login(self.manager)
        html = self.client.get(reverse("core:home")).content.decode()
        # DASH-01: the to-do list comes first, then a short "Today's picture" with a link to the full board.
        self.assertLess(html.index('id="todo"'), html.index('id="picture-title"'))
        self.assertIn(reverse("attendance:day"), html)
        self.assertNotIn('class="chart"', html)


class WithoutLocationTests(AttendanceBase):
    """ATT-01 and Q7: sign in without location, with a reason; the server stamps the time."""

    def test_guard_goes_to_supervisor_with_reason(self):
        rec = services.sign_in_without_location(self.staff_a1, "no_signal", now=at(self.day, 6, 20))
        self.assertEqual((rec.method, rec.status, rec.supervisor, rec.manual_reason),
                         ("no_location", S.WAITING_SUPERVISOR, self.sup_a, "no_signal"))
        self.assertEqual(rec.signed_in_at, at(self.day, 6, 20))
        self.assertIsNone(rec.latitude)
        self.assertTrue(self.sup_a.notifications.filter(kind="attendance.no_location").exists())
        from core.todo import todos_for

        todo = [t for t in todos_for(self.sup_a) if t.sender == self.staff_a1][0]
        self.assertIn("No location: No signal", todo.summary)
        self.assertIn("without location", todo.actions[0].confirm)

    def test_supervisor_goes_to_the_manager(self):
        rec = services.sign_in_without_location(self.sup_a, "phone", now=at(self.day, 6, 0))
        self.assertIsNone(rec.supervisor)
        self.assertEqual(rec.get_status_display(), "Waiting for Manager")  # ATT-04: not "Waiting for supervisor"
        self.assertTrue(self.manager.notifications.filter(kind="attendance.no_location").exists())
        self.assertFalse(services.can_approve(self.sup_b, rec))
        from core.todo import todos_for

        self.assertTrue(any(t.sender == self.sup_a and "without location" in t.summary for t in todos_for(self.manager)))
        services.approve(rec, self.manager)
        self.assertEqual(AttendanceRecord.objects.get(pk=rec.pk).status, S.WAITING_MANAGER)

    def test_reason_is_needed_and_same_shift_rules_apply(self):
        with self.assertRaises(ValidationError):
            services.sign_in_without_location(self.staff_a1, "", now=at(self.day, 6, 0))
        with self.assertRaisesMessage(ValidationError, "You can sign in from 05:00"):
            services.sign_in_without_location(self.staff_a1, "other", now=at(self.day, 4, 0))
        services.sign_in_without_location(self.staff_a1, "other", now=at(self.day, 6, 0))
        with self.assertRaisesMessage(ValidationError, "already recorded"):
            services.sign_in_without_location(self.staff_a1, "other", now=at(self.day, 6, 5))
        with self.assertRaises(ValidationError):
            services.sign_in_without_location(self.secretary, "other", now=at(self.day, 6, 0))

    def test_third_in_a_month_is_a_manager_to_do(self):
        from core.todo import todos_for

        first = self.day.replace(day=1)
        for i in range(2):
            AttendanceRecord.objects.create(user=self.staff_a1, date=first + timedelta(days=i), site=self.site, outcome=O.PRESENT,
                                            status=S.COMPLETED, method="no_location", manual_reason="no_signal")
        self.assertFalse(any("times this month" in t.summary for t in todos_for(self.manager)))
        services.sign_in_without_location(self.staff_a1, "wrong_place", now=at(self.day, 6, 0)) if self.day.day > 2 else \
            AttendanceRecord.objects.create(user=self.staff_a1, date=first + timedelta(days=2), site=self.site,
                                            outcome=O.PRESENT, status=S.WAITING_SUPERVISOR, method="no_location")
        todo = [t for t in todos_for(self.manager) if "times this month" in t.summary][0]
        self.assertEqual((todo.summary, todo.actions[0].label), (f"{self.staff_a1} signed in without location 3 times this month", "Check this"))
        self.login(self.manager)
        r = self.client.get(todo.url)
        self.assertEqual(len(r.context["records"]), 3)

    def test_form_view(self):
        self.login(self.staff_a1)
        with mock.patch("attendance.services.timezone.now", return_value=at(self.day, 6, 5)):
            r = self.client.post(reverse("attendance:sign_in_no_location"), {"reason": "phone", "note": "Screen cracked"})
        self.assertRedirects(r, reverse("core:home"), fetch_redirect_response=False)
        rec = AttendanceRecord.objects.get()
        self.assertEqual((rec.method, rec.note, rec.marked_by), ("no_location", "Screen cracked", self.staff_a1))
        self.login(self.secretary)
        self.assertEqual(self.client.post(reverse("attendance:sign_in_no_location"), {"reason": "phone"}).status_code, 403)


class SignOutTests(AttendanceBase):
    """ATT-02 and Q8: sign-out is recorded, never approved, and never filled in."""

    def test_sign_out_with_location_records_time_and_distance(self):
        rec = services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 50))
        services.sign_out(rec, self.staff_a1, FAR_AWAY, now=at(self.day, 18, 5))
        rec.refresh_from_db()
        self.assertEqual((rec.sign_out_method, rec.status), ("gps", S.WAITING_SUPERVISOR))  # nothing to approve
        self.assertGreater(rec.sign_out_distance_m, 1000)
        self.assertIn("In 06:50 · Out 18:05 · 11 h 15 m", rec.in_out)

    def test_sign_out_without_location_needs_a_reason(self):
        rec = services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 0))
        with self.assertRaises(ValidationError):
            services.sign_out(rec, self.staff_a1, reason="", now=at(self.day, 18, 0))
        services.sign_out(rec, self.staff_a1, reason="no_signal", now=at(self.day, 18, 0))
        rec.refresh_from_db()
        self.assertEqual((rec.sign_out_method, rec.sign_out_reason), ("no_location", "no_signal"))
        with self.assertRaises(ValidationError):  # only once
            services.sign_out(rec, self.staff_a1, reason="no_signal", now=at(self.day, 18, 5))

    def test_only_your_own_recent_day(self):
        rec = services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 0))
        with self.assertRaises(ValidationError):
            services.sign_out(rec, self.staff_a2, reason="other", now=at(self.day, 18, 0))
        old = AttendanceRecord.objects.create(user=self.staff_a2, date=self.day - timedelta(days=3), site=self.site,
                                              outcome=O.PRESENT, status=S.COMPLETED, method="gps",
                                              signed_in_at=at(self.day - timedelta(days=3), 6))
        self.assertFalse(services.can_sign_out(self.staff_a2, old))
        self.assertEqual(old.in_out, "In 06:00 · No sign-out")  # never filled in for them

    def test_completing_the_day_does_not_need_sign_out(self):
        services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 0))
        services.complete_day(self.day, self.manager)
        rec = AttendanceRecord.objects.get(user=self.staff_a1)
        self.assertEqual(rec.status, S.COMPLETED)
        self.assertIsNone(rec.signed_out_at)

    def test_pages_show_in_and_out(self):
        rec = services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 50))
        services.sign_out(rec, self.staff_a1, ON_SITE, now=at(self.day, 18, 5))
        for user, name in ((self.staff_a1, "attendance:mine"), (self.sup_a, "attendance:team"),
                           (self.manager, "attendance:day"), (self.manager, "attendance:records")):
            self.login(user)
            self.assertContains(self.client.get(reverse(name)), "In 06:50 · Out 18:05 · 11 h 15 m", msg_prefix=name)

    def test_api_and_form(self):
        rec = services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 0))
        self.login(self.staff_a2)
        self.assertEqual(self.client.post(reverse("attendance:api_sign_out", args=[rec.pk]), ON_SITE,
                                          content_type="application/json").status_code, 404)
        self.login(self.staff_a1)
        r = self.client.post(reverse("attendance:api_sign_out", args=[rec.pk]), ON_SITE, content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("Signed out at", r.json()["message"])
        rec2 = services.sign_in(self.staff_a2, ON_SITE, now=at(self.day, 6, 0))
        self.login(self.staff_a2)
        r = self.client.post(reverse("attendance:sign_out_no_location", args=[rec2.pk]), {"reason": "phone", "next": "mine"})
        self.assertRedirects(r, reverse("attendance:mine"), fetch_redirect_response=False)
        self.assertEqual(AttendanceRecord.objects.get(pk=rec2.pk).sign_out_reason, "phone")


class TodayCardTests(AttendanceBase):
    def test_one_status_card_with_sign_in_and_location(self):
        # ATT-04: "✔ Signed in 06:50 · ⚠ Location is off: turn it on" in one card at the top of Today.
        services.sign_in(self.staff_a1, ON_SITE, now=at(self.day, 6, 50))
        self.login(self.staff_a1)
        page = self.client.get(reverse("core:home")).content.decode()
        card = page[page.index('id="today-status"'):]
        card = card[:card.index('id="location-card"')]
        self.assertIn("✔ Signed in 06:50", card)
        self.assertIn("⚠ Location is off: turn it on", card)
        self.assertEqual(page.count('id="location-card"'), 1)
        self.assertIn("Sign out", page)
