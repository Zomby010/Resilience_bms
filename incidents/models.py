from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse

from accounts.models import Role


class IncidentQuerySet(models.QuerySet):
    def visible_to(self, user):
        """The one rule for who sees which incident (pages, lists, CSV and file downloads)."""
        if not user.is_authenticated:
            return self.none()
        if user.role == Role.MANAGER:
            return self
        if user.role == Role.SECRETARY:
            return self.none()
        if user.role == Role.SUPERVISOR:
            return self.filter(Q(reported_by=user) | Q(reported_by__supervisor=user) | Q(site__supervisor=user))
        return self.filter(reported_by=user)


class Incident(models.Model):
    """Something that went wrong at a site, reported by the person who saw it."""

    class Kind(models.TextChoices):
        THEFT = "theft", "Theft"
        BREAK_IN = "break_in", "Break-in"
        FIRE = "fire", "Fire"
        INJURY = "injury", "Injury"
        TRESPASS = "trespass", "Trespass"
        DAMAGE = "damage", "Damage"
        FORCE_ARREST = "force_arrest", "Use of force or arrest"
        OTHER = "other", "Other"

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        REPORTED = "reported", "Reported"
        SUPERVISOR_REVIEWED = "supervisor_reviewed", "Reviewed by supervisor"
        MANAGER_REVIEWED = "manager_reviewed", "Reviewed by manager"
        CLOSED = "closed", "Closed"

    site = models.ForeignKey("tracking.Site", on_delete=models.PROTECT, related_name="incidents")
    occurred_at = models.DateTimeField("date and time it happened", db_index=True)
    kind = models.CharField("type", max_length=20, choices=Kind.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    what_happened = models.TextField()
    who_involved = models.TextField("who was involved", blank=True)
    action_taken = models.TextField(blank=True)
    police_reported = models.BooleanField("reported to the police", default=False)
    police_ob_number = models.CharField("police OB number", max_length=50, blank=True)
    client_told = models.BooleanField("client was told", default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REPORTED, db_index=True)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="incidents_reported")
    reported_at = models.DateTimeField(auto_now_add=True)
    supervisor_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    supervisor_reviewed_at = models.DateTimeField(null=True, blank=True)
    manager_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    manager_reviewed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = IncidentQuerySet.as_manager()

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [models.Index(fields=["site", "-occurred_at"])]

    def __str__(self):
        return f"{self.number} {self.get_kind_display()}"

    def clean(self):
        if self.police_reported and not (self.police_ob_number or "").strip():
            raise ValidationError({"police_ob_number": "Write the police OB number."})

    @property
    def number(self):
        return f"INC-{self.pk:04d}" if self.pk else "INC-new"

    @property
    def serious(self):
        return self.severity in (self.Severity.HIGH, self.Severity.CRITICAL)

    def get_absolute_url(self):
        return reverse("incidents:detail", args=[self.pk])


class IncidentNote(models.Model):
    """The trail: notes and status changes, with who and when."""

    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    body = models.TextField(blank=True)
    status_from = models.CharField(max_length=20, blank=True)
    status_to = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Note on {self.incident.number}"

    @property
    def status_to_label(self):
        return Incident.Status(self.status_to).label if self.status_to in Incident.Status.values else self.status_to
