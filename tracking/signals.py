from django.contrib.auth.signals import user_logged_out
from django.db.models.signals import post_init, post_save
from django.dispatch import receiver
from django.utils import timezone

from . import services
from .models import SitePosting, TrackingProfile


@receiver(user_logged_out)
def stop_tracking_on_logout(sender, request, user, **kwargs):
    """Signing out stops location sharing, so nobody is tracked without being signed in."""
    if user is not None and services.is_tracked(user):
        services.set_tracking(user, False)


@receiver(post_init, sender=TrackingProfile)
def remember_loaded_site(sender, instance, **kwargs):
    # Compared after saving, so a location update (which saves the profile) costs no extra query.
    instance._old_site_id = instance.__dict__.get("site_id") if instance.pk else None


@receiver(post_save, sender=TrackingProfile)
def record_posting(sender, instance, created, raw=False, **kwargs):
    """Keep the posting history in step with the person's current site."""
    if raw or (not created and getattr(instance, "_old_site_id", None) == instance.site_id):
        return
    instance._old_site_id = instance.site_id
    now = timezone.now()
    SitePosting.objects.filter(user_id=instance.user_id, ended_at__isnull=True).exclude(site_id=instance.site_id).update(ended_at=now)
    if instance.site_id and not SitePosting.objects.filter(user_id=instance.user_id, ended_at__isnull=True).exists():
        SitePosting.objects.create(user_id=instance.user_id, site_id=instance.site_id, started_at=now)
