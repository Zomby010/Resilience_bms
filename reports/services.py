"""Read-only report queries for the Manager's Team page."""
from django.db.models import Count, Q

from accounts.models import Role, User

from .models import Status


def supervisor_performance():
    """Each supervisor's team size, team reports, open reports and feedback given (Company ▸ Team)."""
    return (
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
