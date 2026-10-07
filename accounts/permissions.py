"""Role-based access control helpers used by every view in the system."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class RoleRequiredMixin(LoginRequiredMixin):
    """Restrict a class-based view to the roles listed in `allowed_roles`.

    Anonymous users go to the login page; logged-in users with the wrong role
    get a 403 (never a redirect that would hint at hidden pages).
    """

    allowed_roles: tuple = ()
    raise_exception = False

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role not in self.allowed_roles:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


# Role groups used by the Secretary operations pages.
def office_roles():
    from .models import Role

    return (Role.SECRETARY, Role.MANAGER)


def is_office(user):
    """Secretary or Manager: the people who run clients, money, payroll and stock."""
    return user.is_authenticated and user.role in office_roles()
