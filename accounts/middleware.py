"""Suivi des sessions (appareils connectés) et double authentification imposée par l'agence."""
import time

from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

SEEN_EVERY = 300  # secondes entre deux mises à jour de « dernière activité »
ALLOWED_PREFIXES = ("/static/", "/compte/deconnexion/", "/compte/securite/", "/logo/", "/health/")


class SecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            self._touch_session(request, user)
            from .security import requires_2fa_setup

            if not request.path.startswith(ALLOWED_PREFIXES) and not request.path.startswith("/api/") \
                    and requires_2fa_setup(user):
                return redirect(f"{reverse('accounts:security')}?obligatoire=1")
        return self.get_response(request)

    def _touch_session(self, request, user):
        session = request.session
        key = session.session_key
        if not key:
            return
        now = time.time()
        if now - session.get("_seen", 0) < SEEN_EVERY:
            return
        from audit.context import client_ip

        from .models import UserSession

        session["_seen"] = int(now)
        UserSession.objects.update_or_create(
            session_key=key,
            defaults={"user": user, "last_seen": timezone.now(), "ip": client_ip(request),
                      "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255]},
        )
