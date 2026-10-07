from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.generic import DetailView, FormView, ListView, TemplateView

from clients.models import Client
from core.mixins import ActionView, FilterContextMixin, OfficeRequiredMixin
from core.models import AuditLog, CompanySettings
from core.workflow import TransitionError

from . import services
from .forms import CancelForm, InvoiceForm, LineFormSet, PaymentForm
from .models import Invoice, InvoiceLine
from .pdf import invoice_pdf


class InvoiceListView(OfficeRequiredMixin, FilterContextMixin, ListView):
    template_name = "billing/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 25

    def get_queryset(self):
        qs = Invoice.objects.select_related("client")
        g = self.request.GET
        if g.get("status") in Invoice.Status.values:
            qs = qs.filter(status=g["status"])
        elif g.get("status") == "unpaid":
            qs = qs.filter(status__in=services.OPEN_STATUSES)
        if g.get("client", "").isdigit():
            qs = qs.filter(client_id=int(g["client"]))
        q = (g.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(number__icontains=q) | Q(client__name__icontains=q))
        date_from, date_to = parse_date(g.get("from", "")), parse_date(g.get("to", ""))
        if date_from:
            qs = qs.filter(invoice_date__gte=date_from)
        if date_to:
            qs = qs.filter(invoice_date__lte=date_to)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        unpaid = Invoice.objects.filter(status__in=services.OPEN_STATUSES)
        ctx["outstanding"] = sum((i.balance for i in unpaid.only("total", "amount_paid")), 0)
        ctx["overdue_count"] = unpaid.filter(status=Invoice.Status.OVERDUE).count()
        ctx["draft_count"] = Invoice.objects.filter(status=Invoice.Status.DRAFT).count()
        ctx["statuses"] = Invoice.Status.choices
        ctx["clients"] = Client.objects.all()
        return ctx


class InvoiceFormView(OfficeRequiredMixin, TemplateView):
    """Create or edit a draft invoice with its lines. Totals are always worked out on the server."""

    template_name = "billing/invoice_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.invoice = None
        if "pk" in kwargs:
            self.invoice = get_object_or_404(Invoice, pk=kwargs["pk"])
            if self.invoice.status != Invoice.Status.DRAFT:
                messages.error(request, "This invoice has been sent and can no longer be changed.")
                return redirect(self.invoice)
        return super().dispatch(request, *args, **kwargs)

    def forms(self, data=None):
        initial = {}
        c = self.request.GET.get("client", "")
        if c.isdigit():
            initial["client"] = int(c)
        form = InvoiceForm(data, instance=self.invoice, initial=initial)
        qs = self.invoice.lines.all() if self.invoice else InvoiceLine.objects.none()
        formset = LineFormSet(data, queryset=qs, prefix="lines")
        return form, formset

    def get(self, request, *args, **kwargs):
        form, formset = self.forms()
        return self.render_to_response(self.get_context_data(form=form, formset=formset))

    def post(self, request, *args, **kwargs):
        form, formset = self.forms(request.POST)
        if form.is_valid() and formset.is_valid():
            try:
                inv = services.save_draft(form.save(commit=False), formset.lines(), request.user, creating=self.invoice is None)
            except TransitionError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, "Draft invoice saved. Check it, then press Send when ready.")
                return redirect(inv)
        return self.render_to_response(self.get_context_data(form=form, formset=formset))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = CompanySettings.load()
        ctx.update(invoice=self.invoice, company=company, vat_rate=company.vat_rate if company.vat_registered else 0)
        return ctx


class InvoiceDetailView(OfficeRequiredMixin, DetailView):
    template_name = "billing/invoice_detail.html"
    context_object_name = "invoice"

    def get_queryset(self):
        return Invoice.objects.select_related("client", "created_by", "sent_by", "cancelled_by")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        inv = self.object
        ctx.update(
            company=CompanySettings.load(), lines=inv.lines.all(), payments=inv.payments.select_related("recorded_by"),
            payment_form=PaymentForm(invoice=inv), cancel_form=CancelForm(),
            missing=services.missing_company_details(),
            history=AuditLog.objects.filter(entity_type="billing.invoice", entity_id=str(inv.pk)).select_related("actor"),
            emails=inv.client.messages.filter(kind="invoice", related_id=inv.pk),
        )
        return ctx


class InvoicePrintView(InvoiceDetailView):
    template_name = "billing/invoice_print.html"


class InvoicePdfView(OfficeRequiredMixin, DetailView):
    model = Invoice

    def render_to_response(self, context, **kwargs):
        inv = self.object
        response = HttpResponse(invoice_pdf(inv), content_type="application/pdf")
        name = inv.number or f"draft-invoice-{inv.pk}"
        response["Content-Disposition"] = f'attachment; filename="{name}.pdf"'
        return response


class InvoiceSendView(OfficeRequiredMixin, ActionView):
    model = Invoice

    def act(self, inv):
        was_draft = inv.status == Invoice.Status.DRAFT
        services.send_invoice(inv, self.request.user)
        verb = "issued and emailed" if was_draft else "emailed again"
        return f"Invoice {inv.number} {verb} to {inv.client.email}."


class InvoiceDeleteView(OfficeRequiredMixin, ActionView):
    model = Invoice

    def act(self, inv):
        services.delete_draft(inv, self.request.user)
        return "Draft deleted."

    def get_success_url(self):
        if Invoice.objects.filter(pk=self.object.pk).exists():
            return self.object.get_absolute_url()
        return reverse("billing:list")


class InvoiceCancelView(OfficeRequiredMixin, ActionView):
    model = Invoice

    def act(self, inv):
        services.cancel_invoice(inv, self.request.user, self.request.POST.get("reason", ""))
        return f"Invoice {inv.number} cancelled."


class PaymentCreateView(OfficeRequiredMixin, FormView):
    form_class = PaymentForm
    template_name = "billing/payment_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.invoice = get_object_or_404(Invoice.objects.select_related("client"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "invoice": self.invoice}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "invoice": self.invoice}

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            services.record_payment(self.invoice, d["paid_on"], d["amount"], d["method"], d["reference"], self.request.user)
        except TransitionError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, f"Payment of KES {d['amount']:,.2f} recorded. Balance now KES {self.invoice.balance:,.2f}.")
        return redirect(self.invoice)

