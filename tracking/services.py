"""Tracking rules: working hours, location updates, status and alerts.

Everything that decides what a person's status is lives here, on the server.
"""
import math
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, User

from . import geo
from .models import (
    HISTORY_DAYS,
    MIN_UPDATE_INTERVAL_S,
    SIGNAL_LOST_AFTER_S,
    Alert,
    LocationPing,
    LocationStatus,
    Site,
    TrackingProfile,
    WorkHours,
)

TRACKED_ROLES = (Role.STAFF, Role.SUPERVISOR)
ONLINE_WITHIN = timedelta(minutes=5)
MAX_READING_AGE = timedelta(minutes=2)    # older phone readings are refused as stale
MAX_CLOCK_AHEAD = timedelta(minutes=2)    # phone clocks can run a little fast
MAX_SPEED_MPS = 70                        # ~250 km/h; faster than this is an impossible jump


class LocationError(ValueError):
    """A location update that was refused. The message is safe to show the user."""


class RateLimited(LocationError):
    pass


def is_tracked(user):
    return user.is_authenticated and user.is_active and user.role in TRACKED_ROLES


def profile_for(user):
    profile, _ = TrackingProfile.objects.select_related("site").get_or_create(user=user)
    return profile


# --- working hours -----------------------------------------------------------

def hours_for(profile, hours_map=None):
    """The person's shifts: their own if they have them, otherwise their site's.

    Pass `hours_map` (from all_hours()) to avoid one query per person on big screens.
    """
    if hours_map is not None:
        key = ("user", profile.user_id) if profile.own_hours else ("site", profile.site_id)
        return hours_map.get(key, [])
    if profile.own_hours:
        return WorkHours.objects.filter(user_id=profile.user_id)
    if profile.site_id:
        return WorkHours.objects.filter(site_id=profile.site_id)
    return WorkHours.objects.none()


def all_hours():
    hours_map = {}
    for h in WorkHours.objects.all():
        hours_map.setdefault(("user", h.user_id) if h.user_id else ("site", h.site_id), []).append(h)
    return hours_map


def is_working(profile, now=None, hours=None):
    """True when `now` falls inside one of the person's shifts (server-side, local time)."""
    now = timezone.localtime(now or timezone.now())
    today, t = now.weekday(), now.time()
    yesterday = (today - 1) % 7
    for h in hours if hours is not None else hours_for(profile):
        if h.end > h.start:
            if h.weekday == today and h.start <= t < h.end:
                return True
        else:  # overnight shift: today's evening part, or the morning after yesterday's start
            if h.weekday == today and t >= h.start:
                return True
            if h.weekday == yesterday and t < h.end:
                return True
    return False


# --- status ------------------------------------------------------------------

def is_online(profile, now=None):
    now = now or timezone.now()
    return bool(profile.last_seen_at and now - profile.last_seen_at <= ONLINE_WITHIN)


def current_status(profile, now=None):
    """The status to show right now, combining the last reading with tracking state."""
    now = now or timezone.now()
    if not profile.tracking_on:
        return LocationStatus.TRACKING_OFF
    if not profile.site_id:
        return LocationStatus.NO_SITE
    if not profile.last_ping_at or (profile.tracking_changed_at and profile.last_ping_at < profile.tracking_changed_at):
        return LocationStatus.WAITING
    if (now - profile.last_ping_at).total_seconds() > SIGNAL_LOST_AFTER_S:
        return LocationStatus.SIGNAL_LOST
    return LocationStatus(profile.last_status or LocationStatus.WAITING)


# --- turning tracking on and off ---------------------------------------------

def set_tracking(user, on, now=None):
    now = now or timezone.now()
    profile = profile_for(user)
    if profile.tracking_on != on:
        profile.tracking_on = on
        profile.tracking_changed_at = now
        profile.save(update_fields=["tracking_on", "tracking_changed_at"])
    evaluate_alerts([profile], now)
    return profile


# --- location updates --------------------------------------------------------

def _number(data, key, low, high):
    try:
        value = float(data.get(key))
    except (TypeError, ValueError):
        raise LocationError(f"Missing or invalid {key}.")
    if not math.isfinite(value) or not low <= value <= high:
        raise LocationError(f"{key} is out of range.")
    return value


def parse_update(data, now):
    """Validate an update from a phone. Never trust anything in it but the numbers."""
    lat = _number(data, "latitude", -90, 90)
    lng = _number(data, "longitude", -180, 180)
    accuracy = _number(data, "accuracy", 0, 100_000)
    ts = data.get("timestamp")
    if ts is None:
        measured = now
    else:
        try:
            measured = datetime.fromtimestamp(float(ts) / 1000, tz=dt_timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            raise LocationError("Invalid timestamp.")
        if measured > now + MAX_CLOCK_AHEAD:
            raise LocationError("The phone's clock looks wrong (reading is in the future).")
        if now - measured > MAX_READING_AGE:
            raise LocationError("This location reading is too old.")
    if lat == 0 and lng == 0:
        raise LocationError("Location 0,0 is not a real reading.")
    return lat, lng, accuracy, min(measured, now)


@transaction.atomic
def record_update(user, data, now=None):
    """Store one location update for `user` (always the logged-in user) and work out the status."""
    now = now or timezone.now()
    lat, lng, accuracy, measured = parse_update(data, now)
    profile = TrackingProfile.objects.select_for_update(of=("self",)).select_related("site").get(pk=profile_for(user).pk)
    if not profile.tracking_on:
        raise LocationError("Location tracking is off. Turn it on first.")
    if profile.last_ping_at and (now - profile.last_ping_at).total_seconds() < MIN_UPDATE_INTERVAL_S:
        raise RateLimited("Too many updates. Please wait a few seconds.")

    previous = LocationPing.objects.filter(user=user).only("measured_at").first()
    if previous and measured <= previous.measured_at:
        raise LocationError("This reading was already received.")

    flag = ""
    if profile.last_ping_at and profile.last_latitude is not None:
        moved = geo.distance_m(profile.last_latitude, profile.last_longitude, lat, lng)
        seconds = max((now - profile.last_ping_at).total_seconds(), 1)
        # Allow for both readings' uncertainty before calling it impossible.
        slack = accuracy + (profile.last_accuracy_m or 0)
        if moved > slack and (moved - slack) / seconds > MAX_SPEED_MPS:
            flag = f"Impossible jump of {moved:.0f} m in {seconds:.0f} s"

    site, distance, status = profile.site, None, ""
    if site:
        distance = geo.distance_m(site.latitude, site.longitude, lat, lng)
        status = geo.classify(distance, accuracy, site.radius_m)

    ping = LocationPing.objects.create(
        user=user, received_at=now, measured_at=measured, latitude=lat, longitude=lng, accuracy_m=accuracy,
        site=site, distance_m=distance, status=status, flag=flag,
    )
    if not flag:  # a flagged reading is kept for the record but does not change the person's status
        profile.last_ping_at = now
        profile.last_latitude, profile.last_longitude, profile.last_accuracy_m = lat, lng, accuracy
        profile.last_distance_m, profile.last_status = distance, status
        profile.last_seen_at = now
        profile.save()
    evaluate_alerts([profile], now)
    return ping, profile


# --- alerts ------------------------------------------------------------------

def _wanted_alerts(profile, now, hours_map=None):
    """The alert kinds that should be open for this person right now."""
    if not profile.user.is_active or not is_working(profile, now, hours_for(profile, hours_map)):
        return {}
    name = profile.user
    role = profile.user.get_role_display()
    status = current_status(profile, now)
    if status == LocationStatus.TRACKING_OFF:
        if profile.tracking_changed_at and now - profile.tracking_changed_at < timedelta(hours=12):
            return {Alert.Kind.TRACKING_OFF: f"{role} {name} turned off location sharing during working hours."}
        return {Alert.Kind.TRACKING_OFF: f"{role} {name} has not turned on location tracking."}
    if status == LocationStatus.SIGNAL_LOST:
        return {Alert.Kind.SIGNAL_LOST: f"{role} {name} has stopped sending location during working hours."}
    if status == LocationStatus.OFF:
        site = profile.site.name if profile.site else "their site"
        return {Alert.Kind.OFF_LOCATION: f"{role} {name} is OFF LOCATION ({profile.last_distance_m:.0f} m from {site})."}
    return {}


def evaluate_alerts(profiles=None, now=None, hours_map=None):
    """Open alerts for problems that exist now and close those that have cleared."""
    now = now or timezone.now()
    if hours_map is None and (profiles is None or len(profiles) > 1):
        hours_map = all_hours()
    if profiles is None:
        profiles = list(
            TrackingProfile.objects.select_related("user", "site").filter(user__role__in=TRACKED_ROLES)
        )
    if not profiles:
        return
    open_alerts = {}
    for a in Alert.objects.filter(user_id__in=[p.user_id for p in profiles], resolved_at__isnull=True):
        open_alerts[(a.user_id, a.kind)] = a
    for profile in profiles:
        wanted = _wanted_alerts(profile, now, hours_map)
        for kind, message in wanted.items():
            if (profile.user_id, kind) not in open_alerts:
                Alert.objects.create(user_id=profile.user_id, kind=kind, message=message, created_at=now)
        for (user_id, kind), alert in open_alerts.items():
            if user_id == profile.user_id and kind not in wanted:
                alert.resolved_at = now
                alert.save(update_fields=["resolved_at"])


def ensure_profiles():
    """Every active staff member and supervisor gets a tracking row (so 'not set up' people show)."""
    have = set(TrackingProfile.objects.values_list("user_id", flat=True))
    missing = User.objects.filter(role__in=TRACKED_ROLES, is_active=True).exclude(pk__in=have)
    TrackingProfile.objects.bulk_create([TrackingProfile(user=u) for u in missing], ignore_conflicts=True)


def purge_history(now=None):
    """Delete location history older than HISTORY_DAYS, and closed alerts older than that too."""
    cutoff = (now or timezone.now()) - timedelta(days=HISTORY_DAYS)
    pings, _ = LocationPing.objects.filter(received_at__lt=cutoff).delete()
    Alert.objects.filter(resolved_at__lt=cutoff).delete()
    return pings


# --- what each screen shows --------------------------------------------------

STATUS_HELP = {
    LocationStatus.ON: "At their assigned work location.",
    LocationStatus.NEAR: "Close to their work location (within 50 m).",
    LocationStatus.OFF: "More than 50 m away from their work location.",
    LocationStatus.WEAK: "Phone GPS is not accurate enough to tell right now.",
    LocationStatus.WAITING: "Tracking just turned on; waiting for the first reading.",
    LocationStatus.SIGNAL_LOST: "Tracking is on but no update for 5 minutes (phone locked, page closed or no network).",
    LocationStatus.TRACKING_OFF: "Location sharing is off.",
    LocationStatus.NO_SITE: "No work site assigned yet, so location cannot be checked.",
}

MY_STATUS_TEXT = {
    LocationStatus.ON: "You are at your assigned work location.",
    LocationStatus.NEAR: "You are close to your assigned work location.",
    LocationStatus.OFF: "You appear to be away from your assigned work location.",
    LocationStatus.WEAK: "Your GPS signal is weak. Move to an open area if you can.",
    LocationStatus.WAITING: "Finding your location...",
    LocationStatus.SIGNAL_LOST: "Your location has not been received for a while. Keep this page open.",
    LocationStatus.TRACKING_OFF: "Location sharing is currently off.",
    LocationStatus.NO_SITE: "You have no work site yet. Please tell your manager.",
}


def _iso(dt):
    return dt.isoformat() if dt else None


def my_state(user, now=None):
    """What a staff member or supervisor sees about themselves (never anyone else)."""
    now = now or timezone.now()
    profile = profile_for(user)
    status = current_status(profile, now)
    working = is_working(profile, now)
    return {
        "tracking_on": profile.tracking_on,
        "status": status.value,
        "status_label": status.label,
        "status_text": MY_STATUS_TEXT[status],
        "site": profile.site.name if profile.site else None,
        "distance_m": round(profile.last_distance_m) if profile.last_distance_m is not None and profile.tracking_on else None,
        "accuracy_m": round(profile.last_accuracy_m) if profile.last_accuracy_m is not None and profile.tracking_on else None,
        "last_update": _iso(profile.last_ping_at) if profile.tracking_on else None,
        "working_now": working,
        "tracking_required": working and not profile.tracking_on,
    }


COUNT_KEYS = ("on", "near", "off", "tracking_off", "other")


def manager_overview(now=None):
    """Counts, one row per tracked person, sites, and open alerts. Managers only."""
    now = now or timezone.now()
    ensure_profiles()
    profiles = list(
        TrackingProfile.objects.select_related("user", "site")
        .filter(user__role__in=TRACKED_ROLES, user__is_active=True)
        .order_by("user__first_name", "user__username")
    )
    hours_map = all_hours()
    evaluate_alerts(profiles, now, hours_map)
    if cache.add("tracking:purged-today", True, 24 * 3600):
        purge_history(now)

    counts = dict.fromkeys(COUNT_KEYS, 0)
    rows = []
    for p in profiles:
        status = current_status(p, now)
        bucket = status.value if status.value in COUNT_KEYS else "other"
        counts[bucket] += 1
        rows.append({
            "id": p.user_id,
            "name": str(p.user),
            "role": p.user.get_role_display(),
            "site": p.site.name if p.site else None,
            "site_id": p.site_id,
            "status": status.value,
            "status_label": status.label,
            "status_help": STATUS_HELP[status],
            "online": is_online(p, now),
            "tracking_on": p.tracking_on,
            "working_now": is_working(p, now, hours_for(p, hours_map)),
            "distance_m": round(p.last_distance_m) if p.last_distance_m is not None else None,
            "accuracy_m": round(p.last_accuracy_m) if p.last_accuracy_m is not None else None,
            "latitude": p.last_latitude if p.tracking_on else None,
            "longitude": p.last_longitude if p.tracking_on else None,
            "last_update": _iso(p.last_ping_at),
        })
    sites = [
        {"id": s.pk, "name": s.name, "latitude": float(s.latitude), "longitude": float(s.longitude), "radius_m": s.radius_m}
        for s in Site.objects.filter(is_active=True)
    ]
    alerts = [
        {"id": a.pk, "user_id": a.user_id, "kind": a.kind, "message": a.message, "since": _iso(a.created_at)}
        for a in Alert.objects.filter(resolved_at__isnull=True, user__is_active=True).order_by("-created_at")[:50]
    ]
    return {"now": _iso(now), "counts": counts, "people": rows, "sites": sites, "alerts": alerts}


def report_location(report):
    """The author's last location in the 15 minutes before a report was submitted, or None."""
    return (
        LocationPing.objects.filter(
            user_id=report.author_id,
            received_at__lte=report.created_at,
            received_at__gte=report.created_at - timedelta(minutes=15),
            flag="",
        )
        .select_related("site")
        .first()
    )
