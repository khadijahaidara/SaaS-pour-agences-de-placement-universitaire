"""Espace agence : tableau de suivi, dossiers, pièces, étapes, paiements."""
import mimetypes
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    AdvanceStageForm,
    AssignForm,
    CancelPaymentForm,
    DocumentRequestForm,
    DocumentReviewForm,
    DocumentUploadForm,
    DossierCreateForm,
    DossierEditForm,
    DossierFilterForm,
    DueDateForm,
    FinanceFilterForm,
    FeeForm,
    PaymentForm,
    StatusForm,
)
from .models import DocumentFile, DocumentRequest, Dossier, DossierEvent, DossierStage, Notification, Payment, ServiceFee
from .permissions import agency_staff_required, get_dossier_for
from .services import BusinessRuleError


def _back(dossier, anchor=""):
    return HttpResponseRedirect(reverse("dossiers:detail", args=[dossier.pk]) + (f"#{anchor}" if anchor else ""))


def _form_errors(request, form):
    for field, errors in form.errors.items():
        label = form.fields[field].label if field in form.fields else ""
        for e in errors:
            messages.error(request, f"{label} : {e}" if label else e)


# --------------------------------------------------------------------------- #
# Tableau de suivi
# --------------------------------------------------------------------------- #
DONUT_COLORS = ["#1f4fb8", "#c98a2b", "#5b8def", "#9c3f1c", "#2f7d4f", "#6b7389"]


@agency_staff_required
def dashboard(request):
    user = request.user
    agency = user.agency
    scope = request.GET.get("scope", "all" if user.is_agency_admin else "mine")
    base = Dossier.objects.for_user(user)
    if scope == "mine":
        base = base.filter(counselor=user)
    open_qs = base.open().select_related("student", "counselor").prefetch_related("stages")

    today = timezone.localdate()
    priority = []
    for d in open_qs:
        alerts = d.alerts()
        if alerts:
            priority.append({"dossier": d, "alerts": alerts, "score": sum(a["weight"] for a in alerts)})
    priority.sort(key=lambda x: x["score"], reverse=True)

    agency_dossiers = Dossier.objects.for_user(user)
    fees = ServiceFee.objects.filter(dossier__in=agency_dossiers).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    paid = Payment.objects.filter(dossier__in=agency_dossiers, cancelled_at__isnull=True).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    month_start = today.replace(day=1)
    stats = {
        "open": base.open().count(),
        "blocked": base.filter(status=Dossier.Status.BLOCKED).count(),
        "to_review": DocumentRequest.objects.filter(dossier__in=base.open(), status=DocumentRequest.Status.SUBMITTED).count(),
        "overdue": DossierStage.objects.filter(
            dossier__in=base.open(), status=DossierStage.Status.IN_PROGRESS, due_date__lt=today
        ).count(),
        "completed": base.filter(status=Dossier.Status.COMPLETED).count(),
        "outstanding": fees - paid,
        "collected_month": Payment.objects.filter(dossier__in=agency_dossiers, cancelled_at__isnull=True,
                                                  paid_on__gte=month_start).aggregate(s=Sum("amount"))["s"] or 0,
    }
    by_stage = list(
        DossierStage.objects.filter(dossier__in=base.open(), status=DossierStage.Status.IN_PROGRESS)
        .values("name").annotate(n=Count("id")).order_by("-n")[:7]
    )
    max_stage = max([s["n"] for s in by_stage] + [1])
    for s in by_stage:
        s["pct"] = round(s["n"] * 100 / max_stage)

    dest_rows = list(base.open().values("destination_country").annotate(n=Count("id")).order_by("-n"))
    top, rest = dest_rows[:5], sum(r["n"] for r in dest_rows[5:])
    if rest:
        top.append({"destination_country": "Autres", "n": rest})
    total = sum(r["n"] for r in top) or 1
    acc, stops = 0, []
    for i, r in enumerate(top):
        r["color"] = DONUT_COLORS[i % len(DONUT_COLORS)]
        start = acc * 360 / total
        acc += r["n"]
        stops.append(f"{r['color']} {start:.1f}deg {acc * 360 / total:.1f}deg")
    donut = "conic-gradient(" + ", ".join(stops) + ")" if stops else "conic-gradient(var(--line) 0 360deg)"

    onboarding = None
    if user.is_agency_admin:
        steps = [
            {"label": "Ajouter votre logo et votre couleur", "done": bool(agency.logo), "url": reverse("agencies:settings")},
            {"label": "Inviter un conseiller", "done": agency.users.filter(role=user.Role.COUNSELOR).exists(), "url": reverse("agencies:team")},
            {"label": "Vérifier vos parcours", "done": agency.workflow_templates.filter(stages__isnull=False).count() > 0 and agency.dossiers.exists(), "url": reverse("agencies:workflows")},
            {"label": "Créer votre premier dossier", "done": agency.dossiers.exists(), "url": reverse("dossiers:create")},
        ]
        if not all(s["done"] for s in steps):
            onboarding = steps

    recent_events = DossierEvent.objects.filter(dossier__in=base).select_related("dossier__student", "actor")[:8]
    return render(request, "dossiers/dashboard.html", {
        "priority": priority[:25], "stats": stats, "by_stage": by_stage, "scope": scope,
        "destinations": top, "donut": donut, "dest_total": sum(r["n"] for r in top),
        "onboarding": onboarding, "recent_events": recent_events,
    })


# --------------------------------------------------------------------------- #
# Liste / création / détail
# --------------------------------------------------------------------------- #
def _filtered_dossiers(request):
    form = DossierFilterForm(request.GET or None, agency=request.user.agency)
    qs = Dossier.objects.for_user(request.user).select_related("student", "counselor")
    if form.is_valid():
        q = form.cleaned_data.get("q")
        if q:
            qs = qs.filter(
                Q(reference__icontains=q) | Q(student__first_name__icontains=q) | Q(student__last_name__icontains=q)
                | Q(student__email__icontains=q) | Q(institution__icontains=q) | Q(program__icontains=q)
            )
        if form.cleaned_data.get("status"):
            qs = qs.filter(status=form.cleaned_data["status"])
        if form.cleaned_data.get("destination"):
            qs = qs.filter(destination_country__icontains=form.cleaned_data["destination"])
        if form.cleaned_data.get("counselor"):
            qs = qs.filter(counselor=form.cleaned_data["counselor"])
    return form, qs


@agency_staff_required
def dossier_list(request):
    form, qs = _filtered_dossiers(request)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "dossiers/list.html", {"form": form, "page": page, "querystring": params.urlencode()})


# --------------------------------------------------------------------------- #
# Exports et finances
# --------------------------------------------------------------------------- #
def _csv_response(filename, header, rows):
    """CSV lisible directement par Excel (séparateur « ; », UTF-8 avec BOM)."""
    import csv

    from django.http import HttpResponse

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if v is None else _csv_safe(v) for v in row])
    return response


def _csv_safe(value):
    """Neutralise les formules (injection CSV) dans les cellules texte."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") and not text.lstrip("-").replace(" ", "").isdigit() else text


@agency_staff_required
def dossiers_export(request):
    _, qs = _filtered_dossiers(request)
    rows = []
    for d in qs.prefetch_related("stages", "fees", "payments"):
        stage = d.current_stage
        rows.append([
            d.reference, d.student.last_name, d.student.first_name, d.student.email, d.student.phone,
            d.destination_country, d.destination_city, d.institution, d.program, d.intake,
            d.get_status_display(), stage.name if stage else "", stage.due_date.strftime("%d/%m/%Y") if stage and stage.due_date else "",
            d.counselor.get_full_name() if d.counselor else "", int(d.total_fees()), int(d.total_paid()), int(d.balance()),
            timezone.localtime(d.created_at).strftime("%d/%m/%Y"),
        ])
    header = ["Référence", "Nom", "Prénom", "Courriel", "Téléphone", "Pays", "Ville", "Établissement", "Programme",
              "Rentrée", "Statut", "Étape en cours", "Échéance", "Conseiller", "Frais", "Payé", "Solde", "Ouvert le"]
    return _csv_response(f"dossiers-{timezone.localdate():%Y%m%d}.csv", header, rows)


def _period_bounds(period, start, end):
    today = timezone.localdate()
    if period == "month":
        return today.replace(day=1), today
    if period == "last_month":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    if period == "year":
        return today.replace(month=1, day=1), today
    if period == "custom":
        return start, end
    return None, None


def _filtered_payments(request):
    form = FinanceFilterForm(request.GET or None, agency=request.user.agency)
    qs = Payment.objects.filter(dossier__in=Dossier.objects.for_user(request.user)).select_related(
        "dossier__student", "dossier__counselor", "recorded_by")
    start = end = None
    if form.is_valid():
        cd = form.cleaned_data
        start, end = _period_bounds(cd.get("period") or "month", cd.get("start"), cd.get("end"))
        if cd.get("method"):
            qs = qs.filter(method=cd["method"])
        if cd.get("counselor"):
            qs = qs.filter(dossier__counselor=cd["counselor"])
    else:
        start, end = _period_bounds("month", None, None)
    if start:
        qs = qs.filter(paid_on__gte=start)
    if end:
        qs = qs.filter(paid_on__lte=end)
    return form, qs, start, end


@agency_staff_required
def finances(request):
    form, qs, start, end = _filtered_payments(request)
    valid = qs.filter(cancelled_at__isnull=True)
    total = valid.aggregate(s=Sum("amount"))["s"] or 0
    by_method = list(valid.values("method").annotate(total=Sum("amount"), n=Count("id")).order_by("-total"))
    labels = dict(Payment.Method.choices)
    top = max([m["total"] for m in by_method] + [1])
    for m in by_method:
        m["label"] = labels.get(m["method"], m["method"])
        m["pct"] = round(m["total"] * 100 / top)
    scope = Dossier.objects.for_user(request.user)
    fees = ServiceFee.objects.filter(dossier__in=scope).aggregate(s=Sum("amount"))["s"] or 0
    paid_all = Payment.objects.filter(dossier__in=scope, cancelled_at__isnull=True).aggregate(s=Sum("amount"))["s"] or 0
    debtors = []
    for d in scope.exclude(status=Dossier.Status.CANCELLED).select_related("student").prefetch_related("fees", "payments"):
        bal = d.balance()
        if bal > 0:
            debtors.append({"dossier": d, "balance": bal})
    debtors.sort(key=lambda x: x["balance"], reverse=True)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "dossiers/finances.html", {
        "form": form, "page": page, "querystring": params.urlencode(), "start": start, "end": end,
        "total": total, "count": valid.count(), "by_method": by_method, "outstanding": fees - paid_all,
        "debtors": debtors[:8], "debtors_count": len(debtors),
    })


@agency_staff_required
def payments_export(request):
    _, qs, start, end = _filtered_payments(request)
    rows = [[
        p.receipt_number, p.paid_on.strftime("%d/%m/%Y"), p.dossier.reference, p.dossier.student.get_full_name(),
        int(p.amount), p.get_method_display(), p.reference, p.recorded_by.get_full_name() if p.recorded_by else "",
        "Annulé" if p.is_cancelled else "Valide", p.cancellation_reason,
    ] for p in qs]
    header = ["Reçu", "Date", "Dossier", "Étudiant", "Montant", "Mode", "Référence", "Enregistré par", "État", "Motif d'annulation"]
    return _csv_response(f"paiements-{timezone.localdate():%Y%m%d}.csv", header, rows)


@agency_staff_required
def dossier_create(request):
    agency = request.user.agency
    if not agency.is_operational:
        messages.error(request, "Votre période d'essai est terminée : vos dossiers restent consultables, "
                                "mais la création de nouveaux dossiers nécessite un abonnement actif.")
        return redirect("dossiers:list")
    form = DossierCreateForm(request.POST or None, agency=agency,
                             initial={"counselor": request.user if not request.user.is_agency_admin else None})
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        counselor = cd["counselor"]
        if not request.user.is_agency_admin:
            # Un conseiller ne crée que des dossiers qu'il suit lui-même.
            counselor = request.user
        try:
            dossier, created = services.create_dossier(
                agency=agency, actor=request.user,
                student_email=cd["student_email"], student_first_name=cd["student_first_name"],
                student_last_name=cd["student_last_name"], student_phone=cd["student_phone"],
                workflow=cd["workflow"], counselor=counselor,
                destination_country=cd["destination_country"], destination_city=cd["destination_city"],
                institution=cd["institution"], program=cd["program"], intake=cd["intake"],
                guardian_name=cd["guardian_name"], guardian_phone=cd["guardian_phone"],
                internal_notes=cd["internal_notes"],
            )
        except BusinessRuleError as e:
            form.add_error("student_email", str(e))
        else:
            messages.success(request, f"Dossier {dossier.reference} créé.")
            if created:
                request.session["show_invitation_for"] = dossier.student_id
            return redirect("dossiers:detail", pk=dossier.pk)
    return render(request, "dossiers/create.html", {"form": form})


@agency_staff_required
def dossier_detail(request, pk):
    dossier = get_dossier_for(request.user, pk)
    invitation_url = None
    student = dossier.student
    if request.session.pop("show_invitation_for", None) == student.pk or request.GET.get("invitation"):
        if not student.has_usable_password() or request.GET.get("invitation"):
            invitation_url = request.build_absolute_uri(services.build_invitation_path(student))
    docs = dossier.document_requests.select_related("stage").prefetch_related("files")
    return render(request, "dossiers/detail.html", {
        "dossier": dossier,
        "stages": dossier.stages.all(),
        "current_stage": dossier.current_stage,
        "documents": docs,
        "fees": dossier.fees.all(),
        "payments": dossier.payments.select_related("recorded_by"),
        "events": dossier.events.select_related("actor")[:50],
        "alerts": dossier.alerts(),
        "invitation_url": invitation_url,
        "student_activated": student.has_usable_password(),
        "forms": {
            "request_doc": DocumentRequestForm(dossier=dossier, auto_id="req_%s"),
            "upload": DocumentUploadForm(),
            "status": StatusForm(auto_id="st_%s", initial={"status": dossier.status}),
            "assign": AssignForm(agency=dossier.agency, auto_id="as_%s", initial={"counselor": dossier.counselor}),
            "advance": AdvanceStageForm(auto_id="adv_%s"),
            "fee": FeeForm(auto_id="fee_%s"),
            "payment": PaymentForm(auto_id="pay_%s", initial={"paid_on": timezone.localdate()}),
            "cancel_payment": CancelPaymentForm(auto_id="cp_%s"),
            "due_date": DueDateForm(auto_id="due_%s"),
        },
        "is_open": dossier.status in {Dossier.Status.ACTIVE, Dossier.Status.BLOCKED},
    })


@agency_staff_required
def dossier_edit(request, pk):
    dossier = get_dossier_for(request.user, pk)
    form = DossierEditForm(request.POST or None, instance=dossier)
    if request.method == "POST" and form.is_valid():
        form.save()
        services.log_event(dossier, request.user, "note", "Informations du dossier mises à jour.", visible_to_student=False)
        messages.success(request, "Dossier mis à jour.")
        return redirect("dossiers:detail", pk=dossier.pk)
    return render(request, "dossiers/edit.html", {"form": form, "dossier": dossier})


# --------------------------------------------------------------------------- #
# Actions (POST uniquement)
# --------------------------------------------------------------------------- #
def _run(request, dossier, fn, success, anchor=""):
    try:
        fn()
    except BusinessRuleError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, success)
    return _back(dossier, anchor)


@require_POST
@agency_staff_required
def advance_stage(request, pk):
    dossier = get_dossier_for(request.user, pk)
    form = AdvanceStageForm(request.POST)
    if not form.is_valid():
        _form_errors(request, form)
        return _back(dossier, "etapes")
    return _run(request, dossier, lambda: services.advance_stage(
        dossier, request.user, next_due_date=form.cleaned_data["next_due_date"], force=form.cleaned_data["force"]
    ), "Le dossier a progressé. L'étudiant a été notifié.", "etapes")


@require_POST
@agency_staff_required
def stage_due_date(request, pk, stage_id):
    dossier = get_dossier_for(request.user, pk)
    stage = get_object_or_404(dossier.stages, pk=stage_id)
    form = DueDateForm(request.POST)
    if not form.is_valid():
        _form_errors(request, form)
        return _back(dossier, "etapes")
    return _run(request, dossier, lambda: services.update_stage_due_date(stage, request.user, form.cleaned_data["due_date"]),
                "Échéance modifiée.", "etapes")


@require_POST
@agency_staff_required
def set_status(request, pk):
    dossier = get_dossier_for(request.user, pk)
    form = StatusForm(request.POST)
    if not form.is_valid():
        _form_errors(request, form)
        return _back(dossier)
    return _run(request, dossier, lambda: services.set_status(
        dossier, request.user, form.cleaned_data["status"], form.cleaned_data["reason"]), "Statut mis à jour.")


@require_POST
@agency_staff_required
def assign(request, pk):
    if not request.user.is_agency_admin:
        messages.error(request, "Seul le responsable d'agence peut réaffecter un dossier.")
        return redirect("dossiers:detail", pk=pk)
    dossier = get_dossier_for(request.user, pk)
    form = AssignForm(request.POST, agency=dossier.agency)
    if not form.is_valid():
        _form_errors(request, form)
        return _back(dossier)
    return _run(request, dossier, lambda: services.assign_counselor(dossier, request.user, form.cleaned_data["counselor"]),
                "Conseiller mis à jour.")


@require_POST
@agency_staff_required
def request_document(request, pk):
    dossier = get_dossier_for(request.user, pk)
    form = DocumentRequestForm(request.POST, dossier=dossier)
    if not form.is_valid():
        _form_errors(request, form)
        return _back(dossier, "pieces")
    cd = form.cleaned_data
    return _run(request, dossier, lambda: services.request_document(
        dossier, request.user, name=cd["name"], description=cd["description"], stage=cd["stage"],
        is_required=cd["is_required"], due_date=cd["due_date"]), "Pièce demandée à l'étudiant.", "pieces")


@require_POST
@agency_staff_required
def review_document(request, pk, doc_id):
    dossier = get_dossier_for(request.user, pk)
    doc = get_object_or_404(dossier.document_requests, pk=doc_id)
    form = DocumentReviewForm(request.POST)
    if not form.is_valid():
        _form_errors(request, form)
        return _back(dossier, "pieces")
    approve = form.cleaned_data["decision"] == "approve"
    return _run(request, dossier, lambda: services.review_document(
        doc, request.user, approve=approve, reason=form.cleaned_data["reason"]),
        "Pièce validée." if approve else "Pièce retournée à l'étudiant avec le motif.", "pieces")


@require_POST
@agency_staff_required
def upload_document(request, pk, doc_id):
    """Le conseiller peut déposer une pièce reçue par WhatsApp ou au guichet."""
    dossier = get_dossier_for(request.user, pk)
    doc = get_object_or_404(dossier.document_requests, pk=doc_id)
    form = DocumentUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        _form_errors(request, form)
        return _back(dossier, "pieces")
    return _run(request, dossier, lambda: services.submit_document(doc, request.user, form.cleaned_data["file"]),
                "Pièce ajoutée au dossier.", "pieces")


@require_POST
@agency_staff_required
def add_fee(request, pk):
    dossier = get_dossier_for(request.user, pk)
    form = FeeForm(request.POST)
    if not form.is_valid():
        _form_errors(request, form)
        return _back(dossier, "paiements")
    cd = form.cleaned_data
    return _run(request, dossier, lambda: services.add_fee(
        dossier, request.user, label=cd["label"], amount=cd["amount"], due_date=cd["due_date"]),
        "Frais ajoutés.", "paiements")


@require_POST
@agency_staff_required
def record_payment(request, pk):
    dossier = get_dossier_for(request.user, pk)
    form = PaymentForm(request.POST)
    if not form.is_valid():
        _form_errors(request, form)
        return _back(dossier, "paiements")
    cd = form.cleaned_data
    return _run(request, dossier, lambda: services.record_payment(
        dossier, request.user, amount=cd["amount"], method=cd["method"], reference=cd["reference"], paid_on=cd["paid_on"]),
        "Paiement enregistré.", "paiements")


@require_POST
@agency_staff_required
def cancel_payment(request, pk, payment_id):
    dossier = get_dossier_for(request.user, pk)
    payment = get_object_or_404(dossier.payments, pk=payment_id)
    form = CancelPaymentForm(request.POST)
    if not form.is_valid():
        _form_errors(request, form)
        return _back(dossier, "paiements")
    return _run(request, dossier, lambda: services.cancel_payment(payment, request.user, form.cleaned_data["reason"]),
                "Paiement annulé.", "paiements")


# --------------------------------------------------------------------------- #
# Partagé agence / étudiant : fichiers, reçus, notifications
# --------------------------------------------------------------------------- #
@login_required
def document_download(request, file_id):
    f = get_object_or_404(DocumentFile.objects.select_related("request__dossier"), pk=file_id)
    # Vérifie que le dossier est visible par l'utilisateur (sinon 404).
    get_dossier_for(request.user, f.request.dossier_id)
    if not f.file or not f.file.storage.exists(f.file.name):
        raise Http404
    content_type = mimetypes.guess_type(f.original_name)[0] or "application/octet-stream"
    response = FileResponse(f.file.open("rb"), content_type=content_type,
                            as_attachment=request.GET.get("download") == "1", filename=f.original_name)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def payment_receipt(request, payment_id):
    payment = get_object_or_404(Payment.objects.select_related("dossier"), pk=payment_id)
    dossier = get_dossier_for(request.user, payment.dossier_id)
    return render(request, "dossiers/receipt.html", {"payment": payment, "dossier": dossier})


@login_required
def notifications(request):
    from accounts.views import layout_for

    qs = request.user.notifications.all()[:100]
    return render(request, "dossiers/notifications.html", {"notifications": qs, "layout": layout_for(request.user)})


@require_POST
@login_required
def notification_open(request, notif_id):
    n = get_object_or_404(Notification, pk=notif_id, recipient=request.user)
    n.is_read = True
    n.save(update_fields=["is_read"])
    if n.url and n.url.startswith("/"):
        return redirect(n.url)
    return redirect("dossiers:notifications")


@require_POST
@login_required
def notifications_mark_all(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return redirect("dossiers:notifications")
