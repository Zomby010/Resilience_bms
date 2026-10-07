from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.utils import timezone
from django.views.generic import TemplateView

from accounts.models import Role
from finance.models import Expense
from reports import services
from tracking import services as tracking


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
            ctx.update(services.manager_dashboard())
            ctx.update(_finance_glance())
        elif user.role == Role.SUPERVISOR:
            ctx.update(services.supervisor_dashboard(user))
            ctx["location_state"] = tracking.my_state(user)
        elif user.role == Role.SECRETARY:
            ctx.update(_finance_glance())
            ctx["recent_expenses"] = Expense.objects.select_related("category")[:8]
        else:
            ctx.update(services.staff_dashboard(user))
            if tracking.is_tracked(user):
                ctx["location_state"] = tracking.my_state(user)
        return ctx


def _finance_glance():
    today = timezone.localdate()
    month = Expense.objects.filter(date__year=today.year, date__month=today.month)
    return {
        "month_total": month.aggregate(t=Sum("amount"))["t"] or 0,
        "month_count": month.count(),
        "month_label": today.strftime("%B %Y"),
    }
