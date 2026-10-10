from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Sum
import logging
import secrets

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from django.views.generic import ListView, TemplateView, UpdateView

from accounts.models import ROLE_CHOICES, Role
from accounts.permissions import RoleRequiredMixin
from finance.models import Expense
from tracking import services as tracking

from . import dashboards, todo
from .access import can_view
from .forms import CompanySettingsForm
from .models import Attachment, AuditLog, CompanySettings
from .services import audit


class HomeView(LoginRequiredMixin, TemplateView):
    """Landing page: each role gets its own dashboard."""

    templates = {
        Role.MANAGER: "core/dashboard_manager.html",
        Role.SUPERVISOR: "core/dashboard_supervisor.html",
        Role.STAFF: "core/dashboard_staff.html",
        Role.SECRETARY: "core/dashboard_secretary.html",
    }

    def get_template_names(self):
        return [self.templates.get(self.request.user.role, "core/dashboard_staff.html")]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        # Every home page starts with "N things need you" (core.todo); the rest is a short picture of today.
        if user.role == Role.MANAGER:
            extra = dashboards.manager_extra(user)
            ctx.update(extra)
            ctx.update(_month_spend())
            ctx.update(todo.context(user, board=extra["board"]))
        elif user.role == Role.SUPERVISOR:
            ctx["location_state"] = tracking.my_state(user)
            ctx.update(dashboards.supervisor_extra(user))
            ctx.update(todo.context(user))
        elif user.role == Role.SECRETARY:
            ctx.update(_month_spend())
            ctx["recent_expenses"] = Expense.objects.filter(status=Expense.Status.RECORDED).select_related("category")[:8]
            ctx.update(dashboards.secretary_overview(user))
            ctx.update(todo.context(user))
        else:
            if tracking.is_tracked(user):
                ctx["location_state"] = tracking.my_state(user)
            ctx.update(dashboards.staff_extra(user))
            ctx.update(todo.context(user))
        return ctx


def _month_spend():
    today = timezone.localdate()
    month = Expense.objects.filter(date__year=today.year, date__month=today.month, status=Expense.Status.RECORDED)
    return {"month_total": month.aggregate(t=Sum("amount"))["t"] or 0, "month_label": today.strftime("%B %Y")}


class CompanySettingsView(RoleRequiredMixin, UpdateView):
    allowed_roles = (Role.MANAGER,)
    form_class = CompanySettingsForm
    template_name = "core/company_settings.html"

    def get_object(self, queryset=None):
        return CompanySettings.load()

    def form_valid(self, form):
        fields = list(form.changed_data)
        before = audit.snapshot(CompanySettings.load(), fields)
        form.instance.updated_by = self.request.user
        self.object = form.save()
        audit.record(
            self.request.user, "settings.updated", self.object, "Updated company settings",
            changes=audit.changes_between(before, audit.snapshot(self.object, fields)),
        )
        messages.success(self.request, "Company settings saved.")
        return redirect("core:company_settings")


class AttachmentDownloadView(LoginRequiredMixin, View):
    """Files are only handed out to people allowed to see the record they belong to."""

    def get(self, request, pk):
        att = get_object_or_404(Attachment.objects.select_related("content_type"), pk=pk)
        if not can_view(request.user, att.parent):
            raise Http404
        try:
            fh = att.file.open("rb")
        except FileNotFoundError:
            raise Http404
        return FileResponse(fh, as_attachment=True, filename=att.original_name, content_type=att.mime_type)


class LogoView(LoginRequiredMixin, View):
    """The company logo for invoice pages (uploads are never served directly)."""

    def get(self, request):
        logo = CompanySettings.load().logo
        if not logo:
            raise Http404
        try:
            fh = logo.open("rb")
        except FileNotFoundError:
            raise Http404
        return FileResponse(fh)


class ReportProblemView(RoleRequiredMixin, TemplateView):
    """FLOW-01: one door for guards and supervisors. It asks what happened and sends them to the right form."""

    allowed_roles = (Role.SUPERVISOR, Role.STAFF)
    template_name = "core/report_problem.html"


class AuditLogView(RoleRequiredMixin, ListView):
    allowed_roles = (Role.MANAGER,)
    template_name = "core/audit_log.html"
    context_object_name = "entries"
    paginate_by = 50

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor")
        g = self.request.GET
        q = (g.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(summary__icontains=q) | Q(action__icontains=q) | Q(actor__username__icontains=q)
                           | Q(actor__first_name__icontains=q))
        if g.get("role") in Role.values:
            qs = qs.filter(actor_role=g["role"])
        date_from, date_to = parse_date(g.get("from", "")), parse_date(g.get("to", ""))
        if date_from:
            qs = qs.filter(at__date__gte=date_from)
        if date_to:
            qs = qs.filter(at__date__lte=date_to)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(q=self.request.GET.get("q", ""), f_role=self.request.GET.get("role", ""), roles=ROLE_CHOICES)
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx["query_string"] = params.urlencode()
        ctx["f"] = self.request.GET
        return ctx


class CronDailyView(View):
    """Vercel Cron's daily call: the daily checks plus the GPS alert check and clean-up.

    Only answers when the request carries CRON_SECRET, which Vercel sends as a Bearer token.
    """

    def get(self, request):
        expected = f"Bearer {settings.CRON_SECRET}"
        if not settings.CRON_SECRET or not secrets.compare_digest(request.headers.get("Authorization", ""), expected):
            raise Http404
        from .checks import run_daily_checks

        result = run_daily_checks() or {"already_ran_today": True}
        tracking.ensure_profiles()
        tracking.evaluate_alerts()
        result["location_records_deleted"] = tracking.purge_history()
        return JsonResponse(result)


csrf_log = logging.getLogger("django.security.csrf")


def csrf_failure(request, reason=""):
    """A form was refused by the CSRF check: log why, and show a plain "try again" page."""
    csrf_log.warning(
        "CSRF failure: %s (host=%s origin=%s referer=%s secure=%s csrf_cookie=%s)",
        reason,
        request.get_host(),
        request.META.get("HTTP_ORIGIN", "-"),
        request.META.get("HTTP_REFERER", "-"),
        request.is_secure(),
        "yes" if settings.CSRF_COOKIE_NAME in request.COOKIES else "no",
    )
    return render(request, "csrf_failure.html", status=403)
