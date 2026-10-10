"""Template helpers: status badges, sender chips, money and masked account numbers."""
from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

register = template.Library()

# Colour family for each status value used across the apps.
TONES = {
    "completed": {
        "resolved", "responded", "sent", "paid", "approved", "returned", "recorded",
        "recorded_offline", "issued_keep", "accepted", "present",
    },
    "reviewed": {
        "assigned", "in_progress", "reviewed", "submitted", "under_review", "ready", "issued", "seen",
        "part_paid", "certificate_received", "waiting_manager", "late", "supervisor_reviewed", "manager_reviewed",
    },
    "pending": {
        "new", "waiting_feedback", "draft", "pending", "awaiting_manager", "return_claimed", "open",
        "awaiting_approval", "revision_required", "sent_back", "waiting", "certificate_needed",
        "waiting_supervisor", "reported",
    },
    "off": {
        "supervisor_needed", "failed", "overdue", "rejected", "lost", "escalated", "urgent", "high",
        "critical", "not_accepted", "absent",
    },
    # Finished and put away: grey, not green, so "closed" never reads as "all good" or "danger".
    "closed": {"closed", "cancelled", "day_off", "shift_over"},
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


# Badges are drawn by the {% badge %} tag; status_badge is the name the design system uses.
status_badge = register.simple_tag(badge, name="status_badge")

# Who sent it: one colour, icon and word per sender (report section 6.1).
SENDERS = {
    "staff": ("guard", "🛡", "Guard"),
    "supervisor": ("supervisor", "⭐", "Supervisor"),
    "secretary": ("secretary", "📋", "Secretary"),
    "manager": ("manager", "👔", "Manager"),
    "client": ("client", "🏢", "Client"),
    "system": ("system", "⚙", "System"),
}


def sender_kind(sender):
    """'staff', 'supervisor', ... for a user; 'client' for a Client; 'system' for nothing."""
    if sender is None or sender == "system":
        return "system"
    if isinstance(sender, str):
        return sender if sender in SENDERS else "system"
    role = getattr(sender, "role", None)
    if role:
        return role
    return "client" if sender.__class__.__name__ == "Client" else "system"


@register.simple_tag
def sender_chip(sender, show_name=True):
    """A coloured chip saying who sent something: icon, ROLE and (optionally) the name."""
    kind = sender_kind(sender)
    css, icon, word = SENDERS.get(kind, SENDERS["system"])
    name = str(sender) if show_name and kind != "system" and not isinstance(sender, str) else ""
    if name:
        return format_html('<span class="sender s-{}"><span aria-hidden="true">{}</span> <b>{}</b> · {}</span>',
                           css, icon, word.upper(), name)
    return format_html('<span class="sender s-{}"><span aria-hidden="true">{}</span> <b>{}</b></span>', css, icon, word.upper())


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


@register.simple_tag(takes_context=True)
def filter_bar(context, *specs):
    """The shared, closed-by-default filter bar (FILT-01), described in the template:

        {% filter_bar "q|Search|text||main|Name or number" "status|Status|select|=unpaid:Not paid,statuses|main" "from|From|date" %}

    Each spec is name|label|kind|options|main|hint|any. `options` is a comma list of context names (a list
    of (value, label) pairs, or objects: their pk and name are used) and literal "=value:Label" choices.
    `any` renames the empty choice (default "Any"). Filters not marked main go under "More filters".
    Other GET values (tabs, view, scope) are kept, so old links keep working.
    """
    from django.template.loader import render_to_string

    from core.filters import F, filter_bar as build

    fields = []
    for spec in specs:
        if not spec:
            continue
        name, label, kind, options, main, hint, any_label = (spec.split("|") + [""] * 7)[:7]
        opts = []
        for item in filter(None, options.split(",")):
            if item.startswith("="):
                value, _, text = item[1:].partition(":")
                opts.append((value, text))
                continue
            for o in context.get(item) or ():
                opts.append((o[0], o[1]) if isinstance(o, (list, tuple)) else (o.pk, str(o)))
        fields.append(F(name, label, kind or "text", opts, hint=hint, main=main == "main", any_label=any_label or "Any"))
    request = context["request"]
    return render_to_string("partials/filter_bar.html", {"fb": build(request, fields)}, request=request)
