from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from django.views.generic import ListView, TemplateView, UpdateView

from accounts.models import Role
from accounts.permissions import RoleRequiredMixin
from finance.models import Expense
from reports import services
from tracking import services as tracking

from . import dashboards
from .filters import PERIODS, clean_period, period_start
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
        if user.role == Role.MANAGER:
            ctx.update(services.manager_dashboard(clean_period(self.request.GET.get("period"))))
            ctx.update(_finance_glance())
            ctx.update(dashboards.manager_extra(user))
            ctx["periods"] = PERIODS
        elif user.role == Role.SUPERVISOR:
            ctx.update(services.supervisor_dashboard(user))
            ctx["location_state"] = tracking.my_state(user)
            ctx.update(dashboards.supervisor_extra(user))
        elif user.role == Role.SECRETARY:
            ctx.update(_finance_glance())
            ctx["recent_expenses"] = Expense.objects.filter(status=Expense.Status.RECORDED).select_related("category")[:8]
            ctx.update(dashboards.secretary_overview(user))
        else:
            ctx.update(services.staff_dashboard(user))
            if tracking.is_tracked(user):
                ctx["location_state"] = tracking.my_state(user)
            ctx.update(dashboards.staff_extra(user))
        return ctx


def _finance_glance():
    today = timezone.localdate()
    month = Expense.objects.filter(
        date__year=today.year, date__month=today.month, status=Expense.Status.RECORDED
    )
    recorded = Expense.objects.filter(status=Expense.Status.RECORDED)

    def spent(period):
        return recorded.filter(date__gte=period_start(period, today), date__lte=today).aggregate(t=Sum("amount"))["t"] or 0

    return {
        "month_total": month.aggregate(t=Sum("amount"))["t"] or 0,
        "month_count": month.count(),
        "month_label": today.strftime("%B %Y"),
        "spend": [("Today", spent("day"), "day"), ("This week", spent("week"), "week"), ("This month", spent("month"), "month")],
        "today": today,
        "week_start": period_start("week", today),
    }


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
        ctx.update(q=self.request.GET.get("q", ""), f_role=self.request.GET.get("role", ""), roles=Role.choices)
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx["query_string"] = params.urlencode()
        ctx["f"] = self.request.GET
        return ctx
