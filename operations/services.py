"""Site operations rules: who sees which site, the OB, site visits and equipment held by each guard."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Role, User
from core.services import audit
from core.services.files import save_attachment
from notifications.services import notify_role
from tracking.models import Site, TrackingProfile

from .models import OBEntry, SiteVisit

OFFICE = (Role.SECRETARY, Role.MANAGER)
SITE_DETAIL_FIELDS = ["name", "address", "supervisor", "guards_needed", "instructions", "emergency_contacts", "is_active"]


# --- sites ------------------------------------------------------------------------

def sites_for(user):
    """Sites a person may look at. Office: all. Supervisor: theirs and their team's. Staff: their own."""
    if user.role in OFFICE:
        return Site.objects.all()
    if user.role == Role.SUPERVISOR:
        return Site.objects.filter(Q(supervisor=user) | Q(people__user__supervisor=user) | Q(people__user=user)).distinct()
    return Site.objects.filter(people__user=user)


def can_edit_site(user):
    """Only the Manager edits sites. The Secretary reads them (clients ask about their sites)."""
    return user.role == Role.MANAGER


@transaction.atomic
def update_site_details(site, before, user):
    site.details_updated_by, site.details_updated_at = user, timezone.now()
    site.save()
    after = audit.snapshot(site, SITE_DETAIL_FIELDS)
    audit.record(user, "site.details", site, f"Site details for {site} updated", changes=audit.changes_between(before, after))
    return site


def people_at(site):
    return User.objects.filter(tracking__site=site, is_active=True).order_by("first_name", "last_name")


# --- Occurrence Book --------------------------------------------------------------

def can_write_ob(user, site):
    """The people at the site write the OB. The office is not at a site: the Manager reads it, the Secretary has no OB."""
    if user.role in OFFICE:
        return False
    return sites_for(user).filter(pk=site.pk, is_active=True).exists()


def write_ob(site, user, kind, text, occurred_at=None, corrects=None, incident=None, check=True):
    """Add one OB entry. Entries are never changed afterwards.

    `check=False` is for entries the system writes for an allowed action (an incident report).
    """
    text = (text or "").strip()
    if not text:
        raise ValidationError("Write what happened.")
    if check and not can_write_ob(user, site):
        raise ValidationError("You can only write in the OB of your own site.")
    now = timezone.now()
    occurred_at = occurred_at or now
    if occurred_at > now + timedelta(minutes=10):
        raise ValidationError("The time cannot be in the future.")
    if corrects is not None and corrects.site_id != site.pk:
        raise ValidationError("A correction must be in the same site's OB.")
    entry = OBEntry.objects.create(site=site, occurred_at=occurred_at, kind=kind, text=text[:4000], written_by=user,
                                   corrects=corrects, incident=incident)
    audit.record(user, "ob.written", entry, f"{entry.number} at {site}: {entry.get_kind_display()}")
    return entry


QUICK_ENTRIES = {
    "shift_start": (OBEntry.Kind.SHIFT_START, "Shift started. All in order."),
    "patrol": (OBEntry.Kind.PATROL, "Patrol done. All in order."),
    "handover": (OBEntry.Kind.HANDOVER, "Handed over to the next guard. All in order."),
}


def my_site(user):
    profile = TrackingProfile.objects.filter(user=user).select_related("site").first()
    return profile.site if profile and profile.site and profile.site.is_active else None


# --- site visits -------------------------------------------------------------------

def can_visit(user):
    return user.role in (Role.SUPERVISOR, Role.MANAGER)


@transaction.atomic
def record_visit(site, user, visited_at, checks, guards, welfare, remarks, photo=None):
    if not can_visit(user):
        raise ValidationError("Only supervisors record site visits.")
    if user.role == Role.SUPERVISOR and not sites_for(user).filter(pk=site.pk).exists():
        raise ValidationError("You can only record visits to your own sites.")
    if visited_at > timezone.now() + timedelta(minutes=10):
        raise ValidationError("The visit time cannot be in the future.")
    valid = {code for code, _ in SiteVisit.CHECKS}
    visit = SiteVisit.objects.create(site=site, supervisor=user, visited_at=visited_at,
                                     checks_done=[c for c in checks if c in valid], welfare_check_done=welfare,
                                     remarks=remarks.strip())
    visit.guards_seen.set(guards)
    if photo is not None:
        save_attachment(visit, photo, user)
    done = len(visit.checks_done)
    text = f"Supervisor visit by {user}: {done} of {len(SiteVisit.CHECKS)} checks fine"
    text += ", welfare check done." if welfare else "."
    if remarks.strip():
        text += f" {remarks.strip()[:300]}"
    OBEntry.objects.create(site=site, occurred_at=visited_at, kind=OBEntry.Kind.SITE_VISIT, text=text, written_by=user)
    audit.record(user, "site.visited", visit, f"Visit to {site} recorded")
    return visit


# --- equipment held ------------------------------------------------------------------

def equipment_held(users=None):
    """Returnable items still out with people, newest first."""
    from inventory.models import ItemRequest

    R = ItemRequest.Status
    qs = ItemRequest.objects.filter(status__in=(R.ISSUED, R.RETURN_CLAIMED), item__returnable=True).select_related(
        "item", "requester", "requester__tracking__site")
    if users is not None:
        qs = qs.filter(requester__in=users)
    return qs.order_by("requester__first_name", "requester__last_name", "-handed_over_at")


def equipment_by_person(users=None):
    held = {}
    for r in equipment_held(users):
        held.setdefault(r.requester_id, []).append(r)
    return held


def remind_items_on_leaving(user):
    """When someone's account is turned off, tell the office which items to collect from them."""
    items = list(equipment_held([user]))
    if not items:
        return 0
    lines = ", ".join(f"{r.qty_issued or r.qty_requested} x {r.item.name}" for r in items)
    from django.urls import reverse

    notify_role(Role.SECRETARY, "items.collect", f"Collect items from {user}",
                f"{user}'s account was turned off. Items still with them: {lines}.",
                reverse("operations:equipment") + f"?person={user.pk}")
    return len(items)
