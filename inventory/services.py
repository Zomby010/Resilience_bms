"""Stock and item-request rules.

Every stock change is one conditional UPDATE (it only happens if the counts it takes from are
big enough), plus one row in the append-only ledger, inside one transaction. Status changes use
core.workflow.advance, so a double click or two people pressing at once is applied only once.

THE PHYSICAL RETURN RULE: a requester saying "I have returned this item" only changes the status
to return_claimed. Stock moves only when the Secretary or Manager (never the requester) confirms
they physically have the item back.
"""
import uuid
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from core.services import audit
from core.workflow import TransitionError, advance
from notifications.models import Notification
from notifications.services import notify, notify_role

from .models import QUANTITY_FIELDS, Item, ItemRequest, StockMovement

A = StockMovement.Action
R = ItemRequest.Status
MAX_REQUEST_QTY = 20
OPEN_REQUEST_STATUSES = (R.AWAITING_MANAGER, R.PENDING, R.READY, R.ISSUED, R.RETURN_CLAIMED)
REQUESTER_ROLES = (Role.STAFF, Role.SUPERVISOR)
OFFICE_ROLES = (Role.SECRETARY, Role.MANAGER)
NOT_ENOUGH = "Not enough stock. Someone may have just taken the last one. Please check the item and try again."


def item_link(item):
    return reverse("inventory:detail", args=[item.pk])


def office_link(req):
    return reverse("inventory:request_detail", args=[req.pk])


def my_link(req):
    return reverse("inventory:mine_detail", args=[req.pk])


# --- stock ------------------------------------------------------------------------

def move_stock(item, changes, action, qty, user, reason="", request=None):
    """Apply {count_field: +/-n} atomically. Raises TransitionError if any count would go below zero.

    Must be called inside transaction.atomic so the ledger row and the counts always agree.
    """
    assert transaction.get_connection().in_atomic_block, "move_stock must run inside a transaction"
    if qty <= 0:
        raise TransitionError("The quantity must be at least 1.")
    guard = {f"{f}__gte": -d for f, d in changes.items() if d < 0}
    updated = Item.objects.filter(pk=item.pk, **guard).update(
        **{f: F(f) + d for f, d in changes.items()}, updated_at=timezone.now()
    )
    if not updated:
        raise TransitionError(NOT_ENOUGH)
    item.refresh_from_db()
    after = item.quantities()
    before = {f: after[f] - changes.get(f, 0) for f in QUANTITY_FIELDS}
    StockMovement.objects.create(item=item, action=action, quantity=qty, before=before, after=after,
                                 request=request, by=user, reason=reason[:255])
    _check_low_stock(item)
    return item


def _check_low_stock(item):
    if item.min_stock and item.qty_available <= item.min_stock:
        if Item.objects.filter(pk=item.pk, low_stock_notified=False).update(low_stock_notified=True):
            item.low_stock_notified = True
            notify_role(Role.SECRETARY, "item.low_stock", f"Low stock: {item.name}",
                        f"Only {item.qty_available} left (minimum {item.min_stock}).", item_link(item), entity=item)
    elif item.low_stock_notified and item.qty_available > item.min_stock:
        Item.objects.filter(pk=item.pk).update(low_stock_notified=False)
        item.low_stock_notified = False


ITEM_FIELDS = ["name", "category", "description", "condition_note", "storage_location", "min_stock", "returnable", "is_active"]


@transaction.atomic
def create_item(item, opening_qty, user):
    item.code = uuid.uuid4().hex[:20]  # placeholder, replaced by ITM-0001 style below
    item.save()
    item.code = f"ITM-{item.pk:04d}"
    Item.objects.filter(pk=item.pk).update(code=item.code)
    audit.record(user, "item.created", item, f"Added item {item.code} {item.name}", changes=audit.snapshot(item, ITEM_FIELDS))
    if opening_qty:
        move_stock(item, {"qty_available": opening_qty}, A.ADDED, opening_qty, user, "Opening stock")
    else:
        _check_low_stock(item)
    return item


@transaction.atomic
def update_item(item, user, before):
    item.save()
    changes = audit.changes_between(before, audit.snapshot(item, ITEM_FIELDS))
    if changes:
        audit.record(user, "item.updated", item, f"Edited item {item.code} {item.name}", changes=changes)
    _check_low_stock(item)
    return item


# action -> (count changes per unit, ledger action, label)
ADJUSTMENTS = {
    "add": ({"qty_available": 1}, A.ADDED, "Add new stock"),
    "damaged": ({"qty_available": -1, "qty_damaged": 1}, A.DAMAGED, "Mark some as damaged"),
    "repaired": ({"qty_damaged": -1, "qty_available": 1}, A.REPAIRED, "Damaged ones are repaired"),
    "lost": ({"qty_available": -1, "qty_lost": 1}, A.LOST, "Some are missing from the store"),
    "write_off": ({"qty_available": -1}, A.WRITTEN_OFF, "Write off (remove from the store)"),
    "write_off_damaged": ({"qty_damaged": -1}, A.WRITTEN_OFF, "Throw away damaged ones"),
}


@transaction.atomic
def adjust_stock(item, action, qty, reason, user):
    if action not in ADJUSTMENTS:
        raise TransitionError("Choose what happened.")
    if not reason.strip():
        raise TransitionError("Please write the reason.")
    per_unit, ledger_action, label = ADJUSTMENTS[action]
    move_stock(item, {f: d * qty for f, d in per_unit.items()}, ledger_action, qty, user, reason.strip())
    audit.record(user, f"item.{action}", item, f"{label}: {qty} x {item.name}. {reason.strip()[:120]}")
    if action in ("damaged", "lost"):
        notify_role(Role.MANAGER, f"item.{action}", f"{qty} x {item.name} {'damaged' if action == 'damaged' else 'lost'}",
                    reason.strip()[:200], item_link(item), Notification.Priority.HIGH, entity=item)
    return item


def set_item_active(item, active, user):
    if not active and item.requests.filter(status__in=OPEN_REQUEST_STATUSES).exists():
        raise TransitionError("This item has open requests or is still out with someone. Finish those first.")
    if item.is_active == active:
        return
    Item.objects.filter(pk=item.pk).update(is_active=active, updated_at=timezone.now())
    item.is_active = active
    audit.record(user, "item.reactivated" if active else "item.retired", item,
                 f"{'Brought back' if active else 'Retired'} item {item.code} {item.name}")


@transaction.atomic
def set_manager_flags(flagged_ids, user):
    """D12: the Manager chooses which items need his approval before the Secretary can give them out."""
    if user.role != Role.MANAGER:
        raise TransitionError("Only the Manager can choose these items.")
    flagged_ids = set(flagged_ids)
    now = timezone.now()
    changed = []
    for item in Item.objects.filter(is_active=True):
        want = item.pk in flagged_ids
        if item.needs_manager_approval != want:
            Item.objects.filter(pk=item.pk).update(needs_manager_approval=want, flag_changed_by=user, flag_changed_at=now)
            audit.record(user, "item.flag_on" if want else "item.flag_off", item,
                         f"{item.name}: {'now needs' if want else 'no longer needs'} Manager approval",
                         changes={"needs_manager_approval": [not want, want]})
            changed.append((item, want))
    if changed:
        on = [i.name for i, w in changed if w]
        off = [i.name for i, w in changed if not w]
        parts = []
        if on:
            parts.append("Now need Manager approval: " + ", ".join(on[:8]))
        if off:
            parts.append("No longer need it: " + ", ".join(off[:8]))
        notify_role(Role.SECRETARY, "item.flags_changed", "The Manager changed which items need his approval",
                    ". ".join(parts) + ".", reverse("inventory:flags"))
    return len(changed)


# --- item requests: requester side ------------------------------------------------

@transaction.atomic
def create_request(item, qty, reason, user):
    if user.role not in REQUESTER_ROLES:
        raise TransitionError("Only guards and supervisors ask for items here.")
    if not item.is_active:
        raise TransitionError("This item is no longer available.")
    if not 1 <= qty <= MAX_REQUEST_QTY:
        raise TransitionError(f"You can ask for between 1 and {MAX_REQUEST_QTY}.")
    if not reason.strip():
        raise TransitionError("Please say why you need it.")
    status = R.AWAITING_MANAGER if item.needs_manager_approval else R.PENDING
    req = ItemRequest.objects.create(requester=user, requester_role=user.role, item=item, qty_requested=qty,
                                     reason=reason.strip(), status=status)
    audit.record(user, "request.created", req, f"{user} asked for {qty} x {item.name}")
    if status == R.AWAITING_MANAGER:
        notify_role(Role.MANAGER, "request.manager_needed", f"{user} asked for {qty} x {item.name}",
                    f"This item needs your approval. Reason: {reason.strip()[:150]}", office_link(req),
                    Notification.Priority.HIGH, entity=req)
    else:
        notify_role(Role.SECRETARY, "request.new", f"{user} asked for {qty} x {item.name}",
                    f"Reason: {reason.strip()[:150]}", office_link(req), entity=req)
    return req


def cancel_by_requester(req, user):
    if req.requester_id != user.pk:
        raise TransitionError("You can only cancel your own requests.")
    if not advance(req, (R.PENDING, R.AWAITING_MANAGER), R.CANCELLED):
        raise TransitionError("This request can no longer be cancelled. Please speak to the Secretary.")
    audit.record(user, "request.cancelled", req, f"{user} cancelled their request for {req.item.name}")


def claim_return(req, user):
    """'I have returned this item'. Status only. NO stock change: the office must confirm it physically."""
    if req.requester_id != user.pk:
        raise TransitionError("You can only do this for your own items.")
    if not req.item.returnable:
        raise TransitionError("This item was given to you to keep, so it does not need to be returned.")
    if not advance(req, R.ISSUED, R.RETURN_CLAIMED, return_claimed_at=timezone.now()):
        raise TransitionError("This item is not marked as with you right now.")
    audit.record(user, "request.return_claimed", req, f"{user} says they returned {req.qty_issued} x {req.item.name}")
    notify_role(Role.SECRETARY, "request.return_claimed", f"{user} says they returned {req.item.name}",
                "Please check you have it, then approve the return.", office_link(req), entity=req)


# --- item requests: office side -----------------------------------------------------

def _not_own(req, user):
    if user.role not in OFFICE_ROLES:
        raise TransitionError("Only the Secretary or Manager can do this.")
    if req.requester_id == user.pk:
        raise TransitionError("You cannot approve your own request. Ask another member of the office.")


@transaction.atomic
def manager_decide(req, user, approve, reason=""):
    if user.role != Role.MANAGER:
        raise TransitionError("Only the Manager can decide this.")
    _not_own(req, user)
    now = timezone.now()
    if approve:
        if not advance(req, R.AWAITING_MANAGER, R.PENDING, manager_decided_by=user, manager_decided_at=now):
            raise TransitionError("This request was already decided.")
        audit.record(user, "request.manager_approved", req, f"Manager approved {req.requester}'s request for {req.item.name}")
        notify_role(Role.SECRETARY, "request.new", f"Manager approved: {req.qty_requested} x {req.item.name} for {req.requester}",
                    "You can now give it out.", office_link(req), entity=req)
        notify(req.requester, "request.progress", f"The Manager approved your request for {req.item.name}",
               "The Secretary will prepare it.", my_link(req), entity=req)
    else:
        if not reason.strip():
            raise TransitionError("Please give a reason, so the person understands.")
        if not advance(req, R.AWAITING_MANAGER, R.REJECTED, manager_decided_by=user, manager_decided_at=now,
                       reject_reason=reason.strip()):
            raise TransitionError("This request was already decided.")
        audit.record(user, "request.manager_rejected", req, f"Manager rejected {req.requester}'s request for {req.item.name}")
        notify(req.requester, "request.rejected", f"Your request for {req.item.name} was not approved", reason.strip()[:200],
               my_link(req), entity=req)


@transaction.atomic
def approve_request(req, user, qty, expected_return_date=None, hand_over_now=False):
    _not_own(req, user)
    if not 1 <= qty <= req.qty_requested:
        raise TransitionError(f"Give between 1 and {req.qty_requested}.")
    if req.item.returnable:
        if not expected_return_date:
            raise TransitionError("Choose the date it must be returned by.")
        if expected_return_date < timezone.localdate():
            raise TransitionError("The return date cannot be in the past.")
    else:
        expected_return_date = None
    now = timezone.now()
    to = R.ISSUED if hand_over_now else R.READY
    fields = dict(qty_issued=qty, decided_by=user, decided_at=now, expected_return_date=expected_return_date)
    if hand_over_now:
        fields.update(handed_over_by=user, handed_over_at=now)
    if not advance(req, R.PENDING, to, **fields):
        raise TransitionError("This request was already dealt with by someone else.")
    if hand_over_now:
        move_stock(req.item, {"qty_available": -qty, "qty_issued": qty}, A.ISSUED, qty, user, f"Handed to {req.requester}", req)
    else:
        move_stock(req.item, {"qty_available": -qty, "qty_reserved": qty}, A.RESERVED, qty, user, f"Kept for {req.requester}", req)
    audit.record(user, "request.approved", req, f"Approved {qty} x {req.item.name} for {req.requester}"
                 + (" and handed over" if hand_over_now else ""))
    if hand_over_now:
        notify(req.requester, "request.issued", f"You have received {qty} x {req.item.name}",
               _return_text(req), my_link(req), entity=req)
    else:
        notify(req.requester, "request.ready", f"Your {req.item.name} is ready. Collect it from the Secretary",
               f"Quantity: {qty}.", my_link(req), Notification.Priority.HIGH, entity=req)
    return req


def _return_text(req):
    if req.item.returnable and req.expected_return_date:
        return f"Please return it by {req.expected_return_date:%d %B %Y}."
    return "This item is yours to keep."


def reject_request(req, user, reason):
    if user.role not in OFFICE_ROLES:
        raise TransitionError("Only the Secretary or Manager can do this.")
    if not reason.strip():
        raise TransitionError("Please give a reason, so the person understands.")
    if not advance(req, R.PENDING, R.REJECTED, decided_by=user, decided_at=timezone.now(), reject_reason=reason.strip()):
        raise TransitionError("This request was already dealt with.")
    audit.record(user, "request.rejected", req, f"Rejected {req.requester}'s request for {req.item.name}")
    notify(req.requester, "request.rejected", f"Your request for {req.item.name} was not approved", reason.strip()[:200],
           my_link(req), entity=req)


@transaction.atomic
def hand_over(req, user):
    _not_own(req, user)
    if not advance(req, R.READY, R.ISSUED, handed_over_by=user, handed_over_at=timezone.now()):
        raise TransitionError("This item is not waiting for collection.")
    move_stock(req.item, {"qty_reserved": -req.qty_issued, "qty_issued": req.qty_issued}, A.ISSUED, req.qty_issued,
               user, f"Handed to {req.requester}", req)
    audit.record(user, "request.handed_over", req, f"Handed {req.qty_issued} x {req.item.name} to {req.requester}")
    notify(req.requester, "request.issued", f"You have received {req.qty_issued} x {req.item.name}", _return_text(req),
           my_link(req), entity=req)


@transaction.atomic
def cancel_approval(req, user, reason):
    if user.role not in OFFICE_ROLES:
        raise TransitionError("Only the Secretary or Manager can do this.")
    if not reason.strip():
        raise TransitionError("Please give a reason.")
    if not advance(req, R.READY, R.CANCELLED, reject_reason=reason.strip()):
        raise TransitionError("This item is not waiting for collection.")
    move_stock(req.item, {"qty_reserved": -req.qty_issued, "qty_available": req.qty_issued}, A.RELEASED, req.qty_issued,
               user, reason.strip(), req)
    audit.record(user, "request.approval_cancelled", req, f"Cancelled uncollected {req.item.name} for {req.requester}")
    notify(req.requester, "request.cancelled", f"Your {req.item.name} is no longer being kept for you", reason.strip()[:200],
           my_link(req), entity=req)


@transaction.atomic
def approve_return(req, user, good, damaged, lost, notes=""):
    """The Secretary/Manager confirms what physically came back. The requester can never do this."""
    _not_own(req, user)
    if not req.item.returnable:
        raise TransitionError("This item was issued to keep, so there is nothing to return.")
    good, damaged, lost = int(good or 0), int(damaged or 0), int(lost or 0)
    if min(good, damaged, lost) < 0:
        raise TransitionError("Numbers cannot be below zero.")
    if good + damaged + lost != req.qty_issued:
        raise TransitionError(f"Good + damaged + lost must add up to {req.qty_issued}, the number that was handed out.")
    if (damaged or lost) and not notes.strip():
        raise TransitionError("Please write what happened to the damaged or lost items.")
    to = R.LOST if lost == req.qty_issued else R.RETURNED
    if not advance(req, (R.ISSUED, R.RETURN_CLAIMED), to, return_approved_by=user, return_approved_at=timezone.now(),
                   qty_returned_good=good, qty_returned_damaged=damaged, qty_lost=lost, return_notes=notes.strip()):
        raise TransitionError("This item is not out with anyone right now.")
    who = f"from {req.requester}"
    if good:
        move_stock(req.item, {"qty_issued": -good, "qty_available": good}, A.RETURNED_GOOD, good, user, f"Returned {who}", req)
    if damaged:
        move_stock(req.item, {"qty_issued": -damaged, "qty_damaged": damaged}, A.RETURNED_DAMAGED, damaged, user,
                   f"Returned damaged {who}: {notes.strip()}", req)
    if lost:
        move_stock(req.item, {"qty_issued": -lost, "qty_lost": lost}, A.LOST, lost, user, f"Lost by {req.requester}: {notes.strip()}", req)
    audit.record(user, "request.return_approved", req,
                 f"Return of {req.item.name} {who} checked: {good} good, {damaged} damaged, {lost} lost",
                 changes={"good": good, "damaged": damaged, "lost": lost})
    notify(req.requester, "request.returned", f"Return of {req.item.name} confirmed",
           f"Received: {good} in good condition" + (f", {damaged} damaged" if damaged else "") + (f", {lost} lost" if lost else "") + ".",
           my_link(req), entity=req)
    if damaged or lost:
        notify_role(Role.MANAGER, "request.damaged_lost", f"{req.item.name}: {damaged} damaged, {lost} lost ({req.requester})",
                    notes.strip()[:200], office_link(req), Notification.Priority.HIGH, entity=req)
    return req


def not_received(req, user, note):
    if user.role not in OFFICE_ROLES:
        raise TransitionError("Only the Secretary or Manager can do this.")
    if not note.strip():
        raise TransitionError("Please write a short note for the person.")
    if not advance(req, R.RETURN_CLAIMED, R.ISSUED, return_claimed_at=None):
        raise TransitionError("Nobody has said this item was returned.")
    audit.record(user, "request.return_not_received", req, f"{req.item.name} not received back from {req.requester}: {note.strip()[:100]}")
    notify(req.requester, "request.not_received", f"The office has not received your {req.item.name}",
           note.strip()[:200], my_link(req), Notification.Priority.HIGH, entity=req)


def remind(req, user=None):
    """One reminder per day at most. Returns True if sent."""
    today = timezone.localdate()
    if req.status != R.ISSUED or not req.item.returnable:
        raise TransitionError("Reminders are only for returnable items that are still out.")
    start_of_today = timezone.make_aware(datetime.combine(today, time.min))
    updated = ItemRequest.objects.filter(pk=req.pk, status=R.ISSUED).exclude(last_reminder_at__gte=start_of_today).update(
        last_reminder_at=timezone.now()
    )
    if not updated:
        raise TransitionError("A reminder was already sent today.")
    late = req.expected_return_date and req.expected_return_date < today
    notify(req.requester, "request.reminder",
           f"Please return {req.qty_issued} x {req.item.name}" + (" (it is late)" if late else ""),
           f"It was due back on {req.expected_return_date:%d %B %Y}." if req.expected_return_date else "",
           my_link(req), Notification.Priority.HIGH, entity=req)
    if user is not None:
        audit.record(user, "request.reminded", req, f"Reminded {req.requester} to return {req.item.name}")
    return True


def overdue_requests(today=None):
    today = today or timezone.localdate()
    return ItemRequest.objects.filter(
        status__in=(R.ISSUED, R.RETURN_CLAIMED), item__returnable=True, expected_return_date__lt=today
    ).select_related("item", "requester")


def daily_item_checks(today=None):
    """Reminders for overdue items (at most once a day each) and a Manager alert for items 7+ days late."""
    today = today or timezone.localdate()
    reminded = 0
    for req in overdue_requests(today).filter(status=R.ISSUED):
        try:
            remind(req)
            reminded += 1
        except TransitionError:
            pass
    very_late = overdue_requests(today).filter(expected_return_date__lt=today - timedelta(days=7))
    count = very_late.count()
    if count and reminded:
        notify_role(Role.MANAGER, "request.very_late", f"{count} item(s) are more than 7 days late",
                    ", ".join(f"{r.item.name} ({r.requester})" for r in very_late[:6]),
                    reverse("inventory:overdue"), Notification.Priority.HIGH)
    if reminded:
        notify_role(Role.SECRETARY, "request.overdue", f"{reminded} overdue item reminder(s) sent", "",
                    reverse("inventory:overdue"))
    return reminded


def requests_visible_to(user):
    qs = ItemRequest.objects.select_related("item", "requester")
    if user.role in OFFICE_ROLES:
        return qs
    return qs.filter(requester=user)


def steps_for(req):
    """Plain progress steps for the requester's page: (label, state) with state done/now/todo/bad."""
    returnable = req.item.returnable
    flow = []
    if req.status == R.AWAITING_MANAGER or req.manager_decided_at:
        flow.append(("awaiting_manager", "Manager approval"))
    flow += [("pending", "Request sent to the Secretary"), ("ready", "Approved: collect it from the Secretary"),
             ("issued", "You have the item")]
    if returnable:
        flow += [("return_claimed", "You said you returned it"), ("returned", "Return confirmed by the Secretary")]
    order = [k for k, _ in flow]
    if req.status in (R.REJECTED, R.CANCELLED, R.LOST):
        reached = order.index("issued") if req.status == R.LOST else 0
        steps = [(label, "done" if i < reached else "todo") for i, (_, label) in enumerate(flow)]
        steps.append((req.get_status_display(), "bad"))
        return steps
    current = order.index(req.status) if req.status in order else 0
    if req.status == R.ISSUED and not returnable:
        return [(label, "done") for _, label in flow]
    return [(label, "done" if i < current or (req.status == R.RETURNED and i == current) else "now" if i == current else "todo")
            for i, (_, label) in enumerate(flow)]
