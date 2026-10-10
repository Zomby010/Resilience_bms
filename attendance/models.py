"""Daily attendance.

Each guard (and supervisor) signs in at their site. The sign-in is stamped with the server time
and the distance from the site, then goes to their supervisor for approval and finally to the
Manager, who completes the day. Completing the day also records who was absent, on leave or sick.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse


class AttendanceRecordQuerySet(models.QuerySet):
    def visible_to(self, user):
        from accounts.models import Role

        if user.role in (Role.MANAGER, Role.SECRETARY):
            return self
        if user.role == Role.SUPERVISOR:
            return self.filter(Q(user=user) | Q(user__supervisor=user))
        return self.filter(user=user)


class AttendanceRecord(models.Model):
    class Outcome(models.TextChoices):
        PRESENT = "present", "Present"
        LATE = "late", "Late"
        ABSENT = "absent", "Absent"
        ON_LEAVE = "on_leave", "On leave"
        SICK = "sick", "Sick"

    class Status(models.TextChoices):
        WAITING_SUPERVISOR = "waiting_supervisor", "Waiting for supervisor"
        WAITING_MANAGER = "waiting_manager", "Waiting for Manager"
        REJECTED = "rejected", "Not accepted by supervisor"
        COMPLETED = "completed", "Completed"

    class Method(models.TextChoices):
        GPS = "gps", "Signed in at the site"
        NO_LOCATION = "no_location", "Signed in without location"
        SUPERVISOR = "supervisor", "Marked by supervisor"
        OFFICE = "office", "Marked by the Manager"
        SYSTEM = "system", "Recorded when the day was completed"

    class Reason(models.TextChoices):
        """Why the phone's location could not be used (Q7)."""
        NO_SIGNAL = "no_signal", "No signal"
        PHONE = "phone", "Phone problem"
        WRONG_PLACE = "wrong_place", "GPS shows wrong place"
        OTHER = "other", "Other"

    class OutMethod(models.TextChoices):
        GPS = "gps", "Signed out with location"
        NO_LOCATION = "no_location", "Signed out without location"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="attendance")
    date = models.DateField(db_index=True, help_text="The day the shift started.")
    site = models.ForeignKey("tracking.Site", null=True, blank=True, on_delete=models.SET_NULL, related_name="attendance")
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="attendance_to_approve",
        help_text="Who approves this sign-in. Empty means it goes straight to the Manager.",
    )
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    status = models.CharField(max_length=20, choices=Status.choices, db_index=True)
    method = models.CharField(max_length=20, choices=Method.choices)
    signed_in_at = models.DateTimeField(null=True, blank=True, help_text="Server time of the sign-in.")
    shift_start = models.DateTimeField(null=True, blank=True)
    late_minutes = models.PositiveIntegerField(default=0)
    # Where the phone was at sign-in. Only the distance and status are ever shown; never to supervisors.
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    accuracy_m = models.FloatField(null=True, blank=True)
    distance_m = models.FloatField(null=True, blank=True)
    location_status = models.CharField(max_length=20, blank=True)
    manual_reason = models.CharField("reason for no location", max_length=20, choices=Reason.choices, blank=True)
    # Sign-out is recorded, never approved, and never filled in for the person (Q8).
    signed_out_at = models.DateTimeField(null=True, blank=True, help_text="Server time of the sign-out.")
    sign_out_method = models.CharField(max_length=20, choices=OutMethod.choices, blank=True)
    sign_out_distance_m = models.FloatField(null=True, blank=True)
    sign_out_reason = models.CharField(max_length=20, choices=Reason.choices, blank=True)
    note = models.CharField(max_length=255, blank=True)
    marked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    supervisor_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    supervisor_decided_at = models.DateTimeField(null=True, blank=True)
    supervisor_note = models.CharField(max_length=255, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AttendanceRecordQuerySet.as_manager()

    class Meta:
        ordering = ["-date", "user__first_name"]
        constraints = [models.UniqueConstraint(fields=["user", "date"], name="one_attendance_per_person_day")]
        indexes = [models.Index(fields=["date", "status"])]

    def __str__(self):
        return f"{self.user} on {self.date:%d %b %Y}: {self.get_outcome_display()}"

    def get_absolute_url(self):
        return reverse("attendance:records") + f"?from={self.date}&to={self.date}&person={self.user_id}"

    @property
    def worked(self):
        if self.signed_in_at and self.signed_out_at and self.signed_out_at > self.signed_in_at:
            return self.signed_out_at - self.signed_in_at
        return None

    @property
    def in_out(self):
        """'In 06:50 · Out 18:05 · 11 h 15 m', 'In 06:50 · Not signed out yet' or 'In 06:50 · No sign-out' (Q8:
        never filled in). Empty when there was no sign-in."""
        from django.utils import timezone

        if not self.signed_in_at:
            return ""
        text = f"In {timezone.localtime(self.signed_in_at):%H:%M}"
        if not self.signed_out_at:
            from datetime import timedelta

            # Today's (or a night shift from yesterday) may still be going on; older days are simply missing it.
            still_open = self.date >= timezone.localdate() - timedelta(days=1)
            return text + (" · Not signed out yet" if still_open else " · No sign-out")
        text += f" · Out {timezone.localtime(self.signed_out_at):%H:%M}"
        worked = self.worked
        if worked:
            minutes = int(worked.total_seconds() // 60)
            text += f" · {minutes // 60} h {minutes % 60} m"
        return text

    @property
    def is_in(self):
        return self.outcome in (self.Outcome.PRESENT, self.Outcome.LATE) and self.status != self.Status.REJECTED


class AttendanceDay(models.Model):
    """One row per day the Manager has completed. A completed day can no longer change."""

    date = models.DateField(unique=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    completed_at = models.DateTimeField()
    present = models.PositiveIntegerField(default=0)
    late = models.PositiveIntegerField(default=0)
    absent = models.PositiveIntegerField(default=0)
    on_leave = models.PositiveIntegerField(default=0)
    sick = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"Attendance for {self.date:%d %b %Y}"
