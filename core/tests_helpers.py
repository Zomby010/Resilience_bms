"""Test-only helpers."""
from django.core.mail.backends.base import BaseEmailBackend


class BrokenEmailBackend(BaseEmailBackend):
    """Fails like an unreachable SMTP server."""

    def send_messages(self, email_messages):
        raise ConnectionRefusedError("SMTP server unreachable")
