from rest_framework import permissions

from .models import ApiKey


def request_agency(request):
    """Agence visée par la requête : celle de la clé API, sinon celle du membre connecté."""
    if isinstance(getattr(request, "auth", None), ApiKey):
        return request.auth.agency
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_agency_staff:
        return user.agency
    return None


class IsAgencyClient(permissions.BasePermission):
    message = "Accès réservé aux agences (clé API ou compte d'agence)."

    def has_permission(self, request, view):
        agency = request_agency(request)
        if agency is None or not agency.is_active:
            return False
        if agency.plan == agency.Plan.SUSPENDED:
            self.message = "L'abonnement de l'agence est suspendu."
            return False
        return True
