from rest_framework.throttling import SimpleRateThrottle

from .permissions import request_agency


class AgencyRateThrottle(SimpleRateThrottle):
    """Quota de requêtes par agence (toutes clés confondues)."""

    scope = "agency"

    def get_cache_key(self, request, view):
        agency = request_agency(request)
        ident = f"agency-{agency.pk}" if agency else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
