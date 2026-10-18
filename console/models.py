"""CRM commercial de NEURALIS : prospection des agences avant qu'elles deviennent clientes."""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Prospect(models.Model):
    class Priority(models.TextChoices):
        P1 = "P1", "P1 — cœur de cible"
        P2 = "P2", "P2 — éducation / formation"
        P3 = "P3", "P3 — à qualifier"

    class Status(models.TextChoices):
        NEW = "new", "À contacter"
        CONTACTED = "contacted", "Contacté"
        DEMO_SCHEDULED = "demo_scheduled", "Démo planifiée"
        DEMO_DONE = "demo_done", "Démo faite"
        TRIAL = "trial", "En essai"
        WON = "won", "Client"
        LOST = "lost", "Perdu"
        NOT_TARGET = "not_target", "Hors cible"

    PIPELINE = ["new", "contacted", "demo_scheduled", "demo_done", "trial", "won"]
    CLOSED = {"won", "lost", "not_target"}

    name = models.CharField("prospect", max_length=200)
    zone = models.CharField("zone / quartier", max_length=150, blank=True)
    phone = models.CharField("téléphone(s)", max_length=150, blank=True)
    email = models.CharField("courriel", max_length=200, blank=True)
    segment = models.CharField(max_length=120, blank=True)
    website = models.CharField("site web", max_length=300, blank=True)
    whatsapp = models.CharField(max_length=150, blank=True)
    decision_maker = models.CharField("décideur / fonction", max_length=300, blank=True)
    channel = models.CharField("canal recommandé", max_length=150, blank=True)
    source = models.CharField("source de vérification", max_length=500, blank=True)
    priority = models.CharField("priorité", max_length=2, choices=Priority.choices, default=Priority.P3)
    status = models.CharField("étape commerciale", max_length=20, choices=Status.choices, default=Status.NEW)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="prospects", verbose_name="commercial",
    )
    next_follow_up = models.DateField("prochaine relance", null=True, blank=True)
    estimated_dossiers = models.PositiveIntegerField("dossiers par an (estimation)", null=True, blank=True)
    notes = models.TextField(blank=True)
    lost_reason = models.CharField("motif", max_length=255, blank=True)
    agency = models.OneToOneField(
        "agencies.Agency", on_delete=models.SET_NULL, null=True, blank=True, related_name="prospect",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_contact_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["priority", "name"]
        indexes = [models.Index(fields=["status", "priority"]), models.Index(fields=["next_follow_up"])]

    def __str__(self) -> str:
        return self.name

    @property
    def is_closed(self) -> bool:
        return self.status in self.CLOSED

    @property
    def is_follow_up_due(self) -> bool:
        return bool(self.next_follow_up and self.next_follow_up <= timezone.localdate() and not self.is_closed)

    @property
    def first_email(self) -> str:
        for part in (self.email or "").replace(";", "/").split("/"):
            if "@" in part:
                return part.strip()
        return ""

    @property
    def website_url(self) -> str:
        w = (self.website or "").strip()
        return w if w.startswith(("http://", "https://")) else ""

    @property
    def whatsapp_number(self) -> str:
        """Premier numéro au format international (wa.me), indicatif Mali par défaut."""
        for raw in ((self.whatsapp or "") + "/" + (self.phone or "")).split("/"):
            digits = "".join(c for c in raw if c.isdigit())
            if len(digits) == 8:
                return "223" + digits
            if len(digits) == 11 and digits.startswith("223"):
                return digits
        return ""


class ProspectActivity(models.Model):
    class Kind(models.TextChoices):
        CALL = "call", "Appel"
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "Courriel"
        VISIT = "visit", "Visite"
        DEMO = "demo", "Démonstration"
        NOTE = "note", "Note"
        STATUS = "status", "Changement d'étape"

    prospect = models.ForeignKey(Prospect, on_delete=models.CASCADE, related_name="activities")
    kind = models.CharField("type", max_length=20, choices=Kind.choices, default=Kind.NOTE)
    summary = models.TextField("compte rendu")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} — {self.prospect}"
