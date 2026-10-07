from django.utils import timezone

from .models import TrackingProfile
from .services import is_tracked

SEEN_EVERY_S = 60


class LastSeenMiddleware:
    """Records when staff and supervisors last used the site (their ONLINE status).

    Writes at most once a minute per person, tracked in their session.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and is_tracked(user):
            now = timezone.now()
            last = request.session.get("tracking_seen", 0)
            if now.timestamp() - last >= SEEN_EVERY_S:
                updated = TrackingProfile.objects.filter(user=user).update(last_seen_at=now)
                if not updated:
                    TrackingProfile.objects.get_or_create(user=user, defaults={"last_seen_at": now})
                request.session["tracking_seen"] = now.timestamp()
        return self.get_response(request)
