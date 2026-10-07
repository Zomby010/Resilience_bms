from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q


class Escalation(models.Model):
    """'Send to Manager': links to the original record so nothing is copied by hand."""

    class Kind(models.TextChoices):
        ISSUE = "issue", "Client issue"
        FEEDBACK = "feedback", "Client feedback"
        ITEM = "item", "Item"
        PAYROLL = "payroll", "Payroll"
        OTHER = "other", "Other matter"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        SEEN = "seen", "Seen by Manager"
        SENT_BACK = "sent_back", "Sent back to Secretary"
        RESOLVED = "resolved", "Resolved"

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.PROTECT)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    record = GenericForeignKey("content_type", "object_id")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    subject = models.CharField(max_length=200)
    note = models.TextField(help_text="What the Secretary needs from the Manager.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    raised_at = models.DateTimeField(auto_now_add=True)
    seen_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-raised_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id"],
                condition=~Q(status="resolved") & Q(object_id__isnull=False),
                name="one_open_escalation_per_record",
            ),
            models.CheckConstraint(
                condition=Q(kind="other") | Q(content_type__isnull=False, object_id__isnull=False),
                name="escalation_record_required_unless_other",
            ),
        ]

    def __str__(self):
        return f"Escalation #{self.pk}: {self.subject}"


class EscalationReply(models.Model):
    escalation = models.ForeignKey(Escalation, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "escalation replies"

    def __str__(self):
        return f"Reply by {self.author} on escalation #{self.escalation_id}"
