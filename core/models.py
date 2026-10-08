"""Shared building blocks used by the Secretary operations apps.

- CompanySettings: one row of company details used on invoices, plus a few switches.
- Attachment: a file (PDF/JPG/PNG) attached to any record, downloaded only through a permission check.
- AuditLog: an append-only record of who did what, with old and new values.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # Vercel refuses requests over 4.5 MB
STORED_FILE_MAX_BYTES = 5 * 1024 * 1024  # database limit; older files may be up to 5 MB
ALLOWED_MIME_TYPES = ("application/pdf", "image/jpeg", "image/png")


class CompanySettings(models.Model):
    """The single row (id=1) of company details. Edited by the Manager only."""

    company_name = models.CharField(max_length=150, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    kra_pin = models.CharField("KRA PIN", max_length=20, blank=True)
    logo = models.FileField(upload_to="company/", blank=True)
    payment_instructions = models.TextField(blank=True, help_text="Bank or paybill details printed on invoices.")
    vat_registered = models.BooleanField(default=False)
    vat_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("16.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    invoice_due_days = models.PositiveSmallIntegerField(default=14)
    expense_approval_enabled = models.BooleanField(default=False)
    expense_approval_limit = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    last_checks_at = models.DateTimeField(null=True, blank=True)
    # Attendance, leave and sick leave.
    late_after_minutes = models.PositiveSmallIntegerField(
        "late after (minutes)", default=15,
        help_text="Someone who signs in more than this many minutes after their shift starts is marked late.",
    )
    sick_note_due_days = models.PositiveSmallIntegerField(
        "sick sheet expected within (days)", default=3,
        help_text="A reminder goes out if no sick sheet has been uploaded this many days after sick leave starts.",
    )
    sick_note_keep_days = models.PositiveSmallIntegerField(
        "keep sick sheets for (days)", default=365, validators=[MinValueValidator(30)],
        help_text="Sick sheet files are deleted after this many days. The dates of the sick leave are kept.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = verbose_name_plural = "company settings"
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="companysettings_single_row"),
            models.CheckConstraint(condition=Q(vat_rate__gte=0, vat_rate__lte=100), name="companysettings_vat_rate_range"),
            models.CheckConstraint(
                condition=Q(expense_approval_limit__isnull=True) | Q(expense_approval_limit__gt=0),
                name="companysettings_expense_limit_positive",
            ),
        ]

    def __str__(self):
        return self.company_name or "Company settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


def attachment_path(instance, filename):
    # Random stored name: the original name is kept in `original_name` for display only.
    ext = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}.get(instance.mime_type, "bin")
    return f"attachments/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext}"


class Attachment(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    parent = GenericForeignKey("content_type", "object_id")
    file = models.FileField(upload_to=attachment_path)
    original_name = models.CharField(max_length=200)
    mime_type = models.CharField(max_length=50)
    size_bytes = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]
        constraints = [
            models.CheckConstraint(condition=Q(mime_type__in=ALLOWED_MIME_TYPES), name="attachment_allowed_type"),
            models.CheckConstraint(condition=Q(size_bytes__lte=STORED_FILE_MAX_BYTES), name="attachment_max_size"),
        ]

    def __str__(self):
        return self.original_name


class AuditLog(models.Model):
    """Append-only: never edited or deleted through the app or the admin site."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    actor_role = models.CharField(max_length=20, blank=True)
    action = models.CharField(max_length=60, db_index=True)
    entity_type = models.CharField(max_length=60)
    entity_id = models.CharField(max_length=40)
    summary = models.CharField(max_length=255)
    changes = models.JSONField(default=dict, blank=True)
    confidential = models.BooleanField(default=False, help_text="Payroll entries: only Secretary and Manager may see them.")

    class Meta:
        ordering = ["-at", "-id"]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.actor}: {self.summary}"
