from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver

from . import services


@receiver(user_logged_out)
def stop_tracking_on_logout(sender, request, user, **kwargs):
    """Signing out stops location sharing, so nobody is tracked without being signed in."""
    if user is not None and services.is_tracked(user):
        services.set_tracking(user, False)
