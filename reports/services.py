"""Read-only queries that power the role dashboards."""
from django.db.models import Count, Q

from accounts.models import Role, User
from core.filters import period_start

from .models import Reply, Report, Status


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


RECEIVED_GROUPS = (
    (Role.SECRETARY, "From the Secretary"),
    (Role.SUPERVISOR, "From supervisors"),
    (Role.STAFF, "From guards"),
)


def reports_received(period="week", today=None):
    """The Manager's Reports Received section: one group per sender role, for today, this week or this month."""
    start = period_start(period, today)
    since = Report.objects.filter(created_at__date__gte=start).select_related("author", "completed_by")
    groups = []
    for role, label in RECEIVED_GROUPS:
        qs = since.filter(author__role=role)
        groups.append({
            "role": role, "label": label, "reports": qs.order_by("status", "-created_at")[:15],
            "total": qs.count(), "open": qs.exclude(status=Status.COMPLETED).count(),
            "resolved": qs.filter(status=Status.COMPLETED).count(),
        })
    return {"received_groups": groups, "received_period": period, "received_since": start}


def manager_dashboard(period="week"):
    reports = Report.objects.all()
    completed = reports.filter(status=Status.COMPLETED)
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
        "unchecked_count": reports.filter(status=Status.PENDING).count(),
        "awaiting_supervisor": reports.filter(status=Status.PENDING).count(),
        "completed_count": completed.count(),
        "resolved_by_supervisors": completed.filter(completed_by__role=Role.SUPERVISOR).count(),
        "resolved_by_manager": completed.filter(completed_by__role=Role.MANAGER).count(),
        "active_supervisors": supervisors.count(),
        "feedback_sent": Reply.objects.count(),
        "supervisors": supervisors,
        "recent_reports": reports.select_related("author")[:8],
        "activity": recent_activity(reports),
        "feedback_history": Reply.objects.select_related("author", "report").order_by("-created_at")[:8],
        **reports_received(period),
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
