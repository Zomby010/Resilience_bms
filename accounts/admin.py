from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class RoleUserAdmin(UserAdmin):
    list_display = ("username", "get_full_name", "role", "supervisor", "is_active")
    list_filter = ("role", "is_active")
    fieldsets = UserAdmin.fieldsets + (("Business role", {"fields": ("role", "phone", "supervisor")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Business role", {"fields": ("role", "phone", "supervisor")}),)
