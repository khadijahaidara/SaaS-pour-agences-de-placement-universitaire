"""Émission des événements et gestion des livraisons de webhooks."""
import logging
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import MAX_CONSECUTIVE_FAILURES, RETRY_DELAYS, WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)


def emit(agency, event: str, data: dict) -> int:
    """Crée une livraison par webhook actif abonné à l'événement, envoyée après validation de la transaction."""
    if agency is None:
        return 0
    from billing.services import has_feature

    endpoints = [e for e in WebhookEndpoint.objects.filter(agency=agency, is_active=True) if e.listens_to(event)]
    if not endpoints or not has_feature(agency, "webhooks"):
        return 0
    created = []
    for endpoint in endpoints:
        event_id = uuid.uuid4()
        payload = {"id": str(event_id), "type": event, "created": timezone.now().isoformat(),
                   "agency": agency.slug, "data": data}
        created.append(WebhookDelivery.objects.create(endpoint=endpoint, event=event, event_id=event_id,
                                                      payload=payload,
                                                      next_attempt_at=timezone.now() + timedelta(minutes=2)))
    ids = [d.pk for d in created]
    transaction.on_commit(lambda: _enqueue(ids))
    return len(created)


def _enqueue(ids):
    from .tasks import deliver_webhook

    for pk in ids:
        try:
            deliver_webhook.delay(pk)
        except Exception:  # broker indisponible : la tâche périodique reprendra la livraison
            logger.exception("Mise en file du webhook %s impossible", pk)


def attempt(delivery: WebhookDelivery) -> WebhookDelivery:
    """Une tentative d'envoi ; planifie la suivante en cas d'échec (backoff exponentiel).

    La livraison est d'abord « réservée » (bail de 15 min) pour qu'un worker et la tâche
    périodique ne l'envoient jamais deux fois en parallèle.
    """
    from .delivery import post

    claimed = WebhookDelivery.objects.filter(
        pk=delivery.pk, status=WebhookDelivery.Status.PENDING, attempts=delivery.attempts,
    ).update(next_attempt_at=timezone.now() + timedelta(minutes=15))
    if not claimed:
        return delivery
    endpoint = delivery.endpoint
    status, body, error, duration = post(endpoint.url, endpoint.secret, delivery.payload,
                                         event=delivery.event, delivery_id=str(delivery.event_id))
    delivery.attempts += 1
    delivery.response_status, delivery.response_body = status, body[:2000]
    delivery.last_error, delivery.duration_ms = error[:300], duration
    if status is not None and 200 <= status < 300:
        delivery.status, delivery.delivered_at, delivery.next_attempt_at = (
            WebhookDelivery.Status.SUCCESS, timezone.now(), None)
        if endpoint.consecutive_failures:
            WebhookEndpoint.objects.filter(pk=endpoint.pk).update(consecutive_failures=0)
    else:
        if delivery.attempts > len(RETRY_DELAYS):
            delivery.status, delivery.next_attempt_at = WebhookDelivery.Status.FAILED, None
        else:
            delivery.next_attempt_at = timezone.now() + timedelta(seconds=RETRY_DELAYS[delivery.attempts - 1])
        _register_failure(endpoint)
    delivery.save()
    return delivery


def _register_failure(endpoint: WebhookEndpoint):
    endpoint.refresh_from_db(fields=["consecutive_failures", "is_active"])
    endpoint.consecutive_failures += 1
    fields = ["consecutive_failures"]
    if endpoint.is_active and endpoint.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        endpoint.is_active = False
        endpoint.disabled_reason = f"Désactivé automatiquement après {MAX_CONSECUTIVE_FAILURES} échecs consécutifs."
        fields += ["is_active", "disabled_reason"]
        from audit.services import record
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        from dossiers.services import notify

        User = get_user_model()
        record("webhook.disabled", agency=endpoint.agency, target=endpoint)
        for admin in endpoint.agency.users.filter(role=User.Role.AGENCY_ADMIN, is_active=True):
            notify(admin, f"Webhook « {endpoint} » désactivé : {MAX_CONSECUTIVE_FAILURES} échecs consécutifs. "
                          "Vérifiez votre serveur puis réactivez-le.", url=reverse("integrations:webhooks"))
    endpoint.save(update_fields=fields)


def send_test(endpoint: WebhookEndpoint) -> WebhookDelivery:
    payload = {"id": str(uuid.uuid4()), "type": "ping", "created": timezone.now().isoformat(),
               "agency": endpoint.agency.slug, "data": {"message": "Test de votre webhook NEURALIS Mobility."}}
    delivery = WebhookDelivery.objects.create(endpoint=endpoint, event="ping", payload=payload,
                                              event_id=payload["id"])
    attempt(delivery)
    if delivery.status != WebhookDelivery.Status.SUCCESS:  # un test ne se relance pas tout seul
        delivery.status, delivery.next_attempt_at = WebhookDelivery.Status.FAILED, None
        delivery.save(update_fields=["status", "next_attempt_at"])
    return delivery


def redeliver(delivery: WebhookDelivery) -> WebhookDelivery:
    clone = WebhookDelivery.objects.create(endpoint=delivery.endpoint, event=delivery.event,
                                           event_id=delivery.event_id, payload=delivery.payload)
    return attempt(clone)


# --------------------------------------------------------------------------- #
# Charges utiles
# --------------------------------------------------------------------------- #
def dossier_data(dossier) -> dict:
    stage = dossier.current_stage
    return {
        "reference": dossier.reference, "status": dossier.status,
        "student": {"first_name": dossier.student.first_name, "last_name": dossier.student.last_name,
                    "email": dossier.student.email, "phone": dossier.student.phone},
        "destination_country": dossier.destination_country, "institution": dossier.institution,
        "program": dossier.program, "intake": dossier.intake,
        "counselor": dossier.counselor.email if dossier.counselor else None,
        "current_stage": stage.name if stage else None,
        "progress_percent": dossier.progress_percent(),
        "custom_data": dossier.custom_data or {},
    }


def emit_dossier(dossier, event: str, **extra) -> int:
    return emit(dossier.agency, event, {"dossier": dossier_data(dossier), **extra})
