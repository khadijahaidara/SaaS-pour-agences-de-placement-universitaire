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


ACCESS_ALLOWED_PREFIXES = (
    "/agence/acces/", "/agence/abonnement/", "/compte/", "/static/", "/logo/", "/marque/", "/health/",
    "/conditions/", "/confidentialite/",
)


class AccessGateMiddleware:
    """L'équipe d'une agence n'accède à son espace que si NEURALIS l'a validé et que l'abonnement est à jour.

    - « pending » : inscription en ligne non encore validée (après paiement) ;
    - « blocked » : suspendue, essai terminé ou période payée dépassée de plus de GRACE_DAYS jours.
    Seules restent accessibles la page d'accès, l'abonnement (pour payer) et le compte personnel.
    Les étudiants gardent leur portail en lecture seule (dépôts refusés par les services).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (user is not None and user.is_authenticated and user.is_agency_staff and user.agency_id
                and not request.path.startswith(ACCESS_ALLOWED_PREFIXES)
                and user.agency.access_status in {"pending", "blocked"}):
            if request.path.startswith("/api/"):
                from django.http import JsonResponse

                return JsonResponse({"detail": "Accès de l'agence suspendu ou en attente de validation.",
                                     "code": "agency_inactive"}, status=403)
            return redirect("agency_access")
        return self.get_response(request)
