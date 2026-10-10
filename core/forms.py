from django import forms

from .models import CompanySettings
from .services.files import detect_type


class CompanySettingsForm(forms.ModelForm):
    class Meta:
        model = CompanySettings
        fields = [
            "company_name", "address", "phone", "email", "kra_pin", "logo", "payment_instructions",
            "vat_registered", "vat_rate", "invoice_due_days", "expense_approval_enabled", "expense_approval_limit",
            "late_after_minutes", "sick_note_due_days", "sick_note_keep_days",
        ]
        widgets = {"address": forms.Textarea(attrs={"rows": 3}), "payment_instructions": forms.Textarea(attrs={"rows": 3})}
        help_texts = {
            "vat_registered": "Tick only if the company is registered for VAT. Invoices can then add VAT.",
            "invoice_due_days": "How many days clients have to pay an invoice, by default.",
            "expense_approval_enabled": "When ticked, expenses above the limit below wait for your approval.",
            "expense_approval_limit": "Amount in KES. Expenses above this need Manager approval.",
        }

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and hasattr(logo, "size") and getattr(logo, "content_type", None) is not None:
            if detect_type(logo) not in ("image/png", "image/jpeg"):
                raise forms.ValidationError("The logo must be a PNG or JPG picture.")
            if logo.size > 2 * 1024 * 1024:
                raise forms.ValidationError("The logo can be up to 2 MB.")
        return logo

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("expense_approval_enabled") and not cleaned.get("expense_approval_limit"):
            self.add_error("expense_approval_limit", "Enter the amount above which expenses need your approval.")
        return cleaned


class MoreDetailsMixin:
    """Optional fields listed in `more_fields` go under "Add more details ▸" (partials/form.html); it opens by
    itself when one of them was filled in or has an error."""

    more_fields = ()

    @property
    def more_open(self):
        if not self.is_bound:
            return False
        return any(self.errors.get(n) or self.data.get(self.add_prefix(n)) or self.files.get(self.add_prefix(n))
                   for n in self.more_fields)
