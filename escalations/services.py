"""'Send to Manager': the Secretary passes a matter to the Manager, linked to the original record."""
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from core.services import audit
from core.workflow import TransitionError, advance
from notifications.models import Notification
from notifications.services import notify, notify_role

from .models import Escalation, EscalationReply

E = Escalation.Status


def record_types():
    from clients.models import Feedback, Issue
    from inventory.models import Item
    from payroll.models import PayrollRun

    return {
        Escalation.Kind.ISSUE: Issue, Escalation.Kind.FEEDBACK: Feedback,
        Escalation.Kind.ITEM: Item, Escalation.Kind.PAYROLL: PayrollRun,
    }


def find_record(kind, pk):
    model = record_types().get(kind)
    if model is None or not str(pk).isdigit():
        return None
    return model.objects.filter(pk=int(pk)).first()


def open_escalation(obj):
    return Escalation.objects.filter(
        content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk
    ).exclude(status=E.RESOLVED).first()


def link(esc):
    return reverse("escalations:detail", args=[esc.pk])


@transaction.atomic
def raise_escalation(kind, record, subject, note, user):
    if user.role != Role.SECRETARY:
        raise TransitionError("Only the Secretary sends matters to the Manager.")
    if not note.strip():
        raise TransitionError("Write what you need from the Manager.")
    if record is not None and open_escalation(record):
        raise TransitionError("This has already been sent to the Manager and is still open.")
    esc = Escalation(kind=kind, subject=subject.strip()[:200] or str(record)[:200], note=note.strip(), raised_by=user)
    if record is not None:
        esc.content_type = ContentType.objects.get_for_model(record)
        esc.object_id = record.pk
    try:
        with transaction.atomic():
            esc.save()
    except IntegrityError:
        raise TransitionError("This has already been sent to the Manager and is still open.")
    confidential = kind == Escalation.Kind.PAYROLL
    audit.record(user, "escalation.raised", esc, f"Sent to Manager: {esc.subject}", confidential=confidential)
    if kind == Escalation.Kind.FEEDBACK and record is not None:
        from clients.models import Feedback

        Feedback.objects.filter(pk=record.pk).exclude(status=Feedback.Status.CLOSED).update(status=Feedback.Status.ESCALATED)
    notify_role(Role.MANAGER, "escalation.new", f"Sent to you: {esc.subject}", note.strip()[:200], link(esc),
                Notification.Priority.HIGH, entity=esc)
    return esc


def manager_seen(esc, user):
    if user.role == Role.MANAGER and advance(esc, E.OPEN, E.SEEN, seen_at=timezone.now()):
        notify(esc.raised_by, "escalation.seen", f"The Manager has seen: {esc.subject}", "", link(esc), entity=esc)


@transaction.atomic
def reply(esc, user, body):
    if user.role not in (Role.MANAGER, Role.SECRETARY):
        raise TransitionError("You cannot reply here.")
    if esc.status == E.RESOLVED:
        raise TransitionError("This matter is resolved.")
    if not body.strip():
        raise TransitionError("Write your reply first.")
    EscalationReply.objects.create(escalation=esc, author=user, body=body.strip())
    if user.role == Role.SECRETARY:
        advance(esc, E.SENT_BACK, E.SEEN)
        notify_role(Role.MANAGER, "escalation.reply", f"Secretary replied: {esc.subject}", body.strip()[:200], link(esc), entity=esc)
    else:
        notify(esc.raised_by, "escalation.reply", f"Manager replied: {esc.subject}", body.strip()[:200], link(esc),
               Notification.Priority.HIGH, entity=esc)
    audit.record(user, "escalation.reply", esc, f"Replied on: {esc.subject}", confidential=esc.kind == Escalation.Kind.PAYROLL)


def send_back(esc, user, note):
    if user.role != Role.MANAGER:
        raise TransitionError("Only the Manager can do this.")
    if not note.strip():
        raise TransitionError("Write what the Secretary should do.")
    if not advance(esc, (E.OPEN, E.SEEN), E.SENT_BACK):
        raise TransitionError("This matter was already changed.")
    EscalationReply.objects.create(escalation=esc, author=user, body=note.strip())
    audit.record(user, "escalation.sent_back", esc, f"Sent back to Secretary: {esc.subject}", confidential=esc.kind == Escalation.Kind.PAYROLL)
    notify(esc.raised_by, "escalation.sent_back", f"Manager sent back: {esc.subject}", note.strip()[:200], link(esc),
           Notification.Priority.HIGH, entity=esc)


def resolve(esc, user, note):
    if user.role != Role.MANAGER:
        raise TransitionError("Only the Manager can do this.")
    if not note.strip():
        raise TransitionError("Write how this was resolved.")
    if not advance(esc, (E.OPEN, E.SEEN, E.SENT_BACK), E.RESOLVED, resolved_by=user, resolved_at=timezone.now(),
                   resolution_note=note.strip()):
        raise TransitionError("This matter is already resolved.")
    audit.record(user, "escalation.resolved", esc, f"Resolved: {esc.subject}", confidential=esc.kind == Escalation.Kind.PAYROLL)
    notify(esc.raised_by, "escalation.resolved", f"Manager resolved: {esc.subject}", note.strip()[:200], link(esc), entity=esc)
