"""Attendance rules: when someone may sign in, who approves, completing the day, and today's picture."""
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Role, User
from core.models import CompanySettings
from core.services import audit
from core.workflow import TransitionError, advance, require
from notifications.services import notify, notify_role
from tracking import geo
from tracking import services as tracking
from tracking.models import LocationStatus, TrackingProfile

from .models import AttendanceDay, AttendanceRecord

O = AttendanceRecord.Outcome
S = AttendanceRecord.Status
M = AttendanceRecord.Method
EARLY_SIGN_IN = timedelta(hours=1)  # people may sign in up to an hour before their shift starts


class AttendanceError(ValidationError):
    """A sign-in that was refused. The message is safe to show the person."""


def expected_people():
    """Everyone who signs in: active staff and supervisors."""
    return User.objects.filter(is_active=True, role__in=tracking.TRACKED_ROLES)


def approver_for(person):
    if person.role == Role.STAFF and person.supervisor_id and person.supervisor.is_active:
        return person.supervisor
    return None


# --- shifts -----------------------------------------------------------------------

def shift_on(hours, day):
    """(start, end) aware datetimes of the shift that starts on `day`, or None for a day off."""
    for h in hours:
        if h.weekday == day.weekday():
            start = timezone.make_aware(datetime.combine(day, h.start))
            end = timezone.make_aware(datetime.combine(day + timedelta(days=1) if h.end <= h.start else day, h.end))
            return start, end
    return None


def current_shift(hours, now):
    """(day, start, end) of the shift someone can sign in to now, or None."""
    today = timezone.localdate(now)
    for day in (today, today - timedelta(days=1)):
        shift = shift_on(hours, day)
        if shift and shift[0] - EARLY_SIGN_IN <= now < shift[1]:
            return day, shift[0], shift[1]
    return None


def _next_shift_text(hours, now):
    today = timezone.localdate(now)
    shift = shift_on(hours, today)
    if shift and now < shift[0]:
        opens = timezone.localtime(shift[0] - EARLY_SIGN_IN)
        return f"Your shift today starts at {timezone.localtime(shift[0]):%H:%M}. You can sign in from {opens:%H:%M}."
    if shift:
        return "Your shift today has ended."
    return "Today is not one of your working days. If you are working, ask your supervisor to mark you present."


def day_completed(day):
    return AttendanceDay.objects.filter(date=day).exists()


def _late_minutes(start, at):
    if start is None:
        return 0
    grace = timedelta(minutes=CompanySettings.load().late_after_minutes)
    return int((at - start).total_seconds() // 60) if at > start + grace else 0


# --- signing in -------------------------------------------------------------------

def _shift_to_sign_in(user, now):
    """(profile, site, day, shift start) for the shift `user` may sign in to now. Refuses with plain words."""
    if user.role not in tracking.TRACKED_ROLES:
        raise AttendanceError("Only guards and supervisors sign in.")
    profile = TrackingProfile.objects.select_for_update(of=("self",)).select_related("site").get(pk=tracking.profile_for(user).pk)
    site = profile.site
    if site is None or not site.is_active:
        raise AttendanceError("You have not been given a site yet. Ask the Manager to assign you to a site.")
    hours = list(tracking.hours_for(profile))
    if hours:
        shift = current_shift(hours, now)
        if shift is None:
            raise AttendanceError(_next_shift_text(hours, now))
        day, start, _end = shift
    else:
        day, start = timezone.localdate(now), None
    if day_completed(day):
        raise AttendanceError("The Manager has already completed this day. Ask your supervisor for help.")
    existing = AttendanceRecord.objects.filter(user=user, date=day).first()
    if existing:
        when = f" at {timezone.localtime(existing.signed_in_at):%H:%M}" if existing.signed_in_at else ""
        raise AttendanceError(f"You are already recorded for today{when}: {existing.get_outcome_display()}.")
    return profile, site, day, start


@transaction.atomic
def sign_in(user, data, now=None):
    """Sign `user` in at their site. Only the logged-in person can sign themself in."""
    now = now or timezone.now()
    if user.role not in tracking.TRACKED_ROLES:
        raise AttendanceError("Only guards and supervisors sign in.")
    try:
        lat, lng, accuracy, _ = tracking.parse_update(data, now)
    except tracking.LocationError as exc:
        raise AttendanceError(str(exc))
    profile, site, day, start = _shift_to_sign_in(user, now)

    distance = geo.distance_m(site.latitude, site.longitude, lat, lng)
    status = geo.classify(distance, accuracy, site.radius_m)
    if status == LocationStatus.WEAK:
        raise AttendanceError(f"Your GPS is not accurate enough (±{accuracy:.0f} m). Go outside, wait a minute and try "
                              "again, or sign in without location.")
    if status == LocationStatus.OFF:
        raise AttendanceError(f"You are about {distance:.0f} m from {site}. You must be at the site to sign in. "
                              "If the GPS shows the wrong place, sign in without location.")

    late = _late_minutes(start, now)
    supervisor = approver_for(user)
    rec = AttendanceRecord.objects.create(
        user=user, date=day, site=site, supervisor=supervisor, outcome=O.LATE if late else O.PRESENT,
        status=S.WAITING_SUPERVISOR if supervisor else S.WAITING_MANAGER, method=M.GPS, signed_in_at=now,
        shift_start=start, late_minutes=late, latitude=lat, longitude=lng, accuracy_m=accuracy,
        distance_m=round(distance, 1), location_status=status, marked_by=user,
    )
    audit.record(user, "attendance.signed_in", rec, f"{user} signed in at {site}" + (f", {late} minutes late" if late else ""))
    if late and supervisor:
        notify(supervisor, "attendance.late", f"{user} signed in {late} minutes late", f"At {site}.",
               _team_url(day), entity=rec)
    return rec


def _reason(value):
    if value not in AttendanceRecord.Reason.values:
        raise AttendanceError("Choose why the location could not be used.")
    return value


@transaction.atomic
def sign_in_without_location(user, reason, note="", now=None):
    """ATT-01: the server stamps the time and the person says why the phone's location could not be used.

    A guard's goes to their supervisor to approve; a supervisor's goes to the Manager (it waits as
    "waiting for approval" with no supervisor, so only the Manager can approve it).
    """
    now = now or timezone.now()
    reason = _reason(reason)
    _profile, site, day, start = _shift_to_sign_in(user, now)
    late = _late_minutes(start, now)
    supervisor = approver_for(user)
    rec = AttendanceRecord.objects.create(
        user=user, date=day, site=site, supervisor=supervisor, outcome=O.LATE if late else O.PRESENT,
        status=S.WAITING_SUPERVISOR, method=M.NO_LOCATION, signed_in_at=now, shift_start=start, late_minutes=late,
        manual_reason=reason, note=(note or "").strip()[:255], marked_by=user,
    )
    why = rec.get_manual_reason_display()
    audit.record(user, "attendance.signed_in", rec, f"{user} signed in without location at {site} ({why})")
    title = f"{user} signed in without location"
    text = f"At {site}, {timezone.localtime(now):%H:%M}. Reason: {why}."
    if supervisor:
        notify(supervisor, "attendance.no_location", title, text, _team_url(day), entity=rec)
    else:
        notify_role(Role.MANAGER, "attendance.no_location", title, text, _day_url(day), entity=rec)
    return rec


def no_location_this_month(user, now=None):
    today = timezone.localdate(now or timezone.now())
    return AttendanceRecord.objects.filter(user=user, method=M.NO_LOCATION, date__year=today.year,
                                           date__month=today.month).count()


# --- signing out (recorded, never approved) ---------------------------------------------

def can_sign_out(user, rec, now=None):
    """Your own sign-in from today or yesterday (a night shift), not yet signed out."""
    today = timezone.localdate(now or timezone.now())
    return (rec.user_id == user.pk and rec.signed_in_at is not None and rec.signed_out_at is None
            and rec.status != S.REJECTED and rec.date >= today - timedelta(days=1))


def open_sign_in(user, now=None):
    """The sign-in `user` can still sign out of, or None."""
    today = timezone.localdate(now or timezone.now())
    return (AttendanceRecord.objects.filter(user=user, date__gte=today - timedelta(days=1), signed_in_at__isnull=False,
                                            signed_out_at__isnull=True).exclude(status=S.REJECTED)
            .select_related("site").order_by("-date").first())


@transaction.atomic
def sign_out(rec, user, data=None, reason="", now=None):
    """ATT-02: with the phone's position when possible, otherwise with a reason. Nothing to approve."""
    now = now or timezone.now()
    rec = AttendanceRecord.objects.select_for_update().select_related("site").get(pk=rec.pk)
    if not can_sign_out(user, rec, now):
        raise AttendanceError("You cannot sign out of this day. It may already be signed out.")
    fields = {"signed_out_at": now}
    if data is not None:
        try:
            lat, lng, _accuracy, _ = tracking.parse_update(data, now)
        except tracking.LocationError as exc:
            raise AttendanceError(str(exc))
        fields["sign_out_method"] = AttendanceRecord.OutMethod.GPS
        if rec.site:
            fields["sign_out_distance_m"] = round(geo.distance_m(rec.site.latitude, rec.site.longitude, lat, lng), 1)
    else:
        fields["sign_out_method"] = AttendanceRecord.OutMethod.NO_LOCATION
        fields["sign_out_reason"] = _reason(reason)
    AttendanceRecord.objects.filter(pk=rec.pk).update(**fields, updated_at=now)
    for k, v in fields.items():
        setattr(rec, k, v)
    audit.record(user, "attendance.signed_out", rec, f"{user} signed out ({rec.get_sign_out_method_display().lower()})")
    return rec


def _team_url(day):
    from django.urls import reverse

    return reverse("attendance:team") + f"?date={day}"


def _day_url(day):
    from django.urls import reverse

    return reverse("attendance:day") + f"?date={day}"


# --- supervisor and Manager decisions --------------------------------------------------

def can_approve(user, rec):
    return user.role == Role.MANAGER or (user.role == Role.SUPERVISOR and rec.supervisor_id == user.pk)


def can_mark(user, person):
    if person.pk == user.pk or person.role not in tracking.TRACKED_ROLES or not person.is_active:
        return False
    return user.role == Role.MANAGER or (user.role == Role.SUPERVISOR and person.supervisor_id == user.pk)


def _open_day(day):
    if day_completed(day):
        raise TransitionError("The Manager has already completed this day, so it can no longer be changed.")


@transaction.atomic
def approve(rec, user):
    if not can_approve(user, rec):
        raise TransitionError("You cannot approve this sign-in.")
    _open_day(rec.date)
    require(rec, S.WAITING_SUPERVISOR, S.WAITING_MANAGER, supervisor_decided_by=user, supervisor_decided_at=timezone.now())
    audit.record(user, "attendance.approved", rec, f"Sign-in of {rec.user} on {rec.date:%d %b} approved",
                 changes={"status": [S.WAITING_SUPERVISOR, S.WAITING_MANAGER]})
    return rec


@transaction.atomic
def reject(rec, user, note):
    if not can_approve(user, rec):
        raise TransitionError("You cannot answer this sign-in.")
    if not note.strip():
        raise ValidationError("Write why the sign-in is not accepted.")
    _open_day(rec.date)
    old = rec.status
    require(rec, (S.WAITING_SUPERVISOR, S.WAITING_MANAGER), S.REJECTED, supervisor_decided_by=user,
            supervisor_decided_at=timezone.now(), supervisor_note=note.strip()[:255])
    audit.record(user, "attendance.rejected", rec, f"Sign-in of {rec.user} on {rec.date:%d %b} not accepted",
                 changes={"status": [old, S.REJECTED]})
    notify(rec.user, "attendance.rejected", "Your sign-in was not accepted", note, _mine_url(), entity=rec)
    return rec


def _mine_url():
    from django.urls import reverse

    return reverse("attendance:mine")


@transaction.atomic
def approve_all(user, day):
    _open_day(day)
    qs = AttendanceRecord.objects.filter(date=day, status=S.WAITING_SUPERVISOR)
    if user.role != Role.MANAGER:
        qs = qs.filter(supervisor=user)
    count = 0
    for rec in qs:
        if advance(rec, S.WAITING_SUPERVISOR, S.WAITING_MANAGER, supervisor_decided_by=user, supervisor_decided_at=timezone.now()):
            count += 1
    if count:
        audit.record(user, "attendance.approved_all", None, f"Approved {count} sign-ins for {day:%d %b %Y}",
                     entity_type="attendance.day", entity_id=day.isoformat())
    return count


@transaction.atomic
def mark(person, day, outcome, note, user):
    """A supervisor (for their team) or the Manager records attendance for someone who could not sign in."""
    if not can_mark(user, person):
        raise TransitionError("You cannot mark attendance for this person.")
    if outcome not in (O.PRESENT, O.LATE, O.ABSENT):
        raise ValidationError("Choose present, late or absent.")
    if not note.strip():
        raise ValidationError("Write why you are marking this, for example: phone broken.")
    if day > timezone.localdate():
        raise ValidationError("You cannot mark attendance for a day that has not come yet.")
    _open_day(day)
    method = M.OFFICE if user.role == Role.MANAGER else M.SUPERVISOR
    profile = tracking.profile_for(person)
    rec = AttendanceRecord.objects.select_for_update().filter(user=person, date=day).first()
    old = None
    if rec is None:
        rec = AttendanceRecord(user=person, date=day, site=profile.site, supervisor=approver_for(person))
    else:
        old = rec.outcome
    rec.outcome, rec.method, rec.status, rec.marked_by = outcome, method, S.WAITING_MANAGER, user
    rec.note = note.strip()[:255]
    rec.supervisor_decided_by, rec.supervisor_decided_at = user, timezone.now()
    rec.save()
    audit.record(user, "attendance.marked", rec, f"{person} marked {rec.get_outcome_display().lower()} for {day:%d %b}",
                 changes={"outcome": [old, outcome]})
    return rec


@transaction.atomic
def complete_day(day, user):
    """The Manager closes the day: every sign-in becomes final and missing people are recorded."""
    from leave.services import away_on

    if user.role != Role.MANAGER:
        raise TransitionError("Only the Manager completes the day.")
    if day > timezone.localdate():
        raise TransitionError("You cannot complete a day that has not come yet.")
    now = timezone.now()
    try:
        with transaction.atomic():
            summary = AttendanceDay.objects.create(date=day, completed_by=user, completed_at=now)
    except IntegrityError:
        raise TransitionError("This day has already been completed.")

    away = away_on(day)
    records = {r.user_id: r for r in AttendanceRecord.objects.select_for_update().filter(date=day)}
    profiles = {p.user_id: p for p in TrackingProfile.objects.select_related("site")}
    hours_map = tracking.all_hours()
    for rec in records.values():
        if rec.status == S.REJECTED:
            rec.outcome = O.ABSENT
        rec.status, rec.completed_by, rec.completed_at = S.COMPLETED, user, now
        rec.save(update_fields=["outcome", "status", "completed_by", "completed_at", "updated_at"])
    new = []
    for person in expected_people().select_related("supervisor"):
        if person.pk in records:
            continue
        profile = profiles.get(person.pk)
        outcome = {"on_leave": O.ON_LEAVE, "sick": O.SICK}.get(away.get(person.pk))
        if outcome is None:
            hours = tracking.hours_for(profile, hours_map) if profile else []
            works = shift_on(hours, day) is not None if hours else bool(profile and profile.site_id)
            if not works:
                continue
            outcome = O.ABSENT
        new.append(AttendanceRecord(
            user=person, date=day, site=profile.site if profile else None, supervisor=approver_for(person),
            outcome=outcome, status=S.COMPLETED, method=M.SYSTEM, completed_by=user, completed_at=now,
        ))
    AttendanceRecord.objects.bulk_create(new)
    counts = {o: 0 for o in O.values}
    for o in AttendanceRecord.objects.filter(date=day).values_list("outcome", flat=True):
        counts[o] += 1
    for field in ("present", "late", "absent", "on_leave", "sick"):
        setattr(summary, field, counts[field])
    summary.save()
    audit.record(user, "attendance.day_completed", summary,
                 f"Attendance for {day:%d %b %Y} completed: {counts['present'] + counts['late']} in, {counts['absent']} absent",
                 changes=counts)
    return summary


@transaction.atomic
def reopen_day(day, user):
    if user.role != Role.MANAGER:
        raise TransitionError("Only the Manager can reopen a day.")
    summary = AttendanceDay.objects.filter(date=day).first()
    if summary is None:
        raise TransitionError("This day is not completed.")
    summary.delete()
    AttendanceRecord.objects.filter(date=day, method=M.SYSTEM).delete()
    AttendanceRecord.objects.filter(date=day, status=S.COMPLETED).update(status=S.WAITING_MANAGER, completed_by=None, completed_at=None)
    audit.record(user, "attendance.day_reopened", None, f"Attendance for {day:%d %b %Y} reopened",
                 entity_type="attendance.day", entity_id=day.isoformat())


# --- today's picture ------------------------------------------------------------------

STATE_LABELS = {
    "on_duty": "On duty",
    "late": "Late",
    "off_location": "Off location",
    "on_leave": "On leave",
    "sick": "Sick",
    "not_signed_in": "Not signed in",
    "not_started": "Shift not started",
    "day_off": "Day off",
    "rejected": "Sign-in not accepted",
    "absent": "Absent",
    "shift_over": "Shift over",
}
STATE_TONES = {
    "on_duty": "completed", "late": "pending", "off_location": "off", "on_leave": "role", "sick": "role",
    "not_signed_in": "off", "absent": "off", "rejected": "off", "not_started": "reviewed", "day_off": "role",
    "shift_over": "role",
}


def _state(record, away, shift, profile, now, completed):
    if away:
        return away
    if record is not None:
        if record.status == S.REJECTED:
            return "rejected"
        if record.outcome == O.ABSENT:
            return "absent"
        if record.outcome in (O.ON_LEAVE, O.SICK):
            return record.outcome
        if shift and now >= shift[1]:
            return "shift_over"
        if profile and profile.tracking_on and tracking.current_status(profile, now) == LocationStatus.OFF:
            return "off_location"
        return "late" if record.outcome == O.LATE else "on_duty"
    if shift is None:
        return "day_off"
    if now < shift[0]:
        return "not_started"
    return "absent" if completed or now >= shift[1] else "not_signed_in"


def people_on(day=None, people=None, now=None):
    """One row per person for `day`: their site, shift, sign-in and a plain state.

    Rows never include coordinates, so they are safe to show to supervisors.
    """
    from leave.services import away_until

    now = now or timezone.now()
    day = day or timezone.localdate(now)
    people = list((people if people is not None else expected_people()).select_related("supervisor"))
    ids = [p.pk for p in people]
    profiles = {p.user_id: p for p in TrackingProfile.objects.filter(user_id__in=ids).select_related("site")}
    records = {r.user_id: r for r in AttendanceRecord.objects.filter(date=day, user_id__in=ids)}
    away = away_until(day, ids)
    hours_map = tracking.all_hours()
    completed = day_completed(day) or day < timezone.localdate(now)
    rows = []
    for person in people:
        profile = profiles.get(person.pk)
        hours = tracking.hours_for(profile, hours_map) if profile else []
        shift = shift_on(hours, day) if hours else None
        record = records.get(person.pk)
        if not hours and record is None and profile and profile.site_id:
            # No working hours set: treat the whole day as the shift.
            start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
            shift = (start, start + timedelta(days=1))
        gone, until = away.get(person.pk, (None, None))
        state = _state(record, gone, shift, profile, now, completed)
        label = STATE_LABELS[state]
        if state == gone and until:
            # LEAVE-06: "On leave until 23 Oct", from the days the Manager gave.
            label = f"{label} until {until.day} {until:%b}"
        rows.append({
            "person": person, "site": profile.site if profile else None, "record": record,
            "shift": shift if hours else None, "state": state, "label": label, "tone": STATE_TONES[state],
            "until": until if state == gone else None,
            "is_in": state in ("on_duty", "late", "off_location", "shift_over"),
            "is_absent": state in ("not_signed_in", "absent", "rejected"),
        })
    rows.sort(key=lambda r: (r["site"].name if r["site"] else "~", str(r["person"])))
    return rows


def board(day=None, now=None):
    """The Manager's IN ATTENDANCE TODAY strip: totals and one box per site."""
    from tracking.models import Site

    now = now or timezone.now()
    day = day or timezone.localdate(now)
    rows = people_on(day, now=now)
    sites = {s.pk: {"site": s, "in": [], "absent": [], "away": [], "later": []} for s in Site.objects.filter(is_active=True)}
    no_site = {"site": None, "in": [], "absent": [], "away": [], "later": []}
    for row in rows:
        box = sites.get(row["site"].pk) if row["site"] else no_site
        if box is None:
            box = no_site
        if row["is_in"]:
            box["in"].append(row)
        elif row["is_absent"]:
            box["absent"].append(row)
        elif row["state"] in ("on_leave", "sick"):
            box["away"].append(row)
        else:
            box["later"].append(row)
    boxes = [b for b in sites.values() if b["in"] or b["absent"] or b["away"] or b["later"] or b["site"].guards_needed]
    for b in boxes:
        b["short"] = bool(b["site"] and len(b["in"]) < b["site"].guards_needed and not b["later"])
    if any(no_site[k] for k in ("in", "absent", "away")):
        boxes.append(no_site)
    waiting = AttendanceRecord.objects.filter(date=day)
    return {
        "day": day,
        "boxes": boxes,
        "total_in": sum(len(b["in"]) for b in boxes),
        "total_absent": sum(len(b["absent"]) for b in boxes),
        "total_away": sum(len(b["away"]) for b in boxes),
        "total_later": sum(len(b["later"]) for b in boxes),
        "total_expected": sum(1 for r in rows if r["state"] != "day_off"),
        "completed": AttendanceDay.objects.filter(date=day).select_related("completed_by").first(),
        "waiting_supervisor": waiting.filter(status=S.WAITING_SUPERVISOR).count(),
        "waiting_manager": waiting.filter(status=S.WAITING_MANAGER).count(),
    }


def my_today(user, now=None):
    """The small attendance card on a person's own dashboard."""
    now = now or timezone.now()
    rows = people_on(people=User.objects.filter(pk=user.pk), now=now)
    row = rows[0] if rows else None
    profile = tracking.profile_for(user)
    hours = list(tracking.hours_for(profile))
    shift = current_shift(hours, now) if hours else (timezone.localdate(now), None, None)
    day = shift[0] if shift else timezone.localdate(now)
    record = AttendanceRecord.objects.filter(user=user, date=day).first()
    can_sign_in = bool(profile.site_id and shift and record is None and not day_completed(day))
    return {
        "row": row, "record": record, "can_sign_in": can_sign_in, "site": profile.site,
        "open": open_sign_in(user, now), "today": timezone.localdate(now), "reasons": AttendanceRecord.Reason.choices,
        "hint": "" if shift or not hours else _next_shift_text(hours, now),
        "recent": AttendanceRecord.objects.filter(user=user).select_related("site")[:7],
    }


def team_today(user, day=None, now=None):
    team = User.objects.filter(supervisor=user, is_active=True, role__in=tracking.TRACKED_ROLES)
    rows = people_on(day, team, now)
    return {
        "rows": rows,
        "in_count": sum(1 for r in rows if r["is_in"]),
        "absent_count": sum(1 for r in rows if r["is_absent"]),
        "away_count": sum(1 for r in rows if r["state"] in ("on_leave", "sick")),
        "waiting": AttendanceRecord.objects.filter(supervisor=user, status=S.WAITING_SUPERVISOR,
                                                   date=day or timezone.localdate()).count(),
    }


def short_staffed(now=None):
    """Active sites with fewer people in than they need right now."""
    data = board(now=now)
    return [b for b in data["boxes"] if b.get("short") and b["site"]]


def waiting_for(user):
    qs = AttendanceRecord.objects.filter(status=S.WAITING_SUPERVISOR)
    return qs if user.role == Role.MANAGER else qs.filter(supervisor=user)


def lookup_people(user):
    """People whose attendance `user` may filter by."""
    people = expected_people()
    if user.role in (Role.MANAGER, Role.SECRETARY):
        return people
    if user.role == Role.SUPERVISOR:
        return people.filter(Q(pk=user.pk) | Q(supervisor=user))
    return people.filter(pk=user.pk)
