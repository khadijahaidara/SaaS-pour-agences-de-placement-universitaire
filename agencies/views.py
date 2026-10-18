"""Paramètres de l'agence : équipe et modèles de parcours (responsable uniquement)."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from dossiers.models import WorkflowTemplate
from dossiers.permissions import agency_admin_required
from dossiers.services import build_invitation_path

from .forms import DocumentFormSet, StageFormSet, TeamMemberForm, WorkflowTemplateForm

User = get_user_model()


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
        messages.success(request, f"{member} ajouté. Transmettez-lui le lien d'activation ci-dessous.")
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
            messages.success(request, "Modèle enregistré. Il s'appliquera aux prochains dossiers créés.")
            return redirect("agencies:workflows")
    return render(request, "agencies/workflow_edit.html", {"form": form, "stages": stages, "docs": docs, "instance": instance})
