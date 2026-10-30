"""Formules d'abonnement, quotas et factures NEURALIS."""
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

FEATURES = [
    ("api", "API REST"),
    ("webhooks", "Webhooks"),
    ("custom_roles", "Rôles personnalisés"),
    ("audit_log", "Journal d'audit"),
    ("enforce_2fa", "Double authentification obligatoire"),
    ("custom_domain", "Domaine personnalisé"),
    ("white_label", "Marque blanche (sans mention NEURALIS)"),
    ("priority_support", "Support prioritaire"),
]
FEATURE_LABELS = dict(FEATURES)


class Plan(models.Model):
    """Formule commerciale (Starter, Pro, Business) : prix, limites et fonctionnalités."""

    code = models.SlugField(unique=True)
    name = models.CharField("nom", max_length=60)
    tagline = models.CharField("accroche", max_length=150, blank=True)
    price_monthly = models.DecimalField("prix mensuel", max_digits=12, decimal_places=0)
    price_yearly = models.DecimalField("prix annuel", max_digits=12, decimal_places=0)
    max_active_dossiers = models.PositiveIntegerField("dossiers en cours max.", null=True, blank=True,
                                                      help_text="Vide : illimité.")
    max_staff = models.PositiveIntegerField("membres de l'équipe max.", null=True, blank=True, help_text="Vide : illimité.")
    storage_mb = models.PositiveIntegerField("stockage (Mo)", null=True, blank=True, help_text="Vide : illimité.")
    features = models.JSONField("fonctionnalités", default=list, blank=True)
    is_public = models.BooleanField("proposée à la souscription", default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "formule"
        ordering = ["sort_order", "price_monthly"]

    def __str__(self) -> str:
        return self.name

    def has_feature(self, code: str) -> bool:
        return code in (self.features or [])

    def price_for(self, cycle: str) -> Decimal:
        return self.price_yearly if cycle == Subscription.Cycle.YEARLY else self.price_monthly

    @property
    def feature_rows(self):
        return [(label, code in (self.features or [])) for code, label in FEATURES]


class Subscription(models.Model):
    """Abonnement d'une agence : formule choisie et cycle de facturation."""

    class Cycle(models.TextChoices):
        MONTHLY = "monthly", "Mensuel"
        YEARLY = "yearly", "Annuel (2 mois offerts)"

    agency = models.OneToOneField("agencies.Agency", on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    cycle = models.CharField("facturation", max_length=10, choices=Cycle.choices, default=Cycle.MONTHLY)
    renewal_notice_sent_for = models.DateField(null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "abonnement"

    def __str__(self) -> str:
        return f"{self.agency} — {self.plan}"


class PlanChangeRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "À traiter"
        DONE = "done", "Traitée"
        REJECTED = "rejected", "Refusée"

    agency = models.ForeignKey("agencies.Agency", on_delete=models.CASCADE, related_name="plan_requests")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    cycle = models.CharField(max_length=10, choices=Subscription.Cycle.choices, default=Subscription.Cycle.MONTHLY)
    message = models.CharField("message", max_length=300, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class InvoiceCounter(models.Model):
    year = models.PositiveSmallIntegerField(unique=True)
    value = models.PositiveIntegerField(default=0)


def next_invoice_number(year: int | None = None) -> str:
    year = year or timezone.localdate().year
    with transaction.atomic():
        counter, _ = InvoiceCounter.objects.select_for_update().get_or_create(year=year)
        counter.value += 1
        counter.save(update_fields=["value"])
    return f"NM-{year}-{counter.value:04d}"


class Invoice(models.Model):
    class Status(models.TextChoices):
        ISSUED = "issued", "À payer"
        PAID = "paid", "Payée"
        VOID = "void", "Annulée"

    class Method(models.TextChoices):
        ORANGE_MONEY = "orange_money", "Orange Money"
        MOOV_MONEY = "moov_money", "Moov Money"
        WAVE = "wave", "Wave"
        BANK = "bank", "Virement bancaire"
        CASH = "cash", "Espèces"
        OTHER = "other", "Autre"

    number = models.CharField("numéro", max_length=20, unique=True, editable=False)
    agency = models.ForeignKey("agencies.Agency", on_delete=models.PROTECT, related_name="invoices")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="invoices")
    cycle = models.CharField(max_length=10, choices=Subscription.Cycle.choices)
    label = models.CharField("libellé", max_length=200)
    period_start = models.DateField("début de période")
    period_end = models.DateField("fin de période")
    amount = models.DecimalField("montant", max_digits=12, decimal_places=0)
    currency = models.CharField(max_length=10, default="FCFA")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ISSUED)
    issued_on = models.DateField("émise le", default=timezone.localdate)
    due_on = models.DateField("à régler avant le")
    paid_on = models.DateField("payée le", null=True, blank=True)
    payment_method = models.CharField("mode de paiement", max_length=20, choices=Method.choices, blank=True)
    payment_reference = models.CharField("référence du paiement", max_length=100, blank=True)
    notes = models.CharField("notes", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "facture"
        ordering = ["-issued_on", "-id"]
        indexes = [models.Index(fields=["agency", "-issued_on"])]

    def __str__(self) -> str:
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = next_invoice_number(self.issued_on.year if isinstance(self.issued_on, date) else None)
        super().save(*args, **kwargs)

    @property
    def is_overdue(self) -> bool:
        return self.status == self.Status.ISSUED and self.due_on < timezone.localdate()
