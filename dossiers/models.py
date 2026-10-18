"""Modèle de données du suivi de dossiers étudiants.

Vue d'ensemble :
- WorkflowTemplate / StageTemplate / DocumentTemplate : parcours type configurable
  par agence et par destination (ex. « France — Campus France »).
- Dossier : un étudiant + une destination + un programme, suivi par un conseiller.
- DossierStage : copie des étapes du modèle, avec statut et échéance propres au dossier.
- DocumentRequest / DocumentFile : liste de contrôle des pièces et versions déposées.
- ServiceFee / Payment : frais de prestation de l'agence et encaissements.
- DossierEvent : historique (journal d'audit) ; Notification : avis aux utilisateurs.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone


# --------------------------------------------------------------------------- #
# Modèles de parcours (configurables par agence)
# --------------------------------------------------------------------------- #
class WorkflowTemplate(models.Model):
    agency = models.ForeignKey("agencies.Agency", on_delete=models.CASCADE, related_name="workflow_templates")
    name = models.CharField("nom", max_length=120)
    destination_country = models.CharField("pays de destination", max_length=100, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField("actif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "modèle de parcours"
        verbose_name_plural = "modèles de parcours"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["agency", "name"], name="unique_template_name_per_agency")]

    def __str__(self) -> str:
        return self.name


class StageTemplate(models.Model):
    workflow = models.ForeignKey(WorkflowTemplate, on_delete=models.CASCADE, related_name="stages")
    order = models.PositiveSmallIntegerField("ordre")
    name = models.CharField("étape", max_length=120)
    student_instructions = models.TextField(
        "consigne pour l'étudiant", blank=True, help_text="Texte affiché sur le portail pendant cette étape."
    )
    default_duration_days = models.PositiveSmallIntegerField("durée prévue (jours)", default=14)

    class Meta:
        ordering = ["order"]
        constraints = [models.UniqueConstraint(fields=["workflow", "order"], name="unique_stage_order")]

    def __str__(self) -> str:
        return f"{self.order}. {self.name}"


class DocumentTemplate(models.Model):
    workflow = models.ForeignKey(WorkflowTemplate, on_delete=models.CASCADE, related_name="documents")
    name = models.CharField("pièce", max_length=150)
    description = models.CharField("précision", max_length=255, blank=True)
    is_required = models.BooleanField("obligatoire", default=True)
    stage_order = models.PositiveSmallIntegerField(
        "requise avant la fin de l'étape n°",
        null=True,
        blank=True,
        help_text="Laisser vide si la pièce n'est liée à aucune étape.",
    )

    class Meta:
        ordering = ["stage_order", "name"]

    def __str__(self) -> str:
        return self.name


# --------------------------------------------------------------------------- #
# Dossier
# --------------------------------------------------------------------------- #
class DossierQuerySet(models.QuerySet):
    def for_user(self, user):
        """Restreint aux dossiers visibles par l'utilisateur (règle d'isolation centrale)."""
        if not user.is_authenticated:
            return self.none()
        if user.role == user.Role.PLATFORM_ADMIN:
            return self
        if user.role == user.Role.AGENCY_ADMIN:
            return self.filter(agency=user.agency)
        if user.role == user.Role.COUNSELOR:
            return self.filter(agency=user.agency, counselor=user)
        if user.role == user.Role.STUDENT:
            return self.filter(agency=user.agency, student=user)
        return self.none()

    def open(self):
        return self.filter(status__in=[Dossier.Status.ACTIVE, Dossier.Status.BLOCKED])


class Dossier(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "En cours"
        BLOCKED = "blocked", "Bloqué"
        REFUSED = "refused", "Refusé"
        COMPLETED = "completed", "Terminé (accueilli)"
        CANCELLED = "cancelled", "Abandonné"

    reference = models.CharField("référence", max_length=20, unique=True, editable=False)
    agency = models.ForeignKey("agencies.Agency", on_delete=models.PROTECT, related_name="dossiers")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="dossiers", verbose_name="étudiant"
    )
    counselor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_dossiers",
        verbose_name="conseiller responsable",
    )
    workflow = models.ForeignKey(
        WorkflowTemplate, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="modèle de parcours"
    )
    destination_country = models.CharField("pays de destination", max_length=100)
    destination_city = models.CharField("ville", max_length=100, blank=True)
    institution = models.CharField("établissement visé", max_length=200, blank=True)
    program = models.CharField("programme / filière", max_length=200, blank=True)
    intake = models.CharField("rentrée visée", max_length=50, blank=True, help_text="Ex. : Septembre 2027")
    guardian_name = models.CharField("parent / répondant", max_length=150, blank=True)
    guardian_phone = models.CharField("téléphone du répondant", max_length=30, blank=True)
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    blocked_reason = models.CharField("motif du blocage / refus", max_length=255, blank=True)
    internal_notes = models.TextField("notes internes (non visibles par l'étudiant)", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_activity_at = models.DateTimeField(default=timezone.now)

    objects = DossierQuerySet.as_manager()

    class Meta:
        ordering = ["-last_activity_at"]
        indexes = [models.Index(fields=["agency", "status"]), models.Index(fields=["agency", "counselor"])]

    def __str__(self) -> str:
        return f"{self.reference} — {self.student}"

    def clean(self):
        if self.student_id and self.student.agency_id != self.agency_id:
            raise ValidationError("L'étudiant doit appartenir à la même agence que le dossier.")
        if self.counselor_id and self.counselor.agency_id != self.agency_id:
            raise ValidationError("Le conseiller doit appartenir à la même agence que le dossier.")
        if self.status in {self.Status.BLOCKED, self.Status.REFUSED} and not self.blocked_reason:
            raise ValidationError({"blocked_reason": "Indiquez le motif."})

    def save(self, *args, **kwargs):
        if not self.reference:
            year = timezone.now().year
            self.reference = f"DOS-{year}-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    # --- Étapes --------------------------------------------------------- #
    @property
    def current_stage(self):
        return self.stages.filter(status=DossierStage.Status.IN_PROGRESS).order_by("order").first()

    def progress_percent(self) -> int:
        total = self.stages.exclude(status=DossierStage.Status.SKIPPED).count()
        if not total:
            return 0
        done = self.stages.filter(status=DossierStage.Status.DONE).count()
        return round(done * 100 / total)

    # --- Pièces --------------------------------------------------------- #
    def documents_awaiting_student(self):
        return self.document_requests.filter(
            status__in=[DocumentRequest.Status.REQUESTED, DocumentRequest.Status.REJECTED]
        )

    def documents_awaiting_review(self):
        return self.document_requests.filter(status=DocumentRequest.Status.SUBMITTED)

    # --- Finances ------------------------------------------------------- #
    def total_fees(self) -> Decimal:
        return self.fees.aggregate(s=Sum("amount"))["s"] or Decimal("0")

    def total_paid(self) -> Decimal:
        return self.payments.filter(cancelled_at__isnull=True).aggregate(s=Sum("amount"))["s"] or Decimal("0")

    def balance(self) -> Decimal:
        return self.total_fees() - self.total_paid()

    # --- Alertes -------------------------------------------------------- #
    def alerts(self) -> list[dict]:
        """Liste des raisons pour lesquelles le dossier demande une intervention.

        Chaque alerte : {"code", "label", "weight"}. Le poids sert à prioriser
        le tableau de suivi (plus il est élevé, plus le dossier remonte).
        """
        today = timezone.localdate()
        alerts: list[dict] = []
        if self.status == self.Status.BLOCKED:
            alerts.append({"code": "blocked", "label": f"Bloqué : {self.blocked_reason}", "weight": 50})
        if self.status not in {self.Status.ACTIVE, self.Status.BLOCKED}:
            return alerts
        stage = self.current_stage
        if stage and stage.due_date and stage.due_date < today:
            days = (today - stage.due_date).days
            alerts.append({"code": "stage_overdue", "label": f"Étape « {stage.name} » en retard de {days} j", "weight": 30 + min(days, 30)})
        elif stage and stage.due_date and stage.due_date <= today + timedelta(days=3):
            alerts.append({"code": "stage_due_soon", "label": f"Échéance proche : {stage.name}", "weight": 15})
        to_review = self.documents_awaiting_review().count()
        if to_review:
            alerts.append({"code": "to_review", "label": f"{to_review} pièce(s) à vérifier", "weight": 25})
        overdue_docs = self.documents_awaiting_student().filter(due_date__lt=today).count()
        if overdue_docs:
            alerts.append({"code": "docs_overdue", "label": f"{overdue_docs} pièce(s) attendue(s) en retard", "weight": 20})
        stale_limit = timezone.now() - timedelta(days=settings.STALE_DOSSIER_DAYS)
        if self.last_activity_at < stale_limit:
            alerts.append({"code": "stale", "label": f"Aucune activité depuis {settings.STALE_DOSSIER_DAYS} j ou plus", "weight": 10})
        if not self.counselor_id:
            alerts.append({"code": "unassigned", "label": "Aucun conseiller assigné", "weight": 12})
        return alerts

    def priority_score(self) -> int:
        return sum(a["weight"] for a in self.alerts())

    def next_action_for_student(self) -> dict:
        """Prochaine action affichée sur le portail étudiant."""
        if self.status == self.Status.COMPLETED:
            return {"kind": "done", "label": "Votre parcours est terminé. Bienvenue à destination !"}
        if self.status in {self.Status.REFUSED, self.Status.CANCELLED}:
            return {"kind": "closed", "label": "Ce dossier est clôturé. Contactez votre conseiller pour toute question."}
        rejected = self.document_requests.filter(status=DocumentRequest.Status.REJECTED).first()
        if rejected:
            return {"kind": "document", "label": f"Déposer à nouveau : {rejected.name}", "target": rejected}
        requested = self.document_requests.filter(status=DocumentRequest.Status.REQUESTED).order_by(
            models.F("due_date").asc(nulls_last=True)
        ).first()
        if requested:
            return {"kind": "document", "label": f"Déposer : {requested.name}", "target": requested}
        if self.balance() > 0:
            return {"kind": "payment", "label": "Régler le solde des frais de service auprès de l'agence"}
        stage = self.current_stage
        if stage:
            return {"kind": "wait", "label": f"Rien à faire pour l'instant : l'agence traite l'étape « {stage.name} »."}
        return {"kind": "wait", "label": "Votre conseiller prépare la suite de votre dossier."}

    def touch(self):
        self.last_activity_at = timezone.now()
        self.save(update_fields=["last_activity_at", "updated_at"])


class DossierStage(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "À venir"
        IN_PROGRESS = "in_progress", "En cours"
        DONE = "done", "Terminée"
        SKIPPED = "skipped", "Non applicable"

    dossier = models.ForeignKey(Dossier, on_delete=models.CASCADE, related_name="stages")
    order = models.PositiveSmallIntegerField()
    name = models.CharField("étape", max_length=120)
    student_instructions = models.TextField(blank=True)
    default_duration_days = models.PositiveSmallIntegerField(default=14)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    due_date = models.DateField("échéance", null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order"]
        constraints = [models.UniqueConstraint(fields=["dossier", "order"], name="unique_dossier_stage_order")]

    def __str__(self) -> str:
        return self.name

    @property
    def is_overdue(self) -> bool:
        return (
            self.status == self.Status.IN_PROGRESS
            and self.due_date is not None
            and self.due_date < timezone.localdate()
        )

    def blocking_documents(self):
        """Pièces obligatoires liées à cette étape et pas encore validées."""
        return self.document_requests.filter(is_required=True).exclude(status=DocumentRequest.Status.APPROVED)


# --------------------------------------------------------------------------- #
# Pièces
# --------------------------------------------------------------------------- #
class DocumentRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Demandée"
        SUBMITTED = "submitted", "Déposée — à vérifier"
        APPROVED = "approved", "Validée"
        REJECTED = "rejected", "À reprendre"

    dossier = models.ForeignKey(Dossier, on_delete=models.CASCADE, related_name="document_requests")
    stage = models.ForeignKey(
        DossierStage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_requests",
        verbose_name="requise pour l'étape",
    )
    name = models.CharField("pièce", max_length=150)
    description = models.CharField("précision", max_length=255, blank=True)
    is_required = models.BooleanField("obligatoire", default=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    due_date = models.DateField("à fournir avant le", null=True, blank=True)
    rejection_reason = models.CharField("motif du retour", max_length=255, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["stage__order", "created_at"]

    def __str__(self) -> str:
        return self.name

    @property
    def latest_file(self):
        return self.files.order_by("-uploaded_at").first()

    @property
    def is_overdue(self) -> bool:
        return (
            self.status in {self.Status.REQUESTED, self.Status.REJECTED}
            and self.due_date is not None
            and self.due_date < timezone.localdate()
        )


def document_upload_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    dossier = instance.request.dossier
    return f"agences/{dossier.agency_id}/dossiers/{dossier.pk}/{uuid.uuid4().hex}.{ext}"


class DocumentFile(models.Model):
    request = models.ForeignKey(DocumentRequest, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to=document_upload_path)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return self.original_name


# --------------------------------------------------------------------------- #
# Finances de l'agence
# --------------------------------------------------------------------------- #
class ServiceFee(models.Model):
    dossier = models.ForeignKey(Dossier, on_delete=models.CASCADE, related_name="fees")
    label = models.CharField("prestation", max_length=150)
    amount = models.DecimalField("montant", max_digits=12, decimal_places=0)
    due_date = models.DateField("échéance", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "frais de service"
        ordering = ["created_at"]
        constraints = [models.CheckConstraint(name="fee_amount_positive", condition=models.Q(amount__gt=0))]

    def __str__(self) -> str:
        return f"{self.label} ({self.amount})"


class Payment(models.Model):
    """Encaissement. Jamais supprimé : une erreur se corrige par une annulation motivée."""

    class Method(models.TextChoices):
        CASH = "cash", "Espèces"
        ORANGE_MONEY = "orange_money", "Orange Money"
        MOOV_MONEY = "moov_money", "Moov Money"
        WAVE = "wave", "Wave"
        BANK = "bank", "Virement / chèque"
        OTHER = "other", "Autre"

    dossier = models.ForeignKey(Dossier, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField("montant", max_digits=12, decimal_places=0)
    method = models.CharField("mode", max_length=20, choices=Method.choices, default=Method.CASH)
    reference = models.CharField("référence de transaction", max_length=100, blank=True)
    paid_on = models.DateField("date du paiement", default=timezone.localdate)
    receipt_number = models.CharField("n° de reçu", max_length=30, unique=True, editable=False)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    cancellation_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "paiement"
        ordering = ["-paid_on", "-recorded_at"]
        constraints = [models.CheckConstraint(name="payment_amount_positive", condition=models.Q(amount__gt=0))]

    def __str__(self) -> str:
        return f"{self.receipt_number} — {self.amount}"

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = f"REC-{timezone.now():%y%m}-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_at is not None


# --------------------------------------------------------------------------- #
# Historique et notifications
# --------------------------------------------------------------------------- #
class DossierEvent(models.Model):
    class Kind(models.TextChoices):
        CREATED = "created", "Dossier créé"
        STAGE = "stage", "Étape"
        DOCUMENT = "document", "Pièce"
        PAYMENT = "payment", "Paiement"
        STATUS = "status", "Statut"
        NOTE = "note", "Note"
        ASSIGNMENT = "assignment", "Affectation"

    dossier = models.ForeignKey(Dossier, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    message = models.CharField(max_length=500)
    visible_to_student = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.message


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    dossier = models.ForeignKey(Dossier, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    message = models.CharField(max_length=300)
    url = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read"])]

    def __str__(self) -> str:
        return self.message
