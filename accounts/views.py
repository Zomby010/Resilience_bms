from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from .forms import ProfileForm, UserCreateForm, UserUpdateForm
from .models import Role, User
from .permissions import RoleRequiredMixin


class ProfileView(LoginRequiredMixin, UpdateView):
    form_class = ProfileForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Your details were updated.")
        return super().form_valid(form)


class TeamListView(RoleRequiredMixin, ListView):
    """Manager: everyone in the company, with their reporting line."""

    allowed_roles = (Role.MANAGER,)
    template_name = "accounts/team_list.html"
    context_object_name = "people"

    def get_queryset(self):
        qs = User.objects.select_related("supervisor").annotate(
            report_count=Count("reports", distinct=True),
            team_size=Count("team_members", distinct=True),
        )
        role = self.request.GET.get("role")
        if role in Role.values:
            qs = qs.filter(role=role)
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["roles"] = Role.choices
        ctx["selected_role"] = self.request.GET.get("role", "")
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class UserCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = (Role.MANAGER,)
    form_class = UserCreateForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:team")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Add team member"
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f"Account created for {form.instance}.")
        return super().form_valid(form)


class UserUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = (Role.MANAGER,)
    model = User
    form_class = UserUpdateForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:team")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["editing_self"] = self.object.pk == self.request.user.pk
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = f"Edit {self.object}"
        return ctx

    def form_valid(self, form):
        was = User.objects.get(pk=self.object.pk)
        response = super().form_valid(form)
        messages.success(self.request, f"{form.instance} was updated.")
        if was.role == Role.SUPERVISOR and was.is_active and not (self.object.is_active and self.object.role == Role.SUPERVISOR):
            # Their clients and open client issues go back to the office to be given a new supervisor.
            from clients.services import supervisor_deactivated

            supervisor_deactivated(self.object, self.request.user)
        return response
