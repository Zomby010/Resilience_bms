from django.contrib import admin

from .models import Incident, IncidentNote


class NoteInline(admin.TabularInline):
    model = IncidentNote
    extra = 0
    readonly_fields = ("author", "body", "status_from", "status_to", "created_at")
    can_delete = False


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ("id", "occurred_at", "site", "kind", "severity", "status", "reported_by")
    list_filter = ("status", "kind", "severity")
    search_fields = ("what_happened", "police_ob_number")
    readonly_fields = ("reported_by", "reported_at", "updated_at")
    inlines = [NoteInline]
