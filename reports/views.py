from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from accounts.models import Role
from accounts.permissions import RoleRequiredMixin

from .forms import ReplyForm, ReportForm
from .models import Report, Status

# Roles that take part in the reporting workflow at all. The Secretary is
# deliberately excluded: finance is kept separate from operational reporting.
REPORT_ROLES = (Role.MANAGER, Role.SUPERVISOR, Role.STAFF)
AUTHOR_ROLES = (Role.SUPERVISOR, Role.STAFF)


class ReportListView(RoleRequiredMixin, ListView):
    allowed_roles = REPORT_ROLES
    template_name = "reports/report_list.html"
    context_object_name = "reports"
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        qs = Report.objects.visible_to(user).select_related("author", "author__supervisor")
        scope = self.request.GET.get("scope")
        if scope == "mine":
            qs = qs.filter(author=user)
        elif scope == "team" and user.role != Role.STAFF:
            qs = qs.exclude(author=user)
        status = self.request.GET.get("status")
        if status in Status.values:
            qs = qs.filter(status=status)
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(body__icontains=q)
                | Q(author__first_name__icontains=q)
                | Q(author__last_name__icontains=q)
                | Q(author__username__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["statuses"] = Status.choices
        ctx["f_status"] = self.request.GET.get("status", "")
        ctx["f_scope"] = self.request.GET.get("scope", "")
        ctx["q"] = self.request.GET.get("q", "")
        ctx["can_submit"] = self.request.user.role in AUTHOR_ROLES
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx["query_string"] = params.urlencode()
        return ctx


class ReportCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = AUTHOR_ROLES
    form_class = ReportForm
    template_name = "reports/report_form.html"

    def form_valid(self, form):
        form.instance.author = self.request.user
        messages.success(self.request, "Report submitted.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Submit a report"
        return ctx


class ReportDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = REPORT_ROLES
    template_name = "reports/report_detail.html"
    context_object_name = "report"

    def get_queryset(self):
        # Out-of-scope reports 404 instead of 403 so their existence is not leaked.
        return Report.objects.visible_to(self.request.user).select_related(
            "author", "author__supervisor", "reviewed_by", "completed_by"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        report, user = self.object, self.request.user
        ctx["replies"] = report.replies.select_related("author")
        ctx["can_edit"] = report.can_edit(user)
        if report.can_reply(user):
            ctx["reply_form"] = ReplyForm(can_complete=user.role == Role.MANAGER)
        return ctx


class ReportUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = AUTHOR_ROLES
    form_class = ReportForm
    template_name = "reports/report_form.html"

    def get_queryset(self):
        return Report.objects.filter(author=self.request.user)

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if not obj.can_edit(self.request.user):
            raise PermissionDenied("This report has already been responded to and can no longer be edited.")
        return obj

    def form_valid(self, form):
        messages.success(self.request, "Report updated.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Edit report"
        return ctx


class ReplyCreateView(RoleRequiredMixin, View):
    """POST only: a supervisor/manager answers a report they are allowed to see."""

    http_method_names = ["post"]
    allowed_roles = (Role.MANAGER, Role.SUPERVISOR)

    def post(self, request, pk):
        report = get_object_or_404(Report.objects.visible_to(request.user).select_related("author"), pk=pk)
        if not report.can_reply(request.user):
            raise PermissionDenied
        form = ReplyForm(request.POST, can_complete=request.user.role == Role.MANAGER)
        if form.is_valid():
            report.add_reply(request.user, form.cleaned_data["body"], complete=form.cleaned_data.get("complete", False))
            messages.success(request, "Reply sent.")
        else:
            messages.error(request, "Please write a reply before sending.")
        return redirect(report)
