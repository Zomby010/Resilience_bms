"""Small view helpers shared by the Secretary operations apps."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views import View

from accounts.models import Role
from accounts.permissions import RoleRequiredMixin

from .workflow import TransitionError

OFFICE = (Role.SECRETARY, Role.MANAGER)


class OfficeRequiredMixin(RoleRequiredMixin):
    """Secretary and Manager only."""

    allowed_roles = OFFICE


class FilterContextMixin:
    """Adds the current GET filters (without `page`) as `query_string` for pagination links."""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx["query_string"] = params.urlencode()
        ctx["f"] = self.request.GET
        return ctx


class ActionView(RoleRequiredMixin, View):
    """A POST-only button: load the record, run one service call, go back with a plain message.

    Subclasses set `model` (or override get_queryset) and implement `act(obj)`, which returns the
    success message. TransitionError / ValidationError become an error message, never a crash.
    """

    model = None
    http_method_names = ["post"]

    def get_queryset(self):
        return self.model.objects.all()

    def get_object(self):
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    def act(self, obj):  # pragma: no cover - always overridden
        raise NotImplementedError

    def get_success_url(self):
        return self.object.get_absolute_url()

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            msg = self.act(self.object)
        except TransitionError as exc:
            messages.error(request, str(exc))
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            if msg:
                messages.success(request, msg)
        return redirect(self.get_success_url())
