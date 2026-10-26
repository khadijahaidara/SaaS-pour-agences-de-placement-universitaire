"""Inscription des agences, paramètres, équipe et modèles de parcours."""
import mimetypes

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.core.cache import cache
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST

from dossiers.models import WorkflowTemplate
from dossiers.permissions import agency_admin_required
from dossiers.services import build_invitation_path

from api.models import ApiKey

from .customization import portal_login_url
from .forms import (
    AgencySettingsForm,
    AgencySignupForm,
    ApiKeyForm,
    CustomFieldForm,
    DocumentFormSet,
    InstallmentFormSet,
    MessageTemplateForm,
    ReceiptSettingsForm,
    ServiceOfferForm,
    StageFormSet,
    TeamMemberForm,
    WebAddressForm,
    WorkflowTemplateForm,
)
from .models import TRIAL_DAYS, Agency, CustomField, MessageTemplate, ServiceOffer
from .services import AgencyCreationError, create_agency

User = get_user_model()

SIGNUPS_PER_HOUR_PER_IP = 5


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")


def signup(request):
    """Création d'un espace agence en libre-service, avec essai gratuit."""
    if request.user.is_authenticated:
        return redirect("home")
    form = AgencySignupForm(request.POST or None)
    if request.method == "POST":
        key = f"signup-ip:{_client_ip(request)}"
        attempts = cache.get(key, 0)
        if attempts >= SIGNUPS_PER_HOUR_PER_IP:
            form.add_error(None, "Trop de créations d'espace depuis cette connexion. Réessayez dans une heure.")
        elif form.is_valid():
            cd = form.cleaned_data
            try:
                agency, admin = create_agency(
                    name=cd["agency_name"], city=cd["city"], phone=cd["phone"], admin_email=cd["email"],
                    admin_first_name=cd["first_name"], admin_last_name=cd["last_name"],
                    admin_password=cd["password"], source="self_signup",
                )
            except AgencyCreationError as e:
                form.add_error("email", str(e))
            else:
                cache.set(key, attempts + 1, 3600)
                login(request, admin, backend="django.contrib.auth.backends.ModelBackend")
                messages.success(request, f"Bienvenue ! Votre espace « {agency.name} » est prêt. Essai gratuit de {TRIAL_DAYS} jours.")
                return redirect("dossiers:dashboard")
    return render(request, "agencies/signup.html", {"form": form, "trial_days": TRIAL_DAYS})


@cache_control(public=True, max_age=3600)
def agency_logo(request, slug):
    """Le logo est public (affiché sur la page de connexion du portail)."""
    agency = get_object_or_404(Agency, slug=slug, is_active=True)
    if not agency.logo or not agency.logo.storage.exists(agency.logo.name):
        raise Http404
    content_type = mimetypes.guess_type(agency.logo.name)[0] or "image/png"
    if not content_type.startswith("image/") or content_type == "image/svg+xml":
        raise Http404
    return FileResponse(agency.logo.open("rb"), content_type=content_type)


@agency_admin_required
def agency_settings(request):
    agency = request.user.agency
    form = AgencySettingsForm(request.POST or None, request.FILES or None, instance=agency)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Paramètres de l'agence enregistrés.")
        return redirect("agencies:settings")
    return render(request, "agencies/settings.html", {
        "form": form, "agency": agency, "tab": "general", "portal_url": portal_login_url(agency, request)})


@agency_admin_required
def team(request):
    agency = request.user.agency
    form = TeamMemberForm(request.POST or None)
    invitation_url = None
    if request.method == "POST" and form.is_valid():
        member = form.save(commit=False)
        member.agency = agency
        member.set_unusable_password()
        member.save()
        invitation_url = request.build_absolute_uri(build_invitation_path(member))
        messages.success(request, f"{member} ajouté. Transmettez-lui le lien d'activation.")
        form = TeamMemberForm()
    members = User.objects.filter(agency=agency, role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR]).order_by("last_name")
    return render(request, "agencies/team.html", {"form": form, "members": members, "invitation_url": invitation_url})


@require_POST
@agency_admin_required
def toggle_member(request, user_id):
    member = get_object_or_404(User, pk=user_id, agency=request.user.agency,
                               role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR])
    if member == request.user:
        messages.error(request, "Vous ne pouvez pas désactiver votre propre compte.")
    else:
        member.is_active = not member.is_active
        member.save(update_fields=["is_active"])
        messages.success(request, f"{member} {'réactivé' if member.is_active else 'désactivé'}.")
    return redirect("agencies:team")


@agency_admin_required
def member_invitation(request, user_id):
    member = get_object_or_404(User, pk=user_id, agency=request.user.agency,
                               role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR])
    members = User.objects.filter(agency=request.user.agency, role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR]).order_by("last_name")
    return render(request, "agencies/team.html", {
        "form": TeamMemberForm(), "members": members,
        "invitation_url": request.build_absolute_uri(build_invitation_path(member)),
    })


@agency_admin_required
def workflow_list(request):
    templates = WorkflowTemplate.objects.filter(agency=request.user.agency).prefetch_related("stages", "documents")
    return render(request, "agencies/workflow_list.html", {"templates": templates})


@agency_admin_required
def workflow_edit(request, pk=None):
    agency = request.user.agency
    instance = get_object_or_404(WorkflowTemplate, pk=pk, agency=agency) if pk else WorkflowTemplate(agency=agency)
    form = WorkflowTemplateForm(request.POST or None, instance=instance)
    stages = StageFormSet(request.POST or None, instance=instance, prefix="stages")
    docs = DocumentFormSet(request.POST or None, instance=instance, prefix="docs")
    if request.method == "POST" and form.is_valid() and stages.is_valid() and docs.is_valid():
        orders = [f.cleaned_data["order"] for f in stages.forms
                  if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if len(orders) != len(set(orders)):
            messages.error(request, "Deux étapes ne peuvent pas avoir le même numéro d'ordre.")
        else:
            with transaction.atomic():
                tpl = form.save()
                stages.instance = tpl
                docs.instance = tpl
                stages.save()
                docs.save()
            messages.success(request, "Parcours enregistré. Il s'appliquera aux prochains dossiers.")
            return redirect("agencies:workflows")
    return render(request, "agencies/workflow_edit.html", {"form": form, "stages": stages, "docs": docs, "instance": instance})


# --------------------------------------------------------------------------- #
# Reçus et adresse web
# --------------------------------------------------------------------------- #
@agency_admin_required
def receipt_settings(request):
    agency = request.user.agency
    form = ReceiptSettingsForm(request.POST or None, instance=agency)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Réglages des reçus enregistrés. Ils s'appliquent aux prochains paiements.")
        return redirect("agencies:receipts")
    from django.utils import timezone
    example = f"{agency.effective_receipt_prefix}-{timezone.localdate().year}-0001"
    return render(request, "agencies/receipts.html", {"form": form, "agency": agency, "tab": "receipts", "example": example})


@agency_admin_required
def web_address(request):
    from django.conf import settings as dj_settings

    agency = request.user.agency
    form = WebAddressForm(request.POST or None, instance=agency)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Adresse web enregistrée.")
        return redirect("agencies:web_address")
    return render(request, "agencies/web_address.html", {
        "form": form, "agency": agency, "tab": "web", "base_domain": dj_settings.BASE_DOMAIN,
        "portal_url": portal_login_url(agency, request),
    })


# --------------------------------------------------------------------------- #
# Prestations
# --------------------------------------------------------------------------- #
@agency_admin_required
def offer_list(request):
    offers = ServiceOffer.objects.filter(agency=request.user.agency).prefetch_related("installments")
    return render(request, "agencies/offers.html", {"offers": offers, "tab": "offers"})


@agency_admin_required
def offer_edit(request, pk=None):
    agency = request.user.agency
    instance = get_object_or_404(ServiceOffer, pk=pk, agency=agency) if pk else ServiceOffer(agency=agency)
    form = ServiceOfferForm(request.POST or None, instance=instance, agency=agency)
    installments = InstallmentFormSet(request.POST or None, instance=instance, prefix="inst")
    if request.method == "POST" and form.is_valid() and installments.is_valid():
        with transaction.atomic():
            offer = form.save()
            installments.instance = offer
            installments.save()
        messages.success(request, f"Prestation « {offer.name} » enregistrée.")
        return redirect("agencies:offers")
    return render(request, "agencies/offer_edit.html", {"form": form, "installments": installments,
                                                        "instance": instance, "tab": "offers"})


# --------------------------------------------------------------------------- #
# Champs personnalisés
# --------------------------------------------------------------------------- #
@agency_admin_required
def field_list(request):
    fields = CustomField.objects.filter(agency=request.user.agency)
    return render(request, "agencies/fields.html", {"fields": fields, "tab": "fields"})


@agency_admin_required
def field_edit(request, pk=None):
    agency = request.user.agency
    instance = get_object_or_404(CustomField, pk=pk, agency=agency) if pk else CustomField(agency=agency)
    form = CustomFieldForm(request.POST or None, instance=instance, agency=agency)
    if request.method == "POST" and form.is_valid():
        field = form.save()
        messages.success(request, f"Champ « {field.label} » enregistré.")
        return redirect("agencies:fields")
    return render(request, "agencies/field_edit.html", {"form": form, "instance": instance, "tab": "fields"})


# --------------------------------------------------------------------------- #
# Modèles de messages
# --------------------------------------------------------------------------- #
@agency_admin_required
def template_list(request):
    templates = MessageTemplate.objects.filter(agency=request.user.agency)
    return render(request, "agencies/templates.html", {"templates": templates, "tab": "messages"})


@agency_admin_required
def template_edit(request, pk=None):
    agency = request.user.agency
    instance = get_object_or_404(MessageTemplate, pk=pk, agency=agency) if pk else MessageTemplate(agency=agency)
    form = MessageTemplateForm(request.POST or None, instance=instance, agency=agency)
    if request.method == "POST" and form.is_valid():
        tpl = form.save()
        messages.success(request, f"Modèle « {tpl.name} » enregistré.")
        return redirect("agencies:templates")
    return render(request, "agencies/template_edit.html", {
        "form": form, "instance": instance, "tab": "messages", "variables": MessageTemplate.VARIABLES})


# --------------------------------------------------------------------------- #
# Clés API
# --------------------------------------------------------------------------- #
@agency_admin_required
def api_keys(request):
    agency = request.user.agency
    form = ApiKeyForm(request.POST or None)
    new_key = None
    if request.method == "POST" and form.is_valid():
        if ApiKey.objects.filter(agency=agency, revoked_at__isnull=True).count() >= 10:
            messages.error(request, "Maximum 10 clés actives. Révoquez une clé inutilisée.")
        else:
            _, new_key = ApiKey.generate(agency=agency, name=form.cleaned_data["name"], created_by=request.user)
            messages.success(request, "Clé créée. Copiez-la maintenant : elle ne sera plus jamais affichée.")
            form = ApiKeyForm()
    keys = ApiKey.objects.filter(agency=agency).select_related("created_by")
    return render(request, "agencies/api_keys.html", {"form": form, "keys": keys, "new_key": new_key, "tab": "api"})


@require_POST
@agency_admin_required
def api_key_revoke(request, pk):
    key = get_object_or_404(ApiKey, pk=pk, agency=request.user.agency, revoked_at__isnull=True)
    key.revoke()
    messages.success(request, f"Clé « {key.name} » révoquée : elle ne fonctionne plus.")
    return redirect("agencies:api_keys")
