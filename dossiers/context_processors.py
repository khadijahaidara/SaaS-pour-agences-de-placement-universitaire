from django.utils import timezone


def unread_notifications(request):
    """Données communes à l'en-tête et à la navigation."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    ctx = {
        "unread_notifications_count": user.notifications.filter(is_read=False).count(),
        "recent_notifications": user.notifications.all()[:6],
    }
    if user.is_student:
        ctx["portal_agency"] = user.agency
    if user.is_agency_staff:
        from .models import DocumentRequest, Dossier

        ctx["nav_to_review"] = DocumentRequest.objects.filter(
            dossier__in=Dossier.objects.for_user(user).open(), status=DocumentRequest.Status.SUBMITTED
        ).count()
    elif user.role == user.Role.PLATFORM_ADMIN:
        from console.models import Prospect

        ctx["nav_due"] = Prospect.objects.filter(next_follow_up__lte=timezone.localdate()).exclude(
            status__in=Prospect.CLOSED).count()
    return ctx
