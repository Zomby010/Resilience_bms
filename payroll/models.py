"""Confidential payroll: only the Secretary and the Manager may see anything in this app.

Deductions (PAYE, SHIF, NSSF, Housing Levy...) are typed in as amounts; the system does not
calculate tax (owner decision D4). Managers are never included in payroll.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse

ZERO = Decimal("0.00")
money = dict(max_digits=12, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)])


class PaymentMethod(models.TextChoices):
    MPESA = "mpesa", "M-Pesa"
    BANK = "bank", "Bank"
    CASH = "cash", "Cash"


class PayProfile(models.Model):
    """A person's usual pay, used to pre-fill each month's payroll."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pay_profile")
    basic_salary = models.DecimalField(**money)
    regular_allowances = models.DecimalField(**money)
    allowance_note = models.CharField(max_length=120, blank=True)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.MPESA)
    mpesa_number = models.CharField(
        max_length=13, blank=True,
        validators=[RegexValidator(r"^(?:\+254|0)(?:7|1)\d{8}$", "Enter an M-Pesa number such as 0712345678.")],
    )
    bank_name = models.CharField(max_length=80, blank=True)
    bank_account = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__first_name", "user__last_name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(basic_salary__gte=0, regular_allowances__gte=0), name="payprofile_amounts_not_negative"
            )
        ]

    def __str__(self):
        return f"Pay profile for {self.user}"


class PayrollRun(models.Model):
    """One month's payroll."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        REVISION_REQUIRED = "revision_required", "Revision required"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    period = models.DateField(help_text="First day of the month this payroll is for.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    total_gross = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    total_deductions = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    total_net = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopen_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-period"]
        constraints = [
            models.UniqueConstraint(
                fields=["period"], condition=~Q(status="rejected"), name="one_active_payroll_per_month"
            ),
            models.CheckConstraint(condition=Q(period__day=1), name="payroll_period_first_of_month"),
        ]

    def __str__(self):
        return f"Payroll {self.period:%B %Y}"

    def get_absolute_url(self):
        return reverse("payroll:detail", args=[self.pk])


class PayrollLine(models.Model):
    """One person's pay for the month. Names and payment details are copied so history never changes."""

    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    employee_name = models.CharField(max_length=150)
    employee_number = models.CharField(max_length=20)
    role = models.CharField(max_length=20)
    basic = models.DecimalField(**money)
    allowances = models.DecimalField(**money)
    overtime = models.DecimalField(**money)
    bonus = models.DecimalField(**money)
    gross = models.DecimalField(**money)
    paye = models.DecimalField("PAYE", **money)
    shif = models.DecimalField("SHIF", **money)
    nssf = models.DecimalField("NSSF", **money)
    housing_levy = models.DecimalField(**money)
    advance = models.DecimalField("salary advance", **money)
    other_deductions = models.DecimalField(**money)
    other_note = models.CharField(max_length=120, blank=True)
    total_deductions = models.DecimalField(**money)
    net = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices, blank=True)
    payment_detail = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["employee_name"]
        constraints = [
            models.UniqueConstraint(fields=["run", "employee"], name="one_line_per_person_per_payroll"),
            models.CheckConstraint(
                condition=Q(
                    basic__gte=0, allowances__gte=0, overtime__gte=0, bonus__gte=0, gross__gte=0,
                    paye__gte=0, shif__gte=0, nssf__gte=0, housing_levy__gte=0, advance__gte=0,
                    other_deductions__gte=0, total_deductions__gte=0,
                ),
                name="payrollline_amounts_not_negative",
            ),
        ]

    def __str__(self):
        return f"{self.employee_name} - {self.run}"
