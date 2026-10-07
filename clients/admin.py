from django.contrib import admin

from .models import Client, ClientSite, Feedback, Issue, IssueNote, Message, SupervisorAssignment


class AssignmentInline(admin.TabularInline):
    model = SupervisorAssignment
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_person", "phone", "supervisor", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "contact_person", "email", "phone")
    inlines = [AssignmentInline]


class NoteInline(admin.TabularInline):
    model = IssueNote
    extra = 0


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ("id", "client", "subject", "priority", "status", "supervisor")
    list_filter = ("status", "priority")
    inlines = [NoteInline]


admin.site.register([ClientSite, Feedback, Message])
