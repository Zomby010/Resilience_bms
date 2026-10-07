"""Extra dashboard content for the Secretary operations features. Kept separate so the existing
dashboards (reports, GPS, expenses) are unchanged; each role just gets a few more cards."""
from django.db.models import F, Sum
from django.utils import timezone

from .checks import run_if_due


def _open_issues():
    from clients.models import Issue
    from clients.services import OPEN_ISSUE_STATUSES

    return Issue.objects.filter(status__in=OPEN_ISSUE_STATUSES)


def secretary_overview(user):
    from billing.models import Invoice
    from billing.services import OPEN_STATUSES
    from clients.models import Client, Feedback, Issue, Message
    from escalations.models import Escalation
    from inventory.models import Item, ItemRequest
    from inventory.services import overdue_requests
    from payroll.models import PayrollRun

    run_if_due()
    R = ItemRequest.Status
    today = timezone.localdate()
    unpaid = Invoice.objects.filter(status__in=OPEN_STATUSES)
    open_issues = _open_issues()
    return {
        "active_clients": Client.objects.filter(is_active=True).count(),
        "clients_no_supervisor": Client.objects.filter(is_active=True, supervisor__isnull=True).count(),
        "open_issue_count": open_issues.count(),
        "supervisor_needed": open_issues.filter(status=Issue.Status.SUPERVISOR_NEEDED).select_related("client")[:5],
        "resolved_to_close": Issue.objects.filter(status=Issue.Status.RESOLVED).select_related("client", "supervisor")[:5],
        "new_feedback": Feedback.objects.filter(status=Feedback.Status.NEW).select_related("client")[:5],
        "failed_messages": Message.objects.filter(status=Message.Status.FAILED).select_related("client")[:5],
        "outstanding": unpaid.aggregate(t=Sum(F("total") - F("amount_paid")))["t"] or 0,
        "overdue_invoices": unpaid.filter(status=Invoice.Status.OVERDUE).select_related("client")[:5],
        "overdue_invoice_count": unpaid.filter(status=Invoice.Status.OVERDUE).count(),
        "draft_invoices": Invoice.objects.filter(status=Invoice.Status.DRAFT).count(),
        "billed_this_month": Invoice.objects.filter(invoice_date__year=today.year, invoice_date__month=today.month)
        .exclude(status__in=(Invoice.Status.DRAFT, Invoice.Status.CANCELLED)).aggregate(t=Sum("total"))["t"] or 0,
        "requests_waiting": ItemRequest.objects.filter(status=R.PENDING).select_related("item", "requester")[:6],
        "requests_waiting_count": ItemRequest.objects.filter(status=R.PENDING).count(),
        "returns_to_check": ItemRequest.objects.filter(status=R.RETURN_CLAIMED).select_related("item", "requester")[:6],
        "ready_for_collection": ItemRequest.objects.filter(status=R.READY).count(),
        "overdue_items": overdue_requests(today).count(),
        "low_stock": Item.objects.filter(is_active=True, min_stock__gt=0, qty_available__lte=F("min_stock"))[:6],
        "payroll_this_month": PayrollRun.objects.filter(period=today.replace(day=1)).exclude(status=PayrollRun.Status.REJECTED).first(),
        "payroll_needs_changes": PayrollRun.objects.filter(status=PayrollRun.Status.REVISION_REQUIRED).first(),
        "escalations_back": Escalation.objects.filter(status=Escalation.Status.SENT_BACK).count(),
        "escalations_open": Escalation.objects.exclude(status=Escalation.Status.RESOLVED).count(),
    }


def manager_extra(user):
    """The 'Waiting for me' card on the Manager dashboard."""
    from escalations.models import Escalation
    from finance.models import Expense
    from inventory.models import ItemRequest
    from payroll.models import PayrollRun

    run_if_due()
    payroll = PayrollRun.objects.filter(status__in=(PayrollRun.Status.SUBMITTED, PayrollRun.Status.UNDER_REVIEW))
    waiting = {
        "payroll_waiting": payroll,
        "escalations_waiting": Escalation.objects.filter(status__in=(Escalation.Status.OPEN, Escalation.Status.SEEN))
        .select_related("raised_by")[:5],
        "items_waiting": ItemRequest.objects.filter(status=ItemRequest.Status.AWAITING_MANAGER).select_related("item", "requester")[:5],
        "expenses_waiting": Expense.objects.filter(status=Expense.Status.AWAITING_APPROVAL).count(),
        "open_issue_count": _open_issues().count(),
    }
    waiting["waiting_total"] = (payroll.count() + len(waiting["escalations_waiting"]) + len(waiting["items_waiting"])
                                + waiting["expenses_waiting"])
    return waiting


def supervisor_extra(user):
    from clients.models import Issue

    from inventory.models import ItemRequest

    mine = _open_issues().filter(supervisor=user).select_related("client")
    return {
        "my_issues": mine[:8],
        "my_issue_count": mine.count(),
        "my_urgent_count": mine.filter(priority__in=(Issue.Priority.HIGH, Issue.Priority.URGENT)).count(),
        **_my_items(user, ItemRequest),
    }


def staff_extra(user):
    from inventory.models import ItemRequest

    return _my_items(user, ItemRequest)


def _my_items(user, ItemRequest):
    R = ItemRequest.Status
    mine = ItemRequest.objects.filter(requester=user).select_related("item")
    return {
        "my_item_requests": mine.filter(status__in=(R.AWAITING_MANAGER, R.PENDING, R.READY, R.ISSUED, R.RETURN_CLAIMED))
        .exclude(status=R.ISSUED, item__returnable=False)[:6],
        "items_ready": mine.filter(status=R.READY).count(),
    }
