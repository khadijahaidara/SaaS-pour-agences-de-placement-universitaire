from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.forms import inlineformset_factory

from dossiers.forms import StyledFormMixin
from dossiers.models import DocumentTemplate, StageTemplate, WorkflowTemplate

from .models import Agency, CustomField, MessageTemplate, OfferInstallment, ServiceOffer

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
    accept_terms = forms.BooleanField(label="J'accepte les conditions d'utilisation et la politique de confidentialité",
                                      help_text="")
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


class ReceiptSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Agency
        fields = ["receipt_prefix", "legal_info", "receipt_footer"]

    def clean_receipt_prefix(self):
        value = (self.cleaned_data.get("receipt_prefix") or "").upper()
        if value and not value.isalnum():
            raise forms.ValidationError("Lettres et chiffres uniquement (ex. HZN).")
        return value


class WebAddressForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Agency
        fields = ["subdomain"]

    def clean_subdomain(self):
        value = (self.cleaned_data.get("subdomain") or "").strip().lower() or None
        if value and Agency.objects.exclude(pk=self.instance.pk).filter(subdomain=value).exists():
            raise forms.ValidationError("Ce sous-domaine est déjà utilisé par une autre agence.")
        return value


class ServiceOfferForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ServiceOffer
        fields = ["name", "destination_country", "description", "is_active"]

    def __init__(self, *args, agency, **kwargs):
        self.agency = agency
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if ServiceOffer.objects.filter(agency=self.agency, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Une prestation porte déjà ce nom.")
        return name


InstallmentFormSet = inlineformset_factory(
    ServiceOffer, OfferInstallment, form=type("_InstallmentForm", (StyledFormMixin, forms.ModelForm), {}),
    fields=["label", "amount", "due_after_days"], extra=2, can_delete=True, min_num=1, validate_min=True,
)


class CustomFieldForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CustomField
        fields = ["label", "key", "field_type", "choices", "help_text", "required", "visible_to_student", "order", "is_active"]
        widgets = {"choices": forms.Textarea(attrs={"rows": 3, "placeholder": "Un choix par ligne"})}

    def __init__(self, *args, agency, **kwargs):
        self.agency = agency
        super().__init__(*args, **kwargs)
        self.fields["key"].required = False
        self.fields["key"].help_text = "Laisser vide pour le générer depuis l'intitulé. Utilisé dans les exports et l'API."
        if self.instance.pk:
            self.fields["key"].disabled = True

    def clean(self):
        from django.utils.text import slugify

        data = super().clean()
        if not self.instance.pk:
            key = slugify(data.get("key") or data.get("label") or "").replace("-", "_")[:50]
            if not key:
                self.add_error("label", "Intitulé requis.")
            elif CustomField.objects.filter(agency=self.agency, key=key).exists():
                self.add_error("key", "Un champ utilise déjà cet identifiant.")
            data["key"] = key
            self.instance.key = key
        if data.get("field_type") == CustomField.Type.CHOICE:
            choices = [c for c in (data.get("choices") or "").splitlines() if c.strip()]
            if len(choices) < 2:
                self.add_error("choices", "Indiquez au moins deux choix, un par ligne.")
        return data


class MessageTemplateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = MessageTemplate
        fields = ["name", "channel", "subject", "body", "is_active"]
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, agency, **kwargs):
        self.agency = agency
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if MessageTemplate.objects.filter(agency=self.agency, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Un modèle porte déjà ce nom.")
        return name


class ApiKeyForm(StyledFormMixin, forms.Form):
    name = forms.CharField(label="Nom de la clé", max_length=80,
                           widget=forms.TextInput(attrs={"placeholder": "Ex. : Application mobile, Site web"}))


class TeamMemberForm(StyledFormMixin, forms.ModelForm):
    access = forms.ChoiceField(label="Rôle", help_text="Les permissions de chaque rôle se règlent dans « Rôles et permissions ».")

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone"]

    def __init__(self, *args, agency, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["access"].choices = access_choices(agency)
        self.fields["access"].widget.attrs["class"] = "input"
        for name in ("first_name", "last_name"):
            self.fields[name].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec ce courriel.")
        return email


def access_choices(agency):
    from accounts.models import Role
    from accounts.rbac import ensure_default_roles

    ensure_default_roles(agency)
    roles = [(f"role:{r.pk}", r.name) for r in Role.objects.filter(agency=agency)]
    return roles + [("admin", "Responsable d'agence (tous les droits)")]


def apply_access(member, access: str, agency):
    """Applique un choix « admin » ou « role:<id> » au membre (sans sauvegarder)."""
    from accounts.models import Role

    if access == "admin":
        member.role, member.agency_role = User.Role.AGENCY_ADMIN, None
    else:
        role = Role.objects.get(pk=int(access.split(":", 1)[1]), agency=agency)
        member.role, member.agency_role = User.Role.COUNSELOR, role
    member._agency_perms_cache = None


class RoleForm(StyledFormMixin, forms.ModelForm):
    permissions = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)

    class Meta:
        from accounts.models import Role

        model = Role
        fields = ["name", "description", "permissions"]

    def __init__(self, *args, agency, **kwargs):
        from accounts.rbac import PERMISSION_LABELS

        self.agency = agency
        super().__init__(*args, **kwargs)
        self.fields["permissions"].choices = list(PERMISSION_LABELS.items())
        self.instance.agency = agency

    def clean_name(self):
        from accounts.models import Role

        name = self.cleaned_data["name"].strip()
        if Role.objects.filter(agency=self.agency, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Un rôle porte déjà ce nom.")
        return name


class SecurityPolicyForm(forms.ModelForm):
    class Meta:
        model = Agency
        fields = ["require_2fa"]


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
