"""Webhooks de l'agence : configuration, test, journal des livraisons."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from audit.services import record
from billing.services import has_feature
from dossiers.permissions import agency_perm_required

from . import services
from .forms import WebhookForm
from .models import EVENTS, MAX_CONSECUTIVE_FAILURES, WebhookDelivery, WebhookEndpoint, new_secret

MAX_ENDPOINTS = 10


def _endpoint(request, pk):
    return get_object_or_404(WebhookEndpoint, pk=pk, agency=request.user.agency)


@agency_perm_required("integrations.manage")
def webhooks(request):
    agency = request.user.agency
    feature = has_feature(agency, "webhooks")
    endpoints = WebhookEndpoint.objects.filter(agency=agency)
    for e in endpoints:
        e.recent = list(e.deliveries.all()[:20])
        e.success_rate = (round(sum(1 for d in e.recent if d.status == "success") * 100 / len(e.recent))
                          if e.recent else None)
    form = WebhookForm()
    return render(request, "integrations/webhooks.html", {
        "endpoints": endpoints, "form": form, "feature": feature, "events": EVENTS, "tab": "webhooks",
    })


@agency_perm_required("integrations.manage")
def webhook_edit(request, pk=None):
    agency = request.user.agency
    if not has_feature(agency, "webhooks"):
        messages.error(request, "Les webhooks sont inclus à partir de la formule Pro.")
        return redirect("integrations:webhooks")
    instance = _endpoint(request, pk) if pk else WebhookEndpoint(agency=agency, created_by=request.user)
    if not pk and WebhookEndpoint.objects.filter(agency=agency).count() >= MAX_ENDPOINTS:
        messages.error(request, f"Maximum {MAX_ENDPOINTS} webhooks par agence.")
        return redirect("integrations:webhooks")
    form = WebhookForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        endpoint = form.save()
        record("webhook.updated" if pk else "webhook.created", agency=agency, target=endpoint,
               metadata={"url": endpoint.url[:120]})
        messages.success(request, "Webhook enregistré. Envoyez un test pour vérifier la réception.")
        return redirect("integrations:webhook_detail", pk=endpoint.pk)
    return render(request, "integrations/webhook_edit.html", {"form": form, "instance": instance, "tab": "webhooks"})


@agency_perm_required("integrations.manage")
def webhook_detail(request, pk):
    endpoint = _endpoint(request, pk)
    deliveries = endpoint.deliveries.all()[:50]
    return render(request, "integrations/webhook_detail.html", {
        "endpoint": endpoint, "deliveries": deliveries, "tab": "webhooks", "max_failures": MAX_CONSECUTIVE_FAILURES,
    })


@require_POST
@agency_perm_required("integrations.manage")
def webhook_test(request, pk):
    endpoint = _endpoint(request, pk)
    delivery = services.send_test(endpoint)
    if delivery.status == WebhookDelivery.Status.SUCCESS:
        messages.success(request, f"Test reçu par votre serveur (HTTP {delivery.response_status}, {delivery.duration_ms} ms).")
    else:
        messages.error(request, f"Échec du test : {delivery.last_error or 'réponse HTTP ' + str(delivery.response_status)}.")
    return redirect("integrations:webhook_detail", pk=pk)


@require_POST
@agency_perm_required("integrations.manage")
def webhook_toggle(request, pk):
    endpoint = _endpoint(request, pk)
    endpoint.is_active = not endpoint.is_active
    if endpoint.is_active:
        endpoint.consecutive_failures, endpoint.disabled_reason = 0, ""
    endpoint.save(update_fields=["is_active", "consecutive_failures", "disabled_reason"])
    record("webhook.updated", agency=endpoint.agency, target=endpoint,
           metadata={"etat": "activé" if endpoint.is_active else "suspendu"})
    messages.success(request, "Webhook réactivé." if endpoint.is_active else "Webhook suspendu.")
    return redirect("integrations:webhook_detail", pk=pk)


@require_POST
@agency_perm_required("integrations.manage")
def webhook_rotate(request, pk):
    endpoint = _endpoint(request, pk)
    endpoint.secret = new_secret()
    endpoint.save(update_fields=["secret"])
    record("webhook.updated", agency=endpoint.agency, target=endpoint, metadata={"secret": "renouvelé"})
    messages.success(request, "Nouveau secret de signature généré : mettez-le à jour sur votre serveur.")
    return redirect("integrations:webhook_detail", pk=pk)


@require_POST
@agency_perm_required("integrations.manage")
def webhook_delete(request, pk):
    endpoint = _endpoint(request, pk)
    record("webhook.deleted", agency=endpoint.agency, metadata={"url": endpoint.url[:120]})
    endpoint.delete()
    messages.success(request, "Webhook supprimé.")
    return redirect("integrations:webhooks")


@require_POST
@agency_perm_required("integrations.manage")
def delivery_resend(request, pk, delivery_id):
    endpoint = _endpoint(request, pk)
    delivery = get_object_or_404(endpoint.deliveries, pk=delivery_id)
    new = services.redeliver(delivery)
    if new.status == WebhookDelivery.Status.SUCCESS:
        messages.success(request, "Événement renvoyé avec succès.")
    else:
        messages.warning(request, "Renvoi en échec : une nouvelle tentative est planifiée automatiquement.")
    return redirect("integrations:webhook_detail", pk=pk)
