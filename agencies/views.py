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

from accounts.models import Role
from accounts.rbac import PERMISSION_GROUPS, default_role, ensure_default_roles
from api.models import ApiKey
from audit.services import record
from billing.services import check_quota, has_feature, usage
from core.exceptions import BusinessRuleError
from dossiers.models import WorkflowTemplate
from dossiers.permissions import agency_perm_required
from dossiers.services import build_invitation_path

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
    RoleForm,
    SecurityPolicyForm,
    ServiceOfferForm,
    StageFormSet,
    TeamMemberForm,
    WebAddressForm,
    WorkflowTemplateForm,
    access_choices,
    apply_access,
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


@agency_perm_required("settings.manage")
def agency_settings(request):
    agency = request.user.agency
    form = AgencySettingsForm(request.POST or None, request.FILES or None, instance=agency)
    if request.method == "POST" and form.is_valid():
        form.save()
        record("settings.updated", agency=agency, metadata={"section": "agence et portail"})
        messages.success(request, "Paramètres de l'agence enregistrés.")
        return redirect("agencies:settings")
    return render(request, "agencies/settings.html", {
        "form": form, "agency": agency, "tab": "general", "portal_url": portal_login_url(agency, request)})


@agency_perm_required("team.manage")
def team(request):
    agency = request.user.agency
    form = TeamMemberForm(request.POST or None, agency=agency)
    invitation_url = None
    if request.method == "POST" and form.is_valid():
        try:
            check_quota(agency, "staff")
            access = form.cleaned_data["access"]
            if access == "admin" and not request.user.is_agency_admin:
                raise BusinessRuleError("Seul un responsable d'agence peut nommer un autre responsable.")
            if access != "admin" and not request.user.is_agency_admin and not set(
                    Role.objects.get(pk=int(access.split(":", 1)[1]), agency=agency).permissions
            ) <= request.user.agency_permissions:
                raise BusinessRuleError("Vous ne pouvez pas attribuer un rôle plus puissant que le vôtre.")
        except BusinessRuleError as e:
            form.add_error(None, str(e))
        else:
            member = form.save(commit=False)
            member.agency = agency
            apply_access(member, form.cleaned_data["access"], agency)
            member.set_unusable_password()
            member.save()
            record("team.invited", agency=agency, target=member, metadata={"role": member.role_label})
            invitation_url = request.build_absolute_uri(build_invitation_path(member))
            messages.success(request, f"{member} ajouté. Transmettez-lui le lien d'activation.")
            form = TeamMemberForm(agency=agency)
    return _team_page(request, form, invitation_url)


def _team_page(request, form, invitation_url=None):
    agency = request.user.agency
    members = (User.objects.filter(agency=agency, role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR])
               .select_related("agency_role", "totp_device").order_by("last_name"))
    choices = access_choices(agency)
    for m in members:
        m.access_value = "admin" if m.role == User.Role.AGENCY_ADMIN else (
            f"role:{m.agency_role_id}" if m.agency_role_id else f"role:{default_role(agency).pk}")
    return render(request, "agencies/team.html", {
        "form": form, "members": members, "invitation_url": invitation_url, "access_choices": choices,
        "usage": usage(agency)["staff"],
    })


@require_POST
@agency_perm_required("team.manage")
def member_role(request, user_id):
    agency = request.user.agency
    member = get_object_or_404(User, pk=user_id, agency=agency, role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR])
    access = request.POST.get("access", "")
    valid = dict(access_choices(agency))
    if access not in valid:
        messages.error(request, "Rôle invalide.")
    elif member == request.user:
        messages.error(request, "Vous ne pouvez pas modifier votre propre rôle.")
    elif (access == "admin" or member.role == User.Role.AGENCY_ADMIN) and not request.user.is_agency_admin:
        messages.error(request, "Seul un responsable d'agence peut nommer ou retirer un responsable.")
    elif access != "admin" and not request.user.is_agency_admin and not set(
            Role.objects.get(pk=int(access.split(":", 1)[1]), agency=agency).permissions) <= request.user.agency_permissions:
        messages.error(request, "Vous ne pouvez pas attribuer un rôle plus puissant que le vôtre.")
    elif member.role == User.Role.AGENCY_ADMIN and access != "admin" and not User.objects.filter(
            agency=agency, role=User.Role.AGENCY_ADMIN, is_active=True).exclude(pk=member.pk).exists():
        messages.error(request, "L'agence doit garder au moins un responsable actif.")
    else:
        before = member.role_label
        apply_access(member, access, agency)
        member.save(update_fields=["role", "agency_role"])
        record("team.role_changed", agency=agency, target=member, metadata={"avant": before, "apres": member.role_label})
        messages.success(request, f"{member} : rôle « {member.role_label} ».")
    return redirect("agencies:team")


@require_POST
@agency_perm_required("team.manage")
def toggle_member(request, user_id):
    member = get_object_or_404(User, pk=user_id, agency=request.user.agency,
                               role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR])
    if member == request.user:
        messages.error(request, "Vous ne pouvez pas désactiver votre propre compte.")
    else:
        if not member.is_active:
            try:
                check_quota(request.user.agency, "staff")
            except BusinessRuleError as e:
                messages.error(request, str(e))
                return redirect("agencies:team")
        member.is_active = not member.is_active
        member.save(update_fields=["is_active"])
        record("team.toggled", agency=member.agency, target=member,
               metadata={"acces": "réactivé" if member.is_active else "désactivé"})
        messages.success(request, f"{member} {'réactivé' if member.is_active else 'désactivé'}.")
    return redirect("agencies:team")


@agency_perm_required("team.manage")
def member_invitation(request, user_id):
    member = get_object_or_404(User, pk=user_id, agency=request.user.agency,
                               role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR])
    return _team_page(request, TeamMemberForm(agency=request.user.agency),
                      request.build_absolute_uri(build_invitation_path(member)))


@agency_perm_required("workflows.manage")
def workflow_list(request):
    templates = WorkflowTemplate.objects.filter(agency=request.user.agency).prefetch_related("stages", "documents")
    return render(request, "agencies/workflow_list.html", {"templates": templates})


@agency_perm_required("workflows.manage")
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
@agency_perm_required("settings.manage")
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


@agency_perm_required("settings.manage")
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
        "portal_url": portal_login_url(agency, request), "custom_domain_feature": has_feature(agency, "custom_domain"),
    })


# --------------------------------------------------------------------------- #
# Prestations
# --------------------------------------------------------------------------- #
@agency_perm_required("settings.manage")
def offer_list(request):
    offers = ServiceOffer.objects.filter(agency=request.user.agency).prefetch_related("installments")
    return render(request, "agencies/offers.html", {"offers": offers, "tab": "offers"})


@agency_perm_required("settings.manage")
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
@agency_perm_required("settings.manage")
def field_list(request):
    fields = CustomField.objects.filter(agency=request.user.agency)
    return render(request, "agencies/fields.html", {"fields": fields, "tab": "fields"})


@agency_perm_required("settings.manage")
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
@agency_perm_required("settings.manage")
def template_list(request):
    templates = MessageTemplate.objects.filter(agency=request.user.agency)
    return render(request, "agencies/templates.html", {"templates": templates, "tab": "messages"})


@agency_perm_required("settings.manage")
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
@agency_perm_required("integrations.manage")
def api_keys(request):
    agency = request.user.agency
    form = ApiKeyForm(request.POST or None)
    new_key = None
    feature = has_feature(agency, "api")
    if request.method == "POST" and form.is_valid():
        if not feature:
            messages.error(request, "L'API n'est pas incluse dans votre formule.")
        elif ApiKey.objects.filter(agency=agency, revoked_at__isnull=True).count() >= 10:
            messages.error(request, "Maximum 10 clés actives. Révoquez une clé inutilisée.")
        else:
            key_obj, new_key = ApiKey.generate(agency=agency, name=form.cleaned_data["name"], created_by=request.user)
            record("api_key.created", agency=agency, target=key_obj)
            messages.success(request, "Clé créée. Copiez-la maintenant : elle ne sera plus jamais affichée.")
            form = ApiKeyForm()
    keys = ApiKey.objects.filter(agency=agency).select_related("created_by")
    return render(request, "agencies/api_keys.html", {"form": form, "keys": keys, "new_key": new_key, "tab": "api",
                                                     "feature": feature})


@require_POST
@agency_perm_required("integrations.manage")
def api_key_revoke(request, pk):
    key = get_object_or_404(ApiKey, pk=pk, agency=request.user.agency, revoked_at__isnull=True)
    key.revoke()
    record("api_key.revoked", agency=key.agency, target=key)
    messages.success(request, f"Clé « {key.name} » révoquée : elle ne fonctionne plus.")
    return redirect("agencies:api_keys")


# --------------------------------------------------------------------------- #
# Rôles et permissions
# --------------------------------------------------------------------------- #
@agency_perm_required("roles.manage")
def role_list(request):
    agency = request.user.agency
    ensure_default_roles(agency)
    from django.db.models import Count, Q

    roles = Role.objects.filter(agency=agency).annotate(
        n_members=Count("members", filter=Q(members__is_active=True, members__role=User.Role.COUNSELOR)))
    admins = User.objects.filter(agency=agency, role=User.Role.AGENCY_ADMIN, is_active=True).count()
    return render(request, "agencies/roles.html", {
        "roles": roles, "groups": PERMISSION_GROUPS, "tab": "roles", "admins": admins,
        "feature": has_feature(agency, "custom_roles"),
    })


@agency_perm_required("roles.manage")
def role_edit(request, pk=None):
    agency = request.user.agency
    feature = has_feature(agency, "custom_roles")
    instance = get_object_or_404(Role, pk=pk, agency=agency) if pk else Role(agency=agency)
    form = RoleForm(request.POST or None, instance=instance, agency=agency)
    if request.method == "POST":
        if not feature:
            messages.error(request, "Les rôles personnalisés sont inclus à partir de la formule Pro.")
            return redirect("agencies:roles")
        escalation = not request.user.is_agency_admin and (
            not set(instance.permissions or []) <= request.user.agency_permissions
            or not set(form.data.getlist("permissions")) <= request.user.agency_permissions)
        if escalation:
            form.add_error(None, "Vous ne pouvez pas accorder des permissions que vous n'avez pas vous-même.")
        if form.is_valid():
            role = form.save(commit=False)
            role.clean()
            role.save()
            record("role.saved", agency=agency, target=role, metadata={"permissions": len(role.permissions)})
            messages.success(request, f"Rôle « {role.name} » enregistré. Il s'applique immédiatement à ses membres.")
            return redirect("agencies:roles")
    selected = set(form["permissions"].value() or (instance.permissions if instance.pk else []))
    return render(request, "agencies/role_edit.html", {
        "form": form, "instance": instance, "groups": PERMISSION_GROUPS, "selected": selected,
        "tab": "roles", "feature": feature,
    })


@require_POST
@agency_perm_required("roles.manage")
def role_delete(request, pk):
    agency = request.user.agency
    role = get_object_or_404(Role, pk=pk, agency=agency)
    if role.is_system:
        messages.error(request, "Le rôle par défaut ne peut pas être supprimé.")
    else:
        fallback = default_role(agency)
        moved = User.objects.filter(agency_role=role).update(agency_role=fallback)
        record("role.deleted", agency=agency, metadata={"role": role.name, "membres_deplaces": moved})
        role.delete()
        messages.success(request, f"Rôle supprimé. {moved} membre(s) basculé(s) sur « {fallback.name} ».")
    return redirect("agencies:roles")


# --------------------------------------------------------------------------- #
# Politique de sécurité
# --------------------------------------------------------------------------- #
@agency_perm_required("settings.manage")
def security_settings(request):
    agency = request.user.agency
    feature = has_feature(agency, "enforce_2fa")
    form = SecurityPolicyForm(request.POST or None, instance=agency)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["require_2fa"] and not feature:
            messages.error(request, "La double authentification obligatoire est incluse à partir de la formule Pro.")
        elif form.cleaned_data["require_2fa"] and not request.user.has_2fa:
            messages.error(request, "Activez d'abord la double authentification sur votre propre compte.")
        else:
            form.save()
            record("security.updated", agency=agency, metadata={"2fa_obligatoire": "oui" if agency.require_2fa else "non"})
            messages.success(request, "Politique de sécurité enregistrée.")
            return redirect("agencies:security")
    members = (User.objects.filter(agency=agency, is_active=True, role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR])
               .select_related("totp_device", "agency_role").order_by("last_name"))
    protected = sum(1 for m in members if m.has_2fa)
    return render(request, "agencies/security.html", {
        "form": form, "agency": agency, "members": members, "protected": protected, "tab": "security",
        "feature": feature,
    })
