from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView

from core.mixins import FilterContextMixin

from .models import Notification


class InboxView(LoginRequiredMixin, FilterContextMixin, ListView):
    template_name = "notifications/inbox.html"
    context_object_name = "notes"
    paginate_by = 30

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user)
        if self.request.GET.get("unread") == "1":
            qs = qs.filter(read_at__isnull=True)
        return qs


class OpenView(LoginRequiredMixin, View):
    """Mark one of my notifications read and go to the record. The record's page checks access again."""

    def get(self, request, pk):
        note = get_object_or_404(Notification, pk=pk, recipient=request.user)
        if note.read_at is None:
            Notification.objects.filter(pk=note.pk).update(read_at=timezone.now())
        link = note.link_url
        if link and link.startswith("/") and url_has_allowed_host_and_scheme(link, allowed_hosts=None):
            return redirect(link)
        return redirect("notifications:inbox")


class ReadAllView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        n = Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())
        messages.success(request, f"{n} notification(s) marked as read." if n else "Nothing new to mark.")
        return redirect("notifications:inbox")
