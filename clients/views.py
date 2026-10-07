from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.utils.dateparse import parse_date
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from accounts.models import Role
from accounts.permissions import RoleRequiredMixin
from core.mixins import OFFICE, ActionView, FilterContextMixin, OfficeRequiredMixin
from core.models import AuditLog
from core.services import audit
from core.services.files import attachments_for, save_attachment
from core.workflow import TransitionError

from . import services
from .forms import (
    AssignIssueForm, AssignSupervisorForm, ClientForm, ClientSitesForm, FeedbackForm, FeedbackResponseForm,
    IssueForm, IssueNoteForm, IssueStatusForm, MessageForm,
)
from .models import Client, Feedback, Issue, Message


# --- clients ------------------------------------------------------------------

class ClientListView(OfficeRequiredMixin, FilterContextMixin, ListView):
    template_name = "clients/client_list.html"
    context_object_name = "clients"
    paginate_by = 25

    def get_queryset(self):
        qs = Client.objects.select_related("supervisor").annotate(
            open_issues=Count("issues", filter=Q(issues__status__in=services.OPEN_ISSUE_STATUSES))
        ).order_by("name")
        g = self.request.GET
        q = (g.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(contact_person__icontains=q) | Q(phone__icontains=q)
                           | Q(email__icontains=q) | Q(area__icontains=q))
        status = g.get("status", "active")
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        sup = g.get("supervisor", "")
        if sup == "none":
            qs = qs.filter(supervisor__isnull=True)
        elif sup.isdigit():
            qs = qs.filter(supervisor_id=int(sup))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["supervisors"] = services.active_supervisors()
        ctx["status"] = self.request.GET.get("status", "active")
        return ctx


class ClientCreateView(OfficeRequiredMixin, CreateView):
    form_class = ClientForm
    template_name = "clients/client_form.html"

    def form_valid(self, form):
        client = services.create_client(form.save(commit=False), self.request.user)
        messages.success(self.request, f"{client.name} was added.")
        return redirect(client)


class ClientUpdateView(OfficeRequiredMixin, UpdateView):
    model = Client
    form_class = ClientForm
    template_name = "clients/client_form.html"

    def form_valid(self, form):
        before = audit.snapshot(Client.objects.get(pk=self.object.pk), services.CLIENT_FIELDS)
        client = services.update_client(form.save(commit=False), self.request.user, before)
        messages.success(self.request, "Client details saved.")
        return redirect(client)


class ClientDetailView(RoleRequiredMixin, DetailView):
    """Office sees every tab. A supervisor sees only their own clients, overview and issues."""

    allowed_roles = OFFICE + (Role.SUPERVISOR,)
    template_name = "clients/client_detail.html"
    context_object_name = "client"
    OFFICE_TABS = ["overview", "issues", "messages", "feedback", "invoices", "history"]
    SUPERVISOR_TABS = ["overview", "issues"]

    def get_queryset(self):
        return services.clients_visible_to(self.request.user).select_related("supervisor")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.object
        office = self.request.user.role in OFFICE
        tabs = self.OFFICE_TABS if office else self.SUPERVISOR_TABS
        tab = self.request.GET.get("tab", "overview")
        if tab not in tabs:
            tab = "overview"
        ctx.update(tab=tab, tabs=tabs, office=office)
        ctx["open_issues"] = c.issues.filter(status__in=services.OPEN_ISSUE_STATUSES).count()
        if tab == "overview":
            ctx["sites"] = c.site_links.select_related("site")
            ctx["assignments"] = c.assignments.select_related("supervisor", "assigned_by")[:10]
        elif tab == "issues":
            qs = c.issues.select_related("supervisor")
            if not office:
                qs = qs.filter(supervisor=self.request.user)
            ctx["issues"] = qs
        elif tab == "messages":
            ctx["client_messages"] = c.messages.select_related("created_by", "sent_by")
        elif tab == "feedback":
            ctx["feedback"] = c.feedback.select_related("recorded_by")
        elif tab == "invoices":
            ctx["invoices"] = c.invoices.all()
        elif tab == "history":
            ctx["history"] = AuditLog.objects.filter(
                entity_type="clients.client", entity_id=str(c.pk), confidential=False
            ).select_related("actor")[:100]
        return ctx


class ClientActiveView(OfficeRequiredMixin, ActionView):
    model = Client
    active = True

    def act(self, client):
        services.set_client_active(client, self.active, self.request.user)
        return f"{client.name} is now {'active' if self.active else 'inactive'}."


class ClientSupervisorView(OfficeRequiredMixin, FormView):
    form_class = AssignSupervisorForm
    template_name = "clients/client_supervisor.html"

    def dispatch(self, request, *args, **kwargs):
        self.client = get_object_or_404(Client, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {"supervisor": self.client.supervisor, "move_open_issues": True}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["client"] = self.client
        ctx["assignments"] = self.client.assignments.select_related("supervisor", "assigned_by")
        ctx["open_issues"] = self.client.issues.filter(status__in=services.OPEN_ISSUE_STATUSES).count()
        return ctx

    def form_valid(self, form):
        try:
            moved = services.assign_supervisor(
                self.client, form.cleaned_data["supervisor"], self.request.user, form.cleaned_data["move_open_issues"]
            )
        except TransitionError as exc:
            form.add_error("supervisor", str(exc))
            return self.form_invalid(form)
        sup = form.cleaned_data["supervisor"]
        extra = f" {moved} open issue(s) moved." if moved else ""
        messages.success(self.request, f"{sup or 'Nobody'} is now responsible for {self.client.name}.{extra}")
        return redirect(self.client)


class ClientSitesView(OfficeRequiredMixin, FormView):
    form_class = ClientSitesForm
    template_name = "clients/client_sites.html"

    def dispatch(self, request, *args, **kwargs):
        self.client = get_object_or_404(Client, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "client": self.client}

    def get_initial(self):
        return {"sites": [link.site_id for link in self.client.site_links.all()]}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "client": self.client}

    def form_valid(self, form):
        try:
            services.set_client_sites(self.client, form.cleaned_data["sites"], self.request.user)
        except TransitionError as exc:
            form.add_error("sites", str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "GPS sites saved.")
        return redirect(self.client)


# --- client messages ------------------------------------------------------------

class MessageCreateView(OfficeRequiredMixin, CreateView):
    form_class = MessageForm
    template_name = "clients/message_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.client = get_object_or_404(Client, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "client": self.client}

    def form_valid(self, form):
        msg = form.save(commit=False)
        msg.client = self.client
        msg.created_by = self.request.user
        msg.save()
        upload = form.cleaned_data.get("attachment")
        if upload:
            save_attachment(msg, upload, self.request.user)
        audit.record(self.request.user, "message.drafted", msg, f"Wrote message to {self.client.name}: {msg.subject}")
        return _after_message_save(self.request, msg)


class MessageEditView(OfficeRequiredMixin, UpdateView):
    form_class = MessageForm
    template_name = "clients/message_form.html"
    context_object_name = "msg"

    def get_queryset(self):
        return Message.objects.filter(status__in=(Message.Status.DRAFT, Message.Status.FAILED)).select_related("client")

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "client": self.object.client}

    def form_valid(self, form):
        msg = form.save()
        upload = form.cleaned_data.get("attachment")
        if upload:
            save_attachment(msg, upload, self.request.user)
        return _after_message_save(self.request, msg)


def _after_message_save(request, msg):
    if request.POST.get("action") == "send":
        ok, error = services.send_message(msg, request.user)
        if ok:
            messages.success(request, f"Email sent to {msg.client.name} ({msg.to_email}).")
        else:
            messages.error(request, f"Not sent: {error}")
    else:
        messages.success(request, "Saved as a draft. It has not been sent.")
    return redirect(msg)


class MessageDetailView(OfficeRequiredMixin, DetailView):
    template_name = "clients/message_detail.html"
    context_object_name = "msg"

    def get_queryset(self):
        return Message.objects.select_related("client", "created_by", "sent_by")

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "files": attachments_for(self.object)}


class MessageSendView(OfficeRequiredMixin, ActionView):
    model = Message

    def act(self, msg):
        ok, error = services.send_message(msg, self.request.user)
        if not ok:
            raise TransitionError(f"Not sent: {error}")
        return f"Email sent to {msg.client.name} ({msg.to_email})."


class MessageOfflineView(OfficeRequiredMixin, ActionView):
    model = Message

    def act(self, msg):
        services.record_offline(msg, self.request.user)
        return "Recorded as told to the client by phone or in person."


# --- feedback -------------------------------------------------------------------

class FeedbackListView(OfficeRequiredMixin, FilterContextMixin, ListView):
    template_name = "clients/feedback_list.html"
    context_object_name = "feedback"
    paginate_by = 25

    def get_queryset(self):
        qs = Feedback.objects.select_related("client", "recorded_by")
        g = self.request.GET
        if g.get("status") in Feedback.Status.values:
            qs = qs.filter(status=g["status"])
        if g.get("kind") in Feedback.Kind.values:
            qs = qs.filter(kind=g["kind"])
        if g.get("client", "").isdigit():
            qs = qs.filter(client_id=int(g["client"]))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(statuses=Feedback.Status.choices, kinds=Feedback.Kind.choices)
        return ctx


class FeedbackCreateView(OfficeRequiredMixin, CreateView):
    form_class = FeedbackForm
    template_name = "clients/feedback_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.client = get_object_or_404(Client, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "client": self.client}

    def form_valid(self, form):
        fb = form.save(commit=False)
        fb.client = self.client
        services.record_feedback(fb, self.request.user)
        messages.success(self.request, "Feedback recorded.")
        return redirect(fb)


class FeedbackDetailView(OfficeRequiredMixin, DetailView):
    template_name = "clients/feedback_detail.html"
    context_object_name = "fb"

    def get_queryset(self):
        return Feedback.objects.select_related("client", "recorded_by", "reviewed_by", "responded_by", "closed_by")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["response_form"] = FeedbackResponseForm()
        ctx["issues"] = self.object.issues.all()
        ctx["escalation"] = _open_escalation(self.object)
        return ctx


class FeedbackReviewView(OfficeRequiredMixin, ActionView):
    model = Feedback

    def act(self, fb):
        services.review_feedback(fb, self.request.user)
        return "Marked as reviewed."


class FeedbackRespondView(OfficeRequiredMixin, ActionView):
    model = Feedback

    def act(self, fb):
        form = FeedbackResponseForm(self.request.POST)
        if not form.is_valid():
            raise TransitionError("Write the response and choose how you responded.")
        services.respond_to_feedback(fb, self.request.user, form.cleaned_data["response"], form.cleaned_data["channel"])
        if form.cleaned_data["channel"] == Feedback.Channel.EMAIL:
            return "Response emailed to the client and saved."
        return "Response recorded."


class FeedbackCloseView(OfficeRequiredMixin, ActionView):
    model = Feedback

    def act(self, fb):
        services.close_feedback(fb, self.request.user)
        return "Feedback closed."


class FeedbackMakeIssueView(OfficeRequiredMixin, ActionView):
    model = Feedback

    def act(self, fb):
        if not fb.client.is_active:
            raise TransitionError("This client is inactive. Reactivate the client first.")
        self.issue = services.feedback_to_issue(fb, self.request.user)
        return f"Issue {self.issue.number} created and sent to {self.issue.supervisor or 'the office (no supervisor yet)'}."

    def get_success_url(self):
        issue = getattr(self, "issue", None)
        return issue.get_absolute_url() if issue else self.object.get_absolute_url()


# --- issues ---------------------------------------------------------------------

class IssueListView(RoleRequiredMixin, FilterContextMixin, ListView):
    allowed_roles = OFFICE + (Role.SUPERVISOR,)
    template_name = "clients/issue_list.html"
    context_object_name = "issues"
    paginate_by = 25

    def get_queryset(self):
        qs = services.issues_visible_to(self.request.user)
        g = self.request.GET
        status = g.get("status", "open")
        if status == "open":
            qs = qs.filter(status__in=services.OPEN_ISSUE_STATUSES)
        elif status in Issue.Status.values:
            qs = qs.filter(status=status)
        if g.get("priority") in Issue.Priority.values:
            qs = qs.filter(priority=g["priority"])
        if g.get("client", "").isdigit():
            qs = qs.filter(client_id=int(g["client"]))
        sup = g.get("supervisor", "")
        if self.request.user.role in OFFICE:
            if sup == "none":
                qs = qs.filter(supervisor__isnull=True)
            elif sup.isdigit():
                qs = qs.filter(supervisor_id=int(sup))
        date_from, date_to = parse_date(g.get("from", "")), parse_date(g.get("to", ""))
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            statuses=Issue.Status.choices, priorities=Issue.Priority.choices,
            supervisors=services.active_supervisors(), office=self.request.user.role in OFFICE,
            status=self.request.GET.get("status", "open"),
        )
        return ctx


class IssueCreateView(OfficeRequiredMixin, CreateView):
    form_class = IssueForm
    template_name = "clients/issue_form.html"

    def get_initial(self):
        c = self.request.GET.get("client", "")
        return {"client": int(c)} if c.isdigit() else {}

    def form_valid(self, form):
        d = form.cleaned_data
        issue = services.create_issue(d["client"], d["subject"], d["description"], d["priority"],
                                      self.request.user, upload=d.get("attachment"))
        if issue.supervisor:
            messages.success(self.request, f"Issue {issue.number} created and sent to {issue.supervisor}.")
        else:
            messages.warning(self.request, f"Issue {issue.number} created. This client has no supervisor, so please assign one.")
        return redirect(issue)


class IssueDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = OFFICE + (Role.SUPERVISOR,)
    template_name = "clients/issue_detail.html"
    context_object_name = "issue"

    def get_queryset(self):
        return services.issues_visible_to(self.request.user).select_related("created_by", "resolved_by", "closed_by")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        issue = self.object
        user = self.request.user
        ctx.update(
            notes=issue.notes.select_related("author"),
            files=attachments_for(issue),
            moves=services.allowed_moves(issue, user),
            office=user.role in OFFICE,
            note_form=IssueNoteForm(),
            assign_form=AssignIssueForm(initial={"supervisor": issue.supervisor}),
            escalation=_open_escalation(issue) if user.role in OFFICE else None,
            Status=Issue.Status,
        )
        return ctx


class IssueActionView(ActionView):
    allowed_roles = OFFICE + (Role.SUPERVISOR,)

    def get_queryset(self):
        return services.issues_visible_to(self.request.user)


class IssueNoteView(IssueActionView):
    def act(self, issue):
        form = IssueNoteForm(self.request.POST, self.request.FILES)
        if not form.is_valid():
            raise TransitionError(" ".join(e for errs in form.errors.values() for e in errs))
        services.add_issue_note(issue, self.request.user, form.cleaned_data["body"], form.cleaned_data.get("attachment"))
        return "Note added."


class IssueStatusView(IssueActionView):
    def act(self, issue):
        form = IssueStatusForm(self.request.POST)
        if not form.is_valid():
            raise TransitionError("That change is not allowed.")
        services.change_issue_status(issue, form.cleaned_data["to"], self.request.user, form.cleaned_data["note"])
        return f"{issue.number} is now {issue.get_status_display().lower()}."


class IssueAssignView(OfficeRequiredMixin, ActionView):
    def get_queryset(self):
        return Issue.objects.select_related("client", "supervisor")

    def act(self, issue):
        form = AssignIssueForm(self.request.POST)
        if not form.is_valid():
            raise TransitionError("Choose an active supervisor.")
        services.assign_issue(issue, form.cleaned_data["supervisor"], self.request.user)
        return f"{issue.number} is now with {issue.supervisor}."



def _open_escalation(obj):
    from escalations.services import open_escalation

    return open_escalation(obj)
