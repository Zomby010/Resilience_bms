"""Incident reports: who is told, who may review or close, and the note trail."""
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from core.services import audit
from core.services.files import save_attachment
from core.workflow import TransitionError, require
from notifications.models import Notification
from notifications.services import notify
from operations.models import OBEntry
from operations.services import write_ob

from .models import Incident, IncidentNote

S = Incident.Status
# Incidents happen at sites: guards and supervisors report them. The Manager reads and decides on them from
# the to-do list and the site page; the Secretary has no incident pages and is not told about them.
REPORTERS = (Role.STAFF, Role.SUPERVISOR)
VIEWERS = (Role.STAFF, Role.SUPERVISOR, Role.MANAGER)
OFFICE = (Role.MANAGER,)
MAX_PHOTOS = 5

OBKind = OBEntry.Kind


def link(incident):
    return reverse("incidents:detail", args=[incident.pk])


def _note(incident, user, body="", status_from="", status_to=""):
    return IncidentNote.objects.create(incident=incident, author=user, body=(body or "").strip(),
                                       status_from=status_from, status_to=status_to)


# --- reporting ------------------------------------------------------------------

def people_to_tell(incident):
    """The reporter's supervisor and the site's supervisor; the Manager too when it is serious."""
    people = [incident.reported_by.supervisor, incident.site.supervisor]
    if incident.serious:
        people += list(User.objects.filter(role=Role.MANAGER, is_active=True))
    return [p for p in people if p is not None and p.pk != incident.reported_by_id]


@transaction.atomic
def create_incident(incident, user, photos=()):
    if user.role not in REPORTERS:
        raise TransitionError("You cannot report incidents.")
    if len(photos) > MAX_PHOTOS:
        raise TransitionError(f"You can add up to {MAX_PHOTOS} photos.")
    incident.reported_by = user
    incident.status = S.REPORTED
    incident.clean()
    incident.save()
    for upload in photos:
        save_attachment(incident, upload, user)
    _note(incident, user, "Incident reported.", status_to=S.REPORTED)
    write_ob(incident.site, user, OBKind.INCIDENT, f"{incident.number}: {incident.get_kind_display()} "
             f"({incident.get_severity_display().lower()}). {incident.what_happened[:300]}",
             occurred_at=incident.occurred_at, incident=incident, check=False)
    audit.record(user, "incident.reported", incident,
                 f"Reported {incident.number}: {incident.get_kind_display()} at {incident.site} ({incident.get_severity_display()})")
    priority = Notification.Priority.HIGH if incident.serious else Notification.Priority.NORMAL
    notify(people_to_tell(incident), "incident.new",
           f"{incident.get_severity_display()} incident {incident.number}: {incident.get_kind_display()} at {incident.site}",
           f"Reported by {user}. {incident.what_happened[:200]}", link(incident), priority, entity=incident)
    return incident


# --- who may do what --------------------------------------------------------------

def can_supervisor_review(incident, user):
    return (
        user.role == Role.SUPERVISOR and incident.status == S.REPORTED and incident.reported_by_id != user.pk
        and user.pk in (incident.site.supervisor_id, incident.reported_by.supervisor_id)
    )


def can_manager_review(incident, user):
    return user.role == Role.MANAGER and incident.status in (S.REPORTED, S.SUPERVISOR_REVIEWED)


def can_close(incident, user):
    return user.role in OFFICE and incident.status != S.CLOSED


def can_reopen(incident, user):
    return user.role == Role.MANAGER and incident.status == S.CLOSED


def actions_for(incident, user):
    return {
        "note": incident.status != S.CLOSED,
        "supervisor_review": can_supervisor_review(incident, user),
        "manager_review": can_manager_review(incident, user),
        "close": can_close(incident, user),
        "reopen": can_reopen(incident, user),
    }


# --- actions ----------------------------------------------------------------------

@transaction.atomic
def add_note(incident, user, body):
    if incident.status == S.CLOSED:
        raise TransitionError("This incident is closed. Ask the Manager to reopen it first.")
    if not body.strip():
        raise TransitionError("Write your note first.")
    note = _note(incident, user, body)
    Incident.objects.filter(pk=incident.pk).update(updated_at=timezone.now())
    audit.record(user, "incident.note", incident, f"Added a note to {incident.number}")
    return note


@transaction.atomic
def supervisor_review(incident, user, note=""):
    if not can_supervisor_review(incident, user):
        raise TransitionError("Only the supervisor of this site or of the person who reported it can do this, once.")
    require(incident, S.REPORTED, S.SUPERVISOR_REVIEWED, supervisor_reviewed_by=user, supervisor_reviewed_at=timezone.now())
    _note(incident, user, note, S.REPORTED, S.SUPERVISOR_REVIEWED)
    audit.record(user, "incident.supervisor_reviewed", incident, f"Supervisor reviewed {incident.number}")


@transaction.atomic
def manager_review(incident, user, note=""):
    if user.role != Role.MANAGER:
        raise TransitionError("Only the Manager can do this.")
    before = incident.status
    require(incident, (S.REPORTED, S.SUPERVISOR_REVIEWED), S.MANAGER_REVIEWED,
            manager_reviewed_by=user, manager_reviewed_at=timezone.now())
    _note(incident, user, note, before, S.MANAGER_REVIEWED)
    audit.record(user, "incident.manager_reviewed", incident, f"Manager reviewed {incident.number}")


@transaction.atomic
def close(incident, user, note=""):
    if user.role not in OFFICE:
        raise TransitionError("Only the Manager can close an incident.")
    before = incident.status
    require(incident, (S.REPORTED, S.SUPERVISOR_REVIEWED, S.MANAGER_REVIEWED), S.CLOSED,
            closed_by=user, closed_at=timezone.now())
    _note(incident, user, note, before, S.CLOSED)
    audit.record(user, "incident.closed", incident, f"Closed {incident.number}")
    if incident.reported_by_id != user.pk:
        notify(incident.reported_by, "incident.closed", f"Your incident {incident.number} is closed",
               note.strip()[:200], link(incident), entity=incident)


@transaction.atomic
def reopen(incident, user, note):
    if user.role != Role.MANAGER:
        raise TransitionError("Only the Manager can reopen an incident.")
    if not note.strip():
        raise TransitionError("Write why it is being reopened.")
    require(incident, S.CLOSED, S.MANAGER_REVIEWED, closed_by=None, closed_at=None)
    _note(incident, user, note, S.CLOSED, S.MANAGER_REVIEWED)
    audit.record(user, "incident.reopened", incident, f"Reopened {incident.number}")


# --- for dashboards ---------------------------------------------------------------

def open_serious():
    """High or critical incidents that are not closed yet (they reach the Manager as to-dos)."""
    return Incident.objects.filter(severity__in=(Incident.Severity.HIGH, Incident.Severity.CRITICAL)).exclude(
        status=S.CLOSED)


def open_serious_count():
    return open_serious().count()


def recent_for_site(site, n=5):
    return list(Incident.objects.filter(site=site).select_related("reported_by")[:n])
