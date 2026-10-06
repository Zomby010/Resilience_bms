from django.conf import settings
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role


class Status(models.TextChoices):
    PENDING = "pending", "Pending"
    REVIEWED = "reviewed", "Reviewed"
    COMPLETED = "completed", "Completed"


class ReportQuerySet(models.QuerySet):
    def visible_to(self, user):
        """The single source of truth for who may see which reports.

        Manager: everything. Supervisor: their own plus their team's.
        Staff: their own. Secretary (and anyone else): nothing.
        """
        if user.role == Role.MANAGER:
            return self
        if user.role == Role.SUPERVISOR:
            return self.filter(Q(author=user) | Q(author__supervisor=user))
        if user.role == Role.STAFF:
            return self.filter(author=user)
        return self.none()

    def open(self):
        return self.exclude(status=Status.COMPLETED)


class Report(models.Model):
    """Staff -> Supervisor -> Manager. Every step is time-stamped and attributed."""

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reports")
    title = models.CharField(max_length=200)
    body = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = ReportQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.title}"

    def get_absolute_url(self):
        return reverse("reports:detail", args=[self.pk])

    # --- who may act on this report -------------------------------------
    def can_reply(self, user):
        if not user.is_authenticated or user.pk == self.author_id:
            return False
        if user.role == Role.MANAGER:
            return True
        if user.role == Role.SUPERVISOR:
            return self.author.supervisor_id == user.pk
        return False

    def can_edit(self, user):
        # Authors may fix a report until someone has responded to it.
        return user.pk == self.author_id and self.status == Status.PENDING

    # --- workflow ---------------------------------------------------------
    @transaction.atomic
    def add_reply(self, user, body, complete=False):
        """Record feedback and move the report along its workflow."""
        reply = Reply.objects.create(report=self, author=user, body=body)
        now = timezone.now()
        if user.role == Role.MANAGER and complete:
            self.status = Status.COMPLETED
            self.completed_by, self.completed_at = user, now
        elif self.status == Status.PENDING:
            self.status = Status.REVIEWED
            self.reviewed_by, self.reviewed_at = user, now
        self.save()
        return reply


class Reply(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="replies")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "replies"

    def __str__(self):
        return f"Reply by {self.author} on {self.report}"
