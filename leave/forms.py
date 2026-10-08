from django import forms
from django.utils import timezone

from core.services.files import AttachmentField

from . import services
from .models import LeaveType

DATE = forms.DateInput(attrs={"type": "date"})


class PersonChoiceMixin:
    """Adds a 'Who is it for?' choice for people who may record for others."""

    def add_person(self, user):
        people = services.people_for(user)
        if people.count() > 1:
            self.fields = {"person": forms.ModelChoiceField(
                queryset=people.order_by("first_name", "last_name"), initial=user.pk, label="Who is it for?",
            ), **self.fields}


class LeaveRequestForm(PersonChoiceMixin, forms.Form):
    leave_type = forms.ModelChoiceField(queryset=LeaveType.objects.none(), label="Type of leave", empty_label=None)
    start_date = forms.DateField(label="First day off", widget=DATE)
    end_date = forms.DateField(label="Last day off", widget=DATE)
    reason = forms.CharField(label="Reason (optional)", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["leave_type"].queryset = LeaveType.objects.filter(is_active=True).exclude(code=services.SICK_CODE)
        self.add_person(user)

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "The last day off cannot be before the first day off.")
        return cleaned


class SickForm(PersonChoiceMixin, forms.Form):
    first_day = forms.DateField(label="First day off sick", widget=DATE)
    last_day = forms.DateField(label="Expected last day off sick", widget=DATE,
                               help_text="You can change this later if it is different.")
    comment = forms.CharField(label="Note (optional)", required=False, widget=forms.Textarea(attrs={"rows": 2}),
                              help_text="Do not write what the illness is. The sick sheet is enough.")
    sheet = AttachmentField(label="Sick sheet (optional now, needed later)",
                            help_text="A photo or PDF of the sick sheet. Only you, the Secretary and the Manager can open it.")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["first_day"].initial = today
        self.fields["last_day"].initial = today
        self.add_person(user)
        self.user = user
        if user.role not in services.OFFICE and "person" in self.fields:
            # Supervisors record sickness for their team but cannot attach someone else's medical papers.
            self.fields["sheet"].help_text = "Only for your own sick sheet. A team member uploads their own, or gives it to the office."

    def clean(self):
        cleaned = super().clean()
        first, last = cleaned.get("first_day"), cleaned.get("last_day")
        if first and last and last < first:
            self.add_error("last_day", "The last day cannot be before the first day.")
        person = cleaned.get("person")
        if cleaned.get("sheet") and person and person.pk != self.user.pk and self.user.role not in services.OFFICE:
            self.add_error("sheet", "Only the person themself or the office can upload a sick sheet.")
        return cleaned


class SheetForm(forms.Form):
    sheet = AttachmentField(required=True, label="Sick sheet", help_text="A photo or PDF, up to 4 MB.")


class LastDayForm(forms.Form):
    last_day = forms.DateField(label="Last day off sick", widget=DATE)


class AllowanceForm(forms.Form):
    """One number per leave type for one person and year."""

    def __init__(self, *args, person, year, **kwargs):
        super().__init__(*args, **kwargs)
        for lt in LeaveType.objects.filter(is_active=True):
            self.fields[f"type_{lt.pk}"] = forms.DecimalField(
                label=f"{lt.name} ({lt.get_counting_display().lower()})", min_value=0, max_value=366,
                decimal_places=1, initial=services.allowed_days(person, lt, year),
                help_text=f"Usual: {lt.days_per_year} days." if lt.days_per_year else "No fixed number usually.",
            )

    def values(self):
        types = {f"type_{lt.pk}": lt for lt in LeaveType.objects.filter(is_active=True)}
        return [(types[k], v) for k, v in self.cleaned_data.items() if k in types]
