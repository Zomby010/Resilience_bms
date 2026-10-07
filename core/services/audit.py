"""Write entries to the append-only audit log."""
from decimal import Decimal

from core.models import AuditLog


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "pk"):
        return str(value)
    return value


def snapshot(obj, fields):
    """The current values of `fields` on `obj`, in a JSON-friendly form."""
    return {f: _plain(getattr(obj, f)) for f in fields}


def changes_between(before, after):
    """{field: [old, new]} for every field whose value changed."""
    return {k: [before.get(k), after.get(k)] for k in after if before.get(k) != after.get(k)}


def record(actor, action, obj, summary, changes=None, confidential=False, entity_type=None, entity_id=None):
    return AuditLog.objects.create(
        actor=actor if actor is not None and actor.is_authenticated else None,
        actor_role=getattr(actor, "role", "") or "",
        action=action,
        entity_type=entity_type or (obj._meta.label_lower if obj is not None else ""),
        entity_id=str(entity_id if entity_id is not None else getattr(obj, "pk", "")),
        summary=summary[:255],
        changes=changes or {},
        confidential=confidential,
    )
