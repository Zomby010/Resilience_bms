import shutil
import tempfile
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Attachment, AuditLog
from core.testing import CompanyTestCase
from core.workflow import TransitionError
from notifications.models import Notification
from tracking.models import Site, TrackingProfile

from . import services
from .models import Incident, IncidentNote

S = Incident.Status
MEDIA = tempfile.mkdtemp(prefix="incident-test-media-")
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@override_settings(MEDIA_ROOT=MEDIA)
class IncidentTests(CompanyTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.site_a = Site.objects.create(name="Kondele Site", latitude=-0.08, longitude=34.77, supervisor=cls.sup_a)
        cls.site_b = Site.objects.create(name="Milimani Site", latitude=-0.10, longitude=34.75, supervisor=cls.sup_b)
        cls.closed_site = Site.objects.create(name="Old Site", latitude=-0.11, longitude=34.74, is_active=False)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def report(self, user, site=None, severity="medium", photos=(), **extra):
        inc = Incident(site=site or self.site_a, occurred_at=timezone.now() - timedelta(hours=1), kind="theft",
                       severity=severity, what_happened="Torch stolen from the gate hut", **extra)
        return services.create_incident(inc, user, photos)

    def form_data(self, **extra):
        data = {
            "site": self.site_a.pk, "occurred_at": (timezone.localtime() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
            "kind": "break_in", "severity": "high", "what_happened": "Window broken at night", "who_involved": "",
            "action_taken": "Called the supervisor",
        }
        data.update(extra)
        return data

    # --- reporting ------------------------------------------------------------

    def test_numbering(self):
        inc = self.report(self.staff_a1)
        self.assertEqual(inc.number, f"INC-{inc.pk:04d}")
        self.assertEqual(Incident().number, "INC-new")
        self.assertEqual(inc.status, S.REPORTED)
        self.assertTrue(IncidentNote.objects.filter(incident=inc, status_to=S.REPORTED).exists())
        self.assertTrue(AuditLog.objects.filter(action="incident.reported", entity_id=str(inc.pk)).exists())

    def test_ob_number_required_when_police_told(self):
        with self.assertRaises(ValidationError):
            self.report(self.staff_a1, police_reported=True, police_ob_number="  ")
        self.login(self.staff_a1)
        r = self.client.post(reverse("incidents:create"), self.form_data(police_reported="on"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("Write the police OB number.", r.content.decode())
        self.assertFalse(Incident.objects.exists())
        r = self.client.post(reverse("incidents:create"), self.form_data(police_reported="on", police_ob_number="OB 12/08/2026"))
        inc = Incident.objects.get()
        self.assertRedirects(r, inc.get_absolute_url())
        self.assertEqual(inc.police_ob_number, "OB 12/08/2026")
        self.assertEqual(inc.reported_by, self.staff_a1)

    def test_future_time_and_inactive_site_refused(self):
        self.login(self.staff_a1)
        later = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        self.assertEqual(self.client.post(reverse("incidents:create"), self.form_data(occurred_at=later)).status_code, 200)
        self.assertEqual(self.client.post(reverse("incidents:create"), self.form_data(site=self.closed_site.pk)).status_code, 200)
        self.assertFalse(Incident.objects.exists())

    def test_form_defaults_to_my_site_and_every_role_can_report(self):
        TrackingProfile.objects.create(user=self.staff_b1, site=self.site_b)
        self.login(self.staff_b1)
        r = self.client.get(reverse("incidents:create"))
        self.assertEqual(r.context["form"].initial["site"], self.site_b.pk)
        for user in (self.sup_a, self.secretary, self.manager):
            self.login(user)
            self.assertEqual(self.client.get(reverse("incidents:create")).status_code, 200)

    def test_create_notifies_supervisors_and_secretary(self):
        inc = self.report(self.staff_a1, site=self.site_b)
        told = set(Notification.objects.filter(kind="incident.new").values_list("recipient__username", flat=True))
        self.assertEqual(told, {"supa", "supb", "secretary"})  # no manager for medium, never the reporter
        self.assertEqual(Notification.objects.get(recipient=self.sup_a).entity_id, str(inc.pk))

    def test_critical_also_goes_to_manager_high_priority(self):
        self.report(self.staff_a1, severity="critical")
        n = Notification.objects.get(recipient=self.manager, kind="incident.new")
        self.assertEqual(n.priority, Notification.Priority.HIGH)
        self.assertFalse(Notification.objects.filter(recipient=self.staff_a1).exists())
        self.assertEqual(Notification.objects.filter(recipient=self.sup_a).count(), 1)  # reporter's and site's supervisor once

    def test_reporter_is_not_told_about_own_report(self):
        self.report(self.manager, severity="high")
        self.assertFalse(Notification.objects.filter(recipient=self.manager).exists())

    # --- visibility -----------------------------------------------------------

    def test_visibility(self):
        inc = self.report(self.staff_a1, site=self.site_a)
        url = inc.get_absolute_url()
        for user, code in ((self.staff_a1, 200), (self.staff_a2, 404), (self.sup_a, 200), (self.sup_b, 404),
                           (self.secretary, 200), (self.manager, 200)):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, code, user)
            self.assertEqual(self.client.get(reverse("incidents:print", args=[inc.pk])).status_code, code, user)
        self.assertEqual(Incident.objects.visible_to(self.staff_a2).count(), 0)
        self.assertEqual(Incident.objects.visible_to(self.secretary).count(), 1)

    def test_site_supervisor_sees_incidents_at_their_site(self):
        inc = self.report(self.staff_a1, site=self.site_b)  # sup_b looks after this site
        self.assertIn(inc, Incident.objects.visible_to(self.sup_b))
        self.assertIn(inc, Incident.objects.visible_to(self.sup_a))
        self.assertNotIn(self.report(self.staff_b1, site=self.site_b), Incident.objects.visible_to(self.sup_a))

    def test_photos_protected(self):
        photo = SimpleUploadedFile("gate.png", PNG, content_type="image/png")
        inc = self.report(self.staff_a1, photos=[photo])
        att = Attachment.objects.get(object_id=inc.pk, content_type__model="incident")
        url = reverse("core:file", args=[att.pk])
        self.login(self.staff_a2)
        self.assertIn(self.client.get(url).status_code, (403, 404))
        self.login(self.sup_b)
        self.assertIn(self.client.get(url).status_code, (403, 404))
        self.login(self.staff_a1)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_form_photos_limit_and_type(self):
        self.login(self.staff_a1)
        bad = SimpleUploadedFile("x.png", b"not an image")
        self.assertEqual(self.client.post(reverse("incidents:create"), {**self.form_data(), "photos": [bad]}).status_code, 200)
        many = [SimpleUploadedFile(f"p{i}.png", PNG) for i in range(6)]
        r = self.client.post(reverse("incidents:create"), {**self.form_data(), "photos": many})
        self.assertIn("up to 5 photos", r.content.decode())
        two = [SimpleUploadedFile(f"p{i}.png", PNG) for i in range(2)]
        self.client.post(reverse("incidents:create"), {**self.form_data(), "photos": two})
        inc = Incident.objects.get()
        self.assertEqual(Attachment.objects.filter(object_id=inc.pk, content_type__model="incident").count(), 2)

    # --- actions --------------------------------------------------------------

    def test_review_and_close_flow_is_double_click_safe(self):
        inc = self.report(self.staff_a1)
        self.login(self.sup_a)
        url = reverse("incidents:supervisor_review", args=[inc.pk])
        self.client.post(url, {"body": "Spoke to the guard"})
        self.client.post(url, {"body": "Spoke to the guard"})
        inc.refresh_from_db()
        self.assertEqual(inc.status, S.SUPERVISOR_REVIEWED)
        self.assertEqual(inc.supervisor_reviewed_by, self.sup_a)
        self.assertEqual(inc.notes.filter(status_to=S.SUPERVISOR_REVIEWED).count(), 1)

        self.login(self.manager)
        url = reverse("incidents:manager_review", args=[inc.pk])
        self.client.post(url)
        self.client.post(url)
        inc.refresh_from_db()
        self.assertEqual(inc.status, S.MANAGER_REVIEWED)
        self.assertEqual(AuditLog.objects.filter(action="incident.manager_reviewed").count(), 1)

        self.login(self.secretary)
        url = reverse("incidents:close", args=[inc.pk])
        self.client.post(url, {"body": "Client informed"})
        self.client.post(url, {"body": "Client informed"})
        inc.refresh_from_db()
        self.assertEqual(inc.status, S.CLOSED)
        self.assertEqual(inc.notes.filter(status_to=S.CLOSED).count(), 1)
        self.assertTrue(Notification.objects.filter(recipient=self.staff_a1, kind="incident.closed").exists())
        with self.assertRaises(TransitionError):
            services.add_note(inc, self.staff_a1, "more")

        with self.assertRaises(TransitionError):
            services.reopen(inc, self.manager, " ")
        services.reopen(inc, self.manager, "The client found more damage")
        self.assertEqual(inc.status, S.MANAGER_REVIEWED)
        self.assertIsNone(inc.closed_at)

    def test_manager_can_review_straight_from_reported(self):
        inc = self.report(self.staff_b1)
        services.manager_review(inc, self.manager)
        self.assertEqual(inc.status, S.MANAGER_REVIEWED)
        with self.assertRaises(TransitionError):
            services.supervisor_review(inc, self.sup_b)  # too late for the supervisor step

    def test_only_the_right_supervisor_reviews(self):
        inc = self.report(self.staff_b1, site=self.site_a)  # sup_a: site, sup_b: reporter's supervisor
        with self.assertRaises(TransitionError):
            services.supervisor_review(inc, self.manager)
        own = self.report(self.sup_a, site=self.site_a)
        with self.assertRaises(TransitionError):
            services.supervisor_review(own, self.sup_a)  # not their own report
        services.supervisor_review(inc, self.sup_b)
        self.assertEqual(inc.status, S.SUPERVISOR_REVIEWED)
        other = self.report(self.staff_a1, site=self.site_a)
        self.login(self.sup_b)
        self.assertEqual(self.client.post(reverse("incidents:supervisor_review", args=[other.pk])).status_code, 404)

    def test_wrong_role_gets_403(self):
        inc = self.report(self.staff_a1)
        self.login(self.staff_a1)
        for name in ("supervisor_review", "manager_review", "close", "reopen"):
            self.assertEqual(self.client.post(reverse(f"incidents:{name}", args=[inc.pk])).status_code, 403, name)
        self.login(self.sup_a)
        for name in ("manager_review", "close", "reopen"):
            self.assertEqual(self.client.post(reverse(f"incidents:{name}", args=[inc.pk])).status_code, 403, name)
        self.login(self.secretary)
        self.assertEqual(self.client.post(reverse("incidents:manager_review", args=[inc.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("incidents:reopen", args=[inc.pk])).status_code, 403)
        inc.refresh_from_db()
        self.assertEqual(inc.status, S.REPORTED)

    def test_notes(self):
        inc = self.report(self.staff_a1)
        self.login(self.sup_a)
        self.client.post(reverse("incidents:note", args=[inc.pk]), {"body": "On my way"})
        self.assertTrue(inc.notes.filter(author=self.sup_a, body="On my way").exists())
        self.login(self.staff_a2)
        self.assertEqual(self.client.post(reverse("incidents:note", args=[inc.pk]), {"body": "x"}).status_code, 404)
        self.login(self.staff_a1)
        page = self.client.get(reverse("incidents:detail", args=[inc.pk])).content.decode()
        self.assertIn("On my way", page)
        self.assertNotIn("I have reviewed this", page)

    # --- list, filters and CSV ------------------------------------------------

    def test_list_filters_and_counts(self):
        a = self.report(self.staff_a1, severity="critical")
        b = self.report(self.staff_b1, site=self.site_b)
        services.close(b, self.secretary)
        self.login(self.manager)
        r = self.client.get(reverse("incidents:list"))
        self.assertEqual(len(r.context["incidents"]), 2)
        chips = {v: n for v, _, n in r.context["chips"]}
        self.assertEqual((chips[""], chips["reported"], chips["closed"]), (2, 1, 1))
        self.assertEqual(list(self.client.get(reverse("incidents:list") + "?severity=critical").context["incidents"]), [a])
        self.assertEqual(list(self.client.get(reverse("incidents:list") + "?status=closed").context["incidents"]), [b])
        self.assertEqual(list(self.client.get(reverse("incidents:list") + f"?site={self.site_b.pk}").context["incidents"]), [b])
        self.assertEqual(list(self.client.get(reverse("incidents:list") + f"?q={a.number}").context["incidents"]), [a])
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        self.assertEqual(len(self.client.get(reverse("incidents:list") + f"?from={tomorrow}").context["incidents"]), 0)
        self.login(self.staff_a2)
        self.assertEqual(len(self.client.get(reverse("incidents:list")).context["incidents"]), 0)

    def test_csv_office_only_and_injection_guarded(self):
        inc = Incident(site=self.site_a, occurred_at=timezone.now(), kind="other", severity="low",
                       what_happened="=HYPERLINK(\"http://evil\")")
        services.create_incident(inc, self.staff_a1)
        self.login(self.staff_a1)
        self.assertEqual(self.client.get(reverse("incidents:list") + "?export=csv").status_code, 403)
        self.login(self.sup_a)
        self.assertEqual(self.client.get(reverse("incidents:list") + "?export=csv").status_code, 403)
        self.login(self.secretary)
        r = self.client.get(reverse("incidents:list") + "?export=csv")
        self.assertEqual(r["Content-Type"], "text/csv")
        body = r.content.decode()
        self.assertIn(inc.number, body)
        self.assertIn("'=HYPERLINK", body)

    def test_dashboard_helpers(self):
        self.report(self.staff_a1, severity="high")
        done = self.report(self.staff_a1, severity="critical")
        self.report(self.staff_a1, severity="low")
        self.assertEqual(services.open_serious_count(), 2)
        services.close(done, self.manager)
        self.assertEqual(services.open_serious_count(), 1)
        self.assertEqual(len(services.recent_for_site(self.site_a, 2)), 2)
        self.assertEqual(services.recent_for_site(self.site_b), [])

    def test_nav_links_for_every_role(self):
        for user, label in ((self.staff_a1, "My incidents"), (self.sup_a, "Incidents"), (self.secretary, "Incidents")):
            self.login(user)
            page = self.client.get(reverse("incidents:list")).content.decode()
            self.assertIn("Report an incident", page)
            self.assertIn(label, page)
