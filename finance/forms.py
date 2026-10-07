from django import forms

from core.services.files import AttachmentField

from .models import Expense, ExpenseCategory


class ExpenseForm(forms.ModelForm):
    receipt = AttachmentField(label="Receipt photo or PDF (optional)")

    class Meta:
        model = Expense
        fields = ["date", "category", "description", "amount", "reference"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class CategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ["name"]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if ExpenseCategory.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError("That category already exists.")
        return name
