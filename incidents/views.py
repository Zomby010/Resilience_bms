from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView

from accounts.models import Role
from accounts.permissions import RoleRequiredMixin
from core.filters import apply_dates, csv_response, query_string
from core.mixins import ActionView
from core.services.files import attachments_for
from core.workflow import TransitionError
from tracking.models import Site

from . import services
from .forms import IncidentForm
from .models import Incident

S = Incident.Status
OFFICE = services.OFFICE


class ReporterMixin(RoleRequiredMixin):
    """Reporting and the incidents list: guards and supervisors only."""

    allowed_roles = services.REPORTERS


class ViewerMixin(RoleRequiredMixin):
    """One incident's page: also the Manager, who reaches it from the to-do list or the site page."""

    allowed_roles = services.VIEWERS


def visible(user):
    return Incident.objects.visible_to(user).select_related("site", "reported_by")


class IncidentCreateView(ReporterMixin, CreateView):
    form_class = IncidentForm
    template_name = "incidents/incident_form.html"

    def get_initial(self):
        initial = {"occurred_at": timezone.localtime().replace(second=0, microsecond=0)}
        profile = getattr(self.request.user, "tracking", None)
        if profile is not None and profile.site_id and profile.site.is_active:
            initial["site"] = profile.site_id
        return initial

    def form_valid(self, form):
        try:
            incident = services.create_incident(form.save(commit=False), self.request.user, form.cleaned_data["photos"])
        except TransitionError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, f"Thank you. Your report {incident.number} has been sent to the office.")
        return redirect(incident)


class IncidentListView(ReporterMixin, ListView):
    template_name = "incidents/incident_list.html"
    context_object_name = "incidents"
    paginate_by = 30

    def filtered(self):
        """Every filter except status, so the status chips can show their counts."""
        qs = visible(self.request.user)
        g = self.request.GET
        if g.get("kind") in Incident.Kind.values:
            qs = qs.filter(kind=g["kind"])
        if g.get("severity") in Incident.Severity.values:
            qs = qs.filter(severity=g["severity"])
        if g.get("site", "").isdigit():
            qs = qs.filter(site_id=int(g["site"]))
        qs = apply_dates(qs, g, "occurred_at")
        q = (g.get("q") or "").strip()
        if q:
            cond = Q(what_happened__icontains=q)
            num = q.upper().removeprefix("INC-").lstrip("0")
            if num.isdigit():
                cond |= Q(pk=int(num))
            qs = qs.filter(cond)
        return qs

    def get_queryset(self):
        self.base = self.filtered()
        status = self.request.GET.get("status", "")
        if status == "open":
            return self.base.exclude(status=S.CLOSED)
        if status in S.values:
            return self.base.filter(status=status)
        return self.base

    # The Manager has no incidents page, but can still download them (a site's History tab links here).
    allowed_roles = services.VIEWERS

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv":
            if request.user.role not in OFFICE:
                raise PermissionDenied
            return self.export(self.get_queryset())
        if request.user.role not in services.REPORTERS:
            raise PermissionDenied
        return super().get(request, *args, **kwargs)

    def export(self, qs):
        header = ["Number", "Date and time", "Site", "Type", "Severity", "Status", "What happened", "Who was involved",
                  "Action taken", "Police told", "OB number", "Client told", "Reported by", "Reported at"]
        rows = (
            [i.number, timezone.localtime(i.occurred_at).strftime("%Y-%m-%d %H:%M"), i.site, i.get_kind_display(),
             i.get_severity_display(), i.get_status_display(), i.what_happened, i.who_involved, i.action_taken,
             "Yes" if i.police_reported else "No", i.police_ob_number, "Yes" if i.client_told else "No",
             i.reported_by, timezone.localtime(i.reported_at).strftime("%Y-%m-%d %H:%M")]
            for i in qs
        )
        return csv_response(f"incidents-{timezone.localdate():%Y-%m-%d}.csv", header, rows)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        counts = dict(self.base.order_by().values_list("status").annotate(n=Count("id")))
        params = self.request.GET.copy()
        for key in ("status", "page", "export"):
            params.pop(key, None)
        rest = params.urlencode()
        ctx.update(
            chips=[("", "All", sum(counts.values()))] + [(v, l, counts.get(v, 0)) for v, l in S.choices],
            chip_query=rest, status=self.request.GET.get("status", ""), statuses=S.choices,
            kinds=Incident.Kind.choices, severities=Incident.Severity.choices,
            sites=Site.objects.filter(incidents__in=visible(self.request.user)).distinct(),
            office=self.request.user.role in OFFICE, query_string=query_string(self.request), f=self.request.GET,
            mine_only=self.request.user.role == Role.STAFF,
        )
        return ctx


class IncidentDetailView(ViewerMixin, DetailView):
    template_name = "incidents/incident_detail.html"
    context_object_name = "incident"

    def get_queryset(self):
        return visible(self.request.user).select_related(
            "site__supervisor", "reported_by__supervisor", "supervisor_reviewed_by", "manager_reviewed_by", "closed_by")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        inc = self.object
        ctx.update(
            photos=attachments_for(inc), notes=inc.notes.select_related("author"),
            can=services.actions_for(inc, self.request.user),
        )
        return ctx


class IncidentPrintView(IncidentDetailView):
    template_name = "incidents/incident_print.html"


class IncidentAction(ViewerMixin, ActionView):
    action = None
    done = {
        "add_note": "Note added.",
        "supervisor_review": "Marked as reviewed by you.",
        "manager_review": "Marked as reviewed by you.",
        "close": "Incident closed.",
        "reopen": "Incident reopened.",
    }

    def get_queryset(self):
        return visible(self.request.user).select_related("site", "reported_by")

    def act(self, incident):
        getattr(services, self.action)(incident, self.request.user, self.request.POST.get("body", ""))
        return self.done[self.action]


class SupervisorReviewView(IncidentAction):
    allowed_roles = (Role.SUPERVISOR,)
    action = "supervisor_review"


class ManagerAction(IncidentAction):
    allowed_roles = (Role.MANAGER,)


class OfficeAction(IncidentAction):
    allowed_roles = OFFICE
