from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView, UpdateView

from accounts.models import Role, User
from accounts.permissions import RoleRequiredMixin
from attendance.services import people_on
from core.filters import apply_dates, csv_response
from core.mixins import FilterContextMixin, OfficeRequiredMixin
from core.services import audit
from core.services.files import attachments_for
from tracking.models import Site, SitePosting
from tracking.services import TRACKED_ROLES

from . import services
from .forms import OBForm, SiteDetailsForm, VisitForm
from .models import OBEntry, SiteVisit

OFFICE = services.OFFICE


def _local(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M") if dt else ""


# --- sites -------------------------------------------------------------------------

class SiteListView(LoginRequiredMixin, FilterContextMixin, ListView):
    template_name = "operations/site_list.html"
    context_object_name = "sites"

    def get_queryset(self):
        qs = services.sites_for(self.request.user).select_related("supervisor").annotate(
            posted=Count("people", filter=Q(people__user__is_active=True), distinct=True))
        g = self.request.GET
        if g.get("show") != "all":
            qs = qs.filter(is_active=True)
        q = (g.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(address__icontains=q))
        return qs.order_by("name")

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "can_edit": services.can_edit_site(self.request.user)}


class SiteDetailView(LoginRequiredMixin, DetailView):
    """Read-only for supervisors and staff; the office also gets the Edit button."""

    template_name = "operations/site_detail.html"
    context_object_name = "site"

    def get_queryset(self):
        return services.sites_for(self.request.user).select_related("supervisor", "details_updated_by")

    def get_context_data(self, **kwargs):
        from incidents.models import Incident

        user, site = self.request.user, self.object
        ctx = super().get_context_data(**kwargs)
        office = user.role in OFFICE
        ctx.update(
            can_edit=services.can_edit_site(user),
            hours=site.hours.all(),
            people=services.people_at(site),
            contacts=[line for line in site.emergency_contacts.splitlines() if line.strip()],
            ob=OBEntry.objects.visible_to(user).filter(site=site).select_related("written_by")[:10],
            incidents=Incident.objects.visible_to(user).filter(site=site)[:5],
            visits=SiteVisit.objects.visible_to(user).filter(site=site).select_related("supervisor")[:5],
            postings=SitePosting.objects.filter(site=site).select_related("user")[:20] if office else None,
            can_write_ob=services.can_write_ob(user, site) and site.is_active,
        )
        return ctx


class SiteEditView(OfficeRequiredMixin, UpdateView):
    """Manager and Secretary edit the site details. Location and hours stay on the GPS pages."""

    model = Site
    form_class = SiteDetailsForm
    template_name = "operations/site_form.html"
    context_object_name = "site"

    def form_valid(self, form):
        before = audit.snapshot(Site.objects.get(pk=self.object.pk), services.SITE_DETAIL_FIELDS)
        site = services.update_site_details(form.save(commit=False), before, self.request.user)
        messages.success(self.request, "Site details saved. Supervisors and guards now see the new details.")
        return redirect(site)


# --- my team today -------------------------------------------------------------------

class TeamTodayView(RoleRequiredMixin, TemplateView):
    """Each guard's status today in plain words. No map and no coordinates."""

    allowed_roles = (Role.SUPERVISOR, Role.MANAGER, Role.SECRETARY)
    template_name = "operations/team_today.html"

    def get_context_data(self, **kwargs):
        user, g = self.request.user, self.request.GET
        ctx = super().get_context_data(**kwargs)
        people = User.objects.filter(is_active=True, role__in=TRACKED_ROLES)
        if user.role == Role.SUPERVISOR:
            people = people.filter(supervisor=user)
        else:
            if g.get("supervisor", "").isdigit():
                people = people.filter(Q(supervisor_id=int(g["supervisor"])) | Q(pk=int(g["supervisor"])))
            if g.get("site", "").isdigit():
                people = people.filter(tracking__site_id=int(g["site"]))
        rows = people_on(people=people)
        state = g.get("state", "")
        counts = {}
        for r in rows:
            counts[r["label"]] = counts.get(r["label"], 0) + 1
        if state:
            rows = [r for r in rows if r["state"] == state]
        held = services.equipment_by_person(people)
        for r in rows:
            r["items"] = held.get(r["person"].pk, [])
        from attendance.services import STATE_LABELS

        ctx.update(rows=rows, counts=sorted(counts.items()), states=STATE_LABELS.items(), f=g,
                   sites=Site.objects.filter(is_active=True),
                   supervisors=User.objects.filter(role=Role.SUPERVISOR, is_active=True), now=timezone.localtime())
        return ctx


# --- Occurrence Book ---------------------------------------------------------------------

class OBListView(LoginRequiredMixin, FilterContextMixin, ListView):
    template_name = "operations/ob_list.html"
    context_object_name = "entries"
    paginate_by = 50

    def get_queryset(self):
        g = self.request.GET
        qs = OBEntry.objects.visible_to(self.request.user).select_related("site", "written_by", "corrects")
        if g.get("site", "").isdigit():
            qs = qs.filter(site_id=int(g["site"]))
        if g.get("kind") in OBEntry.Kind.values:
            qs = qs.filter(kind=g["kind"])
        if g.get("writer", "").isdigit():
            qs = qs.filter(written_by_id=int(g["writer"]))
        q = (g.get("q") or "").strip()
        if q:
            num = q.upper().removeprefix("OB-")
            qs = qs.filter(Q(text__icontains=q) | (Q(pk=int(num)) if num.isdigit() else Q()))
        return apply_dates(qs, g, "occurred_at")

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv" and request.user.role in OFFICE:
            rows = ((e.number, e.site, _local(e.occurred_at), e.get_kind_display(), e.text, e.written_by, _local(e.written_at),
                     e.corrects.number if e.corrects else "") for e in self.get_queryset())
            return csv_response("occurrence-book.csv", ["Entry", "Site", "When", "Kind", "What happened", "Written by",
                                                        "Written at", "Corrects"], rows)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        user = self.request.user
        sites = services.sites_for(user)
        my_site = services.my_site(user)
        return {**super().get_context_data(**kwargs), "sites": sites, "kinds": OBEntry.Kind.choices,
                "can_export": user.role in OFFICE, "my_site": my_site,
                "quick": services.QUICK_ENTRIES if my_site else None,
                "print": self.request.GET.get("print") == "1"}

    def get_template_names(self):
        return ["operations/ob_print.html"] if self.request.GET.get("print") == "1" else [self.template_name]

    def get_paginate_by(self, queryset):
        return 500 if self.request.GET.get("print") == "1" else self.paginate_by


class OBWriteView(LoginRequiredMixin, FormView):
    template_name = "operations/ob_form.html"
    form_class = OBForm

    def dispatch(self, request, *args, **kwargs):
        self.corrects = None
        if request.user.is_authenticated and request.GET.get("corrects", "").isdigit():
            self.corrects = get_object_or_404(OBEntry.objects.visible_to(request.user), pk=int(request.GET["corrects"]))
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_initial(self):
        if self.corrects:
            return {"site": self.corrects.site_id, "kind": self.corrects.kind, "occurred_at": timezone.localtime(
                self.corrects.occurred_at).strftime("%Y-%m-%dT%H:%M")}
        return {}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "corrects": self.corrects}

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            entry = services.write_ob(d["site"], self.request.user, d["kind"], d["text"], d["occurred_at"], self.corrects)
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
            return self.form_invalid(form)
        messages.success(self.request, f"Written in the OB as {entry.number}.")
        return redirect(f"{_ob_url()}?site={entry.site_id}")


def _ob_url():
    from django.urls import reverse

    return reverse("operations:ob")


class OBQuickView(LoginRequiredMixin, View):
    """One tap: 'Patrol done. All in order.' in the person's own site OB."""

    http_method_names = ["post"]

    def post(self, request, code):
        site = services.my_site(request.user)
        if code not in services.QUICK_ENTRIES or site is None:
            raise Http404
        kind, text = services.QUICK_ENTRIES[code]
        try:
            entry = services.write_ob(site, request.user, kind, text)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, f"Written in the OB as {entry.number}: {text}")
        if request.POST.get("next") == "home":
            return redirect("core:home")
        return redirect(f"{_ob_url()}?site={site.pk}")


# --- site visits ------------------------------------------------------------------------

class VisitCreateView(RoleRequiredMixin, FormView):
    allowed_roles = (Role.SUPERVISOR, Role.MANAGER)
    template_name = "operations/visit_form.html"
    form_class = VisitForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            visit = services.record_visit(d["site"], self.request.user, d["visited_at"], d["checks"], d["guards_seen"],
                                          d["welfare_check_done"], d["remarks"], d.get("photo"))
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
            return self.form_invalid(form)
        messages.success(self.request, "Site visit recorded and written in the OB.")
        return redirect(visit)


class VisitListView(RoleRequiredMixin, FilterContextMixin, ListView):
    allowed_roles = (Role.SUPERVISOR, Role.MANAGER, Role.SECRETARY)
    template_name = "operations/visit_list.html"
    context_object_name = "visits"
    paginate_by = 30

    def get_queryset(self):
        g = self.request.GET
        qs = SiteVisit.objects.visible_to(self.request.user).select_related("site", "supervisor")
        if g.get("site", "").isdigit():
            qs = qs.filter(site_id=int(g["site"]))
        if g.get("supervisor", "").isdigit():
            qs = qs.filter(supervisor_id=int(g["supervisor"]))
        if g.get("welfare") in ("yes", "no"):
            qs = qs.filter(welfare_check_done=g["welfare"] == "yes")
        return apply_dates(qs, g, "visited_at")

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv" and request.user.role in OFFICE:
            rows = ((_local(v.visited_at), v.site, v.supervisor, ", ".join(l for l, ok in v.check_labels if ok),
                     "Yes" if v.welfare_check_done else "No", v.remarks) for v in self.get_queryset())
            return csv_response("site-visits.csv", ["When", "Site", "Supervisor", "Checks fine", "Welfare check", "Remarks"], rows)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        user = self.request.user
        return {**super().get_context_data(**kwargs), "sites": services.sites_for(user),
                "supervisors": User.objects.filter(role=Role.SUPERVISOR, is_active=True), "can_export": user.role in OFFICE}


class VisitDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = (Role.SUPERVISOR, Role.MANAGER, Role.SECRETARY)
    template_name = "operations/visit_detail.html"
    context_object_name = "visit"

    def get_queryset(self):
        return SiteVisit.objects.visible_to(self.request.user).select_related("site", "supervisor")

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "files": attachments_for(self.object),
                "guards": self.object.guards_seen.all()}


# --- equipment per guard ------------------------------------------------------------------

class EquipmentView(RoleRequiredMixin, FilterContextMixin, TemplateView):
    allowed_roles = (Role.SUPERVISOR, Role.MANAGER, Role.SECRETARY)
    template_name = "operations/equipment.html"

    def people(self):
        user, g = self.request.user, self.request.GET
        people = User.objects.all()
        if user.role == Role.SUPERVISOR:
            people = people.filter(Q(supervisor=user) | Q(pk=user.pk))
        if g.get("person", "").isdigit():
            people = people.filter(pk=int(g["person"]))
        if g.get("site", "").isdigit():
            people = people.filter(tracking__site_id=int(g["site"]))
        if g.get("left") == "1":
            people = people.filter(is_active=False)
        return people

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv" and request.user.role in OFFICE:
            rows = ((r.requester, "No" if not r.requester.is_active else "Yes", r.item.code, r.item.name,
                     r.qty_issued or r.qty_requested, r.handed_over_at and _local(r.handed_over_at),
                     r.expected_return_date or "", r.get_status_display()) for r in services.equipment_held(self.people()))
            return csv_response("equipment-held.csv", ["Person", "Still working", "Item code", "Item", "Quantity",
                                                       "Given", "Return by", "Status"], rows)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        held = services.equipment_by_person(self.people())
        people = User.objects.filter(pk__in=held).select_related("tracking__site").order_by("first_name", "last_name")
        ctx.update(groups=[(p, held[p.pk]) for p in people], today=timezone.localdate(),
                   choices=User.objects.filter(supervisor=user) if user.role == Role.SUPERVISOR else User.objects.all(),
                   sites=Site.objects.filter(is_active=True), can_export=user.role in OFFICE)
        return ctx

