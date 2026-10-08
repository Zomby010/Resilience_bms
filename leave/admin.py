from django.contrib import admin

from .models import LeaveAllowance, LeaveRequest, LeaveType, SickLeave


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "days_per_year", "counting", "needs_balance", "is_active", "order")


@admin.register(LeaveAllowance)
class LeaveAllowanceAdmin(admin.ModelAdmin):
    list_display = ("user", "leave_type", "year", "days", "set_by")
    list_filter = ("year", "leave_type")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "leave_type", "start_date", "end_date", "days", "status")
    list_filter = ("status", "leave_type")


@admin.register(SickLeave)
class SickLeaveAdmin(admin.ModelAdmin):
    # Dates only: sick sheet files are opened through the app, where each opening is logged.
    list_display = ("user", "first_day", "last_day", "status")
    list_filter = ("status",)
    exclude = ("comment",)
