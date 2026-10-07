"""Invoice rules: totals worked out on the server, numbers given on first send, payments, overdue."""
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from clients.models import Message
from core.models import CompanySettings
from core.services import audit, mail
from core.workflow import TransitionError, advance
from notifications.services import notify_role

from .models import Invoice, InvoiceCounter, InvoiceLine, Payment

CENT = Decimal("0.01")
OPEN_STATUSES = (Invoice.Status.SENT, Invoice.Status.PART_PAID, Invoice.Status.OVERDUE)


def q2(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def compute_totals(invoice, lines):
    """Set line amounts and invoice totals. `lines` are unsaved or saved InvoiceLine objects."""
    subtotal = Decimal("0.00")
    for line in lines:
        line.amount = q2(line.quantity * line.unit_price)
        subtotal += line.amount
    invoice.subtotal = q2(subtotal)
    invoice.vat_amount = q2(subtotal * invoice.vat_rate / 100) if invoice.vat_enabled else Decimal("0.00")
    invoice.total = invoice.subtotal + invoice.vat_amount


@transaction.atomic
def save_draft(invoice, lines, user, creating):
    """Save a draft with its lines (replacing the old lines). VAT only if the company is VAT-registered."""
    company = CompanySettings.load()
    if invoice.pk and Invoice.objects.filter(pk=invoice.pk).exclude(status=Invoice.Status.DRAFT).exists():
        raise TransitionError("This invoice has been sent and can no longer be changed.")
    if not lines:
        raise TransitionError("Add at least one line to the invoice.")
    if invoice.vat_enabled and not company.vat_registered:
        invoice.vat_enabled = False
    invoice.vat_rate = company.vat_rate if invoice.vat_enabled else Decimal("0.00")
    compute_totals(invoice, lines)
    if creating:
        invoice.created_by = user
    invoice.save()
    invoice.lines.all().delete()
    for pos, line in enumerate(lines):
        line.pk = None
        line.invoice = invoice
        line.position = pos
    InvoiceLine.objects.bulk_create(lines)
    audit.record(user, "invoice.created" if creating else "invoice.updated", invoice,
                 f"{'Created' if creating else 'Edited'} draft invoice for {invoice.client.name} ({invoice.total} KES)",
                 changes={"total": str(invoice.total)})
    return invoice


@transaction.atomic
def delete_draft(invoice, user):
    if invoice.status != Invoice.Status.DRAFT or invoice.number:
        raise TransitionError("Only drafts that were never sent can be deleted.")
    audit.record(user, "invoice.deleted", invoice, f"Deleted draft invoice #{invoice.pk} for {invoice.client.name}")
    invoice.delete()


def _next_number(year):
    """Take the next number for the year inside the caller's transaction (row lock on the counter)."""
    InvoiceCounter.objects.get_or_create(year=year)
    InvoiceCounter.objects.filter(year=year).update(last_seq=F("last_seq") + 1)
    seq = InvoiceCounter.objects.select_for_update().get(year=year).last_seq
    return seq, f"INV-{year}-{seq:04d}"


def missing_company_details():
    c = CompanySettings.load()
    missing = [label for label, value in (("company name", c.company_name), ("phone", c.phone)) if not value]
    return missing


def send_invoice(invoice, user):
    """Give the invoice its number (first time only), freeze the client details, make the PDF, email it.

    The number and SENT status are saved even if the email fails, so the Secretary can press
    "Email again" without creating a second number.
    """
    client = invoice.client
    if invoice.status == Invoice.Status.CANCELLED:
        raise TransitionError("This invoice is cancelled.")
    if not client.email:
        raise TransitionError("This client has no email address. Add one to the client first, or print the invoice.")
    missing = missing_company_details()
    if missing:
        raise TransitionError(f"Fill in the company {' and '.join(missing)} in Company settings first (Manager).")
    if not invoice.lines.exists():
        raise TransitionError("Add at least one line to the invoice.")
    if invoice.status == Invoice.Status.DRAFT:
        with transaction.atomic():
            locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
            if locked.status == Invoice.Status.DRAFT:
                year = locked.invoice_date.year
                seq, number = _next_number(year)
                Invoice.objects.filter(pk=invoice.pk, status=Invoice.Status.DRAFT).update(
                    status=Invoice.Status.SENT, number=number, year=year, seq=seq,
                    bill_to_name=client.name, bill_to_address="\n".join(x for x in (client.physical_address, client.postal_address) if x),
                    bill_to_kra_pin=client.kra_pin, sent_by=user, sent_at=timezone.now(), updated_at=timezone.now(),
                    payment_instructions=locked.payment_instructions or CompanySettings.load().payment_instructions,
                )
                audit.record(user, "invoice.sent", invoice, f"Issued invoice {number} to {client.name} ({locked.total} KES)")
        invoice.refresh_from_db()
    return email_invoice(invoice, user)


def email_invoice(invoice, user):
    from .pdf import invoice_pdf

    pdf = invoice_pdf(invoice)
    company = CompanySettings.load()
    body = (
        f"Please find attached invoice {invoice.number} for KES {invoice.total:,.2f}, "
        f"due on {invoice.due_date:%d %B %Y}.\n\n"
        + (f"How to pay:\n{invoice.payment_instructions}\n\n" if invoice.payment_instructions else "")
        + "Thank you for your business."
    )
    msg = Message.objects.create(
        client=invoice.client, kind=Message.Kind.INVOICE, subject=f"Invoice {invoice.number} from {company.company_name}",
        body=body, created_by=user, related_type=_ct(invoice), related_id=invoice.pk,
    )
    from clients.services import send_message

    ok, error = send_message(msg, user, attachments=[(f"{invoice.number}.pdf", pdf, "application/pdf")])
    if not ok:
        raise TransitionError(f"Invoice {invoice.number} is saved, but the email was not sent: {error} Use \"Email again\" to retry.")
    return invoice


def _ct(obj):
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(obj)


@transaction.atomic
def record_payment(invoice, paid_on, amount, method, reference, user):
    amount = q2(amount)
    locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if locked.status not in OPEN_STATUSES:
        raise TransitionError("Payments can only be recorded on sent invoices that are not fully paid or cancelled.")
    if amount <= 0:
        raise TransitionError("The amount must be more than zero.")
    if amount > locked.balance:
        raise TransitionError(f"That is more than the balance of KES {locked.balance:,.2f}.")
    Payment.objects.create(invoice=locked, paid_on=paid_on, amount=amount, method=method, reference=reference, recorded_by=user)
    new_paid = locked.amount_paid + amount
    status = Invoice.Status.PAID if new_paid >= locked.total else Invoice.Status.PART_PAID
    Invoice.objects.filter(pk=locked.pk).update(amount_paid=new_paid, status=status, updated_at=timezone.now())
    invoice.refresh_from_db()
    audit.record(user, "invoice.payment", invoice, f"Recorded payment of KES {amount:,.2f} on {invoice.number}",
                 changes={"amount_paid": [str(locked.amount_paid), str(new_paid)], "status": [locked.status, status]})
    return invoice


def cancel_invoice(invoice, user, reason):
    if not reason.strip():
        raise TransitionError("Please give a reason for cancelling.")
    if invoice.payments.exists():
        raise TransitionError("This invoice has payments recorded, so it cannot be cancelled.")
    if not advance(invoice, (Invoice.Status.SENT, Invoice.Status.OVERDUE), Invoice.Status.CANCELLED,
                   cancelled_by=user, cancelled_at=timezone.now(), cancel_reason=reason.strip()):
        raise TransitionError("Only sent invoices without payments can be cancelled. Drafts can simply be deleted.")
    audit.record(user, "invoice.cancelled", invoice, f"Cancelled invoice {invoice.number}: {reason.strip()[:120]}")


def mark_overdue(today=None):
    """Sent / part-paid invoices past their due date become overdue. Safe to run many times."""
    today = today or timezone.localdate()
    due = list(Invoice.objects.filter(status__in=(Invoice.Status.SENT, Invoice.Status.PART_PAID), due_date__lt=today))
    changed = 0
    for inv in due:
        if advance(inv, (Invoice.Status.SENT, Invoice.Status.PART_PAID), Invoice.Status.OVERDUE):
            changed += 1
            audit.record(None, "invoice.overdue", inv, f"Invoice {inv.number} is overdue")
    if changed:
        notify_role(Role.SECRETARY, "invoice.overdue", f"{changed} invoice(s) are now overdue",
                    "Clients have not paid by the due date.", reverse("billing:list") + "?status=overdue")
    return changed
