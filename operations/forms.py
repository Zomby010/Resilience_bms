from django import forms
from django.utils import timezone

from accounts.models import Role, User
from core.forms import MoreDetailsMixin
from core.services.files import AttachmentField
from tracking.models import Site

from . import services
from .models import OBEntry, SiteVisit

WHEN = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class SiteDetailsForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ["name", "address", "supervisor", "guards_needed", "instructions", "emergency_contacts", "is_active"]
        widgets = {
            "instructions": forms.Textarea(attrs={"rows": 5}),
            "emergency_contacts": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supervisor"].queryset = User.objects.filter(role=Role.SUPERVISOR, is_active=True)
        self.fields["is_active"].label = "Site is active"


class OBForm(forms.Form):
    site = forms.ModelChoiceField(queryset=Site.objects.none(), empty_label=None)
    kind = forms.ChoiceField(label="What kind of entry?", choices=[
        c for c in OBEntry.Kind.choices if c[0] not in (OBEntry.Kind.SITE_VISIT, OBEntry.Kind.INCIDENT)
    ])
    occurred_at = forms.DateTimeField(label="When did it happen?", widget=WHEN, input_formats=["%Y-%m-%dT%H:%M"])
    text = forms.CharField(label="What happened?", widget=forms.Textarea(attrs={"rows": 4}), max_length=4000)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site"].queryset = services.sites_for(user).filter(is_active=True)
        self.fields["occurred_at"].initial = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        site = services.my_site(user)
        if site:
            self.fields["site"].initial = site.pk


class VisitForm(MoreDetailsMixin, forms.Form):
    more_fields = ("remarks", "photo")
    site = forms.ModelChoiceField(queryset=Site.objects.none(), empty_label=None)
    visited_at = forms.DateTimeField(label="Time of visit", widget=WHEN, input_formats=["%Y-%m-%dT%H:%M"])
    checks = forms.MultipleChoiceField(label="Checks done (tick what was fine)", choices=SiteVisit.CHECKS,
                                       widget=forms.CheckboxSelectMultiple, required=False)
    guards_seen = forms.ModelMultipleChoiceField(label="Guards seen", queryset=User.objects.none(),
                                                 widget=forms.CheckboxSelectMultiple, required=False)
    welfare_check_done = forms.BooleanField(label="Welfare check done (asked the guards how they are, food, water, health)",
                                            required=False)
    remarks = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    photo = AttachmentField(label="Photo (optional)")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        sites = services.sites_for(user).filter(is_active=True)
        self.fields["site"].queryset = sites
        self.fields["visited_at"].initial = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        guards = User.objects.filter(is_active=True, tracking__site__in=sites)
        if user.role == Role.SUPERVISOR:
            guards = guards.filter(supervisor=user) | User.objects.filter(is_active=True, tracking__site__supervisor=user)
        self.fields["guards_seen"].queryset = guards.distinct().order_by("first_name", "last_name")
