from django import forms
from django.db.models import Q

from accounts.models import Role, User
from core.services.files import AttachmentField
from tracking.models import Site

from .models import Client, Feedback, Issue, Message


def supervisor_choices():
    return User.objects.filter(role=Role.SUPERVISOR, is_active=True)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%d")
        super().__init__(**kwargs)


class ClientForm(forms.ModelForm):
    confirm_duplicate = forms.BooleanField(
        required=False, label="Yes, this is a different client with a similar name, phone or email",
    )

    class Meta:
        model = Client
        fields = [
            "name", "contact_person", "phone", "email", "physical_address", "postal_address", "area",
            "service_description", "contract_start", "contract_end", "monthly_charge", "kra_pin", "supervisor", "notes",
        ]
        widgets = {
            "contract_start": DateInput(), "contract_end": DateInput(),
            "service_description": forms.Textarea(attrs={"rows": 3}), "notes": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {"phone": "For example 0712345678.", "monthly_charge": "Amount in KES (optional)."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supervisor"].queryset = supervisor_choices()
        self.fields["supervisor"].empty_label = "No supervisor yet"
        if self.instance.pk:
            # The supervisor is changed on its own page so the history is kept.
            del self.fields["supervisor"]
        self.duplicates = []

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("phone") and not cleaned.get("email"):
            raise forms.ValidationError("Enter at least a phone number or an email address.")
        start, end = cleaned.get("contract_start"), cleaned.get("contract_end")
        if start and end and end < start:
            self.add_error("contract_end", "The contract end date cannot be before the start date.")
        if cleaned.get("name"):
            from .services import possible_duplicates

            self.duplicates = list(possible_duplicates(
                cleaned["name"], cleaned.get("email", ""), cleaned.get("phone", ""), exclude_pk=self.instance.pk
            )[:5])
            if self.duplicates and not cleaned.get("confirm_duplicate"):
                raise forms.ValidationError(
                    "A client with the same name, phone or email already exists (listed below). "
                    "If this really is a different client, tick the box at the bottom and save again."
                )
        return cleaned


class AssignSupervisorForm(forms.Form):
    supervisor = forms.ModelChoiceField(queryset=User.objects.none(), required=False, empty_label="No supervisor")
    move_open_issues = forms.BooleanField(
        required=False, initial=True, label="Also move this client's open issues to the new supervisor",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supervisor"].queryset = supervisor_choices()


class ClientSitesForm(forms.Form):
    sites = forms.ModelMultipleChoiceField(
        queryset=Site.objects.none(), required=False, widget=forms.CheckboxSelectMultiple,
        help_text="Tick the GPS work sites that belong to this client. A site can belong to one client only.",
    )

    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Sites that are free, or already linked to this client.
        self.fields["sites"].queryset = Site.objects.filter(
            Q(client_link__isnull=True) | Q(client_link__client=client)
        ).order_by("name")


class IssueForm(forms.ModelForm):
    attachment = AttachmentField()

    class Meta:
        model = Issue
        fields = ["client", "subject", "description", "priority"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}
        help_texts = {"client": "The issue goes automatically to this client's supervisor."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.filter(is_active=True)


class IssueNoteForm(forms.Form):
    body = forms.CharField(label="Note", widget=forms.Textarea(attrs={"rows": 3}), required=False)
    attachment = AttachmentField()


class IssueStatusForm(forms.Form):
    to = forms.ChoiceField(choices=Issue.Status.choices)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class AssignIssueForm(forms.Form):
    supervisor = forms.ModelChoiceField(queryset=User.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supervisor"].queryset = supervisor_choices()


class MessageForm(forms.ModelForm):
    attachment = AttachmentField()

    class Meta:
        model = Message
        fields = ["subject", "body", "priority"]
        widgets = {"body": forms.Textarea(attrs={"rows": 7})}
        help_texts = {"body": "Write it as you would say it. A greeting and the company signature are added for you."}


class FeedbackForm(forms.ModelForm):
    class Meta:
        model = Feedback
        fields = ["kind", "channel", "subject", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 5})}


class FeedbackResponseForm(forms.Form):
    response = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), label="Your response")
    channel = forms.ChoiceField(
        choices=Feedback.Channel.choices, initial=Feedback.Channel.EMAIL, label="How are you responding?",
        help_text="Email sends it now. For phone, WhatsApp or in person, this just records what you told them.",
    )
