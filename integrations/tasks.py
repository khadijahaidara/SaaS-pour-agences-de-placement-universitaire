from celery import shared_task
from django.utils import timezone

from .models import WebhookDelivery


@shared_task(ignore_result=True)
def deliver_webhook(delivery_id: int):
    from .services import attempt

    delivery = WebhookDelivery.objects.select_related("endpoint").filter(
        pk=delivery_id, status=WebhookDelivery.Status.PENDING).first()
    if delivery is None or not delivery.endpoint.is_active:
        return
    if delivery.attempts and delivery.next_attempt_at and delivery.next_attempt_at > timezone.now():
        return  # une nouvelle tentative est déjà planifiée
    attempt(delivery)


def retry_due_deliveries(now=None, limit: int = 200) -> dict:
    """Tâche planifiée (chaque minute avec Celery beat) : relance les livraisons arrivées à échéance."""
    from .services import attempt

    now = now or timezone.now()
    due = (WebhookDelivery.objects.select_related("endpoint")
           .filter(status=WebhookDelivery.Status.PENDING, next_attempt_at__lte=now, endpoint__is_active=True)
           .order_by("next_attempt_at")[:limit])
    ok = ko = 0
    for d in due:
        attempt(d)
        if d.status == WebhookDelivery.Status.SUCCESS:
            ok += 1
        else:
            ko += 1
    WebhookDelivery.objects.filter(created_at__lt=now - timezone.timedelta(days=30)).delete()
    return {"livres": ok, "echecs": ko}


@shared_task(ignore_result=True)
def retry_webhooks():
    """Version Celery beat (chaque minute), sans trace TaskRun pour ne pas encombrer la console."""
    retry_due_deliveries()
