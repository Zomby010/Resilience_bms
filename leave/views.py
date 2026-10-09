from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from accounts.models import ROLE_CHOICES, Role, User
from accounts.permissions import RoleRequiredMixin
from core.filters import apply_dates, csv_response
from core.mixins import ActionView, FilterContextMixin

from . import services
from .forms import AllowanceForm, LastDayForm, LeaveRequestForm, SheetForm, SickForm
from .models import LeaveRequest, LeaveType, SickLeave, SickNote

EVERYONE = tuple(Role.values)
S = LeaveRequest.Status


def _year(request):
    value = request.GET.get("year", "")
    return int(value) if value.isdigit() and 2000 <= int(value) <= 2100 else timezone.localdate().year


class MyLeaveView(LoginRequiredMixin, TemplateView):
    """Every person's own page: days left in plain words, their leave and their sick leave."""

    template_name = "leave/mine.html"

    def get_context_data(self, **kwargs):
        user = self.request.user
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            balances=services.balances_for(user),
            requests=LeaveRequest.objects.filter(user=user).select_related("leave_type", "decided_by")[:20],
            sick=SickLeave.objects.filter(user=user)[:10],
            to_decide=_to_decide(user).count() if user.role in (Role.SUPERVISOR, Role.MANAGER) else 0,
        )
        return ctx


def _to_decide(user):
    qs = LeaveRequest.objects.filter(status=S.WAITING).select_related("user", "leave_type")
    if user.role == Role.MANAGER:
        return qs.exclude(user=user).filter(Q(approver__isnull=True) | ~Q(approver__is_active=True)) | qs.filter(approver=user)
    return qs.filter(approver=user)


class AskView(LoginRequiredMixin, FormView):
    template_name = "leave/ask.html"
    form_class = LeaveRequestForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def form_valid(self, form):
        d = form.cleaned_data
        person = d.get("person") or self.request.user
        try:
            req = services.ask_for_leave(person, d["leave_type"], d["start_date"], d["end_date"], d["reason"], self.request.user)
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
            return self.form_invalid(form)
        if req.status == S.APPROVED:
            messages.success(self.request, f"Leave recorded and approved: {services._n(req.days)} days.")
        else:
            who = req.approver or "the Manager"
            messages.success(self.request, f"Leave asked for: {services._n(req.days)} days. {who} will decide.")
        return redirect(req)


class RequestListView(RoleRequiredMixin, FilterContextMixin, ListView):
    # Guards see their own requests on "My leave".
    allowed_roles = (Role.SUPERVISOR, Role.MANAGER, Role.SECRETARY)
    template_name = "leave/request_list.html"
    context_object_name = "requests"
    paginate_by = 30

    def get_queryset(self):
        user, g = self.request.user, self.request.GET
        if g.get("show") == "decide":
            qs = _to_decide(user)
        else:
            qs = LeaveRequest.objects.visible_to(user).select_related("user", "leave_type", "decided_by", "entered_by")
        if g.get("status") in S.values:
            qs = qs.filter(status=g["status"])
        if g.get("type", "").isdigit():
            qs = qs.filter(leave_type_id=int(g["type"]))
        if g.get("person", "").isdigit():
            qs = qs.filter(user_id=int(g["person"]))
        qs = apply_dates(qs, g, "start_date")
        return qs.order_by("-start_date", "-id")

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv" and request.user.role in services.OFFICE:
            rows = ((r.user, r.user.get_role_display(), r.leave_type, r.start_date, r.end_date, r.days, r.get_status_display(),
                     r.entered_by, r.decided_by or "", r.decided_at and timezone.localtime(r.decided_at).strftime("%Y-%m-%d %H:%M") or "",
                     r.reason) for r in self.get_queryset())
            return csv_response("leave.csv", ["Person", "Role", "Type", "First day", "Last day", "Days", "Status",
                                              "Entered by", "Decided by", "Decided at", "Reason"], rows)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        user = self.request.user
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            statuses=S.choices, types=LeaveType.objects.filter(is_active=True), people=services.people_for(user),
            decide_count=_to_decide(user).count(), can_export=user.role in services.OFFICE,
        )
        return ctx


class RequestDetailView(LoginRequiredMixin, DetailView):
    template_name = "leave/request_detail.html"
    context_object_name = "req"

    def get_queryset(self):
        return LeaveRequest.objects.visible_to(self.request.user).select_related("user", "leave_type", "approver", "decided_by", "entered_by")

    def get_context_data(self, **kwargs):
        user, req = self.request.user, self.object
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            can_decide=req.status == S.WAITING and services.can_decide(user, req),
            can_cancel=services.can_cancel(user, req),
            balance=services.plain_balance(req.leave_type, services.balance(req.user, req.leave_type, req.start_date.year),
                                           you=req.user_id == user.pk),
        )
        return ctx


class RequestAction(ActionView):
    allowed_roles = EVERYONE
    action = None

    def get_queryset(self):
        return LeaveRequest.objects.visible_to(self.request.user).select_related("user", "leave_type")

    def act(self, req):
        note = self.request.POST.get("note", "")
        if self.action == "approve":
            services.decide(req, self.request.user, True, note)
            return "Leave approved. They have been told."
        if self.action == "reject":
            services.decide(req, self.request.user, False, note)
            return "Leave not approved. They have been told why."
        services.cancel(req, self.request.user)
        return "Leave cancelled."


# --- allowances (Manager sets, Secretary sees) -----------------------------------

class AllowanceListView(RoleRequiredMixin, TemplateView):
    # Leave days per person are no longer used (the Manager types the days given on each request).
    # The old figures stay readable for the Manager from Leave & sick ▸ Requests to decide.
    allowed_roles = (Role.MANAGER,)
    template_name = "leave/allowances.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        year = _year(self.request)
        types = list(LeaveType.objects.filter(is_active=True))
        q = (self.request.GET.get("q") or "").strip()
        people = User.objects.filter(is_active=True).exclude(role=Role.MANAGER)
        if q:
            people = people.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(username__icontains=q))
        if self.request.GET.get("role") in Role.values:
            people = people.filter(role=self.request.GET["role"])
        rows = [{"person": p, "cells": [services.balance(p, lt, year) for lt in types]} for p in people]
        ctx.update(year=year, types=types, rows=rows, q=q, roles=ROLE_CHOICES, f=self.request.GET)
        return ctx


class AllowanceEditView(RoleRequiredMixin, FormView):
    allowed_roles = (Role.MANAGER,)
    template_name = "leave/allowance_form.html"
    form_class = AllowanceForm

    def dispatch(self, request, *args, **kwargs):
        self.person = get_object_or_404(User, pk=kwargs["pk"], is_active=True)
        self.year = _year(request) if request.method == "GET" else int(request.POST.get("year") or timezone.localdate().year)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "person": self.person, "year": self.year}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "person": self.person, "year": self.year,
                "balances": services.balances_for(self.person, self.year, you=False)}

    def form_valid(self, form):
        for lt, days in form.values():
            services.set_allowance(self.person, lt, self.year, days, self.request.user)
        messages.success(self.request, f"Leave days for {self.person} in {self.year} saved.")
        return redirect(f"{self.request.path}?year={self.year}")


# --- sick leave -------------------------------------------------------------------

class ReportSickView(LoginRequiredMixin, FormView):
    template_name = "leave/sick_form.html"
    form_class = SickForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def form_valid(self, form):
        d = form.cleaned_data
        person = d.get("person") or self.request.user
        try:
            sick = services.report_sick(person, d["first_day"], d["last_day"], d["comment"], self.request.user, d.get("sheet"))
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
            return self.form_invalid(form)
        messages.success(self.request, f"Sick leave recorded for {person}. Get well soon.")
        return redirect(sick)


class SickListView(LoginRequiredMixin, FilterContextMixin, ListView):
    template_name = "leave/sick_list.html"
    context_object_name = "sick_list"
    paginate_by = 30

    def get_queryset(self):
        g = self.request.GET
        qs = SickLeave.objects.visible_to(self.request.user).select_related("user", "reported_by")
        if g.get("status") in SickLeave.Status.values:
            qs = qs.filter(status=g["status"])
        if g.get("person", "").isdigit():
            qs = qs.filter(user_id=int(g["person"]))
        if g.get("now") == "1":
            qs = qs.covering(timezone.localdate())
        return apply_dates(qs, g, "first_day")

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv" and request.user.role in services.OFFICE:
            rows = ((s.user, s.first_day, s.last_day, s.days, s.get_status_display(), s.reported_by, s.notes.count())
                    for s in self.get_queryset())
            return csv_response("sick-leave.csv", ["Person", "First day", "Last day", "Days", "Status", "Reported by",
                                                   "Sick sheets"], rows)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        user = self.request.user
        return {**super().get_context_data(**kwargs), "statuses": SickLeave.Status.choices,
                "people": services.people_for(user), "can_export": user.role in services.OFFICE,
                "office": user.role in services.OFFICE}


class SickDetailView(LoginRequiredMixin, DetailView):
    template_name = "leave/sick_detail.html"
    context_object_name = "sick"

    def get_queryset(self):
        return SickLeave.objects.visible_to(self.request.user).select_related("user", "reported_by", "reviewed_by")

    def get_context_data(self, **kwargs):
        user, sick = self.request.user, self.object
        ctx = super().get_context_data(**kwargs)
        sees_files = services.can_see_sick_files(user, sick)
        ctx.update(
            sees_files=sees_files,
            notes=sick.notes.select_related("uploaded_by") if sees_files else None,
            note_count=sick.notes.count(),
            can_review=user.role in services.OFFICE,
            can_change=services.can_change_sick(user, sick),
            sheet_form=SheetForm() if sees_files else None,
            last_day_form=LastDayForm(initial={"last_day": sick.last_day}),
            sick_balance=services.plain_balance(*_sick_balance(sick.user, sick.first_day.year), you=sick.user_id == user.pk),
        )
        return ctx


def _sick_balance(person, year):
    lt = LeaveType.objects.filter(code=services.SICK_CODE).first() or LeaveType(name="Sick leave", days_per_year=14)
    return lt, services.balance(person, lt, year)


class SickAction(ActionView):
    allowed_roles = EVERYONE
    action = None

    def get_queryset(self):
        return SickLeave.objects.visible_to(self.request.user).select_related("user")

    def act(self, sick):
        user, post = self.request.user, self.request.POST
        if self.action == "sheet":
            if not services.can_see_sick_files(user, sick):
                raise Http404
            form = SheetForm(post, self.request.FILES)
            if not form.is_valid():
                raise ValidationError([e for errs in form.errors.values() for e in errs])
            services.add_sick_note(sick, form.cleaned_data["sheet"], user)
            return "Sick sheet uploaded. The office will check it."
        if self.action == "last_day":
            form = LastDayForm(post)
            if not form.is_valid():
                raise ValidationError("Enter the last day off sick.")
            services.change_last_day(sick, form.cleaned_data["last_day"], user)
            return "Last day off sick changed."
        services.review_sick(sick, user, self.action, post.get("note", ""))
        return {"accept": "Sick leave accepted.", "reject": "Marked as not accepted.",
                "again": "Asked for a proper sick sheet."}[self.action]


class SickNoteDownloadView(LoginRequiredMixin, View):
    """Sick sheets are never at a public address: this checks who is asking and logs every opening."""

    def get(self, request, pk):
        note = get_object_or_404(SickNote.objects.select_related("sick_leave"), pk=pk)
        if not services.can_see_sick_files(request.user, note.sick_leave) or not note.file:
            raise Http404
        try:
            fh = note.file.open("rb")
        except FileNotFoundError:
            raise Http404
        services.log_sheet_download(request.user, note)
        response = FileResponse(fh, as_attachment=False, filename=note.original_name, content_type=note.mime_type)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
