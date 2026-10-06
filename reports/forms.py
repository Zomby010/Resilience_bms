from django import forms

from .models import Reply, Report


class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ["title", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 8})}
        labels = {"body": "Details"}


class ReplyForm(forms.ModelForm):
    complete = forms.BooleanField(required=False, initial=True, label="Mark this report as completed")

    class Meta:
        model = Reply
        fields = ["body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 4})}
        labels = {"body": "Your reply / feedback"}

    def __init__(self, *args, can_complete=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not can_complete:
            del self.fields["complete"]
