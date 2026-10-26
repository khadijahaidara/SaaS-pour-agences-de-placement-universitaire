"""Personnalisation par agence : prestations, champs personnalisés, messages, adresse web.

Toutes les règles liées à ces réglages vivent ici ; les vues et l'API les appellent.
"""
import datetime
import string
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django import forms
from django.conf import settings
from core.tasks import queue_email
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import number_format

from dossiers.models import DocumentRequest, DossierEvent, ServiceFee
from dossiers.services import BusinessRuleError, log_event, notify

from .models import CustomField, MessageTemplate, ServiceOffer


# --------------------------------------------------------------------------- #
# Adresse web de l'agence
# --------------------------------------------------------------------------- #
def agency_base_url(agency, request=None) -> str:
    """URL racine propre à l'agence (domaine personnalisé > sous-domaine > adresse principale)."""
    scheme = "https" if not settings.DEBUG else (request.scheme if request else "http")
    if agency.custom_domain:
        return f"{scheme}://{agency.custom_domain}"
    if settings.BASE_DOMAIN and agency.subdomain:
        port = ""
        if request is not None and ":" in request.get_host():
            port = ":" + request.get_host().rsplit(":", 1)[1]
        return f"{scheme}://{agency.subdomain}.{settings.BASE_DOMAIN}{port}"
    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")
    return ""


def portal_login_url(agency, request=None) -> str:
    base = agency_base_url(agency, request)
    path = reverse("accounts:login")
    if settings.BASE_DOMAIN and agency.subdomain or agency.custom_domain:
        return base + path
    return f"{base}{path}?agence={agency.slug}"


# --------------------------------------------------------------------------- #
# Prestations
# --------------------------------------------------------------------------- #
@transaction.atomic
def apply_offer(dossier, actor, offer: ServiceOffer) -> list[ServiceFee]:
    """Ajoute au dossier les frais de la prestation, avec les échéances de son échéancier."""
    if offer.agency_id != dossier.agency_id or not offer.is_active:
        raise BusinessRuleError("Prestation invalide.")
    installments = list(offer.installments.all())
    if not installments:
        raise BusinessRuleError("Cette prestation n'a pas encore d'échéancier.")
    today = timezone.localdate()
    fees = [
        ServiceFee.objects.create(
            dossier=dossier, label=f"{offer.name} — {i.label}", amount=i.amount,
            due_date=today + timedelta(days=i.due_after_days), offer=offer, created_by=actor,
        )
        for i in installments
    ]
    total = sum(f.amount for f in fees)
    cur = dossier.agency.currency
    log_event(dossier, actor, DossierEvent.Kind.PAYMENT,
              f"Prestation « {offer.name} » appliquée : {number_format(total, force_grouping=True)} {cur} "
              f"en {len(fees)} échéance{'s' if len(fees) > 1 else ''}.")
    notify(dossier.student, f"Votre prestation « {offer.name} » a été enregistrée ({number_format(total, force_grouping=True)} {cur}).",
           dossier=dossier, url=reverse("portal:dossier", args=[dossier.pk]))
    return fees


# --------------------------------------------------------------------------- #
# Champs personnalisés
# --------------------------------------------------------------------------- #
def active_fields(agency):
    return list(CustomField.objects.filter(agency=agency, is_active=True))


def build_form_field(cf: CustomField) -> forms.Field:
    common = {"label": cf.label, "required": cf.required, "help_text": cf.help_text}
    if cf.field_type == CustomField.Type.LONGTEXT:
        return forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), max_length=2000, **common)
    if cf.field_type == CustomField.Type.NUMBER:
        return forms.DecimalField(max_digits=14, decimal_places=2, **common)
    if cf.field_type == CustomField.Type.DATE:
        return forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), **common)
    if cf.field_type == CustomField.Type.CHOICE:
        return forms.ChoiceField(choices=[("", "—")] + [(c, c) for c in cf.choice_list], **common)
    if cf.field_type == CustomField.Type.BOOLEAN:
        return forms.BooleanField(**{**common, "required": False})
    return forms.CharField(max_length=255, **common)


def add_custom_fields(form, agency, initial_data: dict | None = None) -> list[str]:
    """Ajoute les champs personnalisés de l'agence au formulaire ; retourne les noms ajoutés."""
    names = []
    initial_data = initial_data or {}
    for cf in active_fields(agency):
        name = f"cf_{cf.key}"
        field = build_form_field(cf)
        css = "check" if isinstance(field.widget, forms.CheckboxInput) else "input"
        field.widget.attrs.setdefault("class", css)
        form.fields[name] = field
        value = initial_data.get(cf.key)
        if value not in (None, ""):
            form.initial[name] = deserialize(cf, value)
        names.append(name)
    return names


def serialize(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return value


def deserialize(cf: CustomField, value):
    if cf.field_type == CustomField.Type.DATE and isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            return None
    if cf.field_type == CustomField.Type.NUMBER:
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    return value


def collect_custom_data(form, agency, existing: dict | None = None) -> dict:
    """Valeurs nettoyées du formulaire → dict JSON (les champs désactivés sont conservés)."""
    data = dict(existing or {})
    for cf in active_fields(agency):
        name = f"cf_{cf.key}"
        if name in form.cleaned_data:
            value = form.cleaned_data[name]
            if value in (None, "") and cf.field_type != CustomField.Type.BOOLEAN:
                data.pop(cf.key, None)
            else:
                data[cf.key] = serialize(value)
    return data


def validate_custom_data(agency, payload: dict) -> dict:
    """Validation pour l'API : mêmes règles que les formulaires."""
    form = forms.Form(data={f"cf_{k}": ("on" if v is True else v) for k, v in (payload or {}).items() if v is not False})
    add_custom_fields(form, agency)
    unknown = set((payload or {}).keys()) - {cf.key for cf in active_fields(agency)}
    if unknown:
        raise BusinessRuleError(f"Champs inconnus : {', '.join(sorted(unknown))}")
    if not form.is_valid():
        errors = {k.removeprefix("cf_"): [str(e) for e in v] for k, v in form.errors.items()}
        raise BusinessRuleError(f"Champs personnalisés invalides : {errors}")
    return collect_custom_data(form, agency)


def display_custom_data(dossier, *, for_student=False) -> list[dict]:
    rows = []
    for cf in active_fields(dossier.agency):
        if for_student and not cf.visible_to_student:
            continue
        value = dossier.custom_data.get(cf.key)
        if value in (None, ""):
            continue
        if cf.field_type == CustomField.Type.BOOLEAN:
            shown = "Oui" if value else "Non"
        elif cf.field_type == CustomField.Type.DATE:
            d = deserialize(cf, value)
            shown = d.strftime("%d/%m/%Y") if d else value
        else:
            shown = value
        rows.append({"label": cf.label, "value": shown, "key": cf.key})
    return rows


# --------------------------------------------------------------------------- #
# Modèles de messages
# --------------------------------------------------------------------------- #
class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def message_context(dossier, request=None) -> dict:
    stage = dossier.current_stage
    missing = list(dossier.documents_awaiting_student().values_list("name", flat=True))
    cur = dossier.agency.currency
    return {
        "prenom": dossier.student.first_name or dossier.student.email,
        "nom": dossier.student.last_name,
        "reference": dossier.reference,
        "destination": dossier.destination_country,
        "etape": stage.name if stage else "—",
        "echeance": stage.due_date.strftime("%d/%m/%Y") if stage and stage.due_date else "—",
        "pieces_manquantes": ", ".join(missing) if missing else "aucune",
        "solde": f"{number_format(dossier.balance(), force_grouping=True)} {cur}",
        "conseiller": dossier.counselor.get_full_name() if dossier.counselor else dossier.agency.name,
        "agence": dossier.agency.name,
        "lien_portail": portal_login_url(dossier.agency, request),
    }


def render_text(text: str, context: dict) -> str:
    formatter = string.Formatter()
    try:
        return formatter.vformat(text, (), _SafeDict(context))
    except (ValueError, IndexError):
        return text  # accolades mal formées : on renvoie le texte tel quel


def whatsapp_link(phone: str, text: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 8:
        digits = "223" + digits
    return f"https://wa.me/{digits}?text={quote(text)}" if digits else f"https://wa.me/?text={quote(text)}"


@transaction.atomic
def record_message(dossier, actor, *, channel: str, subject: str, body: str, template=None) -> None:
    """Envoie (courriel) ou trace (WhatsApp) un message à l'étudiant et le journalise."""
    if not body.strip():
        raise BusinessRuleError("Le message est vide.")
    name = f" « {template.name} »" if template else ""
    if channel == MessageTemplate.Channel.EMAIL:
        student = dossier.student
        queue_email(subject.strip() or f"[{dossier.agency.name}] Votre dossier {dossier.reference}",
                    body, [student.email])
        log_event(dossier, actor, DossierEvent.Kind.NOTE, f"Courriel envoyé à l'étudiant{name}.", visible_to_student=False)
    else:
        log_event(dossier, actor, DossierEvent.Kind.NOTE, f"Message WhatsApp préparé pour l'étudiant{name}.",
                  visible_to_student=False)


def missing_documents(dossier):
    return dossier.document_requests.filter(
        status__in=[DocumentRequest.Status.REQUESTED, DocumentRequest.Status.REJECTED])
