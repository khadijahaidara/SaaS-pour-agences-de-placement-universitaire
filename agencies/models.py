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
        "couleur principale", max_length=7, default="#2C4A8C", validators=[validate_hex_color],
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
    def initials(self) -> str:
        words = [w for w in re.split(r"\s+", self.name) if w]
        return "".join(w[0] for w in words[:2]).upper() or "A"
