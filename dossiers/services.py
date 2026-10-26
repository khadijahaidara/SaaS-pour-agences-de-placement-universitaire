"""Règles métier du suivi de dossiers.

Les vues n'écrivent jamais directement dans les modèles : elles appellent ces
fonctions, qui appliquent les règles, journalisent l'action (DossierEvent) et
notifient les personnes concernées dans une même transaction.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from audit.services import record as audit
from core.tasks import queue_email
from integrations.services import emit, emit_dossier

from .models import (
    DocumentFile,
    DocumentRequest,
    Dossier,
    DossierEvent,
    DossierStage,
    Notification,
    Payment,
    ServiceFee,
    WorkflowTemplate,
)

logger = logging.getLogger(__name__)
User = get_user_model()


from core.exceptions import BusinessRuleError, QuotaExceeded  # noqa: E402,F401  (réexportées)


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
def notify(recipient, message: str, *, dossier=None, url: str = "", email: bool = True) -> None:
    if recipient is None or not recipient.is_active:
        return
    Notification.objects.create(recipient=recipient, dossier=dossier, message=message, url=url)
    if email and recipient.email and getattr(recipient, "notify_email", True):
        # Envoi asynchrone (Celery) après validation : ne fait jamais échouer l'action métier.
        queue_email(f"[{settings.SITE_NAME}] {message[:80]}",
                    f"{message}\n\nConnectez-vous pour voir le détail.", [recipient.email])


def log_event(dossier, actor, kind, message, *, visible_to_student=True):
    DossierEvent.objects.create(
        dossier=dossier, actor=actor, kind=kind, message=message, visible_to_student=visible_to_student
    )
    dossier.touch()


def build_invitation_path(user) -> str:
    """Lien (relatif) permettant à l'étudiant de choisir son mot de passe."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return reverse("accounts:invitation", kwargs={"uidb64": uid, "token": token})


# --------------------------------------------------------------------------- #
# Création de dossier
# --------------------------------------------------------------------------- #
@transaction.atomic
def create_dossier(
    *,
    agency,
    actor,
    student_email: str,
    student_first_name: str,
    student_last_name: str,
    student_phone: str = "",
    workflow: WorkflowTemplate | None = None,
    counselor=None,
    **fields,
) -> tuple[Dossier, bool]:
    """Crée le dossier (et le compte étudiant s'il n'existe pas).

    Retourne (dossier, compte_cree). Le parcours et la liste de pièces sont
    copiés depuis le modèle choisi : modifier le modèle ensuite n'altère pas
    les dossiers existants.
    """
    if not agency.is_operational:
        raise BusinessRuleError("L'abonnement de l'agence n'est pas actif : création de dossier impossible.")
    from billing.services import check_quota

    check_quota(agency, "dossiers")
    email = student_email.strip().lower()
    student = User.objects.filter(email=email).first()
    created_account = False
    if student is None:
        student = User.objects.create_user(
            email=email,
            first_name=student_first_name.strip(),
            last_name=student_last_name.strip(),
            phone=student_phone.strip(),
            role=User.Role.STUDENT,
            agency=agency,
        )
        created_account = True
    elif student.agency_id != agency.id or student.role != User.Role.STUDENT:
        raise BusinessRuleError("Ce courriel est déjà utilisé par un compte qui n'est pas un étudiant de votre agence.")

    if workflow and workflow.agency_id != agency.id:
        raise BusinessRuleError("Modèle de parcours invalide.")
    if counselor and (counselor.agency_id != agency.id or not counselor.is_agency_staff):
        raise BusinessRuleError("Conseiller invalide.")

    if workflow and not fields.get("destination_country"):
        fields["destination_country"] = workflow.destination_country
    dossier = Dossier.objects.create(
        agency=agency, student=student, counselor=counselor, workflow=workflow, **fields
    )

    if workflow:
        stages_by_order = {}
        for st in workflow.stages.all():
            stages_by_order[st.order] = DossierStage.objects.create(
                dossier=dossier,
                order=st.order,
                name=st.name,
                student_instructions=st.student_instructions,
                default_duration_days=st.default_duration_days,
            )
        for doc in workflow.documents.all():
            DocumentRequest.objects.create(
                dossier=dossier,
                stage=stages_by_order.get(doc.stage_order),
                name=doc.name,
                description=doc.description,
                is_required=doc.is_required,
            )
        first = dossier.stages.order_by("order").first()
        if first:
            _start_stage(first)

    log_event(dossier, actor, DossierEvent.Kind.CREATED, "Dossier ouvert par l'agence.")
    audit("dossier.created", agency=agency, actor=actor, target=dossier)
    emit_dossier(dossier, "dossier.created")
    if counselor and counselor != actor:
        notify(counselor, f"Nouveau dossier assigné : {dossier.reference} ({student})", dossier=dossier,
               url=reverse("dossiers:detail", args=[dossier.pk]))
    return dossier, created_account


def _start_stage(stage: DossierStage, due_date=None):
    stage.status = DossierStage.Status.IN_PROGRESS
    stage.started_at = timezone.now()
    stage.due_date = due_date or (timezone.localdate() + timedelta(days=stage.default_duration_days))
    stage.save(update_fields=["status", "started_at", "due_date"])


# --------------------------------------------------------------------------- #
# Étapes
# --------------------------------------------------------------------------- #
def _ensure_open(dossier):
    if dossier.status not in {Dossier.Status.ACTIVE, Dossier.Status.BLOCKED}:
        raise BusinessRuleError("Ce dossier est clôturé.")


@transaction.atomic
def advance_stage(dossier: Dossier, actor, *, next_due_date=None, force: bool = False) -> DossierStage | None:
    """Termine l'étape en cours et démarre la suivante.

    Règle : une étape ne peut être terminée tant que ses pièces obligatoires
    ne sont pas validées (sauf `force=True`, réservé au responsable d'agence).
    Quand la dernière étape est terminée, le dossier passe à « Terminé ».
    Retourne la nouvelle étape en cours (ou None si le parcours est fini).
    """
    dossier = Dossier.objects.select_for_update().get(pk=dossier.pk)
    _ensure_open(dossier)
    if dossier.status == Dossier.Status.BLOCKED:
        raise BusinessRuleError("Débloquez le dossier avant de le faire progresser.")
    current = dossier.current_stage
    if current is None:
        raise BusinessRuleError("Aucune étape en cours sur ce dossier.")
    blocking = list(current.blocking_documents().values_list("name", flat=True))
    if blocking and not force:
        raise BusinessRuleError(
            "Impossible de terminer l'étape : pièces obligatoires non validées — " + ", ".join(blocking)
        )
    if force and not actor.has_agency_perm("dossiers.force_advance"):
        raise BusinessRuleError("Votre rôle ne permet pas de forcer le passage d'étape.")

    current.status = DossierStage.Status.DONE
    current.completed_at = timezone.now()
    current.save(update_fields=["status", "completed_at"])

    nxt = dossier.stages.filter(status=DossierStage.Status.PENDING, order__gt=current.order).order_by("order").first()
    if nxt:
        _start_stage(nxt, next_due_date)
        msg = f"Étape « {current.name} » terminée. Nouvelle étape : « {nxt.name} » (échéance {nxt.due_date:%d/%m/%Y})."
    else:
        dossier.status = Dossier.Status.COMPLETED
        dossier.save(update_fields=["status", "updated_at"])
        msg = f"Étape « {current.name} » terminée. Parcours achevé."
    if force and blocking:
        log_event(dossier, actor, DossierEvent.Kind.STAGE,
                  f"Passage forcé malgré pièces manquantes : {', '.join(blocking)}", visible_to_student=False)
    log_event(dossier, actor, DossierEvent.Kind.STAGE, msg)
    notify(dossier.student, msg, dossier=dossier, url=reverse("portal:dossier", args=[dossier.pk]))
    emit_dossier(dossier, "dossier.stage_changed", completed_stage=current.name,
                 next_stage=nxt.name if nxt else None, forced=bool(force and blocking))
    return nxt


@transaction.atomic
def update_stage_due_date(stage: DossierStage, actor, due_date):
    _ensure_open(stage.dossier)
    old = stage.due_date
    stage.due_date = due_date
    stage.save(update_fields=["due_date"])
    log_event(stage.dossier, actor, DossierEvent.Kind.STAGE,
              f"Échéance de « {stage.name} » : {old:%d/%m/%Y} → {due_date:%d/%m/%Y}" if old else
              f"Échéance de « {stage.name} » fixée au {due_date:%d/%m/%Y}")


@transaction.atomic
def set_status(dossier: Dossier, actor, status: str, reason: str = ""):
    if status not in Dossier.Status.values:
        raise BusinessRuleError("Statut inconnu.")
    if status in {Dossier.Status.BLOCKED, Dossier.Status.REFUSED, Dossier.Status.CANCELLED} and not reason.strip():
        raise BusinessRuleError("Un motif est obligatoire pour ce statut.")
    if status == Dossier.Status.COMPLETED and dossier.stages.exclude(
        status__in=[DossierStage.Status.DONE, DossierStage.Status.SKIPPED]
    ).exists():
        raise BusinessRuleError("Toutes les étapes doivent être terminées ou non applicables.")
    previous = dossier.get_status_display()
    dossier.status = status
    dossier.blocked_reason = reason.strip()
    dossier.save(update_fields=["status", "blocked_reason", "updated_at"])
    msg = f"Statut : {previous} → {dossier.get_status_display()}" + (f" ({reason.strip()})" if reason.strip() else "")
    log_event(dossier, actor, DossierEvent.Kind.STATUS, msg)
    audit("dossier.status_changed", agency=dossier.agency, actor=actor, target=dossier,
          metadata={"statut": dossier.get_status_display(), "motif": reason.strip()[:120]})
    emit_dossier(dossier, "dossier.status_changed", reason=reason.strip())
    notify(dossier.student, f"Votre dossier {dossier.reference} : {dossier.get_status_display()}",
           dossier=dossier, url=reverse("portal:dossier", args=[dossier.pk]))


@transaction.atomic
def assign_counselor(dossier: Dossier, actor, counselor):
    if counselor is not None and (counselor.agency_id != dossier.agency_id or not counselor.is_agency_staff):
        raise BusinessRuleError("Conseiller invalide.")
    dossier.counselor = counselor
    dossier.save(update_fields=["counselor", "updated_at"])
    log_event(dossier, actor, DossierEvent.Kind.ASSIGNMENT,
              f"Conseiller responsable : {counselor or 'aucun'}", visible_to_student=False)
    audit("dossier.assigned", agency=dossier.agency, actor=actor, target=dossier,
          metadata={"conseiller": str(counselor or "aucun")})
    emit_dossier(dossier, "dossier.assigned")
    if counselor and counselor != actor:
        notify(counselor, f"Dossier {dossier.reference} vous a été assigné.", dossier=dossier,
               url=reverse("dossiers:detail", args=[dossier.pk]))


# --------------------------------------------------------------------------- #
# Pièces
# --------------------------------------------------------------------------- #
@transaction.atomic
def request_document(dossier: Dossier, actor, *, name, description="", stage=None, is_required=True, due_date=None):
    _ensure_open(dossier)
    if stage is not None and stage.dossier_id != dossier.id:
        raise BusinessRuleError("Étape invalide.")
    req = DocumentRequest.objects.create(
        dossier=dossier, name=name, description=description, stage=stage, is_required=is_required, due_date=due_date
    )
    suffix = f" avant le {due_date:%d/%m/%Y}" if due_date else ""
    log_event(dossier, actor, DossierEvent.Kind.DOCUMENT, f"Pièce demandée : {name}{suffix}")
    notify(dossier.student, f"Nouvelle pièce demandée : {name}{suffix}", dossier=dossier,
           url=reverse("portal:dossier", args=[dossier.pk]))
    return req


@transaction.atomic
def submit_document(doc: DocumentRequest, user, uploaded_file) -> DocumentFile:
    dossier = doc.dossier
    _ensure_open(dossier)
    if doc.status == DocumentRequest.Status.APPROVED:
        raise BusinessRuleError("Cette pièce est déjà validée.")
    from billing.services import check_quota

    check_quota(dossier.agency, "storage", extra_bytes=uploaded_file.size)
    f = DocumentFile.objects.create(
        request=doc, file=uploaded_file, original_name=uploaded_file.name[:255],
        size=uploaded_file.size, uploaded_by=user,
    )
    doc.status = DocumentRequest.Status.SUBMITTED
    doc.rejection_reason = ""
    doc.save(update_fields=["status", "rejection_reason"])
    who = "l'étudiant" if user.is_student else str(user)
    log_event(dossier, user, DossierEvent.Kind.DOCUMENT, f"Pièce déposée par {who} : {doc.name}")
    emit(dossier.agency, "document.submitted", {"dossier": dossier.reference, "document": doc.name,
                                                 "file_name": f.original_name, "by_student": user.is_student})
    if user.is_student:
        recipient = dossier.counselor or dossier.agency.users.filter(role=User.Role.AGENCY_ADMIN, is_active=True).first()
        notify(recipient, f"{dossier.student} a déposé « {doc.name} » ({dossier.reference})", dossier=dossier,
               url=reverse("dossiers:detail", args=[dossier.pk]))
    return f


@transaction.atomic
def review_document(doc: DocumentRequest, actor, *, approve: bool, reason: str = ""):
    _ensure_open(doc.dossier)
    if doc.status != DocumentRequest.Status.SUBMITTED:
        raise BusinessRuleError("Seule une pièce déposée peut être validée ou retournée.")
    if not approve and not reason.strip():
        raise BusinessRuleError("Indiquez le motif du retour pour que l'étudiant sache quoi corriger.")
    doc.status = DocumentRequest.Status.APPROVED if approve else DocumentRequest.Status.REJECTED
    doc.rejection_reason = "" if approve else reason.strip()
    doc.reviewed_by = actor
    doc.reviewed_at = timezone.now()
    doc.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at"])
    if approve:
        msg = f"Pièce validée : {doc.name}"
    else:
        msg = f"Pièce à reprendre : {doc.name} — motif : {doc.rejection_reason}"
    log_event(doc.dossier, actor, DossierEvent.Kind.DOCUMENT, msg)
    audit("document.reviewed", agency=doc.dossier.agency, actor=actor, target=doc.dossier,
          metadata={"piece": doc.name, "decision": "validée" if approve else "retournée"})
    emit(doc.dossier.agency, "document.reviewed", {"dossier": doc.dossier.reference, "document": doc.name,
                                                   "approved": approve, "reason": doc.rejection_reason})
    notify(doc.dossier.student, msg, dossier=doc.dossier, url=reverse("portal:dossier", args=[doc.dossier_id]))


# --------------------------------------------------------------------------- #
# Finances
# --------------------------------------------------------------------------- #
@transaction.atomic
def add_fee(dossier: Dossier, actor, *, label, amount: Decimal, due_date=None) -> ServiceFee:
    if amount <= 0:
        raise BusinessRuleError("Le montant doit être positif.")
    fee = ServiceFee.objects.create(dossier=dossier, label=label, amount=amount, due_date=due_date, created_by=actor)
    log_event(dossier, actor, DossierEvent.Kind.PAYMENT,
              f"Frais ajoutés : {label} — {amount:,.0f} {dossier.agency.currency}".replace(",", " "))
    return fee


@transaction.atomic
def record_payment(dossier: Dossier, actor, *, amount: Decimal, method, reference="", paid_on=None) -> Payment:
    if amount <= 0:
        raise BusinessRuleError("Le montant doit être positif.")
    if amount > dossier.balance():
        raise BusinessRuleError(
            f"Le montant dépasse le solde restant ({dossier.balance():,.0f} {dossier.agency.currency}).".replace(",", " ")
        )
    payment = Payment.objects.create(
        dossier=dossier, amount=amount, method=method, reference=reference,
        paid_on=paid_on or timezone.localdate(), recorded_by=actor,
    )
    cur = dossier.agency.currency
    log_event(dossier, actor, DossierEvent.Kind.PAYMENT,
              f"Paiement reçu : {amount:,.0f} {cur} ({payment.get_method_display()}) — reçu {payment.receipt_number}".replace(",", " "))
    audit("payment.recorded", agency=dossier.agency, actor=actor, target=dossier,
          metadata={"recu": payment.receipt_number, "montant": int(amount), "mode": payment.get_method_display()})
    emit(dossier.agency, "payment.recorded", _payment_data(payment))
    notify(dossier.student,
           f"Paiement de {amount:,.0f} {cur} enregistré. Solde restant : {dossier.balance():,.0f} {cur}.".replace(",", " "),
           dossier=dossier, url=reverse("portal:dossier", args=[dossier.pk]))
    return payment


@transaction.atomic
def cancel_payment(payment: Payment, actor, reason: str):
    if not actor.has_agency_perm("payments.cancel"):
        raise BusinessRuleError("Votre rôle ne permet pas d'annuler un paiement.")
    if payment.is_cancelled:
        raise BusinessRuleError("Ce paiement est déjà annulé.")
    if not reason.strip():
        raise BusinessRuleError("Le motif d'annulation est obligatoire.")
    payment.cancelled_at = timezone.now()
    payment.cancelled_by = actor
    payment.cancellation_reason = reason.strip()
    payment.save(update_fields=["cancelled_at", "cancelled_by", "cancellation_reason"])
    log_event(payment.dossier, actor, DossierEvent.Kind.PAYMENT,
              f"Paiement {payment.receipt_number} annulé : {reason.strip()}")
    audit("payment.cancelled", agency=payment.dossier.agency, actor=actor, target=payment.dossier,
          metadata={"recu": payment.receipt_number, "montant": int(payment.amount), "motif": reason.strip()[:120]})
    emit(payment.dossier.agency, "payment.cancelled", _payment_data(payment))


def _payment_data(payment) -> dict:
    return {
        "dossier": payment.dossier.reference, "receipt_number": payment.receipt_number,
        "amount": int(payment.amount), "currency": payment.dossier.agency.currency, "method": payment.method,
        "reference": payment.reference, "paid_on": payment.paid_on.isoformat(),
        "cancelled": payment.is_cancelled, "cancellation_reason": payment.cancellation_reason,
        "balance": int(payment.dossier.balance()),
    }
