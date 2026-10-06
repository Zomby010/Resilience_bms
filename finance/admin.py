from django.contrib import admin

from .models import Expense, ExpenseCategory, ExpenseLog


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("date", "category", "description", "amount", "recorded_by")
    list_filter = ("category",)
    search_fields = ("description", "reference")


@admin.register(ExpenseLog)
class ExpenseLogAdmin(admin.ModelAdmin):
    list_display = ("at", "action", "expense_number", "by")
    readonly_fields = [f.name for f in ExpenseLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
