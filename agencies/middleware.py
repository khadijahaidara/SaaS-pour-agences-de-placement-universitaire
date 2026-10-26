"""Résolution de l'agence à partir de l'adresse web (sous-domaine ou domaine personnalisé).

- horizon.neuralis-mobility.com → agence dont le sous-domaine est « horizon » ;
- suivi.horizon.ml              → agence dont le domaine personnalisé est « suivi.horizon.ml » ;
- en développement, horizon.localhost:8000 fonctionne aussi (BASE_DOMAIN=localhost).

Sur l'adresse d'une agence, seuls ses propres membres et étudiants (et l'équipe NEURALIS)
peuvent rester connectés : un compte d'une autre agence est déconnecté.
"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

from .models import Agency


def resolve_agency(host: str):
    host = (host or "").split(":")[0].lower().rstrip(".")
    if not host:
        return None
    agency = Agency.objects.filter(custom_domain=host, is_active=True).first()
    if agency:
        return agency
    base = (settings.BASE_DOMAIN or "").lower()
    if base and host.endswith("." + base):
        sub = host[: -(len(base) + 1)]
        if sub and "." not in sub and sub != "www":
            return Agency.objects.filter(subdomain=sub, is_active=True).first()
    return None


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = resolve_agency(request.get_host())
        user = getattr(request, "user", None)
        if (
            request.tenant is not None
            and user is not None
            and user.is_authenticated
            and user.role != user.Role.PLATFORM_ADMIN
            and user.agency_id != request.tenant.id
        ):
            logout(request)
            messages.error(request, f"Ce compte n'appartient pas à {request.tenant.name}. Connectez-vous avec un compte de cette agence.")
            return redirect("accounts:login")
        return self.get_response(request)
