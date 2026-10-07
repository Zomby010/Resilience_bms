from django.contrib import admin

from core.admin import ReadOnlyAdmin

from .models import Category, Item, ItemRequest, StockMovement


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "qty_available", "qty_issued", "needs_manager_approval", "is_active")
    list_filter = ("category", "is_active", "needs_manager_approval")
    # Quantities only change through the stock ledger, never by hand here.
    readonly_fields = ("qty_available", "qty_reserved", "qty_issued", "qty_damaged", "qty_lost")


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    list_display = ("at", "item", "action", "quantity", "by")


@admin.register(ItemRequest)
class ItemRequestAdmin(admin.ModelAdmin):
    list_display = ("created_at", "requester", "item", "qty_requested", "status")
    list_filter = ("status",)


admin.site.register(Category)
