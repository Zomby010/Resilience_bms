"""Create in-app notifications. Every helper takes plain-language text."""
from accounts.models import User

from .models import Notification


def notify(recipients, kind, title, message="", link="", priority=Notification.Priority.NORMAL, entity=None):
    """Send one notification to each recipient (a user, or a list/queryset of users)."""
    if recipients is None:
        return []
    if isinstance(recipients, User):
        recipients = [recipients]
    entity_type = entity._meta.label_lower if entity is not None else ""
    entity_id = str(entity.pk) if entity is not None else ""
    seen, rows = set(), []
    for user in recipients:
        if user is None or user.pk in seen or not user.is_active:
            continue
        seen.add(user.pk)
        rows.append(Notification(
            recipient=user, kind=kind, title=title[:120], message=message, link_url=link,
            priority=priority, entity_type=entity_type, entity_id=entity_id,
        ))
    return Notification.objects.bulk_create(rows)


def notify_role(role, kind, title, message="", link="", priority=Notification.Priority.NORMAL, entity=None, exclude=None):
    users = User.objects.filter(role=role, is_active=True)
    if exclude is not None:
        users = users.exclude(pk=exclude.pk)
    return notify(users, kind, title, message, link, priority, entity)


def unread_count(user):
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()
