"""Workflow rules for clients, supervisor assignment, client issues, feedback and messages."""
from django.core.cache import cache
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from core.services import audit, mail
from core.services.files import save_attachment
from core.workflow import TransitionError, advance
from notifications.models import Notification
from notifications.services import notify, notify_role

from .models import Client, Feedback, Issue, IssueNote, Message, SupervisorAssignment

CLIENT_FIELDS = [
    "name", "contact_person", "phone", "email", "physical_address", "postal_address", "area",
    "service_description", "contract_start", "contract_end", "monthly_charge", "kra_pin", "notes",
]
OPEN_ISSUE_STATUSES = (
    Issue.Status.NEW, Issue.Status.SUPERVISOR_NEEDED, Issue.Status.ASSIGNED,
    Issue.Status.IN_PROGRESS, Issue.Status.WAITING_FEEDBACK,
)
EMAILS_PER_MINUTE = 20


def possible_duplicates(name, email="", phone="", exclude_pk=None):
    from django.db.models import Q

    q = Q(name__iexact=name.strip())
    if email:
        q |= Q(email__iexact=email.strip())
    if phone:
        q |= Q(phone=phone.strip())
    qs = Client.objects.filter(q)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs


# --- clients ------------------------------------------------------------------

@transaction.atomic
def create_client(client, user):
    client.created_by = user
    supervisor = client.supervisor
    client.supervisor = None
    client.save()
    audit.record(user, "client.created", client, f"Created client {client.name}",
                 changes=audit.snapshot(client, CLIENT_FIELDS))
    if supervisor:
        assign_supervisor(client, supervisor, user, move_open_issues=False)
    return client


@transaction.atomic
def update_client(client, user, before):
    """`before` is audit.snapshot() of the client taken before the form changed it."""
    client.save()
    changes = audit.changes_between(before, audit.snapshot(client, CLIENT_FIELDS))
    if changes:
        audit.record(user, "client.updated", client, f"Edited client {client.name}", changes=changes)
    return client


@transaction.atomic
def assign_supervisor(client, supervisor, user, move_open_issues=True):
    if supervisor is not None and (supervisor.role != Role.SUPERVISOR or not supervisor.is_active):
        raise TransitionError("Only an active supervisor can be made responsible for a client.")
    old = client.supervisor
    if old == supervisor and client.assignments.filter(ended_at__isnull=True).exists():
        return 0
    now = timezone.now()
    client.assignments.filter(ended_at__isnull=True).update(ended_at=now)
    SupervisorAssignment.objects.create(client=client, supervisor=supervisor, started_at=now, assigned_by=user)
    Client.objects.filter(pk=client.pk).update(supervisor=supervisor, updated_at=now)
    client.supervisor = supervisor
    moved = 0
    if move_open_issues:
        for issue in client.issues.filter(status__in=OPEN_ISSUE_STATUSES).exclude(supervisor=supervisor):
            _set_issue_supervisor(issue, supervisor, user, notify_people=False)
            moved += 1
    audit.record(
        user, "client.supervisor_assigned", client,
        f"Made {supervisor or 'nobody'} responsible for {client.name}",
        changes={"supervisor": [str(old) if old else None, str(supervisor) if supervisor else None]},
    )
    link = reverse("clients:detail", args=[client.pk])
    if supervisor:
        extra = f" {moved} open issue(s) were moved to you." if moved else ""
        notify(supervisor, "client.assigned", f"You are now responsible for {client.name}",
               f"The office has made you the supervisor for this client.{extra}", link, entity=client)
    if old and old != supervisor:
        notify(old, "client.unassigned", f"{client.name} has a new supervisor",
               f"{supervisor or 'Nobody'} is now responsible for this client.", link, entity=client)
    return moved


@transaction.atomic
def set_client_active(client, active, user):
    if client.is_active == active:
        return
    Client.objects.filter(pk=client.pk).update(is_active=active, updated_at=timezone.now())
    client.is_active = active
    word = "Reactivated" if active else "Deactivated"
    audit.record(user, "client.reactivated" if active else "client.deactivated", client, f"{word} client {client.name}",
                 changes={"is_active": [not active, active]})
    if not active and client.supervisor:
        notify(client.supervisor, "client.deactivated", f"{client.name} is no longer an active client",
               "The office has deactivated this client.", reverse("clients:detail", args=[client.pk]), entity=client)


def supervisor_deactivated(supervisor, user):
    """Called when a supervisor account is switched off: their clients need a new supervisor."""
    clients = list(Client.objects.filter(supervisor=supervisor, is_active=True))
    for client in clients:
        assign_supervisor(client, None, user, move_open_issues=True)
    if clients:
        names = ", ".join(c.name for c in clients[:5])
        notify_role(Role.SECRETARY, "client.supervisor_needed", "Clients need a new supervisor",
                    f"{supervisor} was deactivated. These clients have no supervisor now: {names}.",
                    reverse("clients:list") + "?supervisor=none", Notification.Priority.HIGH)


# --- issues -------------------------------------------------------------------

# (from, to) -> who may make that move: "supervisor" = the assigned supervisor, "office" = Secretary/Manager.
ISSUE_TRANSITIONS = {
    (Issue.Status.ASSIGNED, Issue.Status.IN_PROGRESS): {"supervisor", "office"},
    (Issue.Status.IN_PROGRESS, Issue.Status.WAITING_FEEDBACK): {"supervisor", "office"},
    (Issue.Status.WAITING_FEEDBACK, Issue.Status.IN_PROGRESS): {"supervisor", "office"},
    (Issue.Status.ASSIGNED, Issue.Status.RESOLVED): {"supervisor", "office"},
    (Issue.Status.IN_PROGRESS, Issue.Status.RESOLVED): {"supervisor", "office"},
    (Issue.Status.WAITING_FEEDBACK, Issue.Status.RESOLVED): {"supervisor", "office"},
    (Issue.Status.RESOLVED, Issue.Status.CLOSED): {"office"},
    (Issue.Status.RESOLVED, Issue.Status.IN_PROGRESS): {"office"},
    (Issue.Status.CLOSED, Issue.Status.IN_PROGRESS): {"office"},
}
NOTE_REQUIRED = {Issue.Status.RESOLVED, Issue.Status.IN_PROGRESS}  # resolving or reopening needs a reason

ACTION_LABELS = {
    Issue.Status.IN_PROGRESS: "Start work",
    Issue.Status.WAITING_FEEDBACK: "Waiting for client",
    Issue.Status.RESOLVED: "Mark resolved",
    Issue.Status.CLOSED: "Close issue",
}


def actor_kind(issue, user):
    if user.role in (Role.SECRETARY, Role.MANAGER):
        return "office"
    if user.role == Role.SUPERVISOR and issue.supervisor_id == user.pk:
        return "supervisor"
    return None


def allowed_moves(issue, user):
    kind = actor_kind(issue, user)
    moves = []
    for (src, dst), who in ISSUE_TRANSITIONS.items():
        if src == issue.status and kind in who:
            label = "Reopen" if src in (Issue.Status.RESOLVED, Issue.Status.CLOSED) and dst == Issue.Status.IN_PROGRESS else ACTION_LABELS[dst]
            moves.append((dst, label))
    return moves


def issue_link(issue):
    return reverse("clients:issue_detail", args=[issue.pk])


@transaction.atomic
def create_issue(client, subject, description, priority, user, upload=None, source_feedback=None):
    sup = client.supervisor if client.supervisor and client.supervisor.is_active else None
    issue = Issue.objects.create(
        client=client, subject=subject, description=description, priority=priority, created_by=user,
        supervisor=sup, status=Issue.Status.ASSIGNED if sup else Issue.Status.SUPERVISOR_NEEDED,
        source_feedback=source_feedback,
    )
    if upload:
        save_attachment(issue, upload, user)
    if sup:
        IssueNote.objects.create(issue=issue, author=None, body=f"Assigned to {sup} (the client's supervisor).",
                                 status_from=Issue.Status.NEW, status_to=issue.status)
        notify(sup, "issue.assigned", f"New client issue: {subject}", f"{client.name} · priority {issue.get_priority_display()}.",
               issue_link(issue), _priority(issue), entity=issue)
    else:
        IssueNote.objects.create(issue=issue, author=None, body="This client has no supervisor. Please assign one.",
                                 status_from=Issue.Status.NEW, status_to=issue.status)
        notify_role(Role.SECRETARY, "issue.supervisor_needed", f"Supervisor needed: {subject}",
                    f"{client.name} has no supervisor, so this issue is waiting for you to assign one.",
                    issue_link(issue), Notification.Priority.HIGH, entity=issue)
    audit.record(user, "issue.created", issue, f"Created issue {issue.number} for {client.name}")
    return issue


def _priority(issue):
    return Notification.Priority.HIGH if issue.priority in (Issue.Priority.HIGH, Issue.Priority.URGENT) else Notification.Priority.NORMAL


def _set_issue_supervisor(issue, supervisor, user, notify_people=True):
    old = issue.supervisor
    new_status = issue.status
    if supervisor and issue.status == Issue.Status.SUPERVISOR_NEEDED:
        new_status = Issue.Status.ASSIGNED
    elif not supervisor and issue.status in OPEN_ISSUE_STATUSES:
        new_status = Issue.Status.SUPERVISOR_NEEDED
    Issue.objects.filter(pk=issue.pk).update(supervisor=supervisor, status=new_status, updated_at=timezone.now())
    IssueNote.objects.create(issue=issue, author=user, body=f"Supervisor changed from {old or 'nobody'} to {supervisor or 'nobody'}.",
                             status_from=issue.status, status_to=new_status)
    issue.supervisor, issue.status = supervisor, new_status
    audit.record(user, "issue.assigned", issue, f"Assigned {issue.number} to {supervisor or 'nobody'}",
                 changes={"supervisor": [str(old) if old else None, str(supervisor) if supervisor else None]})
    if notify_people:
        if supervisor:
            notify(supervisor, "issue.assigned", f"Client issue assigned to you: {issue.subject}",
                   f"{issue.client.name} · priority {issue.get_priority_display()}.", issue_link(issue), _priority(issue), entity=issue)
        if old and old != supervisor:
            notify(old, "issue.reassigned", f"Issue moved to {supervisor or 'the office'}: {issue.subject}", "", issue_link(issue), entity=issue)


@transaction.atomic
def assign_issue(issue, supervisor, user):
    if supervisor.role != Role.SUPERVISOR or not supervisor.is_active:
        raise TransitionError("Only an active supervisor can be assigned.")
    if issue.status in (Issue.Status.RESOLVED, Issue.Status.CLOSED):
        raise TransitionError("Reopen the issue before giving it to another supervisor.")
    if issue.supervisor_id == supervisor.pk:
        return
    _set_issue_supervisor(issue, supervisor, user)


@transaction.atomic
def change_issue_status(issue, to_status, user, note=""):
    who = ISSUE_TRANSITIONS.get((issue.status, to_status))
    kind = actor_kind(issue, user)
    if not who or kind not in who:
        raise TransitionError("That change is not allowed for this issue right now.")
    reopening = to_status == Issue.Status.IN_PROGRESS and issue.status in (Issue.Status.RESOLVED, Issue.Status.CLOSED)
    if (to_status == Issue.Status.RESOLVED or reopening) and not note.strip():
        raise TransitionError("Please write a short note explaining this.")
    now = timezone.now()
    old = issue.status
    fields = {}
    if to_status == Issue.Status.RESOLVED:
        fields = dict(resolved_by=user, resolved_at=now, resolution_note=note.strip())
    elif to_status == Issue.Status.CLOSED:
        fields = dict(closed_by=user, closed_at=now)
    elif reopening:
        fields = dict(closed_by=None, closed_at=None)
    if not advance(issue, old, to_status, **fields):
        raise TransitionError("This issue was just changed by someone else. Please check it again.")
    IssueNote.objects.create(issue=issue, author=user, body=note.strip(), status_from=old, status_to=to_status)
    audit.record(user, "issue.status_changed", issue, f"{issue.number}: {Issue.Status(old).label} → {Issue.Status(to_status).label}",
                 changes={"status": [old, to_status]})
    link = issue_link(issue)
    label = Issue.Status(to_status).label
    if kind == "supervisor":
        notify_role(Role.SECRETARY, "issue.progress", f"{user} updated {issue.number}: {label}",
                    note.strip()[:200] or issue.subject, link, entity=issue)
    elif issue.supervisor:
        notify(issue.supervisor, "issue.status", f"{issue.number} is now {label.lower()}", note.strip()[:200] or issue.subject, link, entity=issue)
    return issue


@transaction.atomic
def add_issue_note(issue, user, body, upload=None):
    if not actor_kind(issue, user):
        raise TransitionError("You cannot add notes to this issue.")
    if not body.strip() and not upload:
        raise TransitionError("Write a note or attach a file.")
    note = IssueNote.objects.create(issue=issue, author=user, body=body.strip())
    if upload:
        save_attachment(issue, upload, user)
    Issue.objects.filter(pk=issue.pk).update(updated_at=timezone.now())
    if user.role == Role.SUPERVISOR:
        notify_role(Role.SECRETARY, "issue.note", f"{user} added a note to {issue.number}", body.strip()[:200], issue_link(issue), entity=issue)
    elif issue.supervisor and issue.supervisor != user:
        notify(issue.supervisor, "issue.note", f"New note on {issue.number}", body.strip()[:200], issue_link(issue), entity=issue)
    return note


# --- feedback -----------------------------------------------------------------

def feedback_link(fb):
    return reverse("clients:feedback_detail", args=[fb.pk])


@transaction.atomic
def record_feedback(fb, user):
    fb.recorded_by = user
    fb.save()
    audit.record(user, "feedback.recorded", fb, f"Recorded {fb.get_kind_display().lower()} from {fb.client.name}")
    return fb


def review_feedback(fb, user):
    if not advance(fb, Feedback.Status.NEW, Feedback.Status.REVIEWED, reviewed_by=user, reviewed_at=timezone.now()):
        raise TransitionError("This feedback has already been reviewed.")


@transaction.atomic
def respond_to_feedback(fb, user, response, channel):
    if fb.status in (Feedback.Status.CLOSED,):
        raise TransitionError("This feedback is closed.")
    if not response.strip():
        raise TransitionError("Write the response first.")
    if channel == Feedback.Channel.EMAIL:
        msg = Message.objects.create(
            client=fb.client, kind=Message.Kind.FEEDBACK_RESPONSE, subject=f"Re: {fb.subject}", body=response.strip(),
            created_by=user, related_type=_ct(fb), related_id=fb.pk,
        )
        ok, error = send_message(msg, user)
        if not ok:
            raise TransitionError(error)
    Feedback.objects.filter(pk=fb.pk).update(
        status=Feedback.Status.RESPONDED, response=response.strip(), response_channel=channel,
        responded_by=user, responded_at=timezone.now(),
        reviewed_by=fb.reviewed_by or user, reviewed_at=fb.reviewed_at or timezone.now(),
    )
    fb.refresh_from_db()
    audit.record(user, "feedback.responded", fb, f"Responded to feedback from {fb.client.name} by {fb.get_response_channel_display()}")


def close_feedback(fb, user):
    if not advance(fb, [s for s in Feedback.Status.values if s != Feedback.Status.CLOSED], Feedback.Status.CLOSED,
                   closed_by=user, closed_at=timezone.now()):
        raise TransitionError("This feedback is already closed.")
    audit.record(user, "feedback.closed", fb, f"Closed feedback from {fb.client.name}")


def feedback_to_issue(fb, user):
    return create_issue(fb.client, fb.subject, fb.body, Issue.Priority.NORMAL, user, source_feedback=fb)


def _ct(obj):
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(obj)


# --- client messages (email) ---------------------------------------------------

def _rate_limited(user):
    key = f"emails-sent:{user.pk}:{timezone.now():%Y%m%d%H%M}"
    count = cache.get_or_set(key, 0, 70)
    if count >= EMAILS_PER_MINUTE:
        return True
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, 70)
    return False


def send_message(msg, user, attachments=()):
    """Email a client message. Returns (ok, error). The message is updated either way."""
    if msg.status not in (Message.Status.DRAFT, Message.Status.FAILED):
        return False, "This message has already been sent."
    client = msg.client
    if not client.email:
        return False, "This client has no email address. Add one to the client first, or record that you told them by phone."
    if _rate_limited(user):
        return False, "Too many emails in one minute. Please wait a moment and try again."
    from core.services.files import attachments_for

    files = list(attachments)
    for att in attachments_for(msg):
        with att.file.open("rb") as fh:
            files.append((att.original_name, fh.read(), att.mime_type))
    body = f"Dear {client.contact_person or client.name},\n\n{msg.body}\n\n{_signature()}"
    ok, error = mail.send(client.email, msg.subject, body, files)
    now = timezone.now()
    Message.objects.filter(pk=msg.pk).update(
        status=Message.Status.SENT if ok else Message.Status.FAILED, error=error, to_email=client.email,
        sent_by=user if ok else None, sent_at=now if ok else None,
    )
    msg.refresh_from_db()
    if ok:
        audit.record(user, "message.sent", msg, f"Emailed {client.name}: {msg.subject}")
    return ok, error


def record_offline(msg, user):
    if not advance(msg, (Message.Status.DRAFT, Message.Status.FAILED), Message.Status.RECORDED_OFFLINE,
                   sent_by=user, sent_at=timezone.now()):
        raise TransitionError("This message has already been sent.")
    audit.record(user, "message.recorded_offline", msg, f"Recorded message to {msg.client.name} as delivered by phone/in person")


def _signature():
    from core.models import CompanySettings

    s = CompanySettings.load()
    lines = [s.company_name or "Resilience Security", s.phone, s.email]
    return "Kind regards,\n" + "\n".join(x for x in lines if x)


def active_supervisors():
    return User.objects.filter(role=Role.SUPERVISOR, is_active=True)


# --- GPS site links -------------------------------------------------------------

@transaction.atomic
def set_client_sites(client, sites, user):
    from .models import ClientSite

    wanted = {s.pk for s in sites}
    current = set(client.site_links.values_list("site_id", flat=True))
    taken = ClientSite.objects.filter(site_id__in=wanted - current).exclude(client=client)
    if taken.exists():
        raise TransitionError(f"{taken.first().site} already belongs to another client.")
    client.site_links.filter(site_id__in=current - wanted).delete()
    ClientSite.objects.bulk_create([ClientSite(client=client, site_id=pk) for pk in wanted - current])
    if wanted != current:
        audit.record(user, "client.sites_changed", client, f"Changed GPS sites for {client.name}",
                     changes={"sites": [sorted(current), sorted(wanted)]})


# --- who sees what --------------------------------------------------------------

def issues_visible_to(user):
    qs = Issue.objects.select_related("client", "supervisor")
    if user.role in (Role.SECRETARY, Role.MANAGER):
        return qs
    if user.role == Role.SUPERVISOR:
        return qs.filter(supervisor=user)
    return qs.none()


def clients_visible_to(user):
    if user.role in (Role.SECRETARY, Role.MANAGER):
        return Client.objects.all()
    if user.role == Role.SUPERVISOR:
        return Client.objects.filter(supervisor=user)
    return Client.objects.none()
