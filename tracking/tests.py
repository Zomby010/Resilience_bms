import json
from datetime import datetime, time, timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from core.testing import CompanyTestCase
from reports.models import Report

from . import geo, services
from .models import Alert, AuditEntry, LocationPing, LocationStatus, Site, TrackingProfile, WorkHours

SITE = (-0.091702, 34.767956)  # Kisumu


def offset(metres_north, base=SITE):
    """A point `metres_north` metres due north of `base` (1 degree of latitude ~ 111,195 m)."""
    return base[0] + metres_north / 111_195.0, base[1]


def local(year, month, day, hh, mm=0):
    return timezone.make_aware(datetime(year, month, day, hh, mm))


# 2026-10-05 is a Monday.
MONDAY_10 = local(2026, 10, 5, 10)


class GeoTests(CompanyTestCase):
    def test_distance_is_accurate(self):
        lat, lng = offset(100)
        self.assertAlmostEqual(geo.distance_m(*SITE, lat, lng), 100, delta=0.5)
        self.assertEqual(geo.distance_m(*SITE, *SITE), 0)
        # Nairobi CBD to Kisumu is about 265 km in a straight line.
        self.assertAlmostEqual(geo.distance_m(-1.2864, 36.8172, -0.0917, 34.7680) / 1000, 265, delta=5)

    def test_classify_boundaries_have_no_gaps(self):
        r = 30
        self.assertEqual(geo.classify(0, 5, r), LocationStatus.ON)
        self.assertEqual(geo.classify(30, 5, r), LocationStatus.ON)        # exactly the radius
        self.assertEqual(geo.classify(30.01, 5, r), LocationStatus.NEAR)
        self.assertEqual(geo.classify(50, 5, r), LocationStatus.NEAR)      # exactly 50 m
        self.assertEqual(geo.classify(50.01, 5, r), LocationStatus.OFF)
        self.assertEqual(geo.classify(120, 5, r), LocationStatus.OFF)      # the old 50-200 m gap
        self.assertEqual(geo.classify(5000, 5, r), LocationStatus.OFF)

    def test_poor_accuracy_is_never_reported_as_off(self):
        self.assertEqual(geo.classify(500, 51, 30), LocationStatus.WEAK)
        self.assertEqual(geo.classify(500, 50, 30), LocationStatus.OFF)


class TrackingTestCase(CompanyTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.site = Site.objects.create(name="Kondele Site", latitude=SITE[0], longitude=SITE[1], radius_m=30)
        for day in range(5):  # Monday to Friday, 08:00-17:00
            WorkHours.objects.create(site=cls.site, weekday=day, start=time(8), end=time(17))
        for user in (cls.staff_a1, cls.staff_a2, cls.sup_a):
            TrackingProfile.objects.create(user=user, site=cls.site)

    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=MONDAY_10)
        self.now = patcher.start()
        self.addCleanup(patcher.stop)

    def advance(self, seconds):
        self.now.return_value = self.now.return_value + timedelta(seconds=seconds)

    def post(self, name, data=None):
        return self.client.post(reverse(f"tracking:{name}"), json.dumps(data or {}), content_type="application/json")

    def ping(self, metres=0, accuracy=10, **extra):
        lat, lng = offset(metres)
        body = {"latitude": lat, "longitude": lng, "accuracy": accuracy,
                "timestamp": timezone.now().timestamp() * 1000}
        body.update(extra)
        return self.post("api_update", body)

    def profile(self, user):
        return TrackingProfile.objects.get(user=user)


class WorkingHoursTests(TrackingTestCase):
    def test_before_during_after(self):
        p = self.profile(self.staff_a1)
        self.assertFalse(services.is_working(p, local(2026, 10, 5, 7, 59)))
        self.assertTrue(services.is_working(p, local(2026, 10, 5, 8, 0)))
        self.assertTrue(services.is_working(p, local(2026, 10, 5, 16, 59)))
        self.assertFalse(services.is_working(p, local(2026, 10, 5, 17, 0)))
        self.assertFalse(services.is_working(p, local(2026, 10, 10, 10)))  # Saturday

    def test_overnight_shift(self):
        night = Site.objects.create(name="Night Site", latitude=1, longitude=1)
        WorkHours.objects.create(site=night, weekday=4, start=time(18), end=time(6))  # Friday night
        p = TrackingProfile(user=self.staff_b1, site=night)
        self.assertFalse(services.is_working(p, local(2026, 10, 9, 17)))   # Friday 17:00
        self.assertTrue(services.is_working(p, local(2026, 10, 9, 23)))    # Friday 23:00
        self.assertTrue(services.is_working(p, local(2026, 10, 10, 5)))    # Saturday 05:00
        self.assertFalse(services.is_working(p, local(2026, 10, 10, 6)))   # Saturday 06:00

    def test_own_hours_override_site_hours(self):
        p = self.profile(self.staff_a1)
        p.own_hours = True
        p.save()
        WorkHours.objects.create(user=self.staff_a1, weekday=5, start=time(9), end=time(12))
        self.assertFalse(services.is_working(p, MONDAY_10))
        self.assertTrue(services.is_working(p, local(2026, 10, 10, 10)))

    def test_no_site_means_no_hours(self):
        self.assertFalse(services.is_working(TrackingProfile(user=self.staff_b1), MONDAY_10))


class LocationApiTests(TrackingTestCase):
    def test_turn_on_update_and_off(self):
        self.login(self.staff_a1)
        r = self.post("api_start")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["tracking_on"])
        self.assertEqual(r.json()["status"], "waiting")

        r = self.ping(metres=10, accuracy=8)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "on")
        self.assertEqual(r.json()["distance_m"], 10)
        ping = LocationPing.objects.get()
        self.assertEqual((ping.user, ping.site, ping.status), (self.staff_a1, self.site, "on"))

        r = self.post("api_stop")
        self.assertFalse(r.json()["tracking_on"])
        self.assertEqual(r.json()["status"], "tracking_off")

    def test_near_and_off(self):
        self.login(self.staff_a1)
        self.post("api_start")
        self.assertEqual(self.ping(metres=40).json()["status"], "near")
        self.advance(30)
        self.assertEqual(self.ping(metres=150).json()["status"], "off")

    def test_poor_accuracy_shows_weak(self):
        self.login(self.staff_a1)
        self.post("api_start")
        self.assertEqual(self.ping(metres=300, accuracy=80).json()["status"], "weak")

    def test_missing_work_location(self):
        self.login(self.staff_b1)  # no site assigned
        self.post("api_start")
        r = self.ping()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "no_site")
        self.assertIsNone(LocationPing.objects.get().distance_m)

    def test_invalid_coordinates_rejected(self):
        self.login(self.staff_a1)
        self.post("api_start")
        for bad in (
            {"latitude": 91, "longitude": 34, "accuracy": 5},
            {"latitude": 0, "longitude": 181, "accuracy": 5},
            {"latitude": "abc", "longitude": 34, "accuracy": 5},
            {"latitude": "NaN", "longitude": 34, "accuracy": 5},
            {"latitude": 0, "longitude": 0, "accuracy": 5},
            {"longitude": 34, "accuracy": 5},
            {"latitude": -0.09, "longitude": 34.7, "accuracy": -1},
        ):
            self.assertEqual(self.post("api_update", bad).status_code, 400, bad)
        self.assertEqual(self.client.post(reverse("tracking:api_update"), "not json", content_type="application/json").status_code, 400)
        self.assertEqual(self.post("api_update", [1, 2]).status_code, 400)
        self.assertFalse(LocationPing.objects.exists())

    def test_stale_and_future_readings_rejected(self):
        self.login(self.staff_a1)
        self.post("api_start")
        old = (timezone.now() - timedelta(minutes=5)).timestamp() * 1000
        future = (timezone.now() + timedelta(minutes=10)).timestamp() * 1000
        self.assertEqual(self.ping(timestamp=old).status_code, 400)
        self.assertEqual(self.ping(timestamp=future).status_code, 400)

    def test_update_refused_while_tracking_off(self):
        self.login(self.staff_a1)
        self.assertEqual(self.ping().status_code, 400)
        self.assertFalse(LocationPing.objects.exists())

    def test_rate_limit(self):
        self.login(self.staff_a1)
        self.post("api_start")
        self.assertEqual(self.ping().status_code, 200)
        self.advance(5)
        self.assertEqual(self.ping().status_code, 429)
        self.advance(10)
        self.assertEqual(self.ping().status_code, 200)

    def test_replayed_reading_rejected(self):
        self.login(self.staff_a1)
        self.post("api_start")
        ts = timezone.now().timestamp() * 1000
        self.assertEqual(self.ping(timestamp=ts).status_code, 200)
        self.advance(15)
        self.assertEqual(self.ping(timestamp=ts).status_code, 400)

    def test_impossible_jump_is_flagged_and_ignored(self):
        self.login(self.staff_a1)
        self.post("api_start")
        self.ping(metres=5)
        self.advance(15)
        r = self.ping(metres=50_000)  # 50 km in 15 s
        self.assertTrue(r.json()["flagged"])
        self.assertEqual(r.json()["status"], "on")
        self.assertTrue(LocationPing.objects.filter(flag__startswith="Impossible").exists())

    def test_cannot_submit_location_for_someone_else(self):
        self.login(self.staff_a1)
        self.post("api_start")
        self.ping(user=self.staff_a2.pk, user_id=self.staff_a2.pk)
        self.assertEqual(LocationPing.objects.get().user, self.staff_a1)
        self.assertFalse(LocationPing.objects.filter(user=self.staff_a2).exists())

    def test_signal_lost_after_five_minutes(self):
        self.login(self.staff_a1)
        self.post("api_start")
        self.ping()
        self.advance(301)
        self.assertEqual(self.client.get(reverse("tracking:api_me")).json()["status"], "lost")

    def test_session_expired_returns_401_json(self):
        for name in ("api_start", "api_update", "api_stop"):
            r = self.post(name)
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json()["code"], "session")

    def test_logout_stops_tracking(self):
        self.login(self.staff_a1)
        self.post("api_start")
        self.client.post(reverse("accounts:logout"))
        self.assertFalse(self.profile(self.staff_a1).tracking_on)

    def test_supervisor_can_track_themselves(self):
        self.login(self.sup_a)
        self.post("api_start")
        self.assertEqual(self.ping().json()["status"], "on")

    def test_manager_and_secretary_cannot_send_locations(self):
        for user in (self.manager, self.secretary):
            self.login(user)
            self.assertEqual(self.post("api_start").status_code, 403)
            self.assertEqual(self.ping().status_code, 403)

    def test_get_not_allowed_on_write_endpoints(self):
        self.login(self.staff_a1)
        self.assertEqual(self.client.get(reverse("tracking:api_update")).status_code, 405)


class AlertTests(TrackingTestCase):
    def open_kinds(self, user):
        return set(Alert.objects.filter(user=user, resolved_at__isnull=True).values_list("kind", flat=True))

    def test_tracking_off_during_hours_alerts_and_clears(self):
        services.evaluate_alerts()
        self.assertEqual(self.open_kinds(self.staff_a1), {Alert.Kind.TRACKING_OFF})
        self.login(self.staff_a1)
        self.post("api_start")
        self.ping()
        self.assertEqual(self.open_kinds(self.staff_a1), set())

    def test_turning_off_during_hours_says_so(self):
        self.login(self.staff_a1)
        self.post("api_start")
        self.ping()
        self.advance(60)
        self.post("api_stop")
        alert = Alert.objects.get(user=self.staff_a1, resolved_at__isnull=True)
        self.assertIn("turned off location sharing during working hours", alert.message)

    def test_no_alerts_outside_working_hours(self):
        self.now.return_value = local(2026, 10, 5, 20)
        services.evaluate_alerts()
        self.assertFalse(Alert.objects.exists())

    def test_alert_closes_when_shift_ends(self):
        services.evaluate_alerts()
        self.assertTrue(self.open_kinds(self.staff_a1))
        self.now.return_value = local(2026, 10, 5, 17, 30)
        services.evaluate_alerts()
        self.assertEqual(self.open_kinds(self.staff_a1), set())

    def test_off_location_and_signal_lost(self):
        self.login(self.staff_a1)
        self.post("api_start")
        self.ping(metres=400)
        self.assertEqual(self.open_kinds(self.staff_a1), {Alert.Kind.OFF_LOCATION})
        self.assertIn("OFF LOCATION", Alert.objects.get(user=self.staff_a1).message)
        self.advance(400)
        services.evaluate_alerts()
        self.assertEqual(self.open_kinds(self.staff_a1), {Alert.Kind.SIGNAL_LOST})

    def test_one_open_alert_per_problem(self):
        services.evaluate_alerts()
        services.evaluate_alerts()
        self.assertEqual(Alert.objects.filter(user=self.staff_a1).count(), 1)

    def test_staff_sees_required_banner_during_hours_only(self):
        self.login(self.staff_a1)
        # On the dashboard the reminder is inside the location card...
        r = self.client.get(reverse("core:home"))
        self.assertContains(r, 'id="loc-required" role="alert"')
        # ...and on other pages it is a banner at the top.
        r = self.client.get(reverse("reports:list"))
        self.assertContains(r, 'class="location-banner"')
        self.now.return_value = local(2026, 10, 5, 20)
        self.assertContains(self.client.get(reverse("core:home")), 'id="loc-required" hidden')
        self.assertNotContains(self.client.get(reverse("reports:list")), 'class="location-banner"')

    def test_purge_old_history(self):
        LocationPing.objects.create(user=self.staff_a1, received_at=MONDAY_10 - timedelta(days=91),
                                    measured_at=MONDAY_10 - timedelta(days=91), latitude=1, longitude=1, accuracy_m=5)
        keep = LocationPing.objects.create(user=self.staff_a1, received_at=MONDAY_10 - timedelta(days=89),
                                           measured_at=MONDAY_10 - timedelta(days=89), latitude=1, longitude=1, accuracy_m=5)
        self.assertEqual(services.purge_history(), 1)
        self.assertEqual(list(LocationPing.objects.all()), [keep])


class AccessTests(TrackingTestCase):
    manager_pages = ["tracker", "sites", "site_create", "people", "history"]

    def test_only_manager_sees_monitoring(self):
        for user in (self.staff_a1, self.sup_a, self.secretary):
            self.login(user)
            for name in self.manager_pages:
                self.assertEqual(self.client.get(reverse(f"tracking:{name}")).status_code, 403, (user, name))
            self.assertEqual(self.client.get(reverse("tracking:person_edit", args=[self.staff_a2.pk])).status_code, 403)
            self.assertEqual(self.client.get(reverse("tracking:api_overview")).status_code, 403)

    def test_anonymous_redirected_to_login(self):
        r = self.client.get(reverse("tracking:tracker"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r["Location"])

    def test_manager_can_open_every_page(self):
        self.login(self.manager)
        for name in self.manager_pages:
            self.assertEqual(self.client.get(reverse(f"tracking:{name}")).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("tracking:person_edit", args=[self.staff_a1.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("tracking:site_edit", args=[self.site.pk])).status_code, 200)
        # Only staff and supervisors have location settings.
        self.assertEqual(self.client.get(reverse("tracking:person_edit", args=[self.secretary.pk])).status_code, 404)

    def test_staff_only_see_their_own_state(self):
        self.login(self.staff_a2)
        self.post("api_start")
        self.ping(metres=20)
        self.login(self.staff_a1)
        me = self.client.get(reverse("tracking:api_me")).json()
        self.assertFalse(me["tracking_on"])
        self.assertNotIn("people", me)
        page = self.client.get(reverse("tracking:mine"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, str(self.staff_a2))

    def test_manager_overview(self):
        self.login(self.staff_a1)
        self.post("api_start")
        self.ping(metres=10)
        self.login(self.staff_a2)
        self.post("api_start")
        self.advance(15)
        self.ping(metres=45)
        self.login(self.manager)
        data = self.client.get(reverse("tracking:api_overview")).json()
        self.assertEqual(data["counts"]["on"], 1)
        self.assertEqual(data["counts"]["near"], 1)
        # sup_a, sup_b and staff_b1 have tracking off (sup_b and staff_b1 have no profile yet; one is created).
        self.assertEqual(data["counts"]["tracking_off"], 3)
        rows = {r["name"]: r for r in data["people"]}
        self.assertEqual(rows[str(self.staff_a1)]["status"], "on")
        self.assertTrue(rows[str(self.staff_a1)]["online"])
        self.assertFalse(rows[str(self.sup_b)]["online"])
        self.assertNotIn(str(self.manager), rows)
        self.assertNotIn(str(self.secretary), rows)
        self.assertEqual(data["sites"][0]["name"], "Kondele Site")


class ManagerSetupTests(TrackingTestCase):
    def site_data(self, **overrides):
        data = {"site-name": "Mamboleo", "site-latitude": "-0.08", "site-longitude": "34.78",
                "site-radius_m": "25", "site-is_active": "on"}
        for d in range(7):
            data[f"hours-d{d}_start"], data[f"hours-d{d}_end"] = "", ""
        data.update({"hours-d0_on": "on", "hours-d0_start": "18:00", "hours-d0_end": "06:00"})
        data.update(overrides)
        return data

    def test_create_site_with_hours_is_audited(self):
        self.login(self.manager)
        r = self.client.post(reverse("tracking:site_create"), self.site_data())
        self.assertRedirects(r, reverse("tracking:sites"))
        site = Site.objects.get(name="Mamboleo")
        self.assertEqual(site.radius_m, 25)
        hours = site.hours.get()
        self.assertEqual((hours.weekday, hours.start, hours.end), (0, time(18), time(6)))
        entry = AuditEntry.objects.get()
        self.assertEqual(entry.actor, self.manager)
        self.assertIn("created site Mamboleo", entry.action)

    def test_site_validation(self):
        self.login(self.manager)
        for bad in ({"site-latitude": "95"}, {"site-longitude": "-200"}, {"site-radius_m": "500"},
                    {"hours-d0_end": ""}, {"hours-d0_end": "18:00"}):
            r = self.client.post(reverse("tracking:site_create"), self.site_data(**bad))
            self.assertEqual(r.status_code, 200, bad)
        self.assertFalse(Site.objects.filter(name="Mamboleo").exists())

    def test_assign_site_and_own_hours(self):
        other = Site.objects.create(name="Other", latitude=1, longitude=1)
        self.login(self.manager)
        data = {"p-site": other.pk, "p-own_hours": "on"}
        for d in range(7):
            data[f"hours-d{d}_start"], data[f"hours-d{d}_end"] = "", ""
        data.update({"hours-d2_on": "on", "hours-d2_start": "07:00", "hours-d2_end": "15:00"})
        r = self.client.post(reverse("tracking:person_edit", args=[self.staff_b1.pk]), data)
        self.assertRedirects(r, reverse("tracking:people"))
        p = self.profile(self.staff_b1)
        self.assertEqual(p.site, other)
        self.assertTrue(p.own_hours)
        self.assertEqual(self.staff_b1.work_hours.get().weekday, 2)
        self.assertIn("site to Other", AuditEntry.objects.get().action)

    def test_history_filters(self):
        self.login(self.staff_a1)
        self.post("api_start")
        self.ping(metres=5)
        self.login(self.staff_a2)
        self.post("api_start")
        self.advance(15)
        self.ping(metres=300)
        self.login(self.manager)
        r = self.client.get(reverse("tracking:history"), {"status": "off"})
        self.assertEqual([p.user for p in r.context["pings"]], [self.staff_a2])
        r = self.client.get(reverse("tracking:history"), {"person": self.staff_a1.pk})
        self.assertEqual([p.user for p in r.context["pings"]], [self.staff_a1])


class ReportIntegrationTests(TrackingTestCase):
    def test_report_shows_location_to_manager_not_supervisor(self):
        self.login(self.staff_a1)
        self.post("api_start")
        self.ping(metres=18)
        self.advance(60)
        self.client.post(reverse("reports:create"), {"title": "Patrol", "body": "All quiet."})
        report = Report.objects.get()

        self.login(self.manager)
        r = self.client.get(report.get_absolute_url())
        self.assertContains(r, "Location when sent")
        self.assertContains(r, "18 m from Kondele Site")

        self.login(self.staff_a1)
        self.assertContains(self.client.get(report.get_absolute_url()), "18 m from Kondele Site")

        self.login(self.sup_a)
        r = self.client.get(report.get_absolute_url())
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Location when sent")

    def test_report_without_location_still_works(self):
        self.login(self.staff_b1)
        r = self.client.post(reverse("reports:create"), {"title": "Patrol", "body": "All quiet."})
        self.assertEqual(r.status_code, 302)
        self.login(self.manager)
        self.assertContains(self.client.get(Report.objects.get().get_absolute_url()), "Location when sent: not shared")

    def test_dashboards_still_render(self):
        for user in (self.manager, self.sup_a, self.staff_a1, self.secretary):
            self.login(user)
            self.assertEqual(self.client.get(reverse("core:home")).status_code, 200, user)
        self.login(self.staff_a1)
        self.assertContains(self.client.get(reverse("core:home")), "Turn on location")
