"""Tâches automatiques, lancées par « python manage.py run_scheduled_tasks ».

Chaque tâche est idempotente : on peut la lancer toutes les heures sans envoyer de
doublons (dates de dernière relance, marqueurs d'envoi, résumé une fois par jour).
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import number_format

from agencies.models import Agency
from core.tasks import send_email

from .models import DocumentRequest, Dossier, DossierEvent, ServiceFee
from .services import notify

logger = logging.getLogger(__name__)
User = get_user_model()

DOCUMENT_REMINDER_EVERY = timedelta(days=3)
DOCUMENT_REMINDER_AHEAD_DAYS = 2
PAYMENT_REMINDER_EVERY = timedelta(days=7)
PAYMENT_REMINDER_AHEAD_DAYS = 3
TRIAL_WARNING_DAYS = 3

OPEN = [Dossier.Status.ACTIVE, Dossier.Status.BLOCKED]


def remind_documents(now=None) -> dict:
    """Relance l'étudiant pour les pièces attendues dont l'échéance approche ou est dépassée."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    qs = (DocumentRequest.objects
          .filter(status__in=[DocumentRequest.Status.REQUESTED, DocumentRequest.Status.REJECTED],
                  dossier__status__in=OPEN, dossier__agency__is_active=True,
                  due_date__isnull=False, due_date__lte=today + timedelta(days=DOCUMENT_REMINDER_AHEAD_DAYS))
          .filter(Q(last_reminded_at__isnull=True) | Q(last_reminded_at__lt=now - DOCUMENT_REMINDER_EVERY))
          .select_related("dossier__student", "dossier__agency"))
    by_dossier: dict[int, list[DocumentRequest]] = {}
    for doc in qs:
        by_dossier.setdefault(doc.dossier_id, []).append(doc)
    for docs in by_dossier.values():
        dossier = docs[0].dossier
        late = [d for d in docs if d.due_date < today]
        names = ", ".join(d.name for d in docs)
        if late:
            msg = f"Rappel : pièce(s) en retard pour votre dossier {dossier.reference} — {names}."
        else:
            msg = f"Rappel : pièce(s) à fournir avant le {min(d.due_date for d in docs):%d/%m/%Y} — {names}."
        notify(dossier.student, msg, dossier=dossier, url=reverse("portal:dossier", args=[dossier.pk]))
        DossierEvent.objects.create(dossier=dossier, actor=None, kind=DossierEvent.Kind.DOCUMENT,
                                    message=f"Relance automatique envoyée : {names}")
        DocumentRequest.objects.filter(pk__in=[d.pk for d in docs]).update(last_reminded_at=now)
    return {"dossiers": len(by_dossier), "pieces": sum(len(v) for v in by_dossier.values())}


def remind_payments(now=None) -> dict:
    """Rappelle les échéances de paiement proches ou dépassées quand le montant dû n'est pas couvert."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    horizon = today + timedelta(days=PAYMENT_REMINDER_AHEAD_DAYS)
    dossier_ids = (ServiceFee.objects
                   .filter(due_date__isnull=False, due_date__lte=horizon, dossier__status__in=OPEN,
                           dossier__agency__is_active=True)
                   .filter(Q(last_reminded_at__isnull=True) | Q(last_reminded_at__lt=now - PAYMENT_REMINDER_EVERY))
                   .values_list("dossier_id", flat=True).distinct())
    sent = 0
    for dossier in Dossier.objects.filter(pk__in=list(dossier_ids)).select_related("student", "agency"):
        due_fees = dossier.fees.filter(due_date__lte=horizon)
        due_total = due_fees.aggregate(s=Sum("amount"))["s"] or Decimal("0")
        missing = due_total - dossier.total_paid()
        if missing <= 0:
            continue
        cur = dossier.agency.currency
        next_due = due_fees.order_by("-due_date").first().due_date
        when = "échue" if next_due < today else f"due le {next_due:%d/%m/%Y}"
        notify(dossier.student,
               f"Rappel de paiement : {number_format(missing, force_grouping=True)} {cur} ({when}) pour votre dossier {dossier.reference}.",
               dossier=dossier, url=reverse("portal:dossier", args=[dossier.pk]))
        DossierEvent.objects.create(dossier=dossier, actor=None, kind=DossierEvent.Kind.PAYMENT, visible_to_student=False,
                                    message=f"Rappel de paiement automatique : {number_format(missing, force_grouping=True)} {cur}")
        due_fees.update(last_reminded_at=now)
        sent += 1
    return {"rappels": sent}


def send_daily_digest(now=None) -> dict:
    """Courriel du matin à chaque conseiller / responsable : ses dossiers en alerte."""
    sent = 0
    staff = (User.objects.filter(is_active=True, daily_digest=True, agency__is_active=True,
                                 role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR])
             .exclude(email="").select_related("agency"))
    for user in staff:
        lines = []
        for d in Dossier.objects.for_user(user).open().select_related("student"):
            alerts = d.alerts()
            if alerts:
                lines.append((sum(a["weight"] for a in alerts),
                              f"- {d.student.get_full_name() or d.student.email} ({d.reference}) : "
                              + " ; ".join(a["label"] for a in alerts)))
        if not lines:
            continue
        lines.sort(reverse=True)
        body = (f"Bonjour {user.first_name or ''},\n\n{len(lines)} dossier(s) demandent votre attention aujourd'hui :\n\n"
                + "\n".join(line for _, line in lines[:30])
                + "\n\nOuvrez votre tableau de suivi pour les traiter.\n\n— NEURALIS Mobility")
        try:
            send_email.delay(f"[{settings.SITE_NAME}] {len(lines)} dossier(s) à traiter aujourd'hui", body,
                             [user.email])
            sent += 1
        except Exception:  # pragma: no cover - dépend du serveur SMTP
            logger.exception("Résumé quotidien non envoyé à %s", user.email)
    return {"resumes": sent}


def trial_notices(now=None) -> dict:
    """Prévient les responsables 3 jours avant la fin de l'essai, puis à son expiration."""
    now = now or timezone.now()
    warned = ended = 0
    trials = Agency.objects.filter(is_active=True, plan=Agency.Plan.TRIAL, trial_ends_at__isnull=False)
    for agency in trials.filter(trial_warning_sent_at__isnull=True, trial_ends_at__gt=now,
                                trial_ends_at__lte=now + timedelta(days=TRIAL_WARNING_DAYS)):
        for admin in agency.users.filter(role=User.Role.AGENCY_ADMIN, is_active=True):
            notify(admin, f"Votre essai gratuit se termine le {timezone.localtime(agency.trial_ends_at):%d/%m/%Y}. "
                          "Contactez NEURALIS pour activer l'abonnement et continuer à créer des dossiers.",
                   url=reverse("agencies:settings"))
        agency.trial_warning_sent_at = now
        agency.save(update_fields=["trial_warning_sent_at"])
        warned += 1
    for agency in trials.filter(trial_ended_notice_sent_at__isnull=True, trial_ends_at__lte=now):
        for admin in agency.users.filter(role=User.Role.AGENCY_ADMIN, is_active=True):
            notify(admin, "Votre essai gratuit est terminé. Vos données sont conservées ; contactez NEURALIS "
                          "pour activer l'abonnement.", url=reverse("agencies:settings"))
        agency.trial_ended_notice_sent_at = now
        agency.save(update_fields=["trial_ended_notice_sent_at"])
        ended += 1
    return {"avertis": warned, "termines": ended}


# Nom → (fonction, une seule exécution réussie par jour ?)
TASKS = {
    "relances_pieces": (remind_documents, False),
    "relances_paiements": (remind_payments, False),
    "fin_essai": (trial_notices, False),
    "resume_quotidien": (send_daily_digest, True),
}

TASK_LABELS = {
    "relances_pieces": "Relances des pièces",
    "relances_paiements": "Rappels de paiement",
    "fin_essai": "Fin des essais",
    "resume_quotidien": "Résumé quotidien",
}
