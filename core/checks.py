"""Daily checks: overdue invoices and overdue items. Run by `manage.py run_daily_checks` (e.g. from
Windows Task Scheduler) and also automatically, at most once a day, when the office opens the dashboard.
"""
import logging

from django.utils import timezone

from .models import CompanySettings

log = logging.getLogger(__name__)


def run_daily_checks(force=False):
    """Returns a summary dict, or None if the checks already ran today (and force is False)."""
    from billing.services import mark_overdue
    from inventory.services import daily_item_checks

    settings = CompanySettings.load()
    now = timezone.now()
    start_of_day = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    if not force:
        # Claim today's run with one conditional update so two page loads can't both run it.
        claimed = CompanySettings.objects.filter(pk=settings.pk).exclude(last_checks_at__gte=start_of_day).update(last_checks_at=now)
        if not claimed:
            return None
    else:
        CompanySettings.objects.filter(pk=settings.pk).update(last_checks_at=now)
    return {"overdue_invoices": mark_overdue(), "item_reminders": daily_item_checks()}


def run_if_due():
    try:
        return run_daily_checks()
    except Exception:  # a failed background check must never break the dashboard
        log.exception("Daily checks failed")
        return None
