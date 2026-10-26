import math
import re
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

TRIAL_DAYS = 14


def validate_hex_color(value: str) -> None:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value or ""):
        raise ValidationError("Couleur invalide : utilisez le format #RRGGBB.")


RESERVED_SUBDOMAINS = {"www", "api", "admin", "console", "app", "mail", "static", "media", "neuralis", "support"}


def validate_subdomain(value: str) -> None:
    if value in RESERVED_SUBDOMAINS:
        raise ValidationError("Ce sous-domaine est réservé.")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])?", value or ""):
        raise ValidationError("3 à 40 caractères : lettres minuscules, chiffres et tirets.")


def agency_logo_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    return f"logos/{uuid.uuid4().hex}.{ext}"


class Agency(models.Model):
    """Une agence cliente du SaaS (locataire). Toutes les données métier y sont rattachées."""

    class Plan(models.TextChoices):
        TRIAL = "trial", "Essai gratuit"
        ACTIVE = "active", "Abonnement actif"
        SUSPENDED = "suspended", "Suspendu"

    name = models.CharField("nom de l'agence", max_length=150)
    slug = models.SlugField(unique=True)
    city = models.CharField("ville", max_length=100, default="Bamako")
    country = models.CharField("pays", max_length=100, default="Mali")
    address = models.CharField("adresse / quartier", max_length=200, blank=True)
    phone = models.CharField("téléphone", max_length=30, blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=30, blank=True)
    email = models.EmailField("courriel de contact", blank=True)
    website = models.URLField("site web", blank=True)
    currency = models.CharField("devise", max_length=10, default="FCFA")
    logo = models.ImageField("logo", upload_to=agency_logo_path, blank=True)
    brand_color = models.CharField(
        "couleur principale", max_length=7, default="#1F4FB8", validators=[validate_hex_color],
        help_text="Utilisée sur le portail de vos étudiants.",
    )
    welcome_message = models.CharField(
        "message d'accueil des étudiants", max_length=255, blank=True,
        help_text="Affiché en haut du portail étudiant.",
    )
    plan = models.CharField("formule", max_length=20, choices=Plan.choices, default=Plan.TRIAL)
    trial_ends_at = models.DateTimeField("fin de l'essai", null=True, blank=True)
    paid_until = models.DateField("abonnement payé jusqu'au", null=True, blank=True)
    is_active = models.BooleanField("active", default=True)
    signup_source = models.CharField(max_length=30, blank=True, help_text="self_signup, console, cli…")
    # --- Adresse web propre -------------------------------------------------
    subdomain = models.SlugField(
        "sous-domaine", max_length=40, unique=True, null=True, blank=True, validators=[validate_subdomain],
        help_text="Adresse du type horizon.neuralis-mobility.com (lettres, chiffres et tirets).",
    )
    custom_domain = models.CharField(
        "domaine personnalisé", max_length=120, unique=True, null=True, blank=True,
        help_text="Ex. : suivi.monagence.ml — à configurer avec l'équipe NEURALIS.",
    )
    # --- Reçus à l'image de l'agence ----------------------------------------
    receipt_prefix = models.CharField(
        "préfixe des reçus", max_length=8, blank=True,
        help_text="Ex. : HZN donne des reçus HZN-2026-0001. Vide : initiales de l'agence.",
    )
    legal_info = models.CharField("mentions légales", max_length=255, blank=True,
                                  help_text="RCCM, NIF, agrément… imprimés sur les reçus.")
    receipt_footer = models.CharField("pied de page des reçus", max_length=255, blank=True)
    # --- Sécurité -------------------------------------------------------------
    require_2fa = models.BooleanField(
        "double authentification obligatoire", default=False,
        help_text="Chaque membre de l'équipe doit activer une application d'authentification.",
    )
    trial_warning_sent_at = models.DateTimeField(null=True, blank=True, editable=False)
    trial_ended_notice_sent_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "agence"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def start_trial(self, days: int = TRIAL_DAYS):
        self.plan = self.Plan.TRIAL
        self.trial_ends_at = timezone.now() + timedelta(days=days)

    @property
    def trial_days_left(self) -> int | None:
        if self.plan != self.Plan.TRIAL or not self.trial_ends_at:
            return None
        seconds = (self.trial_ends_at - timezone.now()).total_seconds()
        return max(0, math.ceil(seconds / 86400))

    @property
    def is_operational(self) -> bool:
        """L'agence peut-elle créer de nouveaux dossiers ? (lecture toujours possible)"""
        if not self.is_active or self.plan == self.Plan.SUSPENDED:
            return False
        if self.plan == self.Plan.TRIAL:
            return self.trial_ends_at is None or self.trial_ends_at > timezone.now()
        if self.plan == self.Plan.ACTIVE and self.paid_until:
            return self.paid_until >= timezone.localdate()
        return True

    @property
    def effective_receipt_prefix(self) -> str:
        prefix = re.sub(r"[^A-Z0-9]", "", (self.receipt_prefix or "").upper())
        return prefix or re.sub(r"[^A-Z0-9]", "", self.initials) or "REC"

    @property
    def initials(self) -> str:
        words = [w for w in re.split(r"\s+", self.name) if w]
        return "".join(w[0] for w in words[:2]).upper() or "A"


# --------------------------------------------------------------------------- #
# Personnalisation par agence
# --------------------------------------------------------------------------- #
class ServiceOffer(models.Model):
    """Prestation vendue par l'agence (ex. « Pack France complet »), avec son échéancier."""

    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="offers")
    name = models.CharField("nom de la prestation", max_length=120)
    description = models.CharField("description", max_length=255, blank=True)
    destination_country = models.CharField("destination", max_length=100, blank=True,
                                           help_text="Laisser vide si la prestation vaut pour toutes les destinations.")
    is_active = models.BooleanField("proposée", default=True)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name"]
        constraints = [models.UniqueConstraint(fields=["agency", "name"], name="unique_offer_name_per_agency")]

    def __str__(self) -> str:
        return self.name

    @property
    def total(self):
        return sum((i.amount for i in self.installments.all()), 0)


class OfferInstallment(models.Model):
    offer = models.ForeignKey(ServiceOffer, on_delete=models.CASCADE, related_name="installments")
    label = models.CharField("échéance", max_length=120, help_text="Ex. : Acompte à l'inscription")
    amount = models.DecimalField("montant", max_digits=12, decimal_places=0)
    due_after_days = models.PositiveSmallIntegerField("à payer sous (jours)", default=0,
                                                      help_text="Nombre de jours après l'application au dossier.")

    class Meta:
        ordering = ["due_after_days", "id"]
        constraints = [models.CheckConstraint(name="installment_amount_positive", condition=models.Q(amount__gt=0))]

    def __str__(self) -> str:
        return f"{self.label} ({self.amount})"


class CustomField(models.Model):
    """Champ supplémentaire défini par l'agence sur ses dossiers (stocké dans Dossier.custom_data)."""

    class Type(models.TextChoices):
        TEXT = "text", "Texte court"
        LONGTEXT = "longtext", "Texte long"
        NUMBER = "number", "Nombre"
        DATE = "date", "Date"
        CHOICE = "choice", "Liste déroulante"
        BOOLEAN = "boolean", "Oui / non"

    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="custom_fields")
    label = models.CharField("intitulé", max_length=80)
    key = models.SlugField("identifiant", max_length=50, help_text="Utilisé dans les exports et l'API.")
    field_type = models.CharField("type", max_length=10, choices=Type.choices, default=Type.TEXT)
    choices = models.TextField("choix possibles", blank=True, help_text="Un choix par ligne (listes déroulantes).")
    help_text = models.CharField("aide", max_length=150, blank=True)
    required = models.BooleanField("obligatoire", default=False)
    visible_to_student = models.BooleanField("visible par l'étudiant", default=False)
    is_active = models.BooleanField("actif", default=True)
    order = models.PositiveSmallIntegerField("ordre", default=0)

    class Meta:
        ordering = ["order", "label"]
        constraints = [models.UniqueConstraint(fields=["agency", "key"], name="unique_custom_field_key")]

    def __str__(self) -> str:
        return self.label

    @property
    def choice_list(self) -> list[str]:
        return [c.strip() for c in self.choices.splitlines() if c.strip()]

    def clean(self):
        if self.field_type == self.Type.CHOICE and len(self.choice_list) < 2:
            raise ValidationError({"choices": "Indiquez au moins deux choix, un par ligne."})


class MessageTemplate(models.Model):
    """Message réutilisable envoyé aux étudiants (WhatsApp ou courriel), avec variables."""

    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp / SMS"
        EMAIL = "email", "Courriel"

    VARIABLES = {
        "prenom": "Prénom de l'étudiant",
        "nom": "Nom de l'étudiant",
        "reference": "Référence du dossier",
        "destination": "Pays de destination",
        "etape": "Étape en cours",
        "echeance": "Échéance de l'étape",
        "pieces_manquantes": "Pièces à fournir",
        "solde": "Reste à payer",
        "conseiller": "Nom du conseiller",
        "agence": "Nom de l'agence",
        "lien_portail": "Lien vers le portail étudiant",
    }

    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="message_templates")
    name = models.CharField("nom du modèle", max_length=80)
    channel = models.CharField("canal", max_length=10, choices=Channel.choices, default=Channel.WHATSAPP)
    subject = models.CharField("objet (courriel)", max_length=150, blank=True)
    body = models.TextField("message", help_text="Variables possibles : {prenom}, {etape}, {solde}…")
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["agency", "name"], name="unique_template_per_agency")]

    def __str__(self) -> str:
        return self.name


class Counter(models.Model):
    """Compteur séquentiel par agence (numéros de reçus), incrémenté sous verrou."""

    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="counters")
    name = models.CharField(max_length=30)
    year = models.PositiveSmallIntegerField()
    value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["agency", "name", "year"], name="unique_counter")]
