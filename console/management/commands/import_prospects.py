from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from console.importer import import_prospects


class Command(BaseCommand):
    help = "Importe des prospects depuis un fichier CSV ou .docx (tableau de prospection NEURALIS)."

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, path, **opts):
        p = Path(path)
        if not p.exists():
            raise CommandError(f"Fichier introuvable : {p}")
        try:
            result = import_prospects(p.read_bytes(), p.name)
        except ValueError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(
            f"{result['total']} prospects lus : {result['created']} créés, {result['updated']} mis à jour."))
