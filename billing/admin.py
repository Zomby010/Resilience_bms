from django.contrib import admin

from .models import Invoice, InvoiceLine, Payment


class LineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "client", "invoice_date", "due_date", "total", "amount_paid", "status")
    list_filter = ("status",)
    inlines = [LineInline, PaymentInline]
