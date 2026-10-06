from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "expense categories"

    def __str__(self):
        return self.name


class Expense(models.Model):
    date = models.DateField(default=timezone.localdate)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    reference = models.CharField("Receipt / reference no.", max_length=60, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expenses")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.date} {self.description} ({self.amount})"

    def get_absolute_url(self):
        return reverse("finance:detail", args=[self.pk])

    def snapshot(self):
        """Human-readable state, stored in the history so edits/deletes stay traceable."""
        ref = f" ref {self.reference}" if self.reference else ""
        return f"{self.date} | {self.category} | {self.description} | KES {self.amount:,.2f}{ref}"


class ExpenseLog(models.Model):
    """Append-only history of every create / edit / delete of an expense."""

    class Action(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        DELETED = "deleted", "Deleted"

    expense = models.ForeignKey(Expense, null=True, blank=True, on_delete=models.SET_NULL, related_name="log")
    expense_number = models.PositiveIntegerField()  # survives the expense being deleted
    action = models.CharField(max_length=10, choices=Action.choices)
    details = models.TextField()
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]

    def __str__(self):
        return f"{self.action} expense #{self.expense_number} by {self.by}"

    @classmethod
    def record(cls, expense, action, user, details=None):
        return cls.objects.create(
            expense=None if action == cls.Action.DELETED else expense,
            expense_number=expense.pk,
            action=action,
            details=details or expense.snapshot(),
            by=user,
        )
