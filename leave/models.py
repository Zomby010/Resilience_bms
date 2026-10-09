"""Leave (F2) and sick leave with confidential sick sheets (F3).

- LeaveType: annual, maternity, paternity and so on, with the days allowed each year.
- LeaveAllowance: the days the Manager has set for one person, one type, one year.
- LeaveRequest: someone asks for days off; the Manager decides and types the days given.
- SickLeave: sickness is reported and counts at once; no approval is needed to be off sick.
- SickNote: the sick sheet file. Stored outside the normal upload folder and only handed out
  to the person, the Secretary and the Manager, through a view that logs every download.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse


class LeaveType(models.Model):
    class Counting(models.TextChoices):
        WORKING = "working", "Working days"
        CALENDAR = "calendar", "Calendar days"

    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=60)
    days_per_year = models.PositiveSmallIntegerField(
        default=0, help_text="Days allowed each year. 0 means there is no fixed number (for example unpaid leave)."
    )
    counting = models.CharField(max_length=10, choices=Counting.choices, default=Counting.WORKING)
    needs_balance = models.BooleanField(
        default=True, help_text="When ticked, nobody but the Manager can ask for more days than they have left."
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class LeaveAllowance(models.Model):
    """Days allowed for one person, one leave type and one year. Set by the Manager."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_allowances")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name="+")
    year = models.PositiveSmallIntegerField()
    days = models.DecimalField(max_digits=5, decimal_places=1)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    set_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "leave_type", "year"], name="one_allowance_per_person_type_year"),
            models.CheckConstraint(condition=Q(days__gte=0), name="allowance_not_negative"),
        ]

    def __str__(self):
        return f"{self.user}: {self.days} days of {self.leave_type} in {self.year}"


class LeaveRequestQuerySet(models.QuerySet):
    def visible_to(self, user):
        from accounts.models import Role

        if user.role in (Role.MANAGER, Role.SECRETARY):
            return self
        if user.role == Role.SUPERVISOR:
            return self.filter(Q(user=user) | Q(user__supervisor=user))
        return self.filter(user=user)

    def covering(self, day):
        # The days the Manager gave decide when the person is back, not the days asked for.
        return self.filter(start_date__lte=day).filter(
            Q(last_day_given__gte=day) | Q(last_day_given__isnull=True, end_date__gte=day)
        )


class LeaveRequest(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting for approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Not approved"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="requests")
    start_date = models.DateField("first day off")
    end_date = models.DateField("last day off")
    days = models.DecimalField(max_digits=5, decimal_places=1, help_text="Days asked for.")
    days_given = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True, help_text="Days the Manager gave. Empty until decided."
    )
    last_day_given = models.DateField(null=True, blank=True, help_text="Last day off, counted from the days given.")
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.WAITING, db_index=True)
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="leave_to_approve",
        help_text="The supervisor who decides. Empty means the Manager decides.",
    )
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = LeaveRequestQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date", "-id"]
        constraints = [models.CheckConstraint(condition=Q(end_date__gte=models.F("start_date")), name="leave_end_after_start")]

    def __str__(self):
        return f"{self.user}: {self.leave_type} {self.start_date:%d %b} to {self.end_date:%d %b %Y}"

    def get_absolute_url(self):
        return reverse("leave:request_detail", args=[self.pk])

    @property
    def last_day_off(self):
        return self.last_day_given or self.end_date


class SickLeaveQuerySet(models.QuerySet):
    def visible_to(self, user):
        from accounts.models import Role

        if user.role in (Role.MANAGER, Role.SECRETARY):
            return self
        if user.role == Role.SUPERVISOR:
            return self.filter(Q(user=user) | Q(user__supervisor=user))
        return self.filter(user=user)

    def covering(self, day):
        return self.filter(first_day__lte=day, last_day__gte=day)


class SickLeave(models.Model):
    class Status(models.TextChoices):
        CERTIFICATE_NEEDED = "certificate_needed", "Sick sheet needed"
        CERTIFICATE_RECEIVED = "certificate_received", "Sick sheet received"
        ACCEPTED = "accepted", "Accepted"
        NOT_ACCEPTED = "not_accepted", "Not accepted"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sick_leaves")
    first_day = models.DateField("first day off sick")
    last_day = models.DateField("expected last day off", help_text="Change it later if they come back earlier or later.")
    comment = models.TextField(blank=True, help_text="Do not write medical details here.")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.CERTIFICATE_NEEDED, db_index=True)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SickLeaveQuerySet.as_manager()

    class Meta:
        ordering = ["-first_day", "-id"]
        constraints = [models.CheckConstraint(condition=Q(last_day__gte=models.F("first_day")), name="sick_last_after_first")]

    def __str__(self):
        return f"{self.user}: sick {self.first_day:%d %b} to {self.last_day:%d %b %Y}"

    def get_absolute_url(self):
        return reverse("leave:sick_detail", args=[self.pk])

    @property
    def days(self):
        return (self.last_day - self.first_day).days + 1


def sick_note_storage():
    """Sick sheets get their own private bucket when files are kept in the cloud."""
    from django.core.files.storage import default_storage, storages

    return storages["sicksheets"] if "sicksheets" in settings.STORAGES else default_storage


def sick_note_path(instance, filename):
    # A separate folder from ordinary attachments, with a random name: nothing about the person or the illness.
    ext = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}.get(instance.mime_type, "bin")
    return f"medical/{uuid.uuid4().hex}.{ext}"


class SickNote(models.Model):
    """A sick sheet. The file is deleted after the keep period; this row stays as a record that one was given."""

    sick_leave = models.ForeignKey(SickLeave, on_delete=models.CASCADE, related_name="notes")
    file = models.FileField(upload_to=sick_note_path, storage=sick_note_storage, blank=True)
    original_name = models.CharField(max_length=200)
    mime_type = models.CharField(max_length=50)
    size_bytes = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    removed_at = models.DateTimeField(null=True, blank=True, help_text="When the file was deleted under the keep period.")

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"Sick sheet for {self.sick_leave}"
