from django.urls import reverse

from core.testing import OpsTestCase

from .models import Notification
from .services import notify


class NotificationTests(OpsTestCase):
    def test_open_marks_read_and_goes_to_record(self):
        n = notify(self.sup_a, "x", "Look", link=self.issue_a.get_absolute_url())[0]
        self.login(self.sup_a)
        resp = self.client.get(reverse("notifications:open", args=[n.pk]))
        self.assertRedirects(resp, self.issue_a.get_absolute_url())
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_cannot_open_someone_elses(self):
        n = notify(self.sup_a, "x", "Look")[0]
        self.login(self.sup_b)
        self.assertEqual(self.client.get(reverse("notifications:open", args=[n.pk])).status_code, 404)
        n.refresh_from_db()
        self.assertFalse(n.is_read)

    def test_target_page_still_checks_access(self):
        n = notify(self.sup_b, "x", "Look", link=self.issue_a.get_absolute_url())[0]
        self.login(self.sup_b)
        resp = self.client.get(reverse("notifications:open", args=[n.pk]), follow=True)
        self.assertEqual(resp.status_code, 404)

    def test_external_links_are_not_followed(self):
        n = notify(self.sup_a, "x", "Look", link="https://evil.example.com/")[0]
        m = notify(self.sup_a, "x", "Look", link="//evil.example.com/")[0]
        self.login(self.sup_a)
        for note in (n, m):
            self.assertRedirects(self.client.get(reverse("notifications:open", args=[note.pk])), reverse("notifications:inbox"))

    def test_read_all_and_bell(self):
        notify(self.staff_a1, "x", "One")
        notify(self.staff_a1, "x", "Two")
        self.login(self.staff_a1)
        page = self.client.get(reverse("core:home")).content.decode()
        self.assertIn('aria-label="Notifications, 2 unread"', page)
        self.client.post(reverse("notifications:read_all"))
        self.assertFalse(Notification.objects.filter(recipient=self.staff_a1, read_at__isnull=True).exists())

    def test_inactive_users_skipped(self):
        self.staff_b1.is_active = False
        self.staff_b1.save()
        self.assertEqual(notify([self.staff_b1, self.staff_a1, self.staff_a1], "x", "Hi").__len__(), 1)
