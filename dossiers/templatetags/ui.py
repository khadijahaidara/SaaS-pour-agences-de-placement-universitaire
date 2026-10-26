"""Petits outils d'affichage partagés par tous les gabarits."""
import unicodedata

from django import template
from django.contrib.humanize.templatetags.humanize import intcomma
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def icon(name, size=""):
    cls = f"ic {size}".strip()
    return format_html('<svg class="{}" aria-hidden="true"><use href="#i-{}"></use></svg>', cls, name)


@register.filter
def money(value, currency=""):
    try:
        amount = intcomma(int(round(float(value or 0))))
    except (TypeError, ValueError):
        return value
    return f"{amount} {currency}".strip()


@register.filter
def initials(user_or_text):
    if hasattr(user_or_text, "get_full_name"):
        text = user_or_text.get_full_name() or user_or_text.email
    else:
        text = str(user_or_text or "")
    parts = [p for p in text.replace("@", " ").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


_CODES = {
    "paris": "PAR", "lyon": "LYS", "marseille": "MRS", "toulouse": "TLS", "bordeaux": "BOD", "lille": "LIL",
    "nantes": "NTE", "strasbourg": "SXB", "montpellier": "MPL", "rennes": "RNS", "nice": "NCE",
    "montreal": "YUL", "quebec": "YQB", "ottawa": "YOW", "toronto": "YYZ", "sherbrooke": "YSC",
    "casablanca": "CMN", "rabat": "RBA", "marrakech": "RAK", "fes": "FEZ", "tanger": "TNG",
    "istanbul": "IST", "ankara": "ESB", "dakar": "DKR", "abidjan": "ABJ", "tunis": "TUN",
    "bruxelles": "BRU", "pekin": "PEK", "shanghai": "SHA", "moscou": "MOW", "berlin": "BER",
    "france": "PAR", "canada": "YUL", "maroc": "CMN", "turquie": "IST", "senegal": "DKR",
    "cote d'ivoire": "ABJ", "tunisie": "TUN", "belgique": "BRU", "chine": "PEK", "russie": "MOW",
    "allemagne": "BER", "etats-unis": "NYC", "usa": "NYC", "algerie": "ALG", "ghana": "ACC",
}


def _norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().strip().lower()


@register.filter
def place_code(city_or_country):
    key = _norm(city_or_country)
    if key in _CODES:
        return _CODES[key]
    letters = "".join(c for c in key if c.isalpha())
    return (letters[:3] or "???").upper()


@register.filter
def pct(value, total):
    try:
        return round(float(value) * 100 / float(total)) if float(total) else 0
    except (TypeError, ValueError):
        return 0


@register.filter
def split_pairs(value: str):
    """"a:A|b:B" → [("a", "A"), ("b", "B")] (petites listes de choix dans les gabarits)."""
    return [tuple(part.split(":", 1)) for part in value.split("|") if ":" in part]


@register.filter
def pretty_json(value):
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
