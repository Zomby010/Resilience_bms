from django import forms
from django.utils import timezone

from accounts.models import Role, User

from .models import PayProfile, PayrollLine


class PayProfileForm(forms.ModelForm):
    class Meta:
        model = PayProfile
        fields = ["basic_salary", "regular_allowances", "allowance_note", "payment_method", "mpesa_number",
                  "bank_name", "bank_account", "is_active"]
        labels = {
            "basic_salary": "Basic salary per month (KES)", "regular_allowances": "Regular allowances per month (KES)",
            "is_active": "Include this person in new payrolls",
        }

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("payment_method")
        if method == "mpesa" and not cleaned.get("mpesa_number"):
            self.add_error("mpesa_number", "Enter the M-Pesa number.")
        if method == "bank" and not (cleaned.get("bank_name") and cleaned.get("bank_account")):
            self.add_error("bank_account", "Enter the bank name and account number.")
        return cleaned


class NewRunForm(forms.Form):
    period = forms.DateField(
        label="Month", widget=forms.DateInput(attrs={"type": "month"}, format="%Y-%m"),
        input_formats=["%Y-%m", "%Y-%m-%d"], help_text="The month this payroll is for.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("period", timezone.localdate().replace(day=1))


class LineForm(forms.ModelForm):
    class Meta:
        model = PayrollLine
        fields = ["basic", "allowances", "overtime", "bonus", "paye", "shif", "nssf", "housing_levy", "advance",
                  "other_deductions", "other_note"]
        labels = {"other_note": "Note about other deductions"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "other_note":
                field.widget.attrs.update(step="0.01", min="0")


class AddPersonForm(forms.Form):
    person = forms.ModelChoiceField(queryset=User.objects.none())

    def __init__(self, *args, run=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = User.objects.filter(is_active=True).exclude(role=Role.MANAGER)
        if run is not None:
            qs = qs.exclude(pk__in=run.lines.values("employee_id"))
        self.fields["person"].queryset = qs
        self.fields["person"].empty_label = "Choose a person"
