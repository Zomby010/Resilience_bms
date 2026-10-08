import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import ListView, TemplateView

from accounts.models import Role, User
from accounts.permissions import RoleRequiredMixin
from core.filters import apply_dates, csv_response
from core.mixins import FilterContextMixin
from core.workflow import TransitionError
from tracking.models import Site
from tracking.services import TRACKED_ROLES
from tracking.views import api

from . import services
from .models import AttendanceDay, AttendanceRecord

O = AttendanceRecord.Outcome
S = AttendanceRecord.Status


def _day(request, key="date"):
    day = parse_date(request.GET.get(key, "") or request.POST.get(key, "") or "")
    today = timezone.localdate()
    return min(day, today) if day else today


@require_POST
@api(TRACKED_ROLES)
def api_sign_in(request):
    """The phone sends its position; the server decides whether the person is at their site."""
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "Bad request."}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Bad request."}, status=400)
    try:
        rec = services.sign_in(request.user, data)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    at = timezone.localtime(rec.signed_in_at)
    text = f"Signed in at {at:%H:%M} at {rec.site}."
    if rec.late_minutes:
        text += f" You are {rec.late_minutes} minutes late."
    text += " Your supervisor will approve it." if rec.supervisor_id else " The Manager will approve it."
    return JsonResponse({"ok": True, "message": text})


class MyAttendanceView(RoleRequiredMixin, TemplateView):
    allowed_roles = TRACKED_ROLES
    template_name = "attendance/mine.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["att"] = services.my_today(self.request.user)
        ctx["history"] = AttendanceRecord.objects.filter(user=self.request.user).select_related("site")[:31]
        return ctx


class TeamView(RoleRequiredMixin, TemplateView):
    """Supervisor: today's sign-ins for their team, to approve or mark."""

    allowed_roles = (Role.SUPERVISOR,)
    template_name = "attendance/team.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        day = _day(self.request)
        ctx.update(services.team_today(self.request.user, day))
        ctx.update(day=day, today=timezone.localdate(), completed=services.day_completed(day), outcomes=_mark_outcomes())
        return ctx


def _mark_outcomes():
    return [(O.PRESENT, "Present"), (O.LATE, "Late"), (O.ABSENT, "Absent")]


class DaySheetView(RoleRequiredMixin, TemplateView):
    """Manager: everyone for one day, by site, with the button to complete the day."""

    allowed_roles = (Role.MANAGER, Role.SECRETARY)
    template_name = "attendance/day.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        day = _day(self.request)
        ctx["board"] = services.board(day)
        ctx.update(day=day, today=timezone.localdate(), outcomes=_mark_outcomes(),
                   recent_days=AttendanceDay.objects.select_related("completed_by")[:10])
        return ctx


class RecordListView(LoginRequiredMixin, FilterContextMixin, ListView):
    template_name = "attendance/records.html"
    context_object_name = "records"
    paginate_by = 50

    def get_queryset(self):
        g = self.request.GET
        qs = AttendanceRecord.objects.visible_to(self.request.user).select_related("user", "site", "supervisor_decided_by")
        if g.get("person", "").isdigit():
            qs = qs.filter(user_id=int(g["person"]))
        if g.get("site", "").isdigit():
            qs = qs.filter(site_id=int(g["site"]))
        if g.get("outcome") in O.values:
            qs = qs.filter(outcome=g["outcome"])
        if g.get("status") in S.values:
            qs = qs.filter(status=g["status"])
        return apply_dates(qs, g, "date").order_by("-date", "user__first_name")

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv" and request.user.role in (Role.MANAGER, Role.SECRETARY):
            def when(dt):
                return timezone.localtime(dt).strftime("%H:%M") if dt else ""
            rows = ((r.date, r.user, r.site or "", r.get_outcome_display(), r.late_minutes or "", when(r.signed_in_at),
                     r.get_method_display(), r.get_status_display(), r.note or r.supervisor_note)
                    for r in self.get_queryset())
            return csv_response("attendance.csv", ["Date", "Person", "Site", "Attendance", "Minutes late", "Signed in",
                                                   "How", "Status", "Note"], rows)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        user = self.request.user
        return {**super().get_context_data(**kwargs), "people": services.lookup_people(user),
                "sites": Site.objects.filter(is_active=True), "outcomes": O.choices, "statuses": S.choices,
                "can_export": user.role in (Role.MANAGER, Role.SECRETARY)}


class _Post(RoleRequiredMixin, View):
    http_method_names = ["post"]

    def back(self, day):
        nxt = self.request.POST.get("next", "")
        if nxt in ("team", "day"):
            return redirect(reverse(f"attendance:{nxt}") + f"?date={day}")
        return redirect("core:home")

    def run(self, fn, ok, day):
        try:
            result = fn()
        except (TransitionError, ValidationError) as exc:
            messages.error(self.request, " ".join(getattr(exc, "messages", [str(exc)])))
        else:
            messages.success(self.request, ok(result) if callable(ok) else ok)
        return self.back(day)


class RecordActionView(_Post):
    allowed_roles = (Role.SUPERVISOR, Role.MANAGER)
    action = None

    def post(self, request, pk):
        rec = get_object_or_404(AttendanceRecord.objects.visible_to(request.user).select_related("user"), pk=pk)
        if self.action == "approve":
            return self.run(lambda: services.approve(rec, request.user), f"Sign-in of {rec.user} approved.", rec.date)
        return self.run(lambda: services.reject(rec, request.user, request.POST.get("note", "")),
                        f"Sign-in of {rec.user} not accepted. They have been told.", rec.date)


class ApproveAllView(_Post):
    allowed_roles = (Role.SUPERVISOR, Role.MANAGER)

    def post(self, request):
        day = _day(request)
        return self.run(lambda: services.approve_all(request.user, day), lambda n: f"{n} sign-in{'s' if n != 1 else ''} approved.", day)


class MarkView(_Post):
    allowed_roles = (Role.SUPERVISOR, Role.MANAGER)

    def post(self, request, user_pk):
        person = get_object_or_404(User, pk=user_pk)
        day = _day(request)
        if not services.can_mark(request.user, person):
            messages.error(request, "You cannot mark attendance for this person.")
            return self.back(day)
        return self.run(lambda: services.mark(person, day, request.POST.get("outcome", ""), request.POST.get("note", ""), request.user),
                        f"Attendance for {person} recorded. It goes to the Manager to complete the day.", day)


class CompleteDayView(_Post):
    allowed_roles = (Role.MANAGER,)

    def post(self, request):
        day = _day(request)
        return self.run(lambda: services.complete_day(day, request.user),
                        lambda s: f"Day completed: {s.present + s.late} in, {s.absent} absent, {s.on_leave} on leave, {s.sick} sick.", day)


class ReopenDayView(_Post):
    allowed_roles = (Role.MANAGER,)

    def post(self, request):
        day = _day(request)
        return self.run(lambda: services.reopen_day(day, request.user), "Day reopened. You can change it and complete it again.", day)
