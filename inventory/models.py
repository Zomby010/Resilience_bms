"""Company items, stock counts, the stock ledger and item requests.

Stock is held in five counts per item (available, reserved, issued, damaged, lost).
Every change goes through one conditional database update so it can never go below
zero, even when two people press a button at the same moment.
"""
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse

QUANTITY_FIELDS = ("qty_available", "qty_reserved", "qty_issued", "qty_damaged", "qty_lost")


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Item(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    description = models.TextField(blank=True)
    condition_note = models.CharField("condition", max_length=120, blank=True)
    storage_location = models.CharField(max_length=120, blank=True)
    min_stock = models.PositiveIntegerField("minimum stock level", default=0)
    returnable = models.BooleanField(
        "must be returned", default=False, help_text="Ticked: radios, torches. Not ticked: uniforms, boots (issued to keep)."
    )
    # Owner decision D12: only the Manager changes this, on his own page.
    needs_manager_approval = models.BooleanField(default=False)
    flag_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    flag_changed_at = models.DateTimeField(null=True, blank=True)
    qty_available = models.PositiveIntegerField(default=0)
    qty_reserved = models.PositiveIntegerField("waiting for collection", default=0)
    qty_issued = models.PositiveIntegerField(default=0)
    qty_damaged = models.PositiveIntegerField(default=0)
    qty_lost = models.PositiveIntegerField(default=0)
    low_stock_notified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(qty_available__gte=0, qty_reserved__gte=0, qty_issued__gte=0, qty_damaged__gte=0, qty_lost__gte=0),
                name="item_quantities_not_negative",
            )
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("inventory:detail", args=[self.pk])

    @property
    def total(self):
        return sum(getattr(self, f) for f in QUANTITY_FIELDS)

    @property
    def is_low(self):
        return self.qty_available <= self.min_stock

    def quantities(self):
        return {f: getattr(self, f) for f in QUANTITY_FIELDS}


class StockMovement(models.Model):
    """The stock ledger. Append-only."""

    class Action(models.TextChoices):
        ADDED = "added", "Added stock"
        WRITTEN_OFF = "written_off", "Written off"
        DAMAGED = "damaged", "Marked damaged"
        REPAIRED = "repaired", "Marked repaired"
        RESERVED = "reserved", "Approved (waiting for collection)"
        RELEASED = "released", "Approval cancelled"
        ISSUED = "issued", "Handed over"
        RETURNED_GOOD = "returned_good", "Returned in good condition"
        RETURNED_DAMAGED = "returned_damaged", "Returned damaged"
        LOST = "lost", "Recorded as lost"

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="movements")
    action = models.CharField(max_length=20, choices=Action.choices)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    before = models.JSONField()
    after = models.JSONField()
    request = models.ForeignKey("ItemRequest", null=True, blank=True, on_delete=models.SET_NULL, related_name="movements")
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-at", "-id"]
        indexes = [models.Index(fields=["item", "-at"])]
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="stockmovement_quantity_positive")]

    def __str__(self):
        return f"{self.get_action_display()} {self.quantity} x {self.item}"


class ItemRequest(models.Model):
    class Status(models.TextChoices):
        AWAITING_MANAGER = "awaiting_manager", "Waiting for Manager"
        PENDING = "pending", "Item request pending"
        READY = "ready", "Approved - collect from Secretary"
        ISSUED = "issued", "Item issued"
        RETURN_CLAIMED = "return_claimed", "Item returned - awaiting Secretary approval"
        RETURNED = "returned", "Item returned"
        LOST = "lost", "Item recorded as lost"
        REJECTED = "rejected", "Request rejected"
        CANCELLED = "cancelled", "Request cancelled"

    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="item_requests")
    requester_role = models.CharField(max_length=20)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="requests")
    qty_requested = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    qty_issued = models.PositiveIntegerField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    manager_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    manager_decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField(blank=True)
    expected_return_date = models.DateField(null=True, blank=True, db_index=True)
    handed_over_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    handed_over_at = models.DateTimeField(null=True, blank=True)
    return_claimed_at = models.DateTimeField(null=True, blank=True)
    return_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    return_approved_at = models.DateTimeField(null=True, blank=True)
    qty_returned_good = models.PositiveIntegerField(default=0)
    qty_returned_damaged = models.PositiveIntegerField(default=0)
    qty_lost = models.PositiveIntegerField(default=0)
    return_notes = models.TextField(blank=True)
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["requester", "-created_at"]),
            models.Index(fields=["item", "status"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(qty_requested__gt=0), name="itemrequest_qty_positive"),
            models.CheckConstraint(
                condition=Q(qty_issued__isnull=True) | Q(qty_issued__gt=0, qty_issued__lte=F("qty_requested")),
                name="itemrequest_issued_within_requested",
            ),
            models.CheckConstraint(
                condition=Q(qty_returned_good=0, qty_returned_damaged=0, qty_lost=0)
                | Q(qty_issued__gte=F("qty_returned_good") + F("qty_returned_damaged") + F("qty_lost")),
                name="itemrequest_returns_within_issued",
            ),
        ]

    def __str__(self):
        return f"{self.requester} - {self.qty_requested} x {self.item}"

    def get_absolute_url(self):
        return reverse("inventory:request_detail", args=[self.pk])
