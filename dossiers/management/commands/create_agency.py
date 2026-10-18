from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from agencies.models import Agency
from dossiers.defaults import install_default_workflows
from dossiers.services import build_invitation_path

User = get_user_model()


class Command(BaseCommand):
    help = "Crée une agence cliente, son responsable et les modèles de parcours par défaut."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--admin-email", required=True)
        parser.add_argument("--admin-first-name", default="")
        parser.add_argument("--admin-last-name", default="")
        parser.add_argument("--city", default="Bamako")
        parser.add_argument("--base-url", default="http://localhost:8000")

    @transaction.atomic
    def handle(self, *args, **opts):
        email = opts["admin_email"].lower()
        if User.objects.filter(email=email).exists():
            raise CommandError("Ce courriel est déjà utilisé.")
        slug = slugify(opts["name"])
        if Agency.objects.filter(slug=slug).exists():
            raise CommandError("Une agence porte déjà ce nom.")
        agency = Agency.objects.create(name=opts["name"], slug=slug, city=opts["city"])
        admin = User.objects.create_user(
            email=email, first_name=opts["admin_first_name"], last_name=opts["admin_last_name"],
            role=User.Role.AGENCY_ADMIN, agency=agency,
        )
        n = install_default_workflows(agency)
        self.stdout.write(self.style.SUCCESS(f"Agence « {agency} » créée avec {n} modèles de parcours."))
        self.stdout.write(f"Lien d'activation du responsable : {opts['base_url'].rstrip('/')}{build_invitation_path(admin)}")
