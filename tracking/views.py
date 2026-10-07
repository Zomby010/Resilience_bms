import json
from functools import wraps

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import ListView, TemplateView

from accounts.models import Role, User
from accounts.permissions import RoleRequiredMixin

from . import services
from .forms import HistoryFilterForm, HoursForm, PersonForm, SiteForm
from .models import HISTORY_DAYS, AuditEntry, LocationPing, LocationStatus, Site, TrackingProfile

STORED_STATUSES = [(s.value, s.label) for s in (LocationStatus.ON, LocationStatus.NEAR, LocationStatus.OFF, LocationStatus.WEAK)]


# --- JSON API ----------------------------------------------------------------
# Session login + CSRF token, like the rest of the site. The person is always
# request.user: nothing in the request body can choose whose location it is.

def api(roles):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({"error": "Your session has expired. Please sign in again.", "code": "session"}, status=401)
            if request.user.role not in roles:
                return JsonResponse({"error": "Not allowed.", "code": "forbidden"}, status=403)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


@require_GET
@api(services.TRACKED_ROLES)
def api_me(request):
    return JsonResponse(services.my_state(request.user))


@require_POST
@api(services.TRACKED_ROLES)
def api_start(request):
    services.set_tracking(request.user, True)
    return JsonResponse(services.my_state(request.user))


@require_POST
@api(services.TRACKED_ROLES)
def api_stop(request):
    services.set_tracking(request.user, False)
    return JsonResponse(services.my_state(request.user))


@require_POST
@api(services.TRACKED_ROLES)
def api_update(request):
    try:
        data = json.loads(request.body or b"{}")
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "Invalid data.", "code": "invalid"}, status=400)
    try:
        ping, _ = services.record_update(request.user, data)
    except services.RateLimited as e:
        return JsonResponse({"error": str(e), "code": "rate_limited"}, status=429)
    except services.LocationError as e:
        return JsonResponse({"error": str(e), "code": "invalid"}, status=400)
    state = services.my_state(request.user)
    state["flagged"] = bool(ping.flag)
    return JsonResponse(state)


@require_GET
@api((Role.MANAGER,))
def api_overview(request):
    return JsonResponse(services.manager_overview())


# --- staff and supervisor page -------------------------------------------------

class MyLocationView(RoleRequiredMixin, TemplateView):
    allowed_roles = services.TRACKED_ROLES
    template_name = "tracking/my_location.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        profile = services.profile_for(self.request.user)
        ctx["location_state"] = services.my_state(self.request.user)
        ctx["hours"] = services.hours_for(profile)
        ctx["history_days"] = HISTORY_DAYS
        return ctx


# --- manager pages -----------------------------------------------------------

class ManagerMixin(RoleRequiredMixin):
    allowed_roles = (Role.MANAGER,)


def audit(user, action):
    AuditEntry.objects.create(actor=user, action=action)


class TrackerView(ManagerMixin, TemplateView):
    template_name = "tracking/tracker.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["overview"] = services.manager_overview()
        ctx["status_help"] = [(s.label, services.STATUS_HELP[s]) for s in LocationStatus]
        return ctx


class SiteListView(ManagerMixin, ListView):
    template_name = "tracking/site_list.html"
    context_object_name = "sites"

    def get_queryset(self):
        return Site.objects.annotate(
            people_count=Count("people", filter=Q(people__user__is_active=True))
        ).prefetch_related("hours")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["audit"] = AuditEntry.objects.select_related("actor")[:20]
        return ctx


class SiteEditView(ManagerMixin, TemplateView):
    """Create (pk=None) or edit a site and its working hours on one page."""

    template_name = "tracking/site_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.site = get_object_or_404(Site, pk=kwargs["pk"]) if kwargs.get("pk") else None
        return super().dispatch(request, *args, **kwargs)

    def forms(self, data=None):
        rows = self.site.hours.all() if self.site else ()
        return SiteForm(data, instance=self.site, prefix="site"), HoursForm(data, rows=rows, prefix="hours")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if "form" not in kwargs:
            ctx["form"], ctx["hours_form"] = self.forms()
        ctx["site"] = self.site
        if self.site:
            ctx["people"] = User.objects.filter(tracking__site=self.site, is_active=True)
        return ctx

    def post(self, request, *args, **kwargs):
        form, hours_form = self.forms(request.POST)
        if not (form.is_valid() and hours_form.is_valid()):
            return self.render_to_response(self.get_context_data(form=form, hours_form=hours_form))
        creating = self.site is None
        with transaction.atomic():
            site = form.save()
            hours_form.save(site=site)
            verb = "created" if creating else "updated"
            audit(
                request.user,
                f"{verb} site {site.name} at {site.latitude}, {site.longitude} (radius {site.radius_m} m); "
                f"hours: {hours_form.summary()}",
            )
        messages.success(request, f"Site {site.name} saved.")
        return redirect("tracking:sites")


class PeopleView(ManagerMixin, ListView):
    template_name = "tracking/people_list.html"
    context_object_name = "people"

    def get_queryset(self):
        services.ensure_profiles()
        qs = TrackingProfile.objects.select_related("user", "site").filter(
            user__role__in=services.TRACKED_ROLES, user__is_active=True
        ).order_by("user__first_name", "user__username")
        role = self.request.GET.get("role")
        if role in services.TRACKED_ROLES:
            qs = qs.filter(user__role=role)
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(user__username__icontains=q) | Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()
        for p in ctx["people"]:
            p.status = services.current_status(p, now)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["selected_role"] = self.request.GET.get("role", "")
        return ctx


class PersonEditView(ManagerMixin, TemplateView):
    template_name = "tracking/person_form.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role == Role.MANAGER:
            self.person = get_object_or_404(User, pk=kwargs["pk"], role__in=services.TRACKED_ROLES)
            self.profile = services.profile_for(self.person)
        return super().dispatch(request, *args, **kwargs)

    def forms(self, data=None):
        return (
            PersonForm(data, instance=self.profile, prefix="p"),
            HoursForm(data, rows=self.person.work_hours.all(), prefix="hours"),
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if "form" not in kwargs:
            ctx["form"], ctx["hours_form"] = self.forms()
        ctx["person"], ctx["profile"] = self.person, self.profile
        ctx["status"] = services.current_status(self.profile)
        return ctx

    def post(self, request, *args, **kwargs):
        form, hours_form = self.forms(request.POST)
        own = form.is_valid() and form.cleaned_data["own_hours"]
        if not form.is_valid() or (own and not hours_form.is_valid()):
            return self.render_to_response(self.get_context_data(form=form, hours_form=hours_form))
        with transaction.atomic():
            profile = form.save()
            detail = f"set {self.person}'s site to {profile.site or 'none'}"
            if own:
                hours_form.save(user=self.person)
                detail += f"; own hours: {hours_form.summary()}"
            else:
                self.person.work_hours.all().delete()
                detail += "; uses site hours"
            audit(request.user, detail)
        services.evaluate_alerts([profile])
        messages.success(request, f"Location settings for {self.person} saved.")
        return redirect("tracking:people")


class HistoryView(ManagerMixin, ListView):
    template_name = "tracking/history.html"
    context_object_name = "pings"
    paginate_by = 50

    def get_queryset(self):
        people = User.objects.filter(role__in=services.TRACKED_ROLES)
        self.filter_form = HistoryFilterForm(self.request.GET or None, people=people, statuses=STORED_STATUSES)
        qs = LocationPing.objects.select_related("user", "site")
        if self.filter_form.is_valid():
            f = self.filter_form.cleaned_data
            if f["person"]:
                qs = qs.filter(user=f["person"])
            if f["site"]:
                qs = qs.filter(site=f["site"])
            if f["date"]:
                qs = qs.filter(received_at__date=f["date"])
            if f["status"]:
                qs = qs.filter(status=f["status"])
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        ctx["history_days"] = HISTORY_DAYS
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx["query_string"] = params.urlencode()
        return ctx
