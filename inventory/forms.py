from datetime import timedelta

from django import forms
from django.utils import timezone

from clients.forms import DateInput

from .models import Category, Item
from .services import ADJUSTMENTS, MAX_REQUEST_QTY


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ["name", "category", "description", "condition_note", "storage_location", "min_stock", "returnable"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
        help_texts = {"min_stock": "You are told when the number in the store falls to this level. 0 = never warn."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(is_active=True)


class NewItemForm(ItemForm):
    opening_qty = forms.IntegerField(label="How many are in the store now?", min_value=0, initial=0)


class AdjustForm(forms.Form):
    action = forms.ChoiceField(choices=[(k, v[2]) for k, v in ADJUSTMENTS.items()], label="What happened?")
    qty = forms.IntegerField(min_value=1, label="How many?")
    reason = forms.CharField(max_length=200, label="Reason", widget=forms.TextInput(attrs={"placeholder": "e.g. New delivery from supplier"}))


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name"]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Category.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError("That category already exists.")
        return name


class RequestForm(forms.Form):
    qty = forms.IntegerField(min_value=1, max_value=MAX_REQUEST_QTY, initial=1, label="How many do you need?")
    reason = forms.CharField(label="Why do you need it?", widget=forms.Textarea(attrs={"rows": 3}),
                             help_text="For example: My torch stopped working.")


class ApproveForm(forms.Form):
    qty = forms.IntegerField(min_value=1, label="How many to give")
    expected_return_date = forms.DateField(required=False, widget=DateInput(), label="Must be returned by")
    hand_over_now = forms.BooleanField(required=False, label="The person is here: hand it over now")

    def __init__(self, *args, req=None, **kwargs):
        super().__init__(*args, **kwargs)
        if req is not None:
            self.fields["qty"].max_value = req.qty_requested
            self.fields["qty"].initial = req.qty_requested
            if not req.item.returnable:
                del self.fields["expected_return_date"]
            else:
                self.fields["expected_return_date"].required = True
                self.fields["expected_return_date"].initial = timezone.localdate() + timedelta(days=30)


class ReturnForm(forms.Form):
    good = forms.IntegerField(min_value=0, label="Back in good condition")
    damaged = forms.IntegerField(min_value=0, initial=0, label="Back but damaged")
    lost = forms.IntegerField(min_value=0, initial=0, label="Not returned (lost)")
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Notes (needed if damaged or lost)")
