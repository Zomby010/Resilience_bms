from django.contrib import admin

from .models import Reply, Report


class ReplyInline(admin.TabularInline):
    model = Reply
    extra = 0
    readonly_fields = ("author", "created_at")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "body", "author__username")
    inlines = [ReplyInline]
