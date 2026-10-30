"""Courriels HTML à l'image de l'agence (logo, couleur, signature, marque blanche)."""
from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse


def _base_url(agency) -> str:
    base = ""
    if agency is not None:
        from agencies.customization import agency_base_url

        base = agency_base_url(agency)
    return base or getattr(settings, "SITE_URL", "").rstrip("/")


def compose(agency, *, subject: str, body: str, cta_url: str = "", cta_label: str = "") -> tuple[str, str, str]:
    """Retourne (objet, texte brut, HTML) prêts à être envoyés."""
    from agencies.theming import get_theme, palette, white_label

    theme = get_theme(agency) if agency is not None else None
    branded = bool(agency is not None and theme is not None and theme.branded_emails)
    base = _base_url(agency)
    if cta_url and cta_url.startswith("/"):
        cta_url = base + cta_url if base else ""
    colors = palette(agency) if branded else {"--river": "#1f4fb8", "--on-river": "#ffffff", "--ochre": "#c98a2b"}
    wl = branded and white_label(agency)
    sender = agency.name if branded else settings.SITE_NAME
    logo_url = ""
    if branded and agency.logo and base:
        logo_url = base + reverse("agency_logo", args=[agency.slug])
    elif not branded and base:
        logo_url = base + "/static/img/neuralis-logo.png"
    signature = (theme.email_signature if branded and theme.email_signature else sender)
    full_subject = f"[{sender}] {subject}"
    text = body.strip()
    if cta_url:
        text += f"\n\n{cta_label or 'Ouvrir'} : {cta_url}"
    text += f"\n\n—\n{signature}"
    if not wl:
        text += "\nEnvoyé avec NEURALIS Mobility"
    html = render_to_string("emails/message.html", {
        "subject": subject, "paragraphs": [p for p in body.strip().split("\n\n") if p.strip()],
        "cta_url": cta_url, "cta_label": cta_label or "Ouvrir", "sender": sender, "logo_url": logo_url,
        "brand": colors["--river"], "on_brand": colors["--on-river"], "accent": colors["--ochre"],
        "signature": signature, "white_label": wl, "agency": agency if branded else None,
    })
    return full_subject, text, html
