from django.contrib import admin

from .models import Alert, AuditEntry, LocationPing, Site, TrackingProfile, WorkHours


class WorkHoursInline(admin.TabularInline):
    model = WorkHours
    fk_name = "site"
    extra = 0


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("name", "latitude", "longitude", "radius_m", "is_active")
    inlines = [WorkHoursInline]


@admin.register(TrackingProfile)
class TrackingProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "site", "tracking_on", "last_status", "last_ping_at")
    list_filter = ("tracking_on", "site")
    readonly_fields = [f.name for f in TrackingProfile._meta.fields if f.name.startswith("last_") or f.name.startswith("tracking_")]


@admin.register(LocationPing)
class LocationPingAdmin(admin.ModelAdmin):
    list_display = ("user", "received_at", "status", "distance_m", "accuracy_m", "flag")
    list_filter = ("status", "site")
    date_hierarchy = "received_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("message", "kind", "created_at", "resolved_at")
    list_filter = ("kind",)


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
