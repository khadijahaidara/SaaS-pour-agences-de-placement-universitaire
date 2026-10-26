"""Lance les tâches automatiques (à planifier toutes les heures).

    python manage.py run_scheduled_tasks             # toutes les tâches
    python manage.py run_scheduled_tasks --only relances_pieces

Linux / Docker : cron « 0 * * * * » ou le service « scheduler » du docker-compose.
Windows : Planificateur de tâches → scripts\\run_tasks.bat toutes les heures.
"""
import traceback

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from console.models import TaskRun
from dossiers.tasks import TASKS


class Command(BaseCommand):
    help = "Relances automatiques, résumé quotidien et suivi des essais."

    def add_arguments(self, parser):
        parser.add_argument("--only", choices=sorted(TASKS), help="Lancer une seule tâche.")
        parser.add_argument("--force", action="store_true", help="Ignorer la règle « une fois par jour ».")

    def handle(self, *args, only=None, force=False, **opts):
        names = [only] if only else list(TASKS)
        failures = 0
        for name in names:
            func, once_a_day = TASKS[name]
            today_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
            if once_a_day and not force and TaskRun.objects.filter(
                    name=name, status=TaskRun.Status.SUCCESS, started_at__gte=today_start).exists():
                self.stdout.write(f"{name} : déjà exécutée aujourd'hui")
                continue
            run = TaskRun.objects.create(name=name)
            try:
                with transaction.atomic():
                    stats = func()
            except Exception as exc:  # une tâche en erreur n'empêche pas les suivantes
                failures += 1
                run.status, run.error = TaskRun.Status.ERROR, "".join(traceback.format_exception(exc))[-4000:]
                self.stderr.write(self.style.ERROR(f"{name} : erreur — {exc}"))
            else:
                run.status, run.stats = TaskRun.Status.SUCCESS, stats
                self.stdout.write(self.style.SUCCESS(f"{name} : {stats}"))
            run.finished_at = timezone.now()
            run.save()
        TaskRun.objects.filter(started_at__lt=timezone.now() - timezone.timedelta(days=90)).delete()
        if failures:
            raise CommandError(f"{failures} tâche(s) en erreur — voir la console NEURALIS.")
