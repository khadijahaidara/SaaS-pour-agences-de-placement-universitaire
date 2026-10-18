from django.core.management.base import BaseCommand, CommandError

from agencies.services import AgencyCreationError, create_agency
from dossiers.services import build_invitation_path


class Command(BaseCommand):
    help = "Crée une agence cliente (essai gratuit), son responsable et les parcours par défaut."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--admin-email", required=True)
        parser.add_argument("--admin-first-name", default="")
        parser.add_argument("--admin-last-name", default="")
        parser.add_argument("--city", default="Bamako")
        parser.add_argument("--base-url", default="http://localhost:8000")

    def handle(self, *args, **opts):
        try:
            agency, admin = create_agency(
                name=opts["name"], admin_email=opts["admin_email"], admin_first_name=opts["admin_first_name"],
                admin_last_name=opts["admin_last_name"], city=opts["city"], source="cli",
            )
        except AgencyCreationError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f"Agence « {agency} » créée en essai gratuit."))
        self.stdout.write(f"Lien d'activation du responsable : {opts['base_url'].rstrip('/')}{build_invitation_path(admin)}")
