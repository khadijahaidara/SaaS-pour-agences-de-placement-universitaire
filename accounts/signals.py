from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    if request is None:
        return
    from audit.context import client_ip
    from audit.services import record
    from django.utils import timezone

    from .models import UserSession

    if not request.session.session_key:
        request.session.save()
    UserSession.objects.update_or_create(
        session_key=request.session.session_key,
        defaults={"user": user, "ip": client_ip(request), "last_seen": timezone.now(),
                  "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255]},
    )
    request.session["_seen"] = int(timezone.now().timestamp())
    record("auth.login", agency=user.agency, actor=user, request=request,
           metadata={"2fa": "oui" if user.has_2fa else "non"})


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if request is None or user is None:
        return
    from audit.services import record

    from .models import UserSession

    if request.session.session_key:
        UserSession.objects.filter(session_key=request.session.session_key).delete()
    record("auth.logout", agency=user.agency, actor=user, request=request)
