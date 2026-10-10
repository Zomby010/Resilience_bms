"""Leave rules: the Manager decides and types the days given; sick is reported, not asked for."""
import io
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Role, User
from core.models import CompanySettings
from core.services import audit
from core.workflow import require
from notifications.services import notify, notify_role

from .models import LeaveAllowance, LeaveRequest, LeaveType, SickLeave, SickNote

S = LeaveRequest.Status
SICK = SickLeave.Status
OFFICE = (Role.SECRETARY, Role.MANAGER)
SICK_CODE = "sick"
WEEKDAYS_DEFAULT = {0, 1, 2, 3, 4, 5}  # Monday to Saturday when the person has no working hours set


# --- who ----------------------------------------------------------------------

def people_for(user):
    """The people `user` may record leave or sickness for (always including themselves)."""
    people = User.objects.filter(is_active=True)
    if user.role in OFFICE:
        return people
    if user.role == Role.SUPERVISOR:
        return people.filter(Q(pk=user.pk) | Q(supervisor=user))
    return people.filter(pk=user.pk)


def approver_for(person):
    """Frank's rule: the Manager decides every leave request. None means the Manager."""
    return None


def supervisor_of(person):
    """The guard's supervisor, who is told about leave (to plan cover) but does not decide it."""
    if person.role == Role.STAFF and person.supervisor_id and person.supervisor.is_active:
        return person.supervisor
    return None


def can_decide(user, req):
    return user.role == Role.MANAGER


def can_cancel(user, req):
    if req.status not in (S.WAITING, S.APPROVED):
        return False
    if user.role == Role.MANAGER:
        return True
    started = req.start_date <= timezone.localdate()
    return not started and (req.user_id == user.pk or req.entered_by_id == user.pk)


# --- counting days --------------------------------------------------------------

def working_weekdays(person):
    """Weekdays the person normally works, from their (or their site's) working hours."""
    from tracking.models import TrackingProfile
    from tracking.services import hours_for

    profile = TrackingProfile.objects.filter(user=person).first()
    days = {h.weekday for h in hours_for(profile)} if profile else set()
    return days or WEEKDAYS_DEFAULT


def count_days(leave_type, person, start, end):
    if end < start:
        return Decimal(0)
    total = (end - start).days + 1
    if leave_type.counting == LeaveType.Counting.CALENDAR:
        return Decimal(total)
    weekdays = working_weekdays(person)
    return Decimal(sum(1 for i in range(total) if (start + timedelta(days=i)).weekday() in weekdays))


def last_day_for(leave_type, person, start, days):
    """The last day off when `days` are given from `start`, counted the type's way (working or calendar days)."""
    need = int(Decimal(days).to_integral_value(rounding="ROUND_CEILING"))
    if need <= 1:
        return start
    if leave_type.counting == LeaveType.Counting.CALENDAR:
        return start + timedelta(days=need - 1)
    weekdays = working_weekdays(person)
    day, counted = start, 1 if start.weekday() in weekdays else 0
    while counted < need and (day - start).days < 731:
        day += timedelta(days=1)
        if day.weekday() in weekdays:
            counted += 1
    return day


def date_span(first, last):
    """'12–23 Oct', '28 Sep–3 Oct' or '30 Dec 2026–4 Jan 2027'."""
    if first == last:
        return f"{first.day} {first:%b}"
    if first.year != last.year:
        return f"{first.day} {first:%b %Y}–{last.day} {last:%b %Y}"
    if first.month != last.month:
        return f"{first.day} {first:%b}–{last.day} {last:%b}"
    return f"{first.day}–{last.day} {last:%b}"


# Kenyan Employment Act minimums. Below these the decide screen shows a quiet warning (it never blocks).
LEGAL_MINIMUM = {"annual": 21, "maternity": 90, "paternity": 14}


def below_minimum(leave_type, days):
    floor = LEGAL_MINIMUM.get(leave_type.code)
    return floor if floor and Decimal(days) < floor else None


def _days_in_year(start, end, year):
    """The part of [start, end] that falls in `year`, as a (start, end) pair or None."""
    lo, hi = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
    return (lo, hi) if lo <= hi else None


# --- balances ------------------------------------------------------------------

def allowed_days(person, leave_type, year):
    row = LeaveAllowance.objects.filter(user=person, leave_type=leave_type, year=year).first()
    return row.days if row else Decimal(leave_type.days_per_year)


def balance(person, leave_type, year=None, exclude=None):
    """{'allowed', 'taken', 'waiting', 'left'} for one person, type and year."""
    year = year or timezone.localdate().year
    taken = waiting = Decimal(0)
    if leave_type.code == SICK_CODE:
        for s in SickLeave.objects.filter(user=person, first_day__year__lte=year, last_day__year__gte=year):
            part = _days_in_year(s.first_day, s.last_day, year)
            taken += Decimal((part[1] - part[0]).days + 1)
    else:
        qs = LeaveRequest.objects.filter(
            user=person, leave_type=leave_type, status__in=(S.WAITING, S.APPROVED),
            start_date__year__lte=year, end_date__year__gte=year,
        )
        if exclude is not None:
            qs = qs.exclude(pk=exclude.pk)
        for r in qs:
            part = _days_in_year(r.start_date, r.end_date, year)
            if r.days_given is not None and part == (r.start_date, r.end_date):
                days = r.days_given
            else:
                days = r.days if part == (r.start_date, r.end_date) else count_days(leave_type, person, *part)
            if r.status == S.APPROVED:
                taken += days
            else:
                waiting += days
    allowed = allowed_days(person, leave_type, year)
    return {"allowed": allowed, "taken": taken, "waiting": waiting, "left": allowed - taken - waiting}


def _n(value):
    value = Decimal(value)
    return f"{value:.0f}" if value == value.to_integral() else f"{value:.1f}"


def plain_balance(leave_type, b, you=True):
    """'You have 12 days of annual leave left this year. 21 allowed, 9 taken, none waiting.'"""
    who = "You have" if you else "They have"
    if not leave_type.days_per_year and not b["allowed"]:
        return f"{leave_type.name}: no fixed number of days. {_n(b['taken'])} taken this year."
    word = "day" if b["left"] == 1 else "days"
    head = f"{who} {_n(b['left'])} {word} of {leave_type.name.lower()} left this year."
    waiting = f"{_n(b['waiting'])} waiting for approval" if b["waiting"] else "none waiting"
    return f"{head} {_n(b['allowed'])} allowed, {_n(b['taken'])} taken, {waiting}."


def balances_for(person, year=None, you=True):
    year = year or timezone.localdate().year
    rows = []
    for lt in LeaveType.objects.filter(is_active=True):
        b = balance(person, lt, year)
        rows.append({"type": lt, **b, "text": plain_balance(lt, b, you)})
    return rows


# --- leave requests --------------------------------------------------------------

def _check_overlap(person, start, end, exclude=None):
    clash = LeaveRequest.objects.filter(user=person, status__in=(S.WAITING, S.APPROVED), start_date__lte=end, end_date__gte=start)
    if exclude is not None:
        clash = clash.exclude(pk=exclude.pk)
    if clash.exists():
        c = clash.first()
        raise ValidationError(f"These dates overlap leave already asked for ({c.start_date:%d %b} to {c.end_date:%d %b %Y}).")


@transaction.atomic
def ask_for_leave(person, leave_type, start, end, reason, entered_by):
    """The person picks dates only. Nothing is blocked by a balance: the Manager types the days given."""
    if not people_for(entered_by).filter(pk=person.pk).exists():
        raise ValidationError("You cannot record leave for this person.")
    if end < start:
        raise ValidationError("The last day off cannot be before the first day off.")
    if (end - start).days > 366:
        raise ValidationError("Leave can be for at most one year at a time.")
    User.objects.select_for_update().filter(pk=person.pk).first()  # one request at a time per person
    _check_overlap(person, start, end)
    days = count_days(leave_type, person, start, end)
    if days <= 0:
        raise ValidationError("Those dates have no working days in them.")
    req = LeaveRequest.objects.create(
        user=person, leave_type=leave_type, start_date=start, end_date=end, days=days, reason=reason,
        approver=None, entered_by=entered_by,
    )
    audit.record(entered_by, "leave.asked", req, f"Leave asked for {person}: {leave_type} {_n(days)} days")
    if can_decide(entered_by, req):
        decide(req, entered_by, approve=True, note="Recorded and approved at the same time.")
        return req
    link = req.get_absolute_url()
    message = f"{leave_type}: {date_span(start, end)}."
    notify_role(Role.MANAGER, "leave.request", f"Leave request from {person}", message, link, entity=req, exclude=entered_by)
    sup = supervisor_of(person)
    if sup and sup.pk != entered_by.pk:
        notify(sup, "leave.fyi", f"{person} asked for leave", message + " The Manager decides. This is so you can plan cover.",
               link, entity=req)
    if entered_by.pk != person.pk:
        notify(person, "leave.request", "Leave was asked for on your behalf", message, link, entity=req)
    return req


@transaction.atomic
def decide(req, user, approve, note="", days_given=None):
    if not can_decide(user, req):
        raise ValidationError("Only the Manager decides leave.")
    if not approve and not note.strip():
        raise ValidationError("Write the reason for saying no, so the person understands.")
    new = S.APPROVED if approve else S.REJECTED
    extra = {}
    if approve:
        given = req.days if days_given in (None, "") else Decimal(str(days_given))
        if given <= 0 or given > 366:
            raise ValidationError("Type the days given: a number from 0.5 to 366.")
        extra = {"days_given": given, "last_day_given": last_day_for(req.leave_type, req.user, req.start_date, given)}
    require(req, S.WAITING, new, decided_by=user, decided_at=timezone.now(), decision_note=note.strip(), **extra)
    word = "approved" if approve else "not approved"
    changes = {"status": [S.WAITING, new]}
    if approve:
        changes["days_given"] = [None, str(req.days_given)]
    audit.record(user, f"leave.{new}", req, f"Leave for {req.user} {word}", changes=changes)
    if approve:
        days = req.days_given
        head = f"Approved: {_n(days)} {'day' if days == 1 else 'days'}, {date_span(req.start_date, req.last_day_given)}."
    else:
        head = "Not approved."
    text = f"{req.leave_type}. " + (f"Note: {note}" if note else "")
    if req.user_id != user.pk:
        notify(req.user, "leave.decided", head, text.strip(), req.get_absolute_url(), entity=req)
    sup = supervisor_of(req.user)
    if sup and sup.pk != user.pk:
        notify(sup, "leave.fyi", f"{req.user}'s leave: {head[0].lower()}{head[1:]}",
               f"{req.leave_type}. Plan cover for these days." if approve else f"{req.leave_type}.",
               req.get_absolute_url(), entity=req)
    return req


@transaction.atomic
def cancel(req, user):
    if not can_cancel(user, req):
        raise ValidationError("This leave can no longer be cancelled.")
    old = req.status
    require(req, (S.WAITING, S.APPROVED), S.CANCELLED)
    audit.record(user, "leave.cancelled", req, f"Leave for {req.user} cancelled", changes={"status": [old, S.CANCELLED]})
    if req.user_id != user.pk:
        notify(req.user, "leave.cancelled", "Your leave was cancelled", str(req), req.get_absolute_url(), entity=req)
    return req


@transaction.atomic
def set_allowance(person, leave_type, year, days, user):
    row, created = LeaveAllowance.objects.get_or_create(
        user=person, leave_type=leave_type, year=year, defaults={"days": days, "set_by": user}
    )
    old = None if created else row.days
    if not created:
        row.days, row.set_by = days, user
        row.save()
    if old != days:
        audit.record(user, "leave.allowance", row, f"{leave_type} for {person} in {year} set to {_n(days)} days",
                     changes={"days": [str(old) if old is not None else None, str(days)]})
    return row


# --- sick leave -------------------------------------------------------------------

def can_see_sick_files(user, sick):
    """Only the person themself, the Secretary and the Manager. Never a supervisor or another guard."""
    return user.is_authenticated and (user.pk == sick.user_id or user.role in OFFICE)


def can_change_sick(user, sick):
    return user.pk == sick.user_id or user.role in OFFICE or (
        user.role == Role.SUPERVISOR and sick.user.supervisor_id == user.pk
    )


@transaction.atomic
def report_sick(person, first_day, last_day, comment, user, upload=None):
    if not people_for(user).filter(pk=person.pk).exists():
        raise ValidationError("You cannot report sickness for this person.")
    if last_day < first_day:
        raise ValidationError("The last day cannot be before the first day.")
    if (last_day - first_day).days > 180:
        raise ValidationError("Sick leave can be recorded for at most 180 days at a time.")
    overlap = SickLeave.objects.filter(user=person, first_day__lte=last_day, last_day__gte=first_day).first()
    if overlap:
        raise ValidationError(f"{person} is already recorded as sick from {overlap.first_day:%d %b} to {overlap.last_day:%d %b %Y}.")
    sick = SickLeave.objects.create(user=person, first_day=first_day, last_day=last_day, comment=comment, reported_by=user)
    audit.record(user, "sick.reported", sick, f"{person} reported sick", confidential=True)
    if upload is not None:
        add_sick_note(sick, upload, user)
    message = f"From {first_day:%d %b} to {last_day:%d %b %Y}."
    if person.role == Role.STAFF and person.supervisor_id and person.supervisor_id != user.pk:
        notify(person.supervisor, "sick.reported", f"{person} is off sick", message + " Please arrange cover.",
               sick.get_absolute_url(), entity=sick)
    notify_role(Role.SECRETARY, "sick.reported", f"{person} is off sick", message, sick.get_absolute_url(), entity=sick, exclude=user)
    if person.pk != user.pk:
        notify(person, "sick.reported", "Sick leave recorded for you",
               message + " Upload your sick sheet when you have it.", sick.get_absolute_url(), entity=sick)
    return sick


def _clean_image(upload, mime):
    """Re-save photos so hidden details (GPS position, phone model, date) are removed."""
    from PIL import Image, ImageOps

    upload.seek(0)
    img = ImageOps.exif_transpose(Image.open(upload))
    out = io.BytesIO()
    if mime == "image/jpeg":
        img.convert("RGB").save(out, format="JPEG", quality=88)
    else:
        img.save(out, format="PNG")
    return out.getvalue()


@transaction.atomic
def add_sick_note(sick, upload, user):
    from core.services.files import detect_type

    if not can_see_sick_files(user, sick):
        raise ValidationError("Only the person, the Secretary or the Manager can upload a sick sheet.")
    mime = getattr(upload, "detected_type", None) or detect_type(upload)
    if mime == "application/pdf":
        upload.seek(0)
        content = upload.read()
    else:
        try:
            content = _clean_image(upload, mime)
        except Exception:
            raise ValidationError("That picture could not be read. Please take the photo again.")
    note = SickNote(sick_leave=sick, original_name=(upload.name or "sick-sheet")[:200], mime_type=mime,
                    size_bytes=len(content), uploaded_by=user)
    note.file.save("sheet", ContentFile(content), save=False)
    note.save()
    if sick.status in (SICK.CERTIFICATE_NEEDED, SICK.NOT_ACCEPTED):
        old = sick.status
        require(sick, (SICK.CERTIFICATE_NEEDED, SICK.NOT_ACCEPTED), SICK.CERTIFICATE_RECEIVED)
        audit.record(user, "sick.sheet_added", sick, f"Sick sheet added for {sick.user}",
                     changes={"status": [old, SICK.CERTIFICATE_RECEIVED]}, confidential=True)
    else:
        audit.record(user, "sick.sheet_added", sick, f"Another sick sheet added for {sick.user}", confidential=True)
    notify_role(Role.SECRETARY, "sick.sheet", f"Sick sheet received from {sick.user}", "Please check it.",
                sick.get_absolute_url(), entity=sick, exclude=user)
    return note


@transaction.atomic
def review_sick(sick, user, outcome, note=""):
    """outcome: 'accept', 'reject' (not accepted) or 'again' (ask for a proper sick sheet)."""
    if user.role not in OFFICE:
        raise ValidationError("Only the Secretary or the Manager can check sick sheets.")
    if outcome in ("reject", "again") and not note.strip():
        raise ValidationError("Write the reason, so the person knows what to do.")
    targets = {"accept": SICK.ACCEPTED, "reject": SICK.NOT_ACCEPTED, "again": SICK.CERTIFICATE_NEEDED}
    new = targets[outcome]
    old = sick.status
    allowed = {
        "accept": (SICK.CERTIFICATE_RECEIVED, SICK.CERTIFICATE_NEEDED, SICK.NOT_ACCEPTED),
        "reject": (SICK.CERTIFICATE_RECEIVED, SICK.CERTIFICATE_NEEDED, SICK.ACCEPTED),
        "again": (SICK.CERTIFICATE_RECEIVED, SICK.NOT_ACCEPTED, SICK.ACCEPTED),
    }[outcome]
    require(sick, allowed, new, reviewed_by=user, reviewed_at=timezone.now(), review_note=note.strip(),
            reminder_sent_at=None if outcome == "again" else sick.reminder_sent_at)
    audit.record(user, f"sick.{outcome}", sick, f"Sick leave for {sick.user}: {sick.get_status_display()}",
                 changes={"status": [old, new]}, confidential=True)
    messages = {
        "accept": "Your sick sheet was accepted.",
        "reject": "Your sick leave was not accepted.",
        "again": "Please bring a proper sick sheet.",
    }
    notify(sick.user, "sick.reviewed", messages[outcome], note, sick.get_absolute_url(), entity=sick)
    return sick


@transaction.atomic
def change_last_day(sick, last_day, user):
    if not can_change_sick(user, sick):
        raise ValidationError("You cannot change this sick leave.")
    if last_day < sick.first_day:
        raise ValidationError("The last day cannot be before the first day.")
    overlap = SickLeave.objects.filter(user=sick.user, first_day__lte=last_day, last_day__gte=sick.first_day).exclude(pk=sick.pk)
    if overlap.exists():
        raise ValidationError("That would overlap another sick leave.")
    old = sick.last_day
    sick.last_day = last_day
    sick.save(update_fields=["last_day", "updated_at"])
    audit.record(user, "sick.dates", sick, f"Last sick day for {sick.user} changed",
                 changes={"last_day": [old.isoformat(), last_day.isoformat()]}, confidential=True)
    return sick


def log_sheet_download(user, note):
    audit.record(user, "sick.sheet_viewed", note.sick_leave, f"Sick sheet for {note.sick_leave.user} opened", confidential=True)


# --- status on a day (used by attendance and the dashboards) -----------------------

def away_on(day, users=None):
    """{user_id: 'on_leave' | 'sick'} for people away on `day`. Sick wins over leave."""
    return {uid: v[0] for uid, v in away_until(day, users).items()}


def away_until(day, users=None):
    """{user_id: (state, last day away)} for people away on `day`. The days given decide the leave end."""
    away = {}
    leave = LeaveRequest.objects.filter(status=S.APPROVED).covering(day)
    sick = SickLeave.objects.exclude(status=SICK.NOT_ACCEPTED).covering(day)
    if users is not None:
        leave, sick = leave.filter(user__in=users), sick.filter(user__in=users)
    for uid, given, end in leave.values_list("user_id", "last_day_given", "end_date"):
        away[uid] = ("on_leave", given or end)
    for uid, last in sick.values_list("user_id", "last_day"):
        away[uid] = ("sick", last)
    return away


# --- daily checks -------------------------------------------------------------------

def daily_sick_checks(now=None):
    """Remind about missing sick sheets and delete sick sheet files past the keep period."""
    now = now or timezone.now()
    settings = CompanySettings.load()
    today = timezone.localdate(now)
    reminders = 0
    due = SickLeave.objects.filter(
        status=SICK.CERTIFICATE_NEEDED, reminder_sent_at__isnull=True,
        first_day__lte=today - timedelta(days=settings.sick_note_due_days),
    ).select_related("user", "user__supervisor")
    for sick in due:
        if SickLeave.objects.filter(pk=sick.pk, reminder_sent_at__isnull=True).update(reminder_sent_at=now):
            reminders += 1
            text = f"Sick leave from {sick.first_day:%d %b %Y} still has no sick sheet."
            notify(sick.user, "sick.reminder", "Please upload your sick sheet", text, sick.get_absolute_url(), entity=sick)
            notify_role(Role.SECRETARY, "sick.reminder", f"No sick sheet yet from {sick.user}", text, sick.get_absolute_url(), entity=sick)
    removed = 0
    old = SickNote.objects.filter(removed_at__isnull=True, uploaded_at__lt=now - timedelta(days=settings.sick_note_keep_days))
    for note in old:
        if note.file:
            note.file.delete(save=False)
        note.file = ""
        note.removed_at = now
        note.save(update_fields=["file", "removed_at"])
        audit.record(None, "sick.sheet_removed", note.sick_leave, "Sick sheet file deleted (keep period ended)", confidential=True)
        removed += 1
    return {"sick_reminders": reminders, "sick_sheets_removed": removed}
