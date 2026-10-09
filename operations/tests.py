import shutil
import tempfile
from datetime import time, timedelta

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Attachment, AuditLog
from core.testing import CompanyTestCase
from incidents.models import Incident
from incidents.services import create_incident
from inventory.models import Category, Item, ItemRequest
from tracking.models import Site, SitePosting, TrackingProfile, WorkHours

from . import services
from .models import OBEntry, SiteVisit

MEDIA = tempfile.mkdtemp(prefix="ops-test-media-")
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class OpsBase(CompanyTestCase):
    def setUp(self):
        super().setUp()
        self.site = Site.objects.create(name="Kondele Site", latitude=-0.09, longitude=34.76, supervisor=self.sup_a)
        self.site_b = Site.objects.create(name="Milimani Site", latitude=-0.1, longitude=34.75, supervisor=self.sup_b)
        WorkHours.objects.create(site=self.site, weekday=0, start=time(6), end=time(18))
        TrackingProfile.objects.create(user=self.staff_a1, site=self.site)
        TrackingProfile.objects.create(user=self.staff_b1, site=self.site_b)


class SiteTests(OpsBase):
    def test_manager_edits_details_others_read_only(self):
        url = reverse("operations:site_edit", args=[self.site.pk])
        for user in (self.sup_a, self.staff_a1, self.secretary):  # the Secretary reads sites (Frank's matrix)
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
            r = self.client.get(self.site.get_absolute_url())
            self.assertEqual(r.status_code, 200)
            self.assertNotContains(r, "Edit details")
        self.login(self.manager)
        r = self.client.post(url, {"name": "Kondele Site", "address": "Off Kibos Road", "supervisor": self.sup_a.pk,
                                   "guards_needed": 3, "instructions": "Check the back gate hourly",
                                   "emergency_contacts": "Kondele Police 0712000000", "is_active": "on"})
        self.assertEqual(r.status_code, 302)
        self.site.refresh_from_db()
        self.assertEqual((self.site.guards_needed, self.site.details_updated_by), (3, self.manager))
        self.assertTrue(AuditLog.objects.filter(action="site.details").exists())
        self.login(self.staff_a1)
        self.assertContains(self.client.get(self.site.get_absolute_url()), "Check the back gate hourly")

    def test_staff_only_see_their_own_site(self):
        self.login(self.staff_a1)
        self.assertEqual(self.client.get(self.site_b.get_absolute_url()).status_code, 404)
        self.login(self.sup_a)
        self.assertEqual(self.client.get(self.site_b.get_absolute_url()).status_code, 404)

    def test_posting_history_follows_site_changes(self):
        profile = TrackingProfile.objects.get(user=self.staff_a1)
        profile.site = self.site_b
        profile.save()
        postings = list(SitePosting.objects.filter(user=self.staff_a1).order_by("started_at", "id"))
        self.assertEqual([p.site for p in postings], [self.site, self.site_b])
        self.assertIsNotNone(postings[0].ended_at)
        self.assertIsNone(postings[1].ended_at)
        profile.last_status = "on"
        profile.save()  # a location update does not start a new posting
        self.assertEqual(SitePosting.objects.filter(user=self.staff_a1).count(), 2)


class OBTests(OpsBase):
    def test_staff_write_only_in_own_site(self):
        services.write_ob(self.site, self.staff_a1, OBEntry.Kind.PATROL, "All fine")
        with self.assertRaises(ValidationError):
            services.write_ob(self.site_b, self.staff_a1, OBEntry.Kind.PATROL, "Sneaky")

    def test_visibility(self):
        mine = services.write_ob(self.site, self.staff_a1, OBEntry.Kind.PATROL, "A")
        other = services.write_ob(self.site_b, self.staff_b1, OBEntry.Kind.PATROL, "B")
        self.assertEqual(set(OBEntry.objects.visible_to(self.staff_a1)), {mine})
        self.assertEqual(set(OBEntry.objects.visible_to(self.sup_a)), {mine})
        self.assertEqual(set(OBEntry.objects.visible_to(self.manager)), {mine, other})

    def test_correction_is_a_new_entry(self):
        first = services.write_ob(self.site, self.staff_a1, OBEntry.Kind.VISITOR, "Car KBX 123A")
        self.login(self.staff_a1)
        now = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("operations:ob_write") + f"?corrects={first.pk}",
                         {"site": self.site.pk, "kind": "visitor", "occurred_at": now, "text": "Car was KBX 128A"})
        first.refresh_from_db()
        self.assertEqual(first.text, "Car KBX 123A")
        self.assertEqual(OBEntry.objects.get(corrects=first).text, "Car was KBX 128A")

    def test_quick_entry_and_future_time_refused(self):
        self.login(self.staff_a1)
        self.client.post(reverse("operations:ob_quick", args=["patrol"]))
        self.assertEqual(OBEntry.objects.get().text, "Patrol done. All in order.")
        with self.assertRaises(ValidationError):
            services.write_ob(self.site, self.staff_a1, "other", "x", occurred_at=timezone.now() + timedelta(hours=2))

    def test_incident_is_written_in_the_ob(self):
        incident = create_incident(Incident(site=self.site, occurred_at=timezone.now(), kind="theft", severity="high",
                                            what_happened="Battery stolen from the gate motor"), self.staff_a1)
        entry = OBEntry.objects.get(kind=OBEntry.Kind.INCIDENT)
        self.assertIn(incident.number, entry.text)

    def test_filters_print_and_csv(self):
        services.write_ob(self.site, self.staff_a1, OBEntry.Kind.PATROL, "=HYPERLINK()")
        services.write_ob(self.site, self.staff_a1, OBEntry.Kind.VISITOR, "Plumber came")
        self.login(self.manager)
        r = self.client.get(reverse("operations:ob") + "?kind=visitor")
        self.assertEqual([e.text for e in r.context["entries"]], ["Plumber came"])
        self.assertEqual(self.client.get(reverse("operations:ob") + "?print=1").status_code, 200)
        csv = self.client.get(reverse("operations:ob") + "?export=csv").content.decode()
        self.assertIn("'=HYPERLINK()", csv)
        self.login(self.staff_a1)
        self.assertNotEqual(self.client.get(reverse("operations:ob") + "?export=csv").get("Content-Type"), "text/csv")


@override_settings(MEDIA_ROOT=MEDIA)
class VisitTests(OpsBase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def test_supervisor_records_visit_with_photo_and_welfare_tick(self):
        self.login(self.sup_a)
        now = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(reverse("operations:visit_create"), {
            "site": self.site.pk, "visited_at": now, "checks": ["uniform", "site_secure"],
            "guards_seen": [self.staff_a1.pk], "welfare_check_done": "on", "remarks": "Good",
            "photo": SimpleUploadedFile("gate.png", PNG),
        })
        self.assertEqual(r.status_code, 302)
        visit = SiteVisit.objects.get()
        self.assertTrue(visit.welfare_check_done)
        self.assertEqual(visit.checks_done, ["uniform", "site_secure"])
        self.assertTrue(OBEntry.objects.filter(kind=OBEntry.Kind.SITE_VISIT, site=self.site).exists())
        att = Attachment.objects.get(object_id=visit.pk, content_type__model="sitevisit")
        url = reverse("core:file", args=[att.pk])
        for user, code in ((self.sup_b, 404), (self.staff_a1, 404), (self.sup_a, 200), (self.manager, 200)):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, code, user.username)

    def test_supervisor_cannot_visit_another_supervisors_site(self):
        with self.assertRaises(ValidationError):
            services.record_visit(self.site_b, self.sup_a, timezone.now(), [], [], False, "")

    def test_staff_cannot_see_visits(self):
        self.login(self.staff_a1)
        self.assertEqual(self.client.get(reverse("operations:visits")).status_code, 403)


class EquipmentTests(OpsBase):
    def setUp(self):
        super().setUp()
        item = Item.objects.create(code="ITM-T001", name="Torch", category=Category.objects.get_or_create(name="T")[0],
                                   returnable=True, qty_available=5)
        ItemRequest.objects.create(requester=self.staff_a1, requester_role="staff", item=item, qty_requested=1,
                                   qty_issued=1, reason="x", status=ItemRequest.Status.ISSUED, handed_over_at=timezone.now())

    def test_equipment_page_scoping(self):
        self.login(self.sup_b)
        self.assertNotContains(self.client.get(reverse("operations:equipment")), "Torch")
        self.login(self.sup_a)
        self.assertContains(self.client.get(reverse("operations:equipment")), "Torch")
        self.login(self.staff_a1)
        self.assertEqual(self.client.get(reverse("operations:equipment")).status_code, 403)

    def test_turning_account_off_tells_secretary_what_to_collect(self):
        self.staff_a1.is_active = False
        self.staff_a1.save()
        note = self.secretary.notifications.get(kind="items.collect")
        self.assertIn("1 x Torch", note.message)

    def test_team_today_lists_items_without_location(self):
        self.login(self.sup_a)
        r = self.client.get(reverse("operations:team_today"))
        self.assertContains(r, "1 x Torch")
        self.assertNotContains(r, "34.76")
