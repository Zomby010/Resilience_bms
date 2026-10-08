from django.contrib import admin

from .models import AttendanceDay, AttendanceRecord


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("date", "user", "site", "outcome", "status", "method", "signed_in_at")
    list_filter = ("status", "outcome", "method", "date")


@admin.register(AttendanceDay)
class AttendanceDayAdmin(admin.ModelAdmin):
    list_display = ("date", "completed_by", "present", "late", "absent", "on_leave", "sick")
