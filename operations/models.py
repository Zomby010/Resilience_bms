"""Site operations: the digital Occurrence Book (OB) and supervisor site visits.

OB entries are never edited or deleted. A mistake is put right with a new entry that points
at the one it corrects, exactly like a paper OB where you never tear out a page.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse


def _visible_sites_q(user, prefix="site__"):
    """Sites a supervisor looks after, or where their team (or they) are posted."""
    return (Q(**{f"{prefix}supervisor": user}) | Q(**{f"{prefix}people__user__supervisor": user})
            | Q(**{f"{prefix}people__user": user}))


class OBEntryQuerySet(models.QuerySet):
    def visible_to(self, user):
        from accounts.models import Role

        if user.role in (Role.MANAGER, Role.SECRETARY):
            return self
        if user.role == Role.SUPERVISOR:
            return self.filter(_visible_sites_q(user) | Q(written_by=user)).distinct()
        return self.filter(Q(site__people__user=user) | Q(written_by=user)).distinct()


class OBEntry(models.Model):
    class Kind(models.TextChoices):
        SHIFT_START = "shift_start", "Shift started"
        HANDOVER = "handover", "Handover to next guard"
        PATROL = "patrol", "Patrol done"
        VISITOR = "visitor", "Visitor or vehicle"
        DELIVERY = "delivery", "Delivery or keys"
        ALARM = "alarm", "Alarm or power problem"
        INCIDENT = "incident", "Incident"
        SITE_VISIT = "site_visit", "Supervisor visit"
        OTHER = "other", "Other"

    site = models.ForeignKey("tracking.Site", on_delete=models.PROTECT, related_name="ob_entries")
    occurred_at = models.DateTimeField(db_index=True, help_text="When it happened.")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    text = models.TextField()
    written_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ob_entries")
    written_at = models.DateTimeField(auto_now_add=True)
    corrects = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="corrections",
                                 help_text="The earlier entry this one corrects.")
    incident = models.ForeignKey("incidents.Incident", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    objects = OBEntryQuerySet.as_manager()

    class Meta:
        ordering = ["-occurred_at", "-id"]
        verbose_name = "OB entry"
        verbose_name_plural = "OB entries"

    def __str__(self):
        return f"{self.number} {self.site}: {self.get_kind_display()}"

    @property
    def number(self):
        return f"OB-{self.pk:05d}" if self.pk else "OB-new"

    # One icon and tone per kind, so a page of entries can be scanned (always shown with the kind's words).
    LOOK = {"shift_start": ("🟢", "calm"), "handover": ("🟢", "calm"), "patrol": ("🔁", ""), "visitor": ("🚗", ""),
            "delivery": ("📦", ""), "alarm": ("🔔", "amber"), "incident": ("🚨", "red"), "site_visit": ("🧭", "blue"),
            "other": ("📝", "")}

    @property
    def icon(self):
        return self.LOOK.get(self.kind, ("📝", ""))[0]

    @property
    def tone(self):
        return self.LOOK.get(self.kind, ("", ""))[1]

    def can_correct(self, user):
        """Supervisors correct any entry they can see; a guard only their own, within 24 hours of writing it."""
        from datetime import timedelta

        from django.utils import timezone

        from accounts.models import Role

        if user.role == Role.SUPERVISOR:
            return True
        return (user.role == Role.STAFF and self.written_by_id == user.pk
                and self.written_at >= timezone.now() - timedelta(hours=24))


class SiteVisitQuerySet(models.QuerySet):
    def visible_to(self, user):
        from accounts.models import Role

        if user.role in (Role.MANAGER, Role.SECRETARY):
            return self
        if user.role == Role.SUPERVISOR:
            return self.filter(supervisor=user)
        return self.none()


class SiteVisit(models.Model):
    CHECKS = (
        ("guards_at_post", "Guards at their post"),
        ("uniform", "Guards in full uniform"),
        ("ob_up_to_date", "OB written up to date"),
        ("equipment_ok", "Equipment working (torch, radio, phone)"),
        ("site_secure", "Gates, doors and fence secure"),
        ("client_spoken", "Spoke with the client"),
    )

    site = models.ForeignKey("tracking.Site", on_delete=models.PROTECT, related_name="visits")
    supervisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="site_visits")
    visited_at = models.DateTimeField(db_index=True)
    checks_done = models.JSONField(default=list, blank=True, help_text="Codes from SiteVisit.CHECKS that were fine.")
    guards_seen = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    welfare_check_done = models.BooleanField("welfare check done", default=False)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SiteVisitQuerySet.as_manager()

    class Meta:
        ordering = ["-visited_at", "-id"]

    def __str__(self):
        return f"Visit to {self.site} by {self.supervisor} on {self.visited_at:%d %b %Y}"

    def get_absolute_url(self):
        return reverse("operations:visit_detail", args=[self.pk])

    @property
    def check_labels(self):
        done = set(self.checks_done or [])
        return [(label, code in done) for code, label in self.CHECKS]
