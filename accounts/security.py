"""Sécurité des comptes : limitation des essais, double authentification, sessions."""
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from audit.context import client_ip

PENDING_KEY = "2fa_pending"
PENDING_TTL = 300  # secondes pour saisir le code après le mot de passe
MAX_2FA_ATTEMPTS = 5


# --------------------------------------------------------------------------- #
# Limitation des essais de connexion
# --------------------------------------------------------------------------- #
def _keys(request, email):
    return f"login-fail:e:{email}", f"login-fail:ip:{client_ip(request) or '-'}"


def is_locked(request, email: str) -> bool:
    email_key, ip_key = _keys(request, email)
    limit = settings.LOGIN_MAX_FAILURES
    return (cache.get(email_key, 0) >= limit) or (cache.get(ip_key, 0) >= limit * 4)


def register_failure(request, email: str) -> None:
    from audit.services import record

    email_key, ip_key = _keys(request, email)
    timeout = settings.LOGIN_LOCKOUT_SECONDS
    for key in (email_key, ip_key):
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout)
    user = get_user_model().objects.filter(email__iexact=email).select_related("agency").first() if email else None
    record("auth.login_failed", agency=getattr(user, "agency", None), actor=None, target=user,
           metadata={"courriel": email[:120]}, request=request)
    if cache.get(email_key, 0) == settings.LOGIN_MAX_FAILURES:
        record("auth.locked", agency=getattr(user, "agency", None), target=user,
               metadata={"courriel": email[:120]}, request=request)


def clear_failures(request, email: str) -> None:
    email_key, _ = _keys(request, email)
    cache.delete(email_key)


# --------------------------------------------------------------------------- #
# Double authentification à la connexion
# --------------------------------------------------------------------------- #
def start_2fa(request, user, next_url: str) -> None:
    request.session[PENDING_KEY] = {
        "uid": user.pk, "backend": getattr(user, "backend", "django.contrib.auth.backends.ModelBackend"),
        "ts": int(time.time()), "next": next_url, "attempts": 0,
    }


def pending_user(request):
    data = request.session.get(PENDING_KEY)
    if not data or time.time() - data.get("ts", 0) > PENDING_TTL:
        request.session.pop(PENDING_KEY, None)
        return None, None
    user = get_user_model().objects.filter(pk=data["uid"], is_active=True).first()
    return user, data


def verify_second_factor(user, code: str) -> str | None:
    """Retourne 'totp', 'recovery' ou None."""
    from .models import RecoveryCode

    code = (code or "").strip()
    device = getattr(user, "totp_device", None)
    if device and device.confirmed_at and device.verify(code):
        return "totp"
    if len(code.replace("-", "")) == 10 and RecoveryCode.consume(user, code):
        return "recovery"
    return None


def requires_2fa_setup(user) -> bool:
    """L'agence impose la double authentification et ce membre ne l'a pas encore activée."""
    if not user.is_authenticated or not user.is_agency_staff or user.has_2fa:
        return False
    agency = user.agency
    if not agency or not agency.require_2fa:
        return False
    from billing.services import has_feature

    return has_feature(agency, "enforce_2fa")


def qr_svg(data: str) -> str:
    import segno

    return segno.make(data, error="m").svg_inline(scale=5, dark="#0e1b3d", light="#ffffff", border=2)
