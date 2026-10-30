"""Thème visuel (agence) et préférences d'affichage (utilisateur), disponibles dans tous les gabarits."""
from .theming import body_classes, get_theme, theme_css, white_label


def _agency_for(request):
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.role != user.Role.PLATFORM_ADMIN:
        return user.agency
    tenant = getattr(request, "tenant", None)
    if tenant is not None:
        return tenant
    slug = request.GET.get("agence", "") if request.method == "GET" else ""
    if slug and request.path.startswith("/compte/"):
        from .models import Agency

        return Agency.objects.filter(slug=slug, is_active=True).first()
    return None


def appearance(request):
    agency = _agency_for(request)
    user = getattr(request, "user", None)
    authenticated = user is not None and user.is_authenticated
    wl = white_label(agency) if agency else False
    return {
        "theme_agency": agency,
        "agency_theme": get_theme(agency) if agency else None,
        "theme_css": theme_css(agency) if agency else "",
        "theme_body_class": body_classes(agency) if agency else "",
        "white_label": wl,
        "site_brand": agency.name if wl else "NEURALIS Mobility",
        "ui_theme": user.ui_theme if authenticated else "auto",
        "ui_density": user.ui_density if authenticated else "comfortable",
    }
