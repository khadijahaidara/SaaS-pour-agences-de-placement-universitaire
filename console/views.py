"""Console NEURALIS : CRM de prospection et pilotage des agences clientes."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from functools import wraps

from agencies.models import Agency
from agencies.services import AgencyCreationError, create_agency
from dossiers.models import Dossier
from dossiers.services import build_invitation_path

from .forms import ActivityForm, AgencyPlanForm, ConvertForm, ImportForm, ProspectFilterForm, ProspectForm, StatusChangeForm
from .importer import import_prospects
from .models import Prospect, ProspectActivity

User = get_user_model()
CONTACT_KINDS = {"call", "whatsapp", "email", "visit", "demo"}


def platform_admin_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.role != User.Role.PLATFORM_ADMIN:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


@platform_admin_required
def dashboard(request):
    today = timezone.localdate()
    counts = dict(Prospect.objects.values_list("status").annotate(n=Count("id")))
    pipeline = [{"key": s, "label": Prospect.Status(s).label, "n": counts.get(s, 0)} for s in Prospect.PIPELINE]
    max_n = max([p["n"] for p in pipeline] + [1])
    for p in pipeline:
        p["pct"] = round(p["n"] * 100 / max_n)
    soon = timezone.now() + timedelta(days=3)
    stats = {
        "prospects": Prospect.objects.count(),
        "p1_open": Prospect.objects.filter(priority="P1").exclude(status__in=Prospect.CLOSED).count(),
        "due": Prospect.objects.filter(next_follow_up__lte=today).exclude(status__in=Prospect.CLOSED).count(),
        "agencies": Agency.objects.count(),
        "trials": Agency.objects.filter(plan=Agency.Plan.TRIAL, trial_ends_at__gt=timezone.now()).count(),
        "customers": Agency.objects.filter(plan=Agency.Plan.ACTIVE).count(),
        "dossiers": Dossier.objects.count(),
    }
    due = (Prospect.objects.filter(next_follow_up__lte=today).exclude(status__in=Prospect.CLOSED)
           .order_by("next_follow_up", "priority")[:10])
    p1_new = Prospect.objects.filter(priority="P1", status="new")[:10]
    expiring = Agency.objects.filter(plan=Agency.Plan.TRIAL, trial_ends_at__lte=soon, trial_ends_at__gt=timezone.now())
    recent = Agency.objects.order_by("-created_at")[:6]
    from core.scheduler import labels, registry

    from .models import TaskRun

    task_labels = labels()
    task_runs = [TaskRun.objects.filter(name=n).first() for n in registry()]
    task_runs = [t for t in task_runs if t]
    for t in task_runs:
        t.label = task_labels.get(t.name, t.name)
    return render(request, "console/dashboard.html", {
        "stats": stats, "pipeline": pipeline, "due": due, "p1_new": p1_new, "expiring": expiring, "recent": recent, "task_runs": task_runs,
    })


@platform_admin_required
def prospect_list(request):
    form = ProspectFilterForm(request.GET or None)
    qs = Prospect.objects.select_related("owner", "agency")
    if form.is_valid():
        cd = form.cleaned_data
        if cd.get("q"):
            q = cd["q"]
            qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q)
                           | Q(decision_maker__icontains=q) | Q(zone__icontains=q))
        for field in ("priority", "status", "segment"):
            if cd.get(field):
                qs = qs.filter(**{field: cd[field]})
        if cd.get("owner"):
            qs = qs.filter(owner=cd["owner"])
        if cd.get("due"):
            qs = qs.filter(next_follow_up__lte=timezone.localdate()).exclude(status__in=Prospect.CLOSED)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "console/prospect_list.html", {
        "form": form, "page": page, "querystring": params.urlencode(),
        "status_choices": Prospect.Status.choices, "total": qs.count(),
    })


@platform_admin_required
def prospect_detail(request, pk):
    prospect = get_object_or_404(Prospect.objects.select_related("owner", "agency"), pk=pk)
    invitation_url = None
    if request.session.pop("console_invitation_for", None) and prospect.agency:
        admin = prospect.agency.users.filter(role=User.Role.AGENCY_ADMIN).first()
        if admin:
            invitation_url = request.build_absolute_uri(build_invitation_path(admin))
    return render(request, "console/prospect_detail.html", {
        "prospect": prospect,
        "activities": prospect.activities.select_related("author"),
        "activity_form": ActivityForm(auto_id="act_%s"),
        "status_form": StatusChangeForm(auto_id="st_%s", initial={"status": prospect.status}),
        "convert_form": ConvertForm(auto_id="cv_%s", initial={
            "agency_name": prospect.name, "admin_email": prospect.first_email,
            "phone": (prospect.phone or "").split("/")[0].strip(),
        }),
        "invitation_url": invitation_url,
    })


@platform_admin_required
def prospect_edit(request, pk=None):
    prospect = get_object_or_404(Prospect, pk=pk) if pk else None
    form = ProspectForm(request.POST or None, instance=prospect)
    if request.method == "POST" and form.is_valid():
        prospect = form.save()
        messages.success(request, "Prospect enregistré.")
        return redirect("console:prospect_detail", pk=prospect.pk)
    return render(request, "console/prospect_form.html", {"form": form, "prospect": prospect})


@require_POST
@platform_admin_required
def prospect_status(request, pk):
    prospect = get_object_or_404(Prospect, pk=pk)
    form = StatusChangeForm(request.POST)
    if form.is_valid() and form.cleaned_data["status"] != prospect.status:
        new = form.cleaned_data["status"]
        reason = form.cleaned_data["reason"].strip()
        old_label = prospect.get_status_display()
        prospect.status = new
        if new in {"lost", "not_target"}:
            prospect.lost_reason = reason
            prospect.next_follow_up = None
        prospect.save()
        ProspectActivity.objects.create(
            prospect=prospect, kind=ProspectActivity.Kind.STATUS, author=request.user,
            summary=f"{old_label} → {prospect.get_status_display()}" + (f" ({reason})" if reason else ""),
        )
        messages.success(request, f"{prospect.name} : {prospect.get_status_display()}.")
    nxt = request.POST.get("next", "")
    if nxt.startswith("/console/"):
        return redirect(nxt)
    return redirect("console:prospect_detail", pk=prospect.pk)


@require_POST
@platform_admin_required
def prospect_activity(request, pk):
    prospect = get_object_or_404(Prospect, pk=pk)
    form = ActivityForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Le compte rendu est obligatoire.")
        return redirect("console:prospect_detail", pk=pk)
    cd = form.cleaned_data
    ProspectActivity.objects.create(prospect=prospect, kind=cd["kind"], summary=cd["summary"], author=request.user)
    fields = ["updated_at"]
    if cd["kind"] in CONTACT_KINDS:
        prospect.last_contact_at = timezone.now()
        fields.append("last_contact_at")
        if prospect.status == Prospect.Status.NEW:
            prospect.status = Prospect.Status.CONTACTED
            fields.append("status")
        if cd["kind"] == "demo" and prospect.status in {"new", "contacted", "demo_scheduled"}:
            prospect.status = Prospect.Status.DEMO_DONE
            fields.append("status")
    prospect.next_follow_up = cd["next_follow_up"]
    fields.append("next_follow_up")
    if prospect.owner_id is None:
        prospect.owner = request.user
        fields.append("owner")
    prospect.save(update_fields=list(dict.fromkeys(fields)))
    messages.success(request, "Activité enregistrée.")
    return redirect("console:prospect_detail", pk=pk)


@require_POST
@platform_admin_required
def prospect_convert(request, pk):
    prospect = get_object_or_404(Prospect, pk=pk)
    if prospect.agency_id:
        messages.info(request, "Ce prospect a déjà un espace agence.")
        return redirect("console:prospect_detail", pk=pk)
    form = ConvertForm(request.POST)
    if not form.is_valid():
        for errs in form.errors.values():
            for e in errs:
                messages.error(request, e)
        return redirect("console:prospect_detail", pk=pk)
    cd = form.cleaned_data
    try:
        create_agency(name=cd["agency_name"], admin_email=cd["admin_email"], admin_first_name=cd["admin_first_name"],
                      admin_last_name=cd["admin_last_name"], phone=cd["phone"], source="console", prospect=prospect)
    except AgencyCreationError as e:
        messages.error(request, str(e))
    else:
        request.session["console_invitation_for"] = prospect.pk
        messages.success(request, "Espace agence créé en essai gratuit. Envoyez le lien d'activation au responsable.")
    return redirect("console:prospect_detail", pk=pk)


@platform_admin_required
def prospect_import(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        f = form.cleaned_data["file"]
        try:
            result = import_prospects(f.read(), f.name)
        except (ValueError, KeyError) as e:
            form.add_error("file", f"Lecture impossible : {e}")
        except Exception:
            form.add_error("file", "Fichier illisible. Vérifiez qu'il s'agit bien d'un CSV ou d'un .docx contenant un tableau.")
        else:
            messages.success(request, f"{result['total']} prospects lus : {result['created']} ajoutés, {result['updated']} mis à jour.")
            return redirect("console:prospects")
    return render(request, "console/prospect_import.html", {"form": form})


@platform_admin_required
def agency_list(request):
    from billing.models import Plan, Subscription

    agencies = (Agency.objects.annotate(n_dossiers=Count("dossiers", distinct=True),
                                        n_users=Count("users", filter=Q(users__role__in=["agency_admin", "counselor"]), distinct=True))
                .select_related("subscription__plan").order_by("-created_at"))
    return render(request, "console/agency_list.html", {
        "agencies": agencies, "plan_actions": AgencyPlanForm.ACTIONS, "plans": Plan.objects.all(),
        "cycles": Subscription.Cycle.choices})


@require_POST
@platform_admin_required
def agency_plan(request, pk):
    agency = get_object_or_404(Agency, pk=pk)
    form = AgencyPlanForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Action inconnue.")
        return redirect("console:agencies")
    action = form.cleaned_data["action"]
    today = timezone.localdate()
    if action == "extend_trial":
        base = max(agency.trial_ends_at or timezone.now(), timezone.now())
        agency.plan = Agency.Plan.TRIAL
        agency.trial_ends_at = base + timedelta(days=14)
    elif action in {"activate_month", "activate_year"}:
        start = max(agency.paid_until or today, today)
        agency.plan = Agency.Plan.ACTIVE
        agency.paid_until = start + timedelta(days=30 if action == "activate_month" else 365)
        prospect = getattr(agency, "prospect", None)
        if prospect and prospect.status != Prospect.Status.WON:
            prospect.status = Prospect.Status.WON
            prospect.save(update_fields=["status", "updated_at"])
            ProspectActivity.objects.create(prospect=prospect, kind="status", author=request.user,
                                            summary="Abonnement activé — client gagné.")
    elif action == "suspend":
        agency.plan = Agency.Plan.SUSPENDED
    elif action == "reactivate":
        agency.plan = Agency.Plan.ACTIVE if agency.paid_until and agency.paid_until >= today else Agency.Plan.TRIAL
        if agency.plan == Agency.Plan.TRIAL and (not agency.trial_ends_at or agency.trial_ends_at < timezone.now()):
            agency.trial_ends_at = timezone.now() + timedelta(days=7)
    if action != "suspend" and agency.validated_at is None:
        agency.validated_at, agency.validated_by = timezone.now(), request.user
    agency.save()
    from audit.services import record

    record("agency.suspended" if action == "suspend" else "agency.approved", agency=agency, actor=request.user,
           metadata={"action": dict(AgencyPlanForm.ACTIONS)[action]})
    messages.success(request, f"{agency.name} : {dict(AgencyPlanForm.ACTIONS)[action].lower()} — fait.")
    return redirect("console:agencies")


# --------------------------------------------------------------------------- #
# Facturation des agences
# --------------------------------------------------------------------------- #
@platform_admin_required
def billing(request):
    from billing.models import Invoice, Plan, PlanChangeRequest, Subscription
    from django.db.models import Sum

    status = request.GET.get("statut", "")
    invoices = Invoice.objects.select_related("agency", "plan")
    if status in Invoice.Status.values:
        invoices = invoices.filter(status=status)
    page = Paginator(invoices, 30).get_page(request.GET.get("page"))
    active_subs = Subscription.objects.filter(agency__plan=Agency.Plan.ACTIVE, agency__is_active=True).select_related("plan")
    mrr = sum(int(s.plan.price_yearly / 12) if s.cycle == "yearly" else int(s.plan.price_monthly) for s in active_subs)
    today = timezone.localdate()
    stats = {
        "mrr": mrr, "arr": mrr * 12, "active": active_subs.count(),
        "due": Invoice.objects.filter(status=Invoice.Status.ISSUED).aggregate(s=Sum("amount"))["s"] or 0,
        "overdue": Invoice.objects.filter(status=Invoice.Status.ISSUED, due_on__lt=today).count(),
        "collected_month": Invoice.objects.filter(status=Invoice.Status.PAID, paid_on__gte=today.replace(day=1))
        .aggregate(s=Sum("amount"))["s"] or 0,
    }
    by_plan = list(active_subs.values("plan__name").annotate(n=Count("id")).order_by("-n"))
    pending_agencies = list(Agency.objects.filter(plan=Agency.Plan.PENDING, is_active=True)
                            .select_related("subscription__plan").order_by("created_at"))
    for a in pending_agencies:
        a.open_invoice = a.invoices.filter(status=Invoice.Status.ISSUED).first()
        a.admin = a.users.filter(role="agency_admin").first()
    return render(request, "console/billing.html", {
        "pending_agencies": pending_agencies,
        "page": page, "status": status, "statuses": Invoice.Status.choices, "stats": stats, "by_plan": by_plan,
        "requests": PlanChangeRequest.objects.filter(status=PlanChangeRequest.Status.PENDING)
        .select_related("agency", "plan", "requested_by"),
        "agencies": Agency.objects.filter(is_active=True).order_by("name"), "plans": Plan.objects.all(),
        "cycles": Subscription.Cycle.choices, "methods": Invoice.Method.choices, "today": today,
    })


@require_POST
@platform_admin_required
def invoice_create(request):
    from billing.models import Plan, PlanChangeRequest, Subscription
    from billing.services import issue_invoice

    agency = get_object_or_404(Agency, pk=request.POST.get("agency"))
    plan = get_object_or_404(Plan, pk=request.POST.get("plan"))
    cycle = request.POST.get("cycle") if request.POST.get("cycle") in Subscription.Cycle.values else "monthly"
    invoice = issue_invoice(agency, plan=plan, cycle=cycle, actor=request.user, notes=request.POST.get("notes", "")[:255])
    if request.POST.get("request"):
        PlanChangeRequest.objects.filter(pk=request.POST["request"], agency=agency).update(
            status=PlanChangeRequest.Status.DONE, handled_at=timezone.now())
    messages.success(request, f"Facture {invoice.number} émise pour {agency.name}. L'agence a été notifiée.")
    return redirect("console:billing")


@require_POST
@platform_admin_required
def invoice_paid(request, pk):
    from billing.models import Invoice
    from billing.services import mark_paid
    from dossiers.services import BusinessRuleError

    invoice = get_object_or_404(Invoice, pk=pk)
    method = request.POST.get("method") if request.POST.get("method") in Invoice.Method.values else Invoice.Method.OTHER
    try:
        paid_on = timezone.datetime.strptime(request.POST.get("paid_on", ""), "%Y-%m-%d").date()
    except ValueError:
        paid_on = None
    try:
        mark_paid(invoice, actor=request.user, method=method, reference=request.POST.get("reference", "")[:100],
                  paid_on=paid_on)
    except BusinessRuleError as e:
        messages.error(request, str(e))
    else:
        prospect = getattr(invoice.agency, "prospect", None)
        if prospect and prospect.status != Prospect.Status.WON:
            prospect.status = Prospect.Status.WON
            prospect.save(update_fields=["status", "updated_at"])
            ProspectActivity.objects.create(prospect=prospect, kind="status", author=request.user,
                                            summary=f"Facture {invoice.number} payée — client gagné.")
        messages.success(request, f"Facture {invoice.number} payée : {invoice.agency.name} est active.")
    return redirect("console:billing")


@require_POST
@platform_admin_required
def invoice_void(request, pk):
    from billing.models import Invoice
    from billing.services import void_invoice
    from dossiers.services import BusinessRuleError

    try:
        void_invoice(get_object_or_404(Invoice, pk=pk), actor=request.user, reason=request.POST.get("reason", ""))
    except BusinessRuleError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Facture annulée.")
    return redirect("console:billing")


@platform_admin_required
def invoice_pdf(request, pk):
    from billing.models import Invoice
    from billing.views import pdf_response

    return pdf_response(get_object_or_404(Invoice.objects.select_related("agency", "plan"), pk=pk))


@require_POST
@platform_admin_required
def agency_tier(request, pk):
    from billing.models import Plan, Subscription
    from billing.services import change_plan

    agency = get_object_or_404(Agency, pk=pk)
    plan = get_object_or_404(Plan, pk=request.POST.get("plan"))
    cycle = request.POST.get("cycle") if request.POST.get("cycle") in Subscription.Cycle.values else "monthly"
    change_plan(agency, plan=plan, cycle=cycle, actor=request.user)
    messages.success(request, f"{agency.name} passe en formule {plan.name}.")
    return redirect("console:agencies")



@require_POST
@platform_admin_required
def agency_approve(request, pk):
    """Ouvre l'accès sans paiement (essai accordé par NEURALIS)."""
    from agencies.services import approve_agency

    agency = get_object_or_404(Agency, pk=pk)
    days = int(request.POST.get("trial_days") or 14)
    approve_agency(agency, actor=request.user, trial_days=max(1, min(days, 60)))
    messages.success(request, f"{agency.name} : essai de {days} jours accordé, l'équipe est prévenue.")
    return redirect(request.POST.get("next") or "console:billing")


@require_POST
@platform_admin_required
def agency_reject(request, pk):
    from agencies.services import reject_agency

    agency = get_object_or_404(Agency, pk=pk)
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "Indiquez le motif du refus.")
    else:
        reject_agency(agency, actor=request.user, reason=reason)
        messages.success(request, f"Demande de {agency.name} refusée.")
    return redirect("console:billing")
