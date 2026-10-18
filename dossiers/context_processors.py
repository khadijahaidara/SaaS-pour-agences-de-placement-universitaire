def unread_notifications(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {"unread_notifications_count": user.notifications.filter(is_read=False).count()}
