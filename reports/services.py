"""Read-only queries that power the role dashboards."""
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import Role, User

from .models import Reply, Report, Status


def _last_months(n=6):
    """First day (local time) of each of the last `n` months, oldest first."""
    now = timezone.localtime()
    year, month = now.year, now.month
    months = []
    for _ in range(n):
        months.append(now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0))
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(months))


def monthly_pending_vs_completed(reports, n=6):
    """One row per month with open/completed counts and bar heights (%)."""
    starts = _last_months(n)
    rows = []
    for i, start in enumerate(starts):
        in_month = reports.filter(created_at__gte=start)
        if i + 1 < len(starts):
            in_month = in_month.filter(created_at__lt=starts[i + 1])
        rows.append(
            {
                "label": start.strftime("%b"),
                "completed": in_month.filter(status=Status.COMPLETED).count(),
                "open": in_month.exclude(status=Status.COMPLETED).count(),
            }
        )
    peak = max([r["completed"] for r in rows] + [r["open"] for r in rows] + [1])
    for r in rows:
        r["completed_pct"] = round(r["completed"] / peak * 100)
        r["open_pct"] = round(r["open"] / peak * 100)
    return rows


def recent_activity(reports, limit=10):
    """Newest submissions and replies, merged into one feed."""
    events = [
        {"when": r.created_at, "who": r.author, "what": f'submitted report "{r.title}"', "report": r}
        for r in reports.select_related("author").order_by("-created_at")[:limit]
    ]
    replies = Reply.objects.filter(report__in=reports).select_related("author", "report").order_by("-created_at")[:limit]
    events += [
        {"when": p.created_at, "who": p.author, "what": f'replied to "{p.report.title}"', "report": p.report}
        for p in replies
    ]
    return sorted(events, key=lambda e: e["when"], reverse=True)[:limit]


def manager_dashboard():
    reports = Report.objects.all()
    supervisors = (
        User.objects.filter(role=Role.SUPERVISOR, is_active=True)
        .annotate(
            team_size=Count("team_members", distinct=True),
            team_open=Count(
                "team_members__reports", filter=~Q(team_members__reports__status=Status.COMPLETED), distinct=True
            ),
            team_reports=Count("team_members__reports", distinct=True),
            feedback_given=Count("replies", distinct=True),
        )
        .order_by("first_name", "username")
    )
    return {
        "open_count": reports.open().count(),
        "awaiting_supervisor": reports.filter(status=Status.PENDING).count(),
        "completed_count": reports.filter(status=Status.COMPLETED).count(),
        "active_supervisors": supervisors.count(),
        "feedback_sent": Reply.objects.count(),
        "chart": monthly_pending_vs_completed(reports),
        "supervisors": supervisors,
        "recent_reports": reports.select_related("author")[:8],
        "activity": recent_activity(reports),
        "feedback_history": Reply.objects.select_related("author", "report").order_by("-created_at")[:8],
    }


def supervisor_dashboard(user):
    team = user.team_members.filter(is_active=True).annotate(
        report_count=Count("reports", distinct=True),
        open_count=Count("reports", filter=~Q(reports__status=Status.COMPLETED), distinct=True),
    )
    team_reports = Report.objects.filter(author__supervisor=user)
    return {
        "team": team,
        "to_review": team_reports.filter(status=Status.PENDING).select_related("author")[:10],
        "to_review_count": team_reports.filter(status=Status.PENDING).count(),
        "team_report_count": team_reports.count(),
        "my_reports": Report.objects.filter(author=user)[:5],
        "feedback_given": Reply.objects.filter(author=user).count(),
    }


def staff_dashboard(user):
    mine = Report.objects.filter(author=user)
    return {
        "pending": mine.filter(status=Status.PENDING).count(),
        "reviewed": mine.filter(status=Status.REVIEWED).count(),
        "completed": mine.filter(status=Status.COMPLETED).count(),
        "recent": mine[:8],
        "latest_feedback": Reply.objects.filter(report__author=user)
        .select_related("author", "report")
        .order_by("-created_at")[:5],
    }
