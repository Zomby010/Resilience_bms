from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError

from .models import Role, User


class ProfileForm(forms.ModelForm):
    """What any user may change about themselves ("Update Information")."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone"]


class BaseUserAdminForm(forms.ModelForm):
    """Shared by the Manager's create/edit user screens."""

    password1 = forms.CharField(
        label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}), required=False
    )
    password2 = forms.CharField(
        label="Confirm password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}), required=False
    )
    password_required = True

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone", "role", "supervisor", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supervisor"].queryset = User.objects.filter(role=Role.SUPERVISOR, is_active=True)
        self.fields["supervisor"].help_text = "Only for staff: the supervisor who reviews their reports."
        self.fields["email"].required = False

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if self.password_required and not p1:
            self.add_error("password1", "A password is required.")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "The two passwords do not match.")
            elif p1:
                try:
                    password_validation.validate_password(p1, self.instance)
                except ValidationError as exc:
                    self.add_error("password1", exc)
        role, supervisor = cleaned.get("role"), cleaned.get("supervisor")
        if supervisor and role != Role.STAFF:
            self.add_error("supervisor", "Only staff members are assigned to a supervisor.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserCreateForm(BaseUserAdminForm):
    password_required = True


class UserUpdateForm(BaseUserAdminForm):
    password_required = False
    password1 = forms.CharField(
        label="New password (leave blank to keep current)",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        required=False,
    )

    def __init__(self, *args, editing_self=False, **kwargs):
        super().__init__(*args, **kwargs)
        if editing_self:
            # A Manager must not lock themselves out or demote themselves.
            for name in ("role", "is_active", "supervisor"):
                self.fields[name].disabled = True
