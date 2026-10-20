from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model

from .models import Dossier, DossierStage, Payment, WorkflowTemplate

User = get_user_model()

DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")

# Signatures de début de fichier acceptées (on ne se fie pas à l'extension seule).
_MAGIC = {
    "pdf": [b"%PDF"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "png": [b"\x89PNG\r\n\x1a\n"],
}


def validate_upload(f):
    name = f.name or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    allowed = settings.ALLOWED_UPLOAD_EXTENSIONS
    if ext not in allowed:
        raise forms.ValidationError(f"Format non accepté. Formats autorisés : {', '.join(allowed).upper()}.")
    if f.size > settings.MAX_UPLOAD_SIZE:
        raise forms.ValidationError(
            f"Fichier trop volumineux (max {settings.MAX_UPLOAD_SIZE // (1024 * 1024)} Mo). "
            "Astuce : photographiez le document en qualité moyenne ou utilisez un scanner mobile."
        )
    if f.size == 0:
        raise forms.ValidationError("Le fichier est vide.")
    head = f.read(16)
    f.seek(0)
    if not any(head.startswith(sig) for sig in _MAGIC.get(ext, [])):
        raise forms.ValidationError("Le contenu du fichier ne correspond pas à son format.")
    return f


class StyledFormMixin:
    """Ajoute la classe CSS commune à tous les champs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "check" if isinstance(field.widget, forms.CheckboxInput) else "input"
            field.widget.attrs.setdefault("class", css)


class DossierCreateForm(StyledFormMixin, forms.ModelForm):
    student_first_name = forms.CharField(label="Prénom de l'étudiant", max_length=150)
    student_last_name = forms.CharField(label="Nom de l'étudiant", max_length=150)
    student_email = forms.EmailField(label="Courriel de l'étudiant")
    student_phone = forms.CharField(label="Téléphone / WhatsApp", max_length=30, required=False)

    class Meta:
        model = Dossier
        fields = [
            "workflow", "counselor", "destination_country", "destination_city",
            "institution", "program", "intake", "guardian_name", "guardian_phone", "internal_notes",
        ]

    def __init__(self, *args, agency, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["workflow"].queryset = WorkflowTemplate.objects.filter(agency=agency, is_active=True)
        self.fields["workflow"].required = True
        self.fields["counselor"].queryset = User.objects.filter(
            agency=agency, is_active=True, role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR]
        )
        self.fields["destination_country"].required = False
        self.fields["destination_country"].help_text = "Laisser vide pour reprendre le pays du modèle."
        self.order_fields(["student_first_name", "student_last_name", "student_email", "student_phone"])


class DossierEditForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Dossier
        fields = [
            "destination_country", "destination_city", "institution", "program", "intake",
            "guardian_name", "guardian_phone", "internal_notes",
        ]


class DocumentRequestForm(StyledFormMixin, forms.Form):
    name = forms.CharField(label="Pièce demandée", max_length=150)
    description = forms.CharField(label="Précision", max_length=255, required=False)
    stage = forms.ModelChoiceField(label="Requise pour l'étape", queryset=DossierStage.objects.none(), required=False)
    is_required = forms.BooleanField(label="Obligatoire", required=False, initial=True)
    due_date = forms.DateField(label="À fournir avant le", required=False, widget=DATE_WIDGET)

    def __init__(self, *args, dossier, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stage"].queryset = dossier.stages.exclude(status=DossierStage.Status.DONE)


class DocumentUploadForm(StyledFormMixin, forms.Form):
    file = forms.FileField(label="Fichier (PDF, JPG ou PNG)", validators=[validate_upload])


class DocumentReviewForm(StyledFormMixin, forms.Form):
    decision = forms.ChoiceField(choices=[("approve", "Valider"), ("reject", "Retourner")], widget=forms.HiddenInput)
    reason = forms.CharField(label="Motif du retour", max_length=255, required=False)

    def clean(self):
        data = super().clean()
        if data.get("decision") == "reject" and not (data.get("reason") or "").strip():
            self.add_error("reason", "Indiquez ce que l'étudiant doit corriger.")
        return data


class StatusForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(label="Nouveau statut", choices=Dossier.Status.choices)
    reason = forms.CharField(label="Motif", max_length=255, required=False)


class AssignForm(StyledFormMixin, forms.Form):
    counselor = forms.ModelChoiceField(label="Conseiller", queryset=User.objects.none(), required=False)

    def __init__(self, *args, agency, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["counselor"].queryset = User.objects.filter(
            agency=agency, is_active=True, role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR]
        )


class AdvanceStageForm(StyledFormMixin, forms.Form):
    next_due_date = forms.DateField(label="Échéance de l'étape suivante", required=False, widget=DATE_WIDGET)
    force = forms.BooleanField(label="Forcer malgré les pièces manquantes (responsable uniquement)", required=False)


class DueDateForm(StyledFormMixin, forms.Form):
    due_date = forms.DateField(label="Nouvelle échéance", widget=DATE_WIDGET)


class FeeForm(StyledFormMixin, forms.Form):
    label = forms.CharField(label="Prestation", max_length=150)
    amount = forms.DecimalField(label="Montant", min_value=1, max_digits=12, decimal_places=0)
    due_date = forms.DateField(label="Échéance", required=False, widget=DATE_WIDGET)


class PaymentForm(StyledFormMixin, forms.Form):
    amount = forms.DecimalField(label="Montant reçu", min_value=1, max_digits=12, decimal_places=0)
    method = forms.ChoiceField(label="Mode", choices=Payment.Method.choices)
    reference = forms.CharField(label="Référence (transaction mobile, chèque…)", max_length=100, required=False)
    paid_on = forms.DateField(label="Date", required=False, widget=DATE_WIDGET)


class CancelPaymentForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(label="Motif d'annulation", max_length=255)


class DossierFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(label="Recherche", required=False,
                        widget=forms.TextInput(attrs={"placeholder": "Nom, courriel, référence, établissement…"}))
    status = forms.ChoiceField(label="Statut", required=False, choices=[("", "Tous les statuts")] + Dossier.Status.choices)
    destination = forms.CharField(label="Destination", required=False)
    counselor = forms.ModelChoiceField(label="Conseiller", required=False, queryset=User.objects.none(),
                                       empty_label="Tous les conseillers")

    def __init__(self, *args, agency, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["counselor"].queryset = User.objects.filter(
            agency=agency, role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR]
        )


class FinanceFilterForm(StyledFormMixin, forms.Form):
    PERIODS = [("month", "Ce mois-ci"), ("last_month", "Mois dernier"), ("year", "Cette année"),
               ("all", "Depuis le début"), ("custom", "Période personnalisée")]
    period = forms.ChoiceField(label="Période", choices=PERIODS, required=False, initial="month")
    start = forms.DateField(label="Du", required=False, widget=DATE_WIDGET)
    end = forms.DateField(label="Au", required=False, widget=DATE_WIDGET)
    method = forms.ChoiceField(label="Mode", required=False, choices=[("", "Tous les modes")] + Payment.Method.choices)
    counselor = forms.ModelChoiceField(label="Conseiller", required=False, queryset=User.objects.none(),
                                       empty_label="Tous les conseillers")

    def __init__(self, *args, agency, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["counselor"].queryset = User.objects.filter(
            agency=agency, role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR])
