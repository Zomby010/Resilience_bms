"""Invoices to clients, their line items and the payments received."""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        PART_PAID = "part_paid", "Part paid"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"
        CANCELLED = "cancelled", "Cancelled"

    # Given only when the invoice is first sent, so abandoned drafts leave no gaps.
    number = models.CharField(max_length=20, unique=True, null=True, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    seq = models.PositiveIntegerField(null=True, blank=True)
    client = models.ForeignKey("clients.Client", on_delete=models.PROTECT, related_name="invoices")
    # Copied when sent, so later edits to the client never change a sent invoice.
    bill_to_name = models.CharField(max_length=150, blank=True)
    bill_to_address = models.TextField(blank=True)
    bill_to_kra_pin = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    invoice_date = models.DateField()
    due_date = models.DateField(db_index=True)
    vat_enabled = models.BooleanField(default=False)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True)
    payment_instructions = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-invoice_date", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["year", "seq"], name="invoice_unique_year_seq"),
            models.CheckConstraint(condition=Q(due_date__gte=F("invoice_date")), name="invoice_due_after_date"),
            models.CheckConstraint(
                condition=Q(subtotal__gte=0, vat_amount__gte=0, total__gte=0, amount_paid__gte=0),
                name="invoice_amounts_not_negative",
            ),
            models.CheckConstraint(condition=Q(amount_paid__lte=F("total")), name="invoice_paid_not_above_total"),
            models.CheckConstraint(condition=Q(vat_rate__gte=0, vat_rate__lte=100), name="invoice_vat_rate_range"),
        ]

    def __str__(self):
        return self.number or f"Draft invoice #{self.pk}"

    def get_absolute_url(self):
        return reverse("billing:detail", args=[self.pk])

    @property
    def balance(self):
        return self.total - self.amount_paid


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveSmallIntegerField(default=0)
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="invoiceline_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="invoiceline_price_not_negative"),
        ]

    def __str__(self):
        return self.description


class Payment(models.Model):
    class Method(models.TextChoices):
        MPESA = "mpesa", "M-Pesa"
        BANK = "bank", "Bank transfer"
        CASH = "cash", "Cash"
        CHEQUE = "cheque", "Cheque"

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    paid_on = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=10, choices=Method.choices)
    reference = models.CharField(max_length=60, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["paid_on", "id"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive")]

    def __str__(self):
        return f"KES {self.amount} on {self.invoice}"


class InvoiceCounter(models.Model):
    """The last invoice sequence number used in each year."""

    year = models.PositiveSmallIntegerField(primary_key=True)
    last_seq = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.year}: {self.last_seq}"
