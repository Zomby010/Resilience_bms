"""Template helpers: status badges, money and masked account numbers."""
from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

register = template.Library()

# Colour family for each status value used across the apps.
TONES = {
    "completed": {
        "resolved", "closed", "responded", "sent", "paid", "approved", "returned", "recorded",
        "recorded_offline", "issued_keep",
    },
    "reviewed": {
        "assigned", "in_progress", "reviewed", "submitted", "under_review", "ready", "issued", "seen",
        "part_paid", "supervisor_reviewed", "manager_reviewed",
    },
    "pending": {
        "new", "waiting_feedback", "draft", "pending", "awaiting_manager", "return_claimed", "open",
        "awaiting_approval", "revision_required", "sent_back", "reported",
    },
    "off": {
        "supervisor_needed", "failed", "overdue", "cancelled", "rejected", "lost", "escalated", "urgent", "high",
        "critical",
    },
}
_TONE_OF = {value: tone for tone, values in TONES.items() for value in values}


@register.filter
def tone(status):
    return _TONE_OF.get(str(status), "role")


@register.simple_tag
def badge(obj, field="status"):
    """<span class="badge ...">Label</span> for obj.<field> using its display value."""
    value = getattr(obj, field, "")
    label = getattr(obj, f"get_{field}_display", lambda: value)()
    return format_html('<span class="badge {}">{}</span>', tone(value), label)


@register.filter
def kes(value):
    """1234.5 -> 'KES 1,234.50'."""
    try:
        amount = Decimal(value or 0)
    except (InvalidOperation, TypeError):
        return value
    return f"KES {amount:,.2f}"


@register.filter
def money(value):
    """1234.5 -> '1,234.50' (no currency, for table columns headed 'KES')."""
    try:
        amount = Decimal(value or 0)
    except (InvalidOperation, TypeError):
        return value
    return f"{amount:,.2f}"


@register.filter
def masked(value):
    """Show only the last 3 characters of an account or phone number."""
    value = str(value or "")
    if len(value) <= 3:
        return value
    return "•" * (len(value) - 3) + value[-3:]


@register.filter
def change_text(value):
    """Audit change value: [old, new] -> 'old → new'; anything else shown as is."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        old, new = ("-" if v in (None, "") else v for v in value)
        return f"{old} → {new}"
    return "-" if value in (None, "") else value


@register.filter
def kes0(value):
    """1234.5 -> 'KES 1,235' (whole shillings, for big dashboard numbers)."""
    try:
        amount = Decimal(value or 0)
    except (InvalidOperation, TypeError):
        return value
    return f"KES {amount:,.0f}"
