from django.contrib import admin

from .models import Escalation, EscalationReply


class ReplyInline(admin.TabularInline):
    model = EscalationReply
    extra = 0


@admin.register(Escalation)
class EscalationAdmin(admin.ModelAdmin):
    list_display = ("raised_at", "kind", "subject", "status", "raised_by")
    list_filter = ("status", "kind")
    inlines = [ReplyInline]
