from django.contrib import admin

from .models import PayProfile, PayrollLine, PayrollRun


class LineInline(admin.TabularInline):
    model = PayrollLine
    extra = 0


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ("period", "status", "total_net", "created_by", "decided_by")
    inlines = [LineInline]


@admin.register(PayProfile)
class PayProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "basic_salary", "payment_method", "is_active")
