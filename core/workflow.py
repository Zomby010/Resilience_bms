"""Status changes that are safe against double clicks and two people acting at once.

`advance()` performs one conditional UPDATE: it only changes the row if it is still in one of
the expected statuses. If someone else (or a second click) already moved it, nothing happens
and False is returned, so stock and notifications are never applied twice.
"""
from django.utils import timezone


class TransitionError(Exception):
    """Raised with a plain-language message when an action is not allowed right now."""


def advance(obj, from_statuses, to_status, **fields):
    if isinstance(from_statuses, str):
        from_statuses = (from_statuses,)
    model = type(obj)
    values = {"status": to_status, **fields}
    if any(f.name == "updated_at" for f in model._meta.fields):
        values["updated_at"] = timezone.now()
    changed = model.objects.filter(pk=obj.pk, status__in=from_statuses).update(**values)
    if changed:
        for k, v in values.items():
            setattr(obj, k, v)
    return bool(changed)


def require(obj, from_statuses, to_status, message="This has already been changed by someone else. Please refresh the page.", **fields):
    if not advance(obj, from_statuses, to_status, **fields):
        raise TransitionError(message)
