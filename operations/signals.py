from django.conf import settings
from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

from . import services


@receiver(post_init, sender=settings.AUTH_USER_MODEL)
def remember_active(sender, instance, **kwargs):
    instance._was_active = instance.__dict__.get("is_active") if instance.pk else None


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def items_to_collect(sender, instance, created, raw=False, **kwargs):
    """Turning an account off tells the Secretary which items to collect from that person."""
    was_active = getattr(instance, "_was_active", None)
    instance._was_active = instance.is_active
    if raw or created or not (was_active and not instance.is_active):
        return
    services.remind_items_on_leaving(instance)
