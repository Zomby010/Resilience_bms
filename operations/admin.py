from django.contrib import admin

from .models import OBEntry, SiteVisit


@admin.register(OBEntry)
class OBEntryAdmin(admin.ModelAdmin):
    """Read-only: the OB is never changed, only added to (through the app)."""

    list_display = ("number", "site", "occurred_at", "kind", "written_by")
    list_filter = ("kind", "site")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SiteVisit)
class SiteVisitAdmin(admin.ModelAdmin):
    list_display = ("site", "supervisor", "visited_at", "welfare_check_done")
    list_filter = ("site", "welfare_check_done")
