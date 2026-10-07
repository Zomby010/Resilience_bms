from django import forms

from .models import Site, TrackingProfile, WorkHours


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ["name", "latitude", "longitude", "radius_m", "is_active"]
        labels = {"name": "Site name", "is_active": "Site is in use"}
        help_texts = {
            "latitude": "Click the map to fill this in, or type it (for example -0.091702).",
            "longitude": "For example 34.767956.",
        }
        widgets = {
            "latitude": forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off"}),
            "longitude": forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off"}),
        }


class PersonForm(forms.ModelForm):
    class Meta:
        model = TrackingProfile
        fields = ["site", "own_hours"]
        labels = {"site": "Work site", "own_hours": "This person has their own working hours"}
        help_texts = {
            "site": "Their location is compared with this site.",
            "own_hours": "Leave unticked to use the site's working hours.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = self.instance.site_id
        self.fields["site"].queryset = Site.objects.filter(is_active=True) | Site.objects.filter(pk=current)
        self.fields["site"].empty_label = "No site"


class HoursForm(forms.Form):
    """A week of working hours: a tick box and start/end time per day."""

    def __init__(self, *args, rows=(), **kwargs):
        super().__init__(*args, **kwargs)
        existing = {r.weekday: r for r in rows}
        self.days = []
        for value, label in WorkHours.Weekday.choices:
            row = existing.get(value)
            on = forms.BooleanField(required=False, label=label, initial=row is not None)
            start = forms.TimeField(
                required=False, label=f"{label} start", initial=row.start if row else None,
                widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            )
            end = forms.TimeField(
                required=False, label=f"{label} end", initial=row.end if row else None,
                widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            )
            self.fields[f"d{value}_on"], self.fields[f"d{value}_start"], self.fields[f"d{value}_end"] = on, start, end
            self.days.append((value, label))

    def day_rows(self):
        """For the template: (label, on-field, start-field, end-field) per day."""
        return [(label, self[f"d{v}_on"], self[f"d{v}_start"], self[f"d{v}_end"]) for v, label in self.days]

    def clean(self):
        data = super().clean()
        for value, label in self.days:
            if not data.get(f"d{value}_on"):
                continue
            start, end = data.get(f"d{value}_start"), data.get(f"d{value}_end")
            if not start or not end:
                self.add_error(f"d{value}_start", f"Enter a start and end time for {label}, or untick it.")
            elif start == end:
                self.add_error(f"d{value}_end", f"{label}: start and end cannot be the same time.")
        return data

    def save(self, **owner):
        """Replace the week for `owner` (site=... or user=...)."""
        WorkHours.objects.filter(**owner).delete()
        WorkHours.objects.bulk_create([
            WorkHours(weekday=v, start=self.cleaned_data[f"d{v}_start"], end=self.cleaned_data[f"d{v}_end"], **owner)
            for v, _ in self.days
            if self.cleaned_data.get(f"d{v}_on")
        ])

    def summary(self):
        parts = []
        for v, label in self.days:
            if self.cleaned_data.get(f"d{v}_on"):
                parts.append(f"{label[:3]} {self.cleaned_data[f'd{v}_start']:%H:%M}-{self.cleaned_data[f'd{v}_end']:%H:%M}")
        return ", ".join(parts) or "no working days"


class HistoryFilterForm(forms.Form):
    person = forms.ModelChoiceField(queryset=None, required=False, empty_label="Everyone")
    site = forms.ModelChoiceField(queryset=Site.objects.all(), required=False, empty_label="All sites")
    date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    status = forms.ChoiceField(required=False)

    def __init__(self, *args, people=None, statuses=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["person"].queryset = people
        self.fields["status"].choices = [("", "Any status")] + list(statuses)
