"""Envoi signé des webhooks, protégé contre les requêtes vers le réseau interne (SSRF).

Signature : en-tête X-Neuralis-Signature: t=<horodatage>,v1=<HMAC-SHA256(secret, "<t>.<corps>")>.
"""
import hashlib
import hmac
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from django.conf import settings


class UnsafeURL(ValueError):
    pass


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def validate_url(url: str) -> None:
    """Refuse les schémas non http(s) et les adresses privées / locales (sauf en développement)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeURL("L'URL doit commencer par https://")
    if parsed.scheme != "https" and not settings.WEBHOOK_ALLOW_PRIVATE:
        raise UnsafeURL("Seules les URL en https:// sont acceptées.")
    if settings.WEBHOOK_ALLOW_PRIVATE:
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeURL("Nom de domaine introuvable.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast \
                or ip.is_unspecified:
            raise UnsafeURL("Cette adresse pointe vers un réseau privé : refusée.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # une redirection pourrait viser le réseau interne
        return None


def post(url: str, secret: str, payload: dict, *, event: str, delivery_id: str) -> tuple[int | None, str, str, int]:
    """Envoie le webhook. Retourne (statut HTTP, corps de réponse tronqué, erreur, durée en ms)."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    timestamp = int(time.time())
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "NEURALIS-Mobility-Webhooks/1.0",
        "X-Neuralis-Event": event,
        "X-Neuralis-Delivery": delivery_id,
        "X-Neuralis-Signature": sign(secret, timestamp, body),
    })
    start = time.monotonic()
    try:
        validate_url(url)
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(request, timeout=settings.WEBHOOK_TIMEOUT) as resp:
            text = resp.read(2000).decode("utf-8", "replace")
            return resp.status, text, "", int((time.monotonic() - start) * 1000)
    except urllib.error.HTTPError as exc:
        text = exc.read(2000).decode("utf-8", "replace") if exc.fp else ""
        return exc.code, text, f"HTTP {exc.code}", int((time.monotonic() - start) * 1000)
    except UnsafeURL as exc:
        return None, "", str(exc), 0
    except Exception as exc:  # délai dépassé, DNS, TLS…
        return None, "", f"{type(exc).__name__} : {exc}"[:300], int((time.monotonic() - start) * 1000)
