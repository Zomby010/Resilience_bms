"""Optional Manager approval for large expenses (owner decision D9). Off by default."""
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from core.models import CompanySettings
from core.services import audit
from core.workflow import TransitionError, advance
from notifications.models import Notification
from notifications.services import notify, notify_role

from .models import Expense, ExpenseLog


def needs_approval(amount):
    s = CompanySettings.load()
    return bool(s.expense_approval_enabled and s.expense_approval_limit and amount > s.expense_approval_limit)


def after_save(expense, user, old_amount=None):
    """Put an expense on hold for the Manager when it is above the limit (and new or its amount changed)."""
    changed = old_amount is None or old_amount != expense.amount or expense.status == Expense.Status.REJECTED
    if not changed:
        return
    if needs_approval(expense.amount):
        if expense.status != Expense.Status.AWAITING_APPROVAL:
            Expense.objects.filter(pk=expense.pk).update(status=Expense.Status.AWAITING_APPROVAL, decided_by=None,
                                                         decided_at=None, decision_note="")
            expense.status = Expense.Status.AWAITING_APPROVAL
        notify_role(Role.MANAGER, "expense.approval", f"Expense of KES {expense.amount:,.2f} needs your approval",
                    expense.description, reverse("finance:detail", args=[expense.pk]), Notification.Priority.HIGH, entity=expense)
    elif expense.status != Expense.Status.RECORDED:
        Expense.objects.filter(pk=expense.pk).update(status=Expense.Status.RECORDED)
        expense.status = Expense.Status.RECORDED


def decide(expense, user, approve, note=""):
    if user.role != Role.MANAGER:
        raise TransitionError("Only the Manager can approve expenses.")
    if not approve and not note.strip():
        raise TransitionError("Please give a reason for rejecting.")
    to = Expense.Status.RECORDED if approve else Expense.Status.REJECTED
    if not advance(expense, Expense.Status.AWAITING_APPROVAL, to, decided_by=user, decided_at=timezone.now(),
                   decision_note=note.strip()):
        raise TransitionError("This expense is not waiting for approval.")
    word = "Approved" if approve else "Rejected"
    ExpenseLog.record(expense, ExpenseLog.Action.UPDATED, user,
                      details=f"{word} by Manager{': ' + note.strip() if note.strip() else ''}. {expense.snapshot()}")
    audit.record(user, f"expense.{'approved' if approve else 'rejected'}", expense,
                 f"{word} expense #{expense.pk} (KES {expense.amount:,.2f})")
    notify(expense.recorded_by, "expense.decided", f"Expense {word.lower()}: {expense.description}", note.strip()[:200],
           reverse("finance:detail", args=[expense.pk]), entity=expense)
