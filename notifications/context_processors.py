from .services import unread_count


def bell(request):
    """Unread notification count for the bell in the menu (one cheap COUNT query)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {"unread_notifications": unread_count(user)}
