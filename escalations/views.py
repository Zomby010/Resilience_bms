from django import forms
from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect
from django.views.generic import DetailView, FormView, ListView

from accounts.models import Role
from core.access import can_view
from core.filters import apply_dates
from core.mixins import ActionView, CsvExportMixin, FilterContextMixin, OfficeRequiredMixin, csv_time
from core.workflow import TransitionError

from . import services
from .models import Escalation


class EscalationForm(forms.Form):
    subject = forms.CharField(max_length=200)
    note = forms.CharField(label="What do you need from the Manager?", widget=forms.Textarea(attrs={"rows": 4}))


class EscalationCreateView(OfficeRequiredMixin, FormView):
    allowed_roles = (Role.SECRETARY,)
    form_class = EscalationForm
    template_name = "escalations/escalation_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.kind = request.GET.get("type") or Escalation.Kind.OTHER
        self.record = None
        if request.user.is_authenticated and request.user.role in self.allowed_roles and self.kind != Escalation.Kind.OTHER:
            self.record = services.find_record(self.kind, request.GET.get("id"))
            if self.record is None or not can_view(request.user, self.record):
                raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        if self.record is not None:
            existing = services.open_escalation(self.record)
            if existing:
                messages.info(request, "This has already been sent to the Manager.")
                return redirect("escalations:detail", pk=existing.pk)
        return super().get(request, *args, **kwargs)

    def get_initial(self):
        return {"subject": str(self.record)[:200] if self.record is not None else ""}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "record": self.record, "kind": self.kind,
                "kind_label": Escalation.Kind(self.kind).label if self.kind in Escalation.Kind.values else "Other"}

    def form_valid(self, form):
        if self.kind not in Escalation.Kind.values:
            raise Http404
        try:
            esc = services.raise_escalation(self.kind, self.record, form.cleaned_data["subject"], form.cleaned_data["note"], self.request.user)
        except TransitionError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Sent to the Manager. You will be notified when they reply.")
        return redirect("escalations:detail", pk=esc.pk)


class EscalationListView(OfficeRequiredMixin, CsvExportMixin, FilterContextMixin, ListView):
    template_name = "escalations/escalation_list.html"
    context_object_name = "escalations"
    paginate_by = 30
    csv_filename = "sent-to-manager.csv"
    csv_header = ["Sent", "Subject", "Type", "Status", "Sent by", "Note", "Answered by", "Answered", "Answer"]

    def get_queryset(self):
        qs = Escalation.objects.select_related("raised_by", "resolved_by")
        g = self.request.GET
        status = g.get("status", "open")
        if status == "open":
            qs = qs.exclude(status=Escalation.Status.RESOLVED)
        elif status in Escalation.Status.values:
            qs = qs.filter(status=status)
        if g.get("kind") in Escalation.Kind.values:
            qs = qs.filter(kind=g["kind"])
        q = (g.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(subject__icontains=q) | Q(note__icontains=q) | Q(resolution_note__icontains=q))
        return apply_dates(qs, g, "raised_at")

    def csv_rows(self, qs):
        for e in qs:
            yield [csv_time(e.raised_at), e.subject, e.get_kind_display(), e.get_status_display(), e.raised_by, e.note,
                   e.resolved_by or "", csv_time(e.resolved_at), e.resolution_note]

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "statuses": Escalation.Status.choices,
                "kinds": Escalation.Kind.choices, "status": self.request.GET.get("status", "open")}


class EscalationDetailView(OfficeRequiredMixin, DetailView):
    template_name = "escalations/escalation_detail.html"
    context_object_name = "esc"

    def get_queryset(self):
        return Escalation.objects.select_related("raised_by", "resolved_by", "content_type")

    def get_object(self, queryset=None):
        esc = super().get_object(queryset)
        services.manager_seen(esc, self.request.user)
        return esc

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        esc = self.object
        record = esc.record
        ctx.update(record=record, replies=esc.replies.select_related("author"))
        if record is not None:
            ctx["record_url"] = record.get_absolute_url()
            label = record._meta.label_lower
            if label == "clients.issue":
                ctx["record_notes"] = record.notes.select_related("author")[:10]
                ctx["record_client"] = record.client
            elif label == "clients.feedback":
                ctx["record_client"] = record.client
            if "record_client" in ctx:
                ctx["client_messages"] = ctx["record_client"].messages.all()[:5]
            from core.services.files import attachments_for

            ctx["record_files"] = attachments_for(record)
        return ctx


class EscalationAction(OfficeRequiredMixin, ActionView):
    model = Escalation
    allowed_roles = (Role.MANAGER,)
    action = None

    def act(self, esc):
        text = self.request.POST.get("body", "")
        getattr(services, self.action)(esc, self.request.user, text)
        return {"reply": "Reply sent.", "send_back": "Sent back to the Secretary.", "resolve": "Marked as resolved."}[self.action]


class ReplyView(EscalationAction):
    allowed_roles = (Role.MANAGER, Role.SECRETARY)
    action = "reply"
