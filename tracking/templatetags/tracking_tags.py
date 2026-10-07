from django import template

from accounts.models import Role

from .. import services

register = template.Library()


@register.inclusion_tag("tracking/_report_location.html", takes_context=True)
def report_location(context, report):
    """Location at the time a report was sent. Shown to the manager and the author only."""
    user = context["request"].user
    allowed = user.role == Role.MANAGER or user.pk == report.author_id
    if not allowed or report.author.role not in services.TRACKED_ROLES:
        return {"show": False}
    return {"show": True, "ping": services.report_location(report), "report": report}
