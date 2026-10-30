"""Abonnements : formule effective, quotas, factures et changements de formule."""
import calendar
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from core.exceptions import BusinessRuleError, QuotaExceeded

from .models import Invoice, Plan, PlanChangeRequest, Subscription

User = get_user_model()
DEFAULT_PLAN_CODE = "pro"  # l'essai gratuit donne accès à la formule Pro
INVOICE_DUE_DAYS = 7
RENEWAL_NOTICE_DAYS = 7


# --------------------------------------------------------------------------- #
# Formule effective et fonctionnalités
# --------------------------------------------------------------------------- #
def get_subscription(agency) -> Subscription:
    cached = getattr(agency, "_subscription_cache", None)
    if cached is not None:
        return cached
    sub = Subscription.objects.select_related("plan").filter(agency=agency).first()
    if sub is None:
        plan = Plan.objects.filter(code=DEFAULT_PLAN_CODE).first() or Plan.objects.order_by("-price_monthly").first()
        if plan is None:
            plan = Plan.objects.create(code=DEFAULT_PLAN_CODE, name="Pro", price_monthly=0, price_yearly=0,
                                       features=["api", "webhooks", "custom_roles", "audit_log", "enforce_2fa"])
        sub, _ = Subscription.objects.get_or_create(agency=agency, defaults={"plan": plan})
    agency._subscription_cache = sub
    return sub


def effective_plan(agency) -> Plan:
    return get_subscription(agency).plan


def has_feature(agency, code: str) -> bool:
    return agency is not None and effective_plan(agency).has_feature(code)


def require_feature(agency, code: str) -> None:
    if not has_feature(agency, code):
        from .models import FEATURE_LABELS

        raise QuotaExceeded(f"« {FEATURE_LABELS.get(code, code)} » n'est pas inclus dans votre formule "
                            f"{effective_plan(agency).name}. Passez à une formule supérieure.")


# --------------------------------------------------------------------------- #
# Consommation et quotas
# --------------------------------------------------------------------------- #
def usage(agency) -> dict:
    from dossiers.models import DocumentFile, Dossier

    plan = effective_plan(agency)
    active = Dossier.objects.filter(agency=agency).open().count()
    staff = User.objects.filter(agency=agency, is_active=True,
                                role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR]).count()
    storage = DocumentFile.objects.filter(request__dossier__agency=agency).aggregate(s=Sum("size"))["s"] or 0
    storage_mb = round(storage / (1024 * 1024), 1)

    def row(label, used, limit, unit=""):
        pct = None if not limit else min(100, round(used * 100 / limit))
        return {"label": label, "used": used, "limit": limit, "unit": unit, "pct": pct,
                "level": "danger" if pct is not None and pct >= 100 else "warn" if pct is not None and pct >= 80 else "ok"}

    return {
        "dossiers": row("Dossiers en cours", active, plan.max_active_dossiers),
        "staff": row("Membres de l'équipe", staff, plan.max_staff),
        "storage": row("Stockage des pièces", storage_mb, plan.storage_mb, " Mo"),
    }


def check_quota(agency, kind: str, *, extra: int = 1, extra_bytes: int = 0) -> None:
    """Lève QuotaExceeded si l'action ferait dépasser la limite de la formule."""
    plan = effective_plan(agency)
    data = usage(agency)
    if kind == "dossiers" and plan.max_active_dossiers is not None:
        if data["dossiers"]["used"] + extra > plan.max_active_dossiers:
            raise QuotaExceeded(f"Limite de {plan.max_active_dossiers} dossiers en cours atteinte (formule {plan.name}). "
                                "Clôturez des dossiers terminés ou passez à une formule supérieure.")
    elif kind == "staff" and plan.max_staff is not None:
        if data["staff"]["used"] + extra > plan.max_staff:
            raise QuotaExceeded(f"Limite de {plan.max_staff} membres atteinte (formule {plan.name}). "
                                "Désactivez un compte ou passez à une formule supérieure.")
    elif kind == "storage" and plan.storage_mb is not None:
        if data["storage"]["used"] + extra_bytes / (1024 * 1024) > plan.storage_mb:
            raise QuotaExceeded(f"Espace de stockage plein ({plan.storage_mb} Mo, formule {plan.name}). "
                                "Contactez votre agence ou NEURALIS.")


# --------------------------------------------------------------------------- #
# Factures
# --------------------------------------------------------------------------- #
def add_period(start, cycle: str):
    """Fin de période (incluse) : 1 mois ou 1 an après `start`."""
    months = 12 if cycle == Subscription.Cycle.YEARLY else 1
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day) - timedelta(days=1)


def next_period_start(agency):
    today = timezone.localdate()
    if agency.paid_until and agency.paid_until >= today:
        return agency.paid_until + timedelta(days=1)
    return today


@transaction.atomic
def issue_invoice(agency, *, plan: Plan, cycle: str, actor=None, period_start=None, notes: str = "") -> Invoice:
    start = period_start or next_period_start(agency)
    end = add_period(start, cycle)
    today = timezone.localdate()
    invoice = Invoice.objects.create(
        agency=agency, plan=plan, cycle=cycle, amount=plan.price_for(cycle), currency="FCFA",
        label=f"Abonnement NEURALIS Mobility — formule {plan.name} ({Subscription.Cycle(cycle).label.lower()})",
        period_start=start, period_end=end, issued_on=today, due_on=today + timedelta(days=INVOICE_DUE_DAYS),
        notes=notes, created_by=actor,
    )
    from audit.services import record

    record("billing.invoice_issued", agency=agency, actor=actor, target=invoice,
           metadata={"amount": int(invoice.amount), "plan": plan.code})
    _notify_admins(agency, f"Nouvelle facture {invoice.number} : {int(invoice.amount):,} FCFA, à régler avant le "
                           f"{invoice.due_on:%d/%m/%Y}.".replace(",", " "))
    return invoice


@transaction.atomic
def mark_paid(invoice: Invoice, *, actor, method: str, reference: str = "", paid_on=None) -> Invoice:
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != Invoice.Status.ISSUED:
        raise BusinessRuleError("Seule une facture à payer peut être marquée payée.")
    invoice.status = Invoice.Status.PAID
    invoice.paid_on = paid_on or timezone.localdate()
    agency = invoice.agency
    # Première ouverture ou accès expiré : la période payée démarre le jour du paiement.
    if agency.paid_until is None or agency.paid_until < invoice.paid_on:
        if invoice.period_start < invoice.paid_on:
            invoice.period_start = invoice.paid_on
            invoice.period_end = add_period(invoice.paid_on, invoice.cycle)
    invoice.payment_method = method
    invoice.payment_reference = reference.strip()
    invoice.save()

    sub = get_subscription(agency)
    sub.plan, sub.cycle = invoice.plan, invoice.cycle
    sub.save(update_fields=["plan", "cycle", "updated_at"])
    agency._subscription_cache = sub
    agency.plan = agency.Plan.ACTIVE
    agency.paid_until = max(filter(None, [agency.paid_until, invoice.period_end]))
    agency.review_note = ""
    fields = ["plan", "paid_until", "review_note"]
    if agency.validated_at is None:
        agency.validated_at, agency.validated_by = timezone.now(), actor
        fields += ["validated_at", "validated_by"]
    agency.save(update_fields=fields)
    PlanChangeRequest.objects.filter(agency=agency, status=PlanChangeRequest.Status.PENDING, plan=invoice.plan).update(
        status=PlanChangeRequest.Status.DONE, handled_at=timezone.now())

    from audit.services import record

    record("billing.invoice_paid", agency=agency, actor=actor, target=invoice,
           metadata={"amount": int(invoice.amount), "method": method})
    _notify_admins(agency, f"Paiement reçu pour la facture {invoice.number}. Merci ! Abonnement {invoice.plan.name} "
                           f"actif jusqu'au {agency.paid_until:%d/%m/%Y}.")
    return invoice


@transaction.atomic
def void_invoice(invoice: Invoice, *, actor, reason: str = "") -> Invoice:
    if invoice.status != Invoice.Status.ISSUED:
        raise BusinessRuleError("Seule une facture à payer peut être annulée.")
    invoice.status = Invoice.Status.VOID
    invoice.notes = (f"Annulée : {reason.strip()}" if reason.strip() else "Annulée")[:255]
    invoice.save(update_fields=["status", "notes"])
    from audit.services import record

    record("billing.invoice_void", agency=invoice.agency, actor=actor, target=invoice)
    return invoice


# --------------------------------------------------------------------------- #
# Changement de formule
# --------------------------------------------------------------------------- #
@transaction.atomic
def request_plan_change(agency, *, user, plan: Plan, cycle: str, message: str = "") -> PlanChangeRequest:
    if not plan.is_public:
        raise BusinessRuleError("Cette formule n'est pas disponible.")
    current = get_subscription(agency)
    if current.plan_id == plan.id and current.cycle == cycle and agency.plan == agency.Plan.ACTIVE:
        raise BusinessRuleError("C'est déjà votre formule actuelle.")
    PlanChangeRequest.objects.filter(agency=agency, status=PlanChangeRequest.Status.PENDING).update(
        status=PlanChangeRequest.Status.REJECTED, handled_at=timezone.now())
    req = PlanChangeRequest.objects.create(agency=agency, plan=plan, cycle=cycle, message=message.strip()[:300],
                                           requested_by=user)
    from audit.services import record
    from dossiers.services import notify

    record("billing.plan_requested", agency=agency, actor=user, target=plan, metadata={"cycle": cycle})
    for admin in User.objects.filter(role=User.Role.PLATFORM_ADMIN, is_active=True):
        notify(admin, f"{agency.name} demande la formule {plan.name} ({Subscription.Cycle(cycle).label.lower()}).",
               url=reverse("console:billing"))
    return req


@transaction.atomic
def change_plan(agency, *, plan: Plan, cycle: str, actor) -> Subscription:
    """Changement immédiat par l'équipe NEURALIS (geste commercial, migration…)."""
    sub = get_subscription(agency)
    old = sub.plan
    sub.plan, sub.cycle = plan, cycle
    sub.save(update_fields=["plan", "cycle", "updated_at"])
    agency._subscription_cache = sub
    from audit.services import record

    record("billing.plan_changed", agency=agency, actor=actor, target=plan, metadata={"from": old.code, "to": plan.code})
    return sub


def _notify_admins(agency, message: str):
    from dossiers.services import notify

    for admin in agency.users.filter(role=User.Role.AGENCY_ADMIN, is_active=True):
        notify(admin, message, url=reverse("billing:overview"))
