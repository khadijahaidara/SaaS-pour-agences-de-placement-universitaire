from django import forms
from django.contrib.auth import get_user_model
from django.forms import inlineformset_factory

from dossiers.forms import StyledFormMixin
from dossiers.models import DocumentTemplate, StageTemplate, WorkflowTemplate

User = get_user_model()


class TeamMemberForm(StyledFormMixin, forms.ModelForm):
    role = forms.ChoiceField(
        label="Rôle",
        choices=[(User.Role.COUNSELOR, "Conseiller"), (User.Role.AGENCY_ADMIN, "Responsable d'agence")],
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "role"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec ce courriel.")
        return email


class WorkflowTemplateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = WorkflowTemplate
        fields = ["name", "destination_country", "description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class _StyledInline(StyledFormMixin, forms.ModelForm):
    pass


StageFormSet = inlineformset_factory(
    WorkflowTemplate, StageTemplate, form=_StyledInline,
    fields=["order", "name", "default_duration_days", "student_instructions"],
    widgets={"student_instructions": forms.Textarea(attrs={"rows": 1})},
    extra=2, can_delete=True,
)

DocumentFormSet = inlineformset_factory(
    WorkflowTemplate, DocumentTemplate, form=_StyledInline,
    fields=["name", "description", "is_required", "stage_order"],
    extra=3, can_delete=True,
)
