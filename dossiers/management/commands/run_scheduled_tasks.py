"""Lance les tâches automatiques sans Celery (cron, Planificateur Windows).

    python manage.py run_scheduled_tasks             # toutes les tâches
    python manage.py run_scheduled_tasks --only relances_pieces

Avec Redis, le service « beat » de Celery s'en charge (voir CELERY_BEAT_SCHEDULE).
"""
from django.core.management.base import BaseCommand, CommandError

from core.scheduler import purge_old_runs, registry, run_task


class Command(BaseCommand):
    help = "Relances automatiques, résumé quotidien, essais, renouvellements et webhooks."

    def add_arguments(self, parser):
        parser.add_argument("--only", help="Lancer une seule tâche.")
        parser.add_argument("--force", action="store_true", help="Ignorer la règle « une fois par jour ».")

    def handle(self, *args, only=None, force=False, **opts):
        tasks = registry()
        if only and only not in tasks:
            raise CommandError(f"Tâche inconnue. Choix : {', '.join(sorted(tasks))}")
        failures = 0
        for name in [only] if only else list(tasks):
            run = run_task(name, force=force)
            if run is None:
                self.stdout.write(f"{name} : déjà exécutée aujourd'hui")
            elif run.status == run.Status.ERROR:
                failures += 1
                self.stderr.write(self.style.ERROR(f"{name} : erreur — {run.error.strip().splitlines()[-1]}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"{name} : {run.stats}"))
        purge_old_runs()
        if failures:
            raise CommandError(f"{failures} tâche(s) en erreur — voir la console NEURALIS.")
