from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from clients.forms import DateInput
from clients.models import Client
from core.models import CompanySettings

from .models import Invoice, InvoiceLine, Payment


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ["client", "invoice_date", "due_date", "vat_enabled", "notes", "payment_instructions"]
        widgets = {
            "invoice_date": DateInput(), "due_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 2}), "payment_instructions": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"vat_enabled": "Add VAT"}
        help_texts = {"payment_instructions": "Leave empty to use the company's usual payment details."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = CompanySettings.load()
        qs = Client.objects.filter(is_active=True)
        if self.instance.pk:
            qs = qs | Client.objects.filter(pk=self.instance.client_id)
        self.fields["client"].queryset = qs.distinct()
        if not self.instance.pk:
            today = timezone.localdate()
            self.initial.setdefault("invoice_date", today)
            self.initial.setdefault("due_date", today + timedelta(days=company.invoice_due_days))
            self.initial.setdefault("payment_instructions", company.payment_instructions)
        if company.vat_registered:
            self.fields["vat_enabled"].help_text = f"Adds VAT at {company.vat_rate.normalize():f}%."
        else:
            del self.fields["vat_enabled"]

    def clean(self):
        cleaned = super().clean()
        d, due = cleaned.get("invoice_date"), cleaned.get("due_date")
        if d and due and due < d:
            self.add_error("due_date", "The due date cannot be before the invoice date.")
        return cleaned


class LineForm(forms.ModelForm):
    class Meta:
        model = InvoiceLine
        fields = ["description", "quantity", "unit_price"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "unit_price": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }
        labels = {"unit_price": "Unit price (KES)"}


class BaseLineFormSet(forms.BaseModelFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE") and f.cleaned_data.get("description")]
        if not kept:
            raise forms.ValidationError("Add at least one line to the invoice.")

    def lines(self):
        out = []
        for f in self.forms:
            d = f.cleaned_data
            if d and not d.get("DELETE") and d.get("description"):
                out.append(InvoiceLine(description=d["description"], quantity=d["quantity"], unit_price=d["unit_price"]))
        return out


LineFormSet = forms.modelformset_factory(
    InvoiceLine, form=LineForm, formset=BaseLineFormSet, extra=1, can_delete=True, max_num=50, validate_max=True,
)


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["paid_on", "amount", "method", "reference"]
        widgets = {"paid_on": DateInput(), "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"})}
        labels = {"amount": "Amount received (KES)", "reference": "Reference (M-Pesa code, cheque no.)"}

    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice = invoice
        self.initial.setdefault("paid_on", timezone.localdate())
        if invoice is not None:
            self.initial.setdefault("amount", invoice.balance)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if self.invoice is not None and amount > self.invoice.balance:
            raise forms.ValidationError(f"That is more than the balance of KES {self.invoice.balance:,.2f}.")
        if amount <= Decimal("0"):
            raise forms.ValidationError("The amount must be more than zero.")
        return amount


class CancelForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))
