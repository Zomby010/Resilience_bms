"""Forms keep working on every address the site answers on (e.g. a new subdomain behind Cloudflare)."""
from django.test import Client, override_settings

from .testing import CompanyTestCase


@override_settings(ALLOWED_HOSTS=["app.example.com"], CSRF_TRUSTED_ORIGINS=["https://app.example.com"])
class CsrfFailureTests(CompanyTestCase):
    def test_refused_form_shows_plain_page_and_logs_the_reason(self):
        client = Client(enforce_csrf_checks=True)
        with self.assertLogs("django.security.csrf", "WARNING") as logs:
            response = client.post("/accounts/login/", {"username": "x"}, HTTP_HOST="app.example.com", secure=True)
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "This page has expired", status_code=403)
        self.assertTrue(any("host=app.example.com" in line for line in logs.output))
