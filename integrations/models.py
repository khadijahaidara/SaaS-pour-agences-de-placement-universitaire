"""Webhooks : l'agence reçoit les événements de ses dossiers sur ses propres outils."""
import secrets
import uuid

from django.conf import settings
from django.db import models

EVENTS = [
    ("dossier.created", "Dossier créé"),
    ("dossier.stage_changed", "Étape franchie"),
    ("dossier.status_changed", "Statut modifié"),
    ("dossier.assigned", "Dossier réaffecté"),
    ("document.submitted", "Pièce déposée"),
    ("document.reviewed", "Pièce validée ou refusée"),
    ("payment.recorded", "Paiement enregistré"),
    ("payment.cancelled", "Paiement annulé"),
]
EVENT_CODES = [code for code, _ in EVENTS]
MAX_CONSECUTIVE_FAILURES = 15
RETRY_DELAYS = [60, 300, 1800, 7200, 21600]  # 1 min, 5 min, 30 min, 2 h, 6 h → 6 tentatives au total


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(24)


class WebhookEndpoint(models.Model):
    agency = models.ForeignKey("agencies.Agency", on_delete=models.CASCADE, related_name="webhooks")
    url = models.URLField("URL de destination", max_length=500)
    description = models.CharField("description", max_length=120, blank=True)
    events = models.JSONField("événements", default=list, blank=True, help_text="Vide : tous les événements.")
    secret = models.CharField(max_length=80, default=new_secret)
    is_active = models.BooleanField("actif", default=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    disabled_reason = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "webhook"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.description or self.url

    def listens_to(self, event: str) -> bool:
        return not self.events or event in self.events

    @property
    def event_labels(self) -> list[str]:
        labels = dict(EVENTS)
        return [labels.get(e, e) for e in self.events] if self.events else ["Tous les événements"]


class WebhookDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        SUCCESS = "success", "Livré"
        FAILED = "failed", "Échec définitif"

    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries")
    event = models.CharField(max_length=40)
    event_id = models.UUIDField(default=uuid.uuid4, editable=False)
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    response_status = models.PositiveIntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "next_attempt_at"])]

    def __str__(self) -> str:
        return f"{self.event} → {self.endpoint}"
