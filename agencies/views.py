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

from .forms import (
    AgencySettingsForm,
    AgencySignupForm,
    DocumentFormSet,
    StageFormSet,
    TeamMemberForm,
    WorkflowTemplateForm,
)
from .models import TRIAL_DAYS, Agency
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
    return render(request, "agencies/settings.html", {"form": form, "agency": agency})


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
