from datetime import timedelta

from django import forms
from django.utils import timezone

from core.services.files import AttachmentField
from tracking.models import Site

from .models import Incident
from .services import MAX_PHOTOS


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class PhotosField(AttachmentField):
    """Up to MAX_PHOTOS files, each checked like any other attachment."""

    widget = MultipleFileInput

    def clean(self, data, initial=None):
        files = [f for f in (data if isinstance(data, (list, tuple)) else [data]) if f]
        if len(files) > MAX_PHOTOS:
            raise forms.ValidationError(f"You can add up to {MAX_PHOTOS} photos.")
        return [super(PhotosField, self).clean(f, initial) for f in files]


class IncidentForm(forms.ModelForm):
    photos = PhotosField(label="Photos (optional)", help_text=f"Up to {MAX_PHOTOS} photos. JPG, PNG or PDF, up to 4 MB each.")

    class Meta:
        model = Incident
        fields = [
            "site", "occurred_at", "kind", "severity", "what_happened", "who_involved", "action_taken",
            "police_reported", "police_ob_number", "client_told",
        ]
        labels = {
            "site": "Where did it happen?",
            "occurred_at": "When did it happen?",
            "kind": "What kind of incident?",
            "severity": "How serious is it?",
            "what_happened": "What happened?",
            "who_involved": "Who was involved? (optional)",
            "action_taken": "What did you do? (optional)",
            "police_reported": "The police were told",
            "police_ob_number": "Police OB number",
            "client_told": "The client was told",
        }
        help_texts = {
            "police_ob_number": "Needed if the police were told.",
            "who_involved": "Names, or what the people looked like.",
        }
        widgets = {
            "occurred_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "what_happened": forms.Textarea(attrs={"rows": 4}),
            "who_involved": forms.Textarea(attrs={"rows": 2}),
            "action_taken": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site"].queryset = Site.objects.filter(is_active=True)
        self.fields["site"].empty_label = "Choose the site"
        self.fields["kind"].choices = [("", "Choose the type")] + list(Incident.Kind.choices)
        self.fields["severity"].choices = [("", "Choose")] + list(Incident.Severity.choices)
        self.fields["photos"].widget.attrs["accept"] = "image/jpeg,image/png,application/pdf"

    def clean_occurred_at(self):
        when = self.cleaned_data["occurred_at"]
        if when and when > timezone.now() + timedelta(minutes=10):
            raise forms.ValidationError("This time is in the future. Check the date and time.")
        return when
