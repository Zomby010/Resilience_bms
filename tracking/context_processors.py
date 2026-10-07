from . import services


def location_reminder(request):
    """Adds `location_required` for staff/supervisors who should be sharing location right now."""
    user = getattr(request, "user", None)
    if user is None or not services.is_tracked(user):
        return {}
    profile = services.profile_for(user)
    return {"location_required": not profile.tracking_on and services.is_working(profile)}
