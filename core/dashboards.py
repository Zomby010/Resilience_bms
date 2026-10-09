"""The short picture of today under each home page's to-do list (the to-dos themselves are in core.todo)."""
from django.db.models import F, Sum
from django.utils import timezone

from .checks import run_if_due


def secretary_overview(user):
    """The folded "Money at a glance" on the Secretary's home page (the to-dos come from core.todo)."""
    from billing.models import Invoice
    from billing.services import OPEN_STATUSES
    from payroll.models import PayrollRun

    run_if_due()
    today = timezone.localdate()
    unpaid = Invoice.objects.filter(status__in=OPEN_STATUSES)
    return {
        "outstanding": unpaid.aggregate(t=Sum(F("total") - F("amount_paid")))["t"] or 0,
        "overdue_invoice_count": unpaid.filter(status=Invoice.Status.OVERDUE).count(),
        "draft_invoices": Invoice.objects.filter(status=Invoice.Status.DRAFT).count(),
        "billed_this_month": Invoice.objects.filter(invoice_date__year=today.year, invoice_date__month=today.month)
        .exclude(status__in=(Invoice.Status.DRAFT, Invoice.Status.CANCELLED)).aggregate(t=Sum("total"))["t"] or 0,
        "payroll_this_month": PayrollRun.objects.filter(period=today.replace(day=1)).exclude(status=PayrollRun.Status.REJECTED).first(),
    }


def manager_extra(user):
    """Today's picture for the Manager's home page (the to-dos come from core.todo)."""
    run_if_due()
    return _operations_glance()


def _operations_glance():
    """The attendance strip and the operations numbers at the top of the Manager dashboard."""
    from attendance.services import board
    from incidents.services import open_serious_count

    today_board = board()
    states = {}
    for box in today_board["boxes"]:
        for group in ("in", "absent", "away", "later"):
            for row in box[group]:
                states[row["state"]] = states.get(row["state"], 0) + 1
    return {
        "board": today_board,
        "today_date": today_board["day"],
        "ops": {
            # "Signed in today" matches the board's "in" count (it includes people whose shift is over);
            # "on_duty" is the part of them still on shift now.
            "signed_in": sum(len(box["in"]) for box in today_board["boxes"]),
            "on_duty": states.get("on_duty", 0) + states.get("late", 0) + states.get("off_location", 0),
            "late": states.get("late", 0),
            "off_location": states.get("off_location", 0),
            "on_leave": states.get("on_leave", 0),
            "sick": states.get("sick", 0),
            "absent": states.get("not_signed_in", 0) + states.get("absent", 0) + states.get("rejected", 0),
            "short_sites": sum(1 for b in today_board["boxes"] if b.get("short") and b["site"]),
            "serious_incidents": open_serious_count(),
        },
    }


def supervisor_extra(user):
    from attendance.services import my_today, team_today

    return {"att": my_today(user), "team_att": team_today(user)}


def staff_extra(user):
    from attendance.services import my_today
    from inventory.models import ItemRequest
    from operations.services import QUICK_ENTRIES, my_site

    site = my_site(user)
    return {**_my_items(user, ItemRequest), "att": my_today(user), "my_site": site, "quick": QUICK_ENTRIES if site else None}


def _my_items(user, ItemRequest):
    R = ItemRequest.Status
    mine = ItemRequest.objects.filter(requester=user).select_related("item")
    return {
        "my_item_requests": mine.filter(status__in=(R.AWAITING_MANAGER, R.PENDING, R.READY, R.ISSUED, R.RETURN_CLAIMED))
        .exclude(status=R.ISSUED, item__returnable=False)[:6],
        "items_ready": mine.filter(status=R.READY).count(),
    }
