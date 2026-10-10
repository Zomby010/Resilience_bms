from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models


class Role(models.TextChoices):
    MANAGER = "manager", "Manager"
    SUPERVISOR = "supervisor", "Supervisor"
    STAFF = "staff", "Staff"
    SECRETARY = "secretary", "Secretary"


# The words people read. "Staff" is a guard everywhere in the interface (the stored value stays "staff").
ROLE_LABELS = {"manager": "Manager", "supervisor": "Supervisor", "staff": "Guard", "secretary": "Secretary"}
ROLE_CHOICES = [(value, ROLE_LABELS[value]) for value in Role.values]


class RoleUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # A superuser created from the command line is the company's Manager.
        extra_fields.setdefault("role", Role.MANAGER)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """One account per person. `role` drives everything they can see and do."""

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    phone = models.CharField(max_length=30, blank=True)
    # Only staff have a supervisor; it scopes which reports that supervisor sees.
    supervisor = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="team_members",
        limit_choices_to={"role": Role.SUPERVISOR},
    )

    objects = RoleUserManager()

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def __str__(self):
        return self.get_full_name() or self.username

    def get_role_display(self):
        return ROLE_LABELS.get(self.role, self.role)

    def clean(self):
        super().clean()
        if self.supervisor_id:
            if self.role != Role.STAFF:
                raise ValidationError({"supervisor": "Only guards are assigned to a supervisor."})
            if self.supervisor.role != Role.SUPERVISOR:
                raise ValidationError({"supervisor": "The selected user is not a supervisor."})

    @property
    def is_manager(self):
        return self.role == Role.MANAGER

    @property
    def is_supervisor(self):
        return self.role == Role.SUPERVISOR

    @property
    def is_staff_member(self):
        # `is_staff` is Django's admin-site flag, so this is named differently.
        return self.role == Role.STAFF

    @property
    def is_secretary(self):
        return self.role == Role.SECRETARY
