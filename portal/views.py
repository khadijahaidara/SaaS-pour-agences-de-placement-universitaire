"""Portail étudiant : avancement, prochaine action, pièces, paiements."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from agencies.customization import display_custom_data
from dossiers import services
from dossiers.forms import DocumentUploadForm
from dossiers.models import Dossier, DocumentRequest
from dossiers.permissions import get_dossier_for, student_required


@student_required
def home(request):
    dossiers = Dossier.objects.for_user(request.user)
    if dossiers.count() == 1:
        return redirect("portal:dossier", pk=dossiers.first().pk)
    return render(request, "portal/home.html", {"dossiers": dossiers})


@student_required
def dossier(request, pk):
    d = get_dossier_for(request.user, pk)
    return render(request, "portal/dossier.html", {
        "dossier": d,
        "stages": d.stages.all(),
        "current_stage": d.current_stage,
        "next_action": d.next_action_for_student(),
        "documents": d.document_requests.select_related("stage").prefetch_related("files"),
        "fees": d.fees.all(),
        "payments": d.payments.filter(cancelled_at__isnull=True),
        "events": d.events.filter(visible_to_student=True)[:20],
        "upload_form": DocumentUploadForm(),
        "is_open": d.status in {Dossier.Status.ACTIVE, Dossier.Status.BLOCKED},
        "custom_rows": display_custom_data(d, for_student=True),
    })


@require_POST
@student_required
def upload(request, pk, doc_id):
    d = get_dossier_for(request.user, pk)
    doc = get_object_or_404(d.document_requests, pk=doc_id)
    form = DocumentUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        for e in form.errors.get("file", []):
            messages.error(request, f"{doc.name} : {e}")
        return redirect("portal:dossier", pk=d.pk)
    if doc.status not in {DocumentRequest.Status.REQUESTED, DocumentRequest.Status.REJECTED,
                          DocumentRequest.Status.SUBMITTED}:
        messages.error(request, "Cette pièce est déjà validée.")
        return redirect("portal:dossier", pk=d.pk)
    try:
        services.submit_document(doc, request.user, form.cleaned_data["file"])
    except services.BusinessRuleError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"« {doc.name} » bien reçu. Votre conseiller va le vérifier.")
    return redirect("portal:dossier", pk=d.pk)
