"""Send email through Django's configured backend without ever crashing a page.

Development prints emails to the console, tests keep them in memory, and production
uses SMTP once the owner has chosen a provider (Gate 7) and set EMAIL_HOST.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

log = logging.getLogger(__name__)


def send(to, subject, body, attachments=()):
    """Return (ok, error_message). `attachments` is a list of (filename, bytes, mime)."""
    if not to:
        return False, "This client has no email address."
    msg = EmailMultiAlternatives(subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[to])
    for name, content, mime in attachments:
        msg.attach(name, content, mime)
    try:
        msg.send(fail_silently=False)
    except Exception as exc:  # network, login and provider errors all end up here
        log.warning("Email to %s failed: %s", to, exc)
        return False, f"The email could not be sent ({exc.__class__.__name__}). Check the email settings and try again."
    return True, ""
