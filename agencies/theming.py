"""Calcul du thème visuel d'une agence (variables CSS) à partir de ses réglages.

Une seule couleur principale suffit : on en dérive les nuances (survol, fonds teintés,
barre de navigation) et on choisit automatiquement un texte lisible (blanc ou bleu nuit)
selon le contraste, pour qu'une agence ne puisse pas rendre l'interface illisible.
"""
import colorsys

from django.core.cache import cache

NEURALIS_NIGHT = "#0E1B3D"
DEFAULT_BRAND = "#1F4FB8"
DEFAULT_ACCENT = "#C98A2B"
CACHE_SECONDS = 3600

FONTS = {
    "character": ('"Manrope", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
                  '"Bricolage Grotesque", "Manrope", system-ui, sans-serif'),
    "modern": ('"Manrope", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
               '"Manrope", system-ui, sans-serif'),
    "system": ('system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
               'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'),
}
CORNERS = {"round": (10, 14, 22), "standard": (6, 10, 16), "square": (2, 4, 6)}


# --------------------------------------------------------------------------- #
# Couleurs
# --------------------------------------------------------------------------- #
def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = (hex_color or DEFAULT_BRAND).lstrip("#")
    if len(h) != 6:
        h = DEFAULT_BRAND.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def mix(a: str, b: str, weight: float) -> str:
    """`weight` de la couleur a, le reste de b."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x * weight + y * (1 - weight) for x, y in zip(ra, rb)))


def with_lightness(hex_color: str, lightness: float, max_saturation: float = 1.0) -> str:
    h, _, s = colorsys.rgb_to_hls(*_rgb(hex_color))
    return _hex(colorsys.hls_to_rgb(h, lightness, min(s, max_saturation)))


def luminance(hex_color: str) -> float:
    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted([luminance(a), luminance(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable_on(background: str) -> str:
    return "#ffffff" if contrast(background, "#ffffff") >= contrast(background, NEURALIS_NIGHT) else NEURALIS_NIGHT


def usable_brand(color: str) -> str:
    """Assombrit une couleur trop claire pour qu'un lien reste lisible sur fond blanc (contraste ≥ 4,5)."""
    lightness = colorsys.rgb_to_hls(*_rgb(color))[1]
    while contrast(color, "#ffffff") < 4.5 and lightness > 0.1:
        lightness -= 0.04
        color = with_lightness(color, lightness)
    return color


# --------------------------------------------------------------------------- #
# Thème
# --------------------------------------------------------------------------- #
def get_theme(agency):
    from .models import AgencyTheme

    if agency is None:
        return None
    cached = getattr(agency, "_theme_cache", None)
    if cached is None:
        cached = AgencyTheme.objects.filter(agency=agency).first() or AgencyTheme(agency=agency)
        agency._theme_cache = cached
    return cached


def palette(agency) -> dict:
    theme = get_theme(agency)
    brand = usable_brand(getattr(agency, "brand_color", "") or DEFAULT_BRAND)
    accent = (theme.accent_color if theme else DEFAULT_ACCENT) or DEFAULT_ACCENT
    sidebar = theme.sidebar_style if theme else "night"
    font = theme.font if theme else "character"
    corners = theme.corners if theme else "standard"

    if sidebar == "brand":
        night = with_lightness(brand, 0.17, 0.75)
    elif sidebar == "light":
        night = "#ffffff"
    else:
        night = NEURALIS_NIGHT
    body_font, display_font = FONTS.get(font, FONTS["character"])
    rs, r, rl = CORNERS.get(corners, CORNERS["standard"])
    return {
        "--river": brand,
        "--river-600": with_lightness(brand, max(0.12, colorsys.rgb_to_hls(*_rgb(brand))[1] - 0.09)),
        "--river-50": mix(brand, "#ffffff", 0.10),
        "--on-river": readable_on(brand),
        "--info": brand,
        "--info-50": mix(brand, "#ffffff", 0.10),
        "--brand": brand,
        "--ochre": accent,
        "--ochre-50": mix(accent, "#ffffff", 0.16),
        "--ochre-ink": with_lightness(accent, 0.28),
        "--on-ochre": readable_on(accent),
        "--night": night,
        "--brand-deep": NEURALIS_NIGHT if sidebar == "night" else with_lightness(brand, 0.16, 0.7),
        "--night-2": with_lightness(night, 0.27, 0.6) if sidebar != "light" else mix(brand, "#ffffff", 0.10),
        "--night-ink": mix(night, "#ffffff", 0.22) if sidebar != "light" else "#45506a",
        "--font-body": body_font,
        "--font-display": display_font,
        "--radius-s": f"{rs}px",
        "--radius": f"{r}px",
        "--radius-l": f"{rl}px",
    }


def theme_css(agency) -> str:
    """Bloc `:root { … }` mis en cache (invalidé à chaque enregistrement de l'apparence)."""
    if agency is None:
        return ""
    theme = get_theme(agency)
    stamp = f"{theme.updated_at.timestamp() if theme and theme.updated_at else 0}-{agency.brand_color}"
    key = f"theme-css:{agency.pk}:{stamp}"
    css = cache.get(key)
    if css is None:
        css = ":root{" + ";".join(f"{k}:{v}" for k, v in palette(agency).items()) + "}"
        cache.set(key, css, CACHE_SECONDS)
    return css


def body_classes(agency) -> str:
    theme = get_theme(agency)
    if theme is None:
        return ""
    classes = [f"sidebar-{theme.sidebar_style}"]
    if white_label(agency):
        classes.append("white-label")
    return " ".join(classes)


def white_label(agency) -> bool:
    theme = get_theme(agency)
    if theme is None or not theme.hide_platform_branding:
        return False
    from billing.services import has_feature

    return has_feature(agency, "white_label")
