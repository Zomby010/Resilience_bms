from django.contrib import admin

from .models import Attachment, AuditLog, CompanySettings


class ReadOnlyAdmin(admin.ModelAdmin):
    """History records: visible in the admin site, never added, edited or deleted there."""

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CompanySettings)
class CompanySettingsAdmin(admin.ModelAdmin):
    list_display = ("company_name", "vat_registered", "expense_approval_enabled", "updated_at")

    def has_add_permission(self, request):
        return not CompanySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Attachment)
class AttachmentAdmin(ReadOnlyAdmin):
    list_display = ("original_name", "content_type", "object_id", "uploaded_by", "uploaded_at")


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ("at", "actor", "actor_role", "action", "summary")
    list_filter = ("action", "actor_role", "confidential")
    search_fields = ("summary", "entity_id")
