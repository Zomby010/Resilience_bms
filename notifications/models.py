from django.conf import settings
from django.db import models


class Notification(models.Model):
    """An in-app message for one person. Clicking it opens `link_url` and marks it read."""

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        HIGH = "high", "Important"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=40)
    title = models.CharField(max_length=120)
    message = models.TextField(blank=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    link_url = models.CharField(max_length=300, blank=True)
    entity_type = models.CharField(max_length=60, blank=True)
    entity_id = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["recipient", "read_at", "-created_at"])]

    def __str__(self):
        return f"{self.recipient}: {self.title}"

    @property
    def is_read(self):
        return self.read_at is not None
