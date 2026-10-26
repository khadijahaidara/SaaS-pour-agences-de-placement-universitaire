"""Contexte de la requête en cours (IP, navigateur, utilisateur) pour journaliser depuis les services."""
import contextvars

_current = contextvars.ContextVar("audit_request", default=None)


def client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    return ip or None


def set_request(request):
    return _current.set(request)


def reset(token):
    _current.reset(token)


def get_request():
    return _current.get()
