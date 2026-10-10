import io
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.models import AuditLog, CompanySettings
from core.testing import CompanyTestCase

from . import services
from .models import LeaveRequest, LeaveType, SickLeave, SickNote

S = LeaveRequest.Status
SICK = SickLeave.Status
MEDIA = tempfile.mkdtemp(prefix="leave-test-media-")


def jpeg_with_gps():
    img = Image.new("RGB", (20, 20), "red")
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make
    exif[0x8825] = {1: "S", 2: (1.0, 5.0, 0.0)}  # GPS block
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif)
    return out.getvalue()


PDF = b"%PDF-1.4\n%fake sick sheet\n"


class LeaveBase(CompanyTestCase):
    def setUp(self):
        super().setUp()
        self.annual = LeaveType.objects.get(code="annual")
        self.sick_type = LeaveType.objects.get(code="sick")
        self.year = timezone.localdate().year
        # A Monday well inside the year, so working-day counts are predictable (Mon to Sat by default).
        d = date(self.year, 3, 1)
        self.monday = d + timedelta(days=(7 - d.weekday()) % 7)


class LeaveTypesTests(LeaveBase):
    def test_kenyan_types_are_seeded(self):
        codes = set(LeaveType.objects.values_list("code", flat=True))
        self.assertTrue({"annual", "sick", "maternity", "paternity", "pre_adoptive", "compassionate", "unpaid"} <= codes)
        self.assertEqual(self.annual.days_per_year, 21)

    def test_only_four_types_can_be_asked_for(self):
        # Frank's rule (LEAVE-02): the others are switched off, never deleted, so old requests keep their type.
        from .forms import LeaveRequestForm

        offered = set(LeaveRequestForm(user=self.staff_a1).fields["leave_type"].queryset.values_list("code", flat=True))
        self.assertEqual(offered, {"annual", "maternity", "paternity", "compassionate"})
        self.assertEqual(LeaveType.objects.filter(is_active=False).count(), 3)

    def test_working_days_skip_sunday(self):
        # Monday to the next Monday = 8 calendar days, 7 working days (Sunday off).
        days = services.count_days(self.annual, self.staff_a1, self.monday, self.monday + timedelta(days=7))
        self.assertEqual(days, Decimal(7))

    def test_plain_words_balance(self):
        b = services.balance(self.staff_a1, self.annual, self.year)
        self.assertEqual(services.plain_balance(self.annual, b), "You have 21 days of annual leave left this year. 21 allowed, 0 taken, none waiting.")


class LeaveRequestTests(LeaveBase):
    def ask(self, person, entered_by=None, start=None, days=3):
        start = start or self.monday
        return services.ask_for_leave(person, self.annual, start, start + timedelta(days=days - 1), "Family", entered_by or person)

    def test_staff_request_goes_to_the_manager_and_supervisor_is_told(self):
        # Frank's rule (LEAVE-04, Q2): the Manager decides; the supervisor is told so they can plan cover.
        req = self.ask(self.staff_a1)
        self.assertEqual(req.status, S.WAITING)
        self.assertIsNone(req.approver)
        self.assertTrue(self.manager.notifications.filter(kind="leave.request").exists())
        self.assertTrue(self.sup_a.notifications.filter(kind="leave.fyi").exists())
        self.assertFalse(self.sup_a.notifications.filter(kind="leave.request").exists())
        self.assertFalse(self.sup_b.notifications.exists())

    def test_supervisor_and_secretary_requests_go_to_manager(self):
        for person in (self.sup_a, self.secretary):
            req = self.ask(person)
            self.assertIsNone(req.approver)
        self.assertEqual(self.manager.notifications.filter(kind="leave.request").count(), 2)

    def test_only_the_manager_decides(self):
        req = self.ask(self.staff_a1)
        for user in (self.sup_a, self.sup_b, self.staff_a2, self.secretary):
            self.assertFalse(services.can_decide(user, req))
            with self.assertRaises(ValidationError):
                services.decide(req, user, True)
        self.assertTrue(services.can_decide(self.manager, req))
        services.decide(req, self.manager, True)
        req.refresh_from_db()
        self.assertEqual((req.status, req.decided_by, req.days_given), (S.APPROVED, self.manager, Decimal(3)))
        self.assertTrue(self.staff_a1.notifications.filter(kind="leave.decided").exists())
        self.assertEqual(self.sup_a.notifications.filter(kind="leave.fyi").count(), 2)  # asked, then decided

    def test_manager_types_the_days_given(self):
        # LEAVE-03: 11 working days asked, 5 given. The person is told the days and dates; "On leave" follows the 5.
        req = self.ask(self.staff_a1, days=12)  # Monday to the second Friday: 11 working days (Sunday off)
        self.assertEqual(req.days, Decimal(11))
        services.decide(req, self.manager, True, days_given=Decimal(5))
        req.refresh_from_db()
        self.assertEqual(req.days_given, Decimal(5))
        self.assertEqual(req.last_day_given, self.monday + timedelta(days=4))
        note = self.staff_a1.notifications.get(kind="leave.decided")
        self.assertTrue(note.title.startswith("Approved: 5 days, "), note.title)
        self.assertEqual(services.away_on(self.monday + timedelta(days=4)), {self.staff_a1.pk: "on_leave"})
        self.assertEqual(services.away_on(self.monday + timedelta(days=5)), {})
        with self.assertRaises(ValidationError):
            services.decide(self.ask(self.staff_a1, start=self.monday + timedelta(days=21)), self.manager, True, days_given=0)

    def test_working_days_given_skip_days_off(self):
        # 7 working days from a Monday (Mon to Sat by default) ends on the next Monday.
        self.assertEqual(services.last_day_for(self.annual, self.staff_a1, self.monday, 7), self.monday + timedelta(days=7))
        maternity = LeaveType.objects.get(code="maternity")
        self.assertEqual(services.last_day_for(maternity, self.staff_a1, self.monday, 90), self.monday + timedelta(days=89))

    def test_legal_minimum_is_a_quiet_warning(self):
        self.assertEqual(services.below_minimum(self.annual, 10), 21)
        self.assertIsNone(services.below_minimum(self.annual, 21))
        self.assertIsNone(services.below_minimum(LeaveType.objects.get(code="compassionate"), 1))

    def test_saying_no_needs_a_reason(self):
        req = self.ask(self.staff_a1)
        with self.assertRaises(ValidationError):
            services.decide(req, self.manager, False, "")
        services.decide(req, self.manager, False, "Two guards already off that week")
        self.assertEqual(LeaveRequest.objects.get().status, S.REJECTED)

    def test_double_click_does_not_decide_twice(self):
        req = self.ask(self.staff_a1)
        services.decide(req, self.manager, True)
        stale = LeaveRequest.objects.get(pk=req.pk)
        stale.status = S.WAITING
        with self.assertRaises(Exception):
            services.decide(stale, self.manager, False, "no")
        self.assertEqual(LeaveRequest.objects.get().status, S.APPROVED)

    def test_supervisor_entering_for_team_still_goes_to_the_manager(self):
        req = self.ask(self.staff_a1, entered_by=self.sup_a)
        self.assertEqual(req.status, S.WAITING)
        self.assertEqual(req.entered_by, self.sup_a)

    def test_manager_entering_is_approved_at_once(self):
        req = self.ask(self.staff_a1, entered_by=self.manager)
        self.assertEqual((req.status, req.days_given), (S.APPROVED, Decimal(3)))

    def test_secretary_entering_on_behalf_still_needs_approval(self):
        req = self.ask(self.staff_a1, entered_by=self.secretary)
        self.assertEqual(req.status, S.WAITING)
        self.assertTrue(self.staff_a1.notifications.filter(title__icontains="on your behalf").exists())

    def test_cannot_enter_for_someone_outside_scope(self):
        with self.assertRaises(ValidationError):
            self.ask(self.staff_b1, entered_by=self.sup_a)
        with self.assertRaises(ValidationError):
            self.ask(self.staff_a2, entered_by=self.staff_a1)

    def test_overlap_is_refused(self):
        self.ask(self.staff_a1)
        with self.assertRaises(ValidationError):
            self.ask(self.staff_a1, start=self.monday + timedelta(days=1))

    def test_no_balance_blocks_a_request(self):
        # LEAVE-03: the guard picks dates only; the Manager decides the days.
        req = self.ask(self.staff_a1, days=30)
        self.assertEqual(req.status, S.WAITING)

    def test_balance_counts_taken_and_waiting(self):
        # Still kept for the Manager's old "leave days per person" page.
        services.decide(self.ask(self.staff_a1, days=3), self.manager, True)
        self.ask(self.staff_a1, start=self.monday + timedelta(days=14), days=2)
        b = services.balance(self.staff_a1, self.annual, self.year)
        self.assertEqual((b["taken"], b["waiting"], b["left"]), (Decimal(3), Decimal(2), Decimal(16)))

    def test_manager_allowance_changes_balance_and_is_audited(self):
        services.set_allowance(self.staff_a1, self.annual, self.year, Decimal(25), self.manager)
        self.assertEqual(services.balance(self.staff_a1, self.annual, self.year)["allowed"], Decimal(25))
        self.assertTrue(AuditLog.objects.filter(action="leave.allowance").exists())

    def test_cancel_rules(self):
        req = self.ask(self.staff_a1, start=timezone.localdate() + timedelta(days=10))
        self.assertFalse(services.can_cancel(self.staff_a2, req))
        services.cancel(req, self.staff_a1)
        self.assertEqual(LeaveRequest.objects.get().status, S.CANCELLED)


class LeavePageTests(LeaveBase):
    def test_my_requests_has_no_balances_or_sick_button(self):
        # LEAVE-01/05: no "My days this year"; Report in sick is its own entry. Sick history stays here.
        today = timezone.localdate()
        services.report_sick(self.staff_a1, today, today, "", self.staff_a1)
        for user in (self.manager, self.sup_a, self.staff_a1, self.secretary):
            self.login(user)
            r = self.client.get(reverse("leave:mine"))
            self.assertContains(r, "My requests")
            for gone in ("My days this year", "left this year", ">Report sick<"):
                self.assertNotContains(r, gone)
        self.login(self.staff_a1)
        self.assertContains(self.client.get(reverse("leave:mine")), f"Sick {today:%d %b}")

    def test_ask_page_has_four_big_buttons_and_no_numbers(self):
        self.login(self.staff_a1)
        page = self.client.get(reverse("leave:ask")).content.decode()
        self.assertEqual(page.count('class="type-btn"'), 4)
        self.assertIn("The Manager will answer", page)
        self.assertNotIn("supervisor will answer", page)
        self.assertNotIn("Sick leave", page)

    def test_ask_form_creates_request(self):
        self.login(self.staff_a1)
        r = self.client.post(reverse("leave:ask"), {"leave_type": self.annual.pk, "start_date": self.monday,
                                                     "end_date": self.monday + timedelta(days=1)})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(LeaveRequest.objects.get().user, self.staff_a1)

    def test_staff_form_cannot_choose_another_person(self):
        self.login(self.staff_a1)
        self.client.post(reverse("leave:ask"), {"leave_type": self.annual.pk, "start_date": self.monday,
                                                "end_date": self.monday, "person": self.staff_a2.pk})
        self.assertEqual(LeaveRequest.objects.get().user, self.staff_a1)

    def test_request_detail_scoping(self):
        req = services.ask_for_leave(self.staff_a1, self.annual, self.monday, self.monday, "", self.staff_a1)
        url = req.get_absolute_url()
        for user, code in ((self.staff_a2, 404), (self.sup_b, 404), (self.sup_a, 200), (self.secretary, 200), (self.manager, 200)):
            self.login(user)
            r = self.client.get(url)
            self.assertEqual(r.status_code, code, user.username)
            if code == 200:
                self.assertNotContains(r, "Days left")
                self.assertEqual('name="days_given"' in r.content.decode(), user == self.manager)

    def test_approve_button(self):
        req = services.ask_for_leave(self.staff_a1, self.annual, self.monday, self.monday + timedelta(days=4), "", self.staff_a1)
        self.login(self.sup_b)
        self.assertEqual(self.client.post(reverse("leave:approve", args=[req.pk])).status_code, 404)
        self.login(self.sup_a)
        self.client.post(reverse("leave:approve", args=[req.pk]))
        self.assertEqual(LeaveRequest.objects.get().status, S.WAITING)  # the supervisor cannot decide
        self.login(self.manager)
        self.client.post(reverse("leave:approve", args=[req.pk]), {"days_given": "abc"})
        self.assertEqual(LeaveRequest.objects.get().status, S.WAITING)
        r = self.client.post(reverse("leave:approve", args=[req.pk]), {"days_given": "2"}, follow=True)
        self.assertContains(r, "legal minimum")
        req.refresh_from_db()
        self.assertEqual((req.status, req.days_given, req.last_day_given), (S.APPROVED, Decimal(2), self.monday + timedelta(days=1)))

    def test_guard_cannot_open_everyones_sick_list(self):
        self.login(self.staff_a1)
        self.assertEqual(self.client.get(reverse("leave:sick_list")).status_code, 403)

    def test_allowances_manager_only(self):
        # Leave days per person are no longer used (Frank's leave rules); only the Manager can still open them.
        self.login(self.staff_a1)
        self.assertEqual(self.client.get(reverse("leave:allowances")).status_code, 403)
        self.login(self.secretary)
        self.assertEqual(self.client.get(reverse("leave:allowances")).status_code, 403)
        self.assertEqual(self.client.get(reverse("leave:allowance_edit", args=[self.staff_a1.pk])).status_code, 403)
        self.login(self.manager)
        r = self.client.post(reverse("leave:allowance_edit", args=[self.staff_a1.pk]),
                             {"year": self.year, **{f"type_{lt.pk}": lt.days_per_year for lt in LeaveType.objects.all()},
                              f"type_{self.annual.pk}": "24"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(services.allowed_days(self.staff_a1, self.annual, self.year), Decimal(24))

    def test_csv_office_only(self):
        services.ask_for_leave(self.staff_a1, self.annual, self.monday, self.monday, "=cmd()", self.staff_a1)
        self.login(self.secretary)
        r = self.client.get(reverse("leave:request_list") + "?export=csv")
        self.assertEqual(r["Content-Type"], "text/csv")
        self.assertIn("'=cmd()", r.content.decode())
        self.login(self.sup_a)
        self.assertNotEqual(self.client.get(reverse("leave:request_list") + "?export=csv").get("Content-Type"), "text/csv")


@override_settings(MEDIA_ROOT=MEDIA)
class SickLeaveTests(LeaveBase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def report(self, person=None, by=None, sheet=None):
        today = timezone.localdate()
        return services.report_sick(person or self.staff_a1, today, today + timedelta(days=2), "", by or person or self.staff_a1, sheet)

    def test_sick_counts_at_once_and_tells_supervisor(self):
        sick = self.report()
        self.assertEqual(sick.status, SICK.CERTIFICATE_NEEDED)
        self.assertEqual(services.away_on(timezone.localdate()), {self.staff_a1.pk: "sick"})
        self.assertTrue(self.sup_a.notifications.filter(kind="sick.reported").exists())

    def test_photo_is_stripped_of_hidden_details(self):
        sheet = SimpleUploadedFile("sheet.jpg", jpeg_with_gps(), content_type="image/jpeg")
        sick = self.report(sheet=sheet)
        note = SickNote.objects.get(sick_leave=sick)
        self.assertTrue(note.file.name.startswith("medical/"))
        with note.file.open("rb") as fh:
            self.assertEqual(dict(Image.open(fh).getexif()), {})
        sick.refresh_from_db()
        self.assertEqual(sick.status, SICK.CERTIFICATE_RECEIVED)

    def test_only_owner_secretary_and_manager_can_open_the_sheet(self):
        sick = self.report(sheet=SimpleUploadedFile("sheet.pdf", PDF, content_type="application/pdf"))
        url = reverse("leave:sheet", args=[sick.notes.get().pk])
        for user, code in ((self.staff_a2, 404), (self.sup_a, 404), (self.sup_b, 404), (self.staff_a1, 200),
                           (self.secretary, 200), (self.manager, 200)):
            self.login(user)
            r = self.client.get(url)
            self.assertEqual(r.status_code, code, user.username)
            if code == 200:
                self.assertEqual(r["Cache-Control"], "private, no-store")
        self.assertEqual(AuditLog.objects.filter(action="sick.sheet_viewed", confidential=True).count(), 3)

    def test_supervisor_sees_dates_but_not_the_sheet_or_note(self):
        today = timezone.localdate()
        sick = services.report_sick(self.staff_a1, today, today, "Hospital visit", self.staff_a1,
                                    SimpleUploadedFile("sheet.pdf", PDF))
        self.login(self.sup_a)
        r = self.client.get(sick.get_absolute_url())
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "sheet.pdf")
        self.assertNotContains(r, "Hospital visit")
        self.assertNotContains(r, reverse("leave:sheet", args=[sick.notes.get().pk]))
        self.login(self.staff_a2)
        self.assertEqual(self.client.get(sick.get_absolute_url()).status_code, 404)

    def test_supervisor_can_report_for_team_but_not_upload_their_sheet(self):
        sick = self.report(by=self.sup_a)
        self.assertEqual(sick.reported_by, self.sup_a)
        with self.assertRaises(ValidationError):
            services.add_sick_note(sick, SimpleUploadedFile("s.pdf", PDF), self.sup_a)
        with self.assertRaises(ValidationError):
            self.report(person=self.staff_b1, by=self.sup_a)

    def test_review_by_office_only(self):
        sick = self.report(sheet=SimpleUploadedFile("s.pdf", PDF))
        with self.assertRaises(ValidationError):
            services.review_sick(sick, self.sup_a, "accept")
        with self.assertRaises(ValidationError):
            services.review_sick(sick, self.secretary, "reject", "")
        services.review_sick(sick, self.secretary, "accept")
        self.assertEqual(SickLeave.objects.get().status, SICK.ACCEPTED)

    def test_reminder_and_keep_period(self):
        settings = CompanySettings.load()
        settings.sick_note_keep_days = 30
        settings.save()
        old = timezone.localdate() - timedelta(days=10)
        sick = services.report_sick(self.staff_a1, old, old, "", self.staff_a1)
        result = services.daily_sick_checks()
        self.assertEqual(result["sick_reminders"], 1)
        self.assertEqual(services.daily_sick_checks()["sick_reminders"], 0)
        note = services.add_sick_note(sick, SimpleUploadedFile("s.pdf", PDF), self.staff_a1)
        SickNote.objects.filter(pk=note.pk).update(uploaded_at=timezone.now() - timedelta(days=31))
        self.assertEqual(services.daily_sick_checks()["sick_sheets_removed"], 1)
        note.refresh_from_db()
        self.assertFalse(note.file)
        self.assertIsNotNone(note.removed_at)
        self.assertTrue(SickLeave.objects.filter(pk=sick.pk).exists())

    def test_wrong_file_type_refused(self):
        self.login(self.staff_a1)
        today = timezone.localdate()
        r = self.client.post(reverse("leave:sick_report"), {"first_day": today, "last_day": today,
                                                            "sheet": SimpleUploadedFile("x.exe", b"MZ....")})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(SickLeave.objects.exists())


class OnLeaveChipTests(LeaveBase):
    def test_people_rows_say_on_leave_until_the_last_day_given(self):
        # LEAVE-06: Team today, Guards today and the day sheet all read these rows.
        from accounts.models import User
        from attendance.services import people_on

        today = timezone.localdate()
        req = services.ask_for_leave(self.staff_a1, self.annual, today, today + timedelta(days=20), "", self.staff_a1)
        services.decide(req, self.manager, True, days_given=1)
        row = people_on(today, User.objects.filter(pk=self.staff_a1.pk))[0]
        self.assertEqual(row["state"], "on_leave")
        self.assertEqual(row["label"], f"On leave until {today.day} {today:%b}")
        tomorrow = people_on(today + timedelta(days=1), User.objects.filter(pk=self.staff_a1.pk))[0]
        self.assertNotEqual(tomorrow["state"], "on_leave")
