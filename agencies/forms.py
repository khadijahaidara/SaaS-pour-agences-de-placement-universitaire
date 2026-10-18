from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.forms import inlineformset_factory

from dossiers.forms import StyledFormMixin
from dossiers.models import DocumentTemplate, StageTemplate, WorkflowTemplate

from .models import Agency

User = get_user_model()

MAX_LOGO_SIZE = 1024 * 1024  # 1 Mo


class AgencySignupForm(StyledFormMixin, forms.Form):
    agency_name = forms.CharField(label="Nom de l'agence", max_length=150,
                                  widget=forms.TextInput(attrs={"placeholder": "Ex. : Horizon Études Bamako", "autocomplete": "organization"}))
    city = forms.CharField(label="Ville", max_length=100, initial="Bamako")
    phone = forms.CharField(label="Téléphone / WhatsApp", max_length=30,
                            widget=forms.TextInput(attrs={"placeholder": "+223 …", "autocomplete": "tel"}))
    first_name = forms.CharField(label="Votre prénom", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "given-name"}))
    last_name = forms.CharField(label="Votre nom", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "family-name"}))
    email = forms.EmailField(label="Courriel professionnel", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password = forms.CharField(label="Mot de passe", strip=False,
                               widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                               help_text="8 caractères minimum, pas uniquement des chiffres.")
    accept_terms = forms.BooleanField(label="J'accepte les conditions d'utilisation et la politique de confidentialité")
    # Champ piège invisible : rempli uniquement par les robots.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec ce courriel.")
        return email

    def clean(self):
        data = super().clean()
        if data.get("website"):
            raise forms.ValidationError("Inscription refusée.")
        pwd = data.get("password")
        if pwd:
            user = User(email=data.get("email", ""), first_name=data.get("first_name", ""), last_name=data.get("last_name", ""))
            try:
                password_validation.validate_password(pwd, user)
            except forms.ValidationError as e:
                self.add_error("password", e)
        return data


class AgencySettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Agency
        fields = ["name", "city", "address", "phone", "whatsapp", "email", "website", "currency",
                  "logo", "brand_color", "welcome_message"]
        widgets = {"brand_color": forms.TextInput(attrs={"type": "color"})}

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and hasattr(logo, "size") and logo.size > MAX_LOGO_SIZE:
            raise forms.ValidationError("Logo trop lourd (1 Mo maximum).")
        return logo


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
        if User.objects.filter(email__iexact=email).exists():
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
