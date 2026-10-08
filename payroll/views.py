import csv

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import DetailView, FormView, ListView, TemplateView, UpdateView

from accounts.models import Role
from core.filters import apply_dates
from core.mixins import ActionView, CsvExportMixin, FilterContextMixin, OfficeRequiredMixin
from core.models import AuditLog, CompanySettings
from core.services import audit
from core.workflow import TransitionError
from escalations.services import open_escalation

from . import services
from .forms import AddPersonForm, LineForm, NewRunForm, PayProfileForm
from .models import PayProfile, PayrollLine, PayrollRun
from .pdf import payslip_pdf

S = PayrollRun.Status


class RunListView(OfficeRequiredMixin, CsvExportMixin, FilterContextMixin, ListView):
    template_name = "payroll/run_list.html"
    context_object_name = "runs"
    paginate_by = 24
    csv_filename = "payroll-months.csv"
    csv_header = ["Month", "Status", "Gross (KES)", "Deductions (KES)", "Net pay (KES)", "Prepared by", "Decided by"]

    def get_queryset(self):
        qs = PayrollRun.objects.select_related("created_by", "submitted_by", "decided_by")
        if self.request.GET.get("status") in S.values:
            qs = qs.filter(status=self.request.GET["status"])
        return apply_dates(qs, self.request.GET, "period")

    def csv_rows(self, qs):
        audit.record(self.request.user, "payroll.list_exported", None, "Downloaded the list of payroll months",
                     confidential=True)
        for r in qs:
            yield [f"{r.period:%B %Y}", r.get_status_display(), r.total_gross, r.total_deductions, r.total_net,
                   r.created_by, r.decided_by or ""]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["statuses"] = S.choices
        ctx["no_profile"] = services.payable_people().filter(pay_profile__isnull=True).count()
        return ctx


class ProfileListView(OfficeRequiredMixin, ListView):
    template_name = "payroll/profile_list.html"
    context_object_name = "people"

    def get_queryset(self):
        return services.payable_people().select_related("pay_profile").order_by("role", "first_name", "username")


class ProfileEditView(OfficeRequiredMixin, UpdateView):
    form_class = PayProfileForm
    template_name = "payroll/profile_form.html"

    def get_object(self, queryset=None):
        person = get_object_or_404(services.payable_people(), pk=self.kwargs["user_id"])
        self.person = person
        return PayProfile.objects.filter(user=person).first() or PayProfile(user=person)

    def form_valid(self, form):
        obj = self.get_object()
        before = audit.snapshot(obj, services.PROFILE_FIELDS) if obj.pk else {}
        services.save_profile(form.save(commit=False), self.request.user, before)
        messages.success(self.request, f"Pay details saved for {self.person}.")
        return redirect("payroll:profiles")

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "person": self.person}


class RunCreateView(OfficeRequiredMixin, FormView):
    form_class = NewRunForm
    template_name = "payroll/run_form.html"

    def form_valid(self, form):
        try:
            run = services.create_run(form.cleaned_data["period"], self.request.user)
        except TransitionError as exc:
            form.add_error("period", str(exc))
            return self.form_invalid(form)
        messages.success(self.request, f"Payroll for {run.period:%B %Y} started from everyone's pay details. Check each line.")
        return redirect(run)


class RunDetailView(OfficeRequiredMixin, DetailView):
    template_name = "payroll/run_detail.html"
    context_object_name = "run"

    def get_queryset(self):
        return PayrollRun.objects.select_related("created_by", "submitted_by", "decided_by", "reopened_by")

    def get_object(self, queryset=None):
        run = super().get_object(queryset)
        services.manager_opened(run, self.request.user)
        return run

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        run = self.object
        ctx.update(
            lines=run.lines.all(), editable=run.status in services.EDITABLE,
            decidable=run.status in services.DECIDABLE, add_form=AddPersonForm(run=run),
            history=AuditLog.objects.filter(entity_type="payroll.payrollrun", entity_id=str(run.pk)).select_related("actor"),
            escalation=open_escalation(run),
        )
        return ctx


class LineEditView(OfficeRequiredMixin, UpdateView):
    form_class = LineForm
    template_name = "payroll/line_form.html"
    context_object_name = "line"

    def get_object(self, queryset=None):
        return get_object_or_404(PayrollLine.objects.select_related("run"), pk=self.kwargs["line"], run_id=self.kwargs["pk"])

    def get(self, request, *args, **kwargs):
        line = self.get_object()
        if line.run.status not in services.EDITABLE:
            messages.error(request, "This payroll can't be changed now.")
            return redirect(line.run)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        fields = list(services.EARNINGS + services.DEDUCTIONS) + ["other_note"]
        before = audit.snapshot(PayrollLine.objects.get(pk=self.object.pk), fields)
        try:
            services.save_line(form.save(commit=False), self.request.user, before)
        except TransitionError as exc:
            messages.error(self.request, str(exc))
        else:
            messages.success(self.request, f"Saved {self.object.employee_name}: net pay KES {self.object.net:,.2f}.")
        return redirect(self.object.run)


class RunAction(OfficeRequiredMixin, ActionView):
    model = PayrollRun

    def note(self):
        return self.request.POST.get("note", "")


class AddPersonView(RunAction):
    def act(self, run):
        form = AddPersonForm(self.request.POST, run=run)
        if not form.is_valid():
            raise TransitionError("Choose a person to add.")
        services.add_person(run, form.cleaned_data["person"], self.request.user)
        return f"{form.cleaned_data['person']} added."


class RemoveLineView(OfficeRequiredMixin, ActionView):
    def get_queryset(self):
        return PayrollLine.objects.filter(run_id=self.kwargs["pk"]).select_related("run")

    def get_object(self):
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["line"])

    def act(self, line):
        services.remove_line(line, self.request.user)
        return f"{line.employee_name} removed from this payroll."

    def get_success_url(self):
        return self.object.run.get_absolute_url()


class SubmitView(RunAction):
    allowed_roles = (Role.SECRETARY,)

    def act(self, run):
        services.submit(run, self.request.user)
        return "Sent to the Manager for approval."


class ManagerAction(RunAction):
    allowed_roles = (Role.MANAGER,)
    action = None

    def act(self, run):
        getattr(services, self.action)(run, self.request.user, self.note())
        return f"Payroll is now {run.get_status_display().lower()}."


class ExportCsvView(OfficeRequiredMixin, DetailView):
    model = PayrollRun

    def render_to_response(self, context, **kwargs):
        run = self.object
        services.exported(run, self.request.user, "CSV")
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="payroll-{run.period:%Y-%m}.csv"'
        w = csv.writer(response)
        w.writerow(["Employee no.", "Name", "Role", "Gross", "Deductions", "Net pay", "Pay by", "Pay to"])
        for line in run.lines.all():
            name = line.employee_name
            if name[:1] in ("=", "+", "-", "@"):
                name = "'" + name
            w.writerow([line.employee_number, name, line.role, line.gross, line.total_deductions, line.net,
                        line.get_payment_method_display(), line.payment_detail])
        return response


class PrintView(OfficeRequiredMixin, DetailView):
    model = PayrollRun
    template_name = "payroll/run_print.html"
    context_object_name = "run"

    def get_context_data(self, **kwargs):
        services.exported(self.object, self.request.user, "print")
        return {**super().get_context_data(**kwargs), "lines": self.object.lines.all()}


# --- payslips -------------------------------------------------------------------

class PayslipMixin:
    """Shared by a person's own payslip and the office copy. Subclasses define get_line()."""

    template_name = "payroll/payslip.html"

    def get(self, request, *args, **kwargs):
        self.line = self.get_line()
        if kwargs.get("pdf"):
            services.payslip_seen(self.line, request.user, "downloaded")
            response = HttpResponse(payslip_pdf(self.line), content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="payslip-{self.line.run.period:%Y-%m}.pdf"'
            return response
        services.payslip_seen(self.line, request.user)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        earnings, deductions = services.payslip_rows(self.line)
        ctx.update(line=self.line, run=self.line.run, earnings=earnings, deductions=deductions,
                   company=CompanySettings.load())
        return ctx


class MyPayslipListView(LoginRequiredMixin, ListView):
    """Everyone: their own payslips from approved payrolls."""

    template_name = "payroll/my_payslips.html"
    context_object_name = "lines"
    paginate_by = 24

    def get_queryset(self):
        return services.my_payslips(self.request.user)


class MyPayslipView(LoginRequiredMixin, PayslipMixin, TemplateView):
    def get_line(self):
        return get_object_or_404(services.my_payslips(self.request.user), pk=self.kwargs["line"])


class OfficePayslipView(OfficeRequiredMixin, PayslipMixin, TemplateView):
    def get_line(self):
        return get_object_or_404(PayrollLine.objects.select_related("run"), pk=self.kwargs["line"],
                                 run_id=self.kwargs["pk"], run__status=S.APPROVED)

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "office": True}


class RunPayslipsView(OfficeRequiredMixin, DetailView):
    """Every payslip of an approved payroll, one per printed page."""

    template_name = "payroll/payslips_print.html"
    context_object_name = "run"

    def get_queryset(self):
        return PayrollRun.objects.filter(status=S.APPROVED)

    def get_context_data(self, **kwargs):
        services.exported(self.object, self.request.user, "payslips")
        slips = []
        for line in self.object.lines.all():
            earnings, deductions = services.payslip_rows(line)
            slips.append({"line": line, "earnings": earnings, "deductions": deductions})
        return {**super().get_context_data(**kwargs), "slips": slips, "company": CompanySettings.load()}
