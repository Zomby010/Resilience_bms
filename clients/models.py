"""Clients, their responsible supervisor, client issues, feedback and communication history.

Clients have no login (owner decision D1): the Secretary records what they send in,
and messages and invoices reach them by email.
"""
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse

from accounts.models import Role

kenyan_phone = RegexValidator(
    r"^(?:\+254|0)(?:7|1)\d{8}$",
    "Enter a Kenyan phone number such as 0712345678, 0112345678 or +254712345678.",
)


class Client(models.Model):
    name = models.CharField("client / organisation name", max_length=150, db_index=True)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=20, blank=True, validators=[kenyan_phone])
    email = models.EmailField(blank=True)
    physical_address = models.CharField(max_length=255, blank=True)
    postal_address = models.CharField(max_length=120, blank=True)
    area = models.CharField("location / area", max_length=120, blank=True)
    service_description = models.TextField("service provided", blank=True)
    contract_start = models.DateField(null=True, blank=True)
    contract_end = models.DateField(null=True, blank=True)
    monthly_charge = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))]
    )
    kra_pin = models.CharField("KRA PIN", max_length=20, blank=True)
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clients",
        limit_choices_to={"role": Role.SUPERVISOR},
        help_text="The supervisor responsible for this client. New issues go to them automatically.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField("office notes", blank=True, help_text="Internal only. Never sent to the client.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=~Q(phone="") | ~Q(email=""), name="client_phone_or_email"),
            models.CheckConstraint(
                condition=Q(contract_end__isnull=True) | Q(contract_start__isnull=True) | Q(contract_end__gte=models.F("contract_start")),
                name="client_contract_dates_order",
            ),
            models.CheckConstraint(
                condition=Q(monthly_charge__isnull=True) | Q(monthly_charge__gte=0), name="client_monthly_charge_not_negative"
            ),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("clients:detail", args=[self.pk])


class SupervisorAssignment(models.Model):
    """History of who was responsible for a client and when."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="assignments")
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-started_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["client"], condition=Q(ended_at__isnull=True), name="one_current_assignment_per_client"
            )
        ]

    def __str__(self):
        return f"{self.supervisor or 'No supervisor'} for {self.client}"


class ClientSite(models.Model):
    """Links a client to the GPS work sites that belong to it (GPS tables stay untouched)."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="site_links")
    site = models.OneToOneField("tracking.Site", on_delete=models.CASCADE, related_name="client_link")

    class Meta:
        ordering = ["site__name"]

    def __str__(self):
        return f"{self.site} ({self.client})"


class Issue(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        NEW = "new", "New"
        SUPERVISOR_NEEDED = "supervisor_needed", "Supervisor needed"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In progress"
        WAITING_FEEDBACK = "waiting_feedback", "Waiting for feedback"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="issues")
    subject = models.CharField(max_length=200)
    description = models.TextField()
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_issues"
    )
    source_feedback = models.ForeignKey(
        "Feedback", null=True, blank=True, on_delete=models.SET_NULL, related_name="issues"
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["supervisor", "status"])]

    def __str__(self):
        return f"{self.number} {self.subject}"

    @property
    def number(self):
        return f"ISS-{self.pk:04d}" if self.pk else "ISS-new"

    def get_absolute_url(self):
        return reverse("clients:issue_detail", args=[self.pk])


class IssueNote(models.Model):
    """The progress trail: notes and status changes, with who and when."""

    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    body = models.TextField(blank=True)
    status_from = models.CharField(max_length=20, blank=True)
    status_to = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Note on {self.issue.number}"


class Feedback(models.Model):
    class Kind(models.TextChoices):
        COMPLIMENT = "compliment", "Compliment"
        COMPLAINT = "complaint", "Complaint"
        SUGGESTION = "suggestion", "Suggestion"

    class Channel(models.TextChoices):
        PHONE = "phone", "Phone"
        EMAIL = "email", "Email"
        WHATSAPP = "whatsapp", "WhatsApp"
        IN_PERSON = "in_person", "In person"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        NEW = "new", "New"
        REVIEWED = "reviewed", "Reviewed"
        RESPONDED = "responded", "Responded"
        ESCALATED = "escalated", "Escalated"
        CLOSED = "closed", "Closed"

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="feedback")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    channel = models.CharField("received by", max_length=20, choices=Channel.choices)
    subject = models.CharField(max_length=200)
    body = models.TextField("feedback")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    response = models.TextField(blank=True)
    response_channel = models.CharField(max_length=20, choices=Channel.choices, blank=True)
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-recorded_at", "-id"]
        verbose_name_plural = "feedback"
        indexes = [models.Index(fields=["client", "-recorded_at"])]

    def __str__(self):
        return f"{self.get_kind_display()} from {self.client}: {self.subject}"


class Message(models.Model):
    """One entry in a client's communication history (usually an email)."""

    class Kind(models.TextChoices):
        NOTIFICATION = "notification", "Notification"
        INVOICE = "invoice", "Invoice"
        FEEDBACK_RESPONSE = "feedback_response", "Response"
        ISSUE_UPDATE = "issue_update", "Issue update"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        RECORDED_OFFLINE = "recorded_offline", "Delivered by phone / in person"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        URGENT = "urgent", "Urgent"

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="messages")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.NOTIFICATION)
    subject = models.CharField(max_length=200)
    body = models.TextField("message")
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    to_email = models.EmailField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    error = models.TextField(blank=True)
    related_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    related_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["client", "-created_at"])]

    def __str__(self):
        return f"{self.get_kind_display()} to {self.client}: {self.subject}"
