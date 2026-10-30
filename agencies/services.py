"""Création d'agences clientes (inscription libre, console NEURALIS, ligne de commande)."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from dossiers.defaults import install_default_workflows

from .defaults import install_default_templates
from .models import RESERVED_SUBDOMAINS, Agency

User = get_user_model()


class AgencyCreationError(Exception):
    pass


def unique_slug(name: str) -> str:
    base = slugify(name)[:40] or "agence"
    slug, n = base, 2
    while Agency.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def unique_subdomain(slug: str) -> str | None:
    base = slug[:36].strip("-")
    if len(base) < 3:
        return None
    candidate, n = base, 2
    while candidate in RESERVED_SUBDOMAINS or Agency.objects.filter(subdomain=candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


@transaction.atomic
def create_agency(
    *,
    name: str,
    admin_email: str,
    admin_first_name: str = "",
    admin_last_name: str = "",
    admin_password: str | None = None,
    city: str = "Bamako",
    phone: str = "",
    source: str = "",
    prospect=None,
    pending: bool = False,
    plan_code: str = "",
    cycle: str = "monthly",
) -> tuple[Agency, "User"]:
    """Crée l'agence, son responsable et les parcours par défaut.

    - Créée par l'équipe NEURALIS (console, ligne de commande) : essai gratuit immédiat.
    - Inscription en ligne (`pending=True`) : espace « en attente de validation » ; une facture
      est émise pour la formule choisie et l'accès n'est ouvert qu'après validation NEURALIS.

    Sans mot de passe, le responsable reçoit un compte à activer par lien d'invitation.
    Si un prospect du CRM correspond, il est rattaché et passe « En essai ».
    """
    email = admin_email.strip().lower()
    if User.objects.filter(email__iexact=email).exists():
        raise AgencyCreationError("Un compte existe déjà avec ce courriel. Connectez-vous ou utilisez un autre courriel.")
    slug = unique_slug(name)
    agency = Agency(name=name.strip(), slug=slug, city=city.strip() or "Bamako",
                    phone=phone.strip(), email=email, signup_source=source, subdomain=unique_subdomain(slug))
    if pending:
        agency.plan = Agency.Plan.PENDING
    else:
        agency.start_trial()
    agency.save()
    admin = User.objects.create_user(
        email=email, password=admin_password, first_name=admin_first_name.strip(),
        last_name=admin_last_name.strip(), phone=phone.strip(), role=User.Role.AGENCY_ADMIN, agency=agency,
    )
    install_default_workflows(agency)
    install_default_templates(agency)
    from accounts.rbac import ensure_default_roles
    from billing.services import get_subscription

    ensure_default_roles(agency)
    sub = get_subscription(agency)
    if plan_code:
        from billing.models import Plan, Subscription

        plan = Plan.objects.filter(code=plan_code, is_public=True).first()
        if plan is not None:
            sub.plan = plan
            sub.cycle = cycle if cycle in Subscription.Cycle.values else Subscription.Cycle.MONTHLY
            sub.save(update_fields=["plan", "cycle", "updated_at"])
    if pending:
        from billing.services import issue_invoice

        issue_invoice(agency, plan=sub.plan, cycle=sub.cycle, notes="Ouverture de l'espace")
        _notify_platform(agency, admin)

    from console.models import Prospect, ProspectActivity  # import local : évite un cycle

    if prospect is None:
        prospect = Prospect.objects.filter(agency__isnull=True, email__icontains=email).first()
    if prospect is not None and prospect.agency_id is None:
        prospect.agency = agency
        if prospect.status not in {Prospect.Status.WON}:
            prospect.status = Prospect.Status.CONTACTED if pending else Prospect.Status.TRIAL
        prospect.save(update_fields=["agency", "status", "updated_at"])
        ProspectActivity.objects.create(
            prospect=prospect, kind=ProspectActivity.Kind.STATUS,
            summary=(f"Inscription en ligne — formule {sub.plan.name}, en attente de paiement et de validation."
                     if pending else f"Espace agence créé ({source or 'console'}) — essai gratuit démarré."),
        )
    return agency, admin



def _notify_platform(agency, admin):
    from django.urls import reverse

    from dossiers.services import notify

    for staff in User.objects.filter(role=User.Role.PLATFORM_ADMIN, is_active=True):
        notify(staff, f"Nouvelle demande d'espace : {agency.name} ({agency.city}) — {admin.email}. "
                      "À valider après paiement.", url=reverse("console:billing"))


@transaction.atomic
def approve_agency(agency, *, actor, trial_days: int | None = None):
    """Ouvre l'accès d'une agence en attente (essai accordé) — l'activation payée passe par mark_paid."""
    from django.utils import timezone

    agency.validated_at, agency.validated_by, agency.review_note = timezone.now(), actor, ""
    if trial_days:
        agency.start_trial(days=trial_days)
    elif agency.plan == Agency.Plan.PENDING:
        agency.plan = Agency.Plan.ACTIVE
    agency.save()
    from audit.services import record

    record("agency.approved", agency=agency, actor=actor, metadata={"essai_jours": trial_days or 0})
    _notify_agency_admins(agency, "Votre espace est ouvert : bienvenue ! Vous pouvez inviter votre équipe et créer vos dossiers.")


@transaction.atomic
def reject_agency(agency, *, actor, reason: str):
    from billing.models import Invoice

    agency.plan, agency.review_note = Agency.Plan.SUSPENDED, reason.strip()[:255]
    agency.save(update_fields=["plan", "review_note"])
    Invoice.objects.filter(agency=agency, status=Invoice.Status.ISSUED).update(
        status=Invoice.Status.VOID, notes="Annulée : demande refusée")
    from audit.services import record

    record("agency.rejected", agency=agency, actor=actor, metadata={"motif": reason.strip()[:120]})
    _notify_agency_admins(agency, f"Votre demande d'espace n'a pas été acceptée : {reason.strip()}")


def _notify_agency_admins(agency, message):
    from django.urls import reverse

    from dossiers.services import notify

    for admin in agency.users.filter(role=User.Role.AGENCY_ADMIN, is_active=True):
        notify(admin, message, url=reverse("home"))
