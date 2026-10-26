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
) -> tuple[Agency, "User"]:
    """Crée l'agence en essai gratuit, son responsable et les parcours par défaut.

    Sans mot de passe, le responsable reçoit un compte à activer par lien d'invitation.
    Si un prospect du CRM correspond, il est rattaché et passe « En essai ».
    """
    email = admin_email.strip().lower()
    if User.objects.filter(email__iexact=email).exists():
        raise AgencyCreationError("Un compte existe déjà avec ce courriel. Connectez-vous ou utilisez un autre courriel.")
    slug = unique_slug(name)
    agency = Agency(name=name.strip(), slug=slug, city=city.strip() or "Bamako",
                    phone=phone.strip(), email=email, signup_source=source, subdomain=unique_subdomain(slug))
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
    get_subscription(agency)

    from console.models import Prospect, ProspectActivity  # import local : évite un cycle

    if prospect is None:
        prospect = Prospect.objects.filter(agency__isnull=True, email__icontains=email).first()
    if prospect is not None and prospect.agency_id is None:
        prospect.agency = agency
        if prospect.status not in {Prospect.Status.WON}:
            prospect.status = Prospect.Status.TRIAL
        prospect.save(update_fields=["agency", "status", "updated_at"])
        ProspectActivity.objects.create(
            prospect=prospect, kind=ProspectActivity.Kind.STATUS,
            summary=f"Espace agence créé ({'inscription en ligne' if source == 'self_signup' else source}) — essai gratuit démarré.",
        )
    return agency, admin
