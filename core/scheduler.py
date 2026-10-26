"""Exécution journalisée des tâches planifiées (commande, Celery beat ou console)."""
import traceback

from django.db import transaction
from django.utils import timezone


def registry() -> dict:
    """Nom → (fonction, une seule exécution réussie par jour ?)."""
    from billing.tasks import renewal_notices
    from dossiers.tasks import TASKS
    from integrations.tasks import retry_due_deliveries

    tasks = dict(TASKS)
    tasks["renouvellements"] = (renewal_notices, False)
    tasks["webhooks_relances"] = (retry_due_deliveries, False)
    tasks["purge_journal"] = (purge_audit_log, True)
    return tasks


def purge_audit_log() -> dict:
    """Conserve le journal d'audit AUDIT_RETENTION_DAYS jours (365 par défaut)."""
    from django.conf import settings

    from audit.models import AuditLog

    limit = timezone.now() - timezone.timedelta(days=settings.AUDIT_RETENTION_DAYS)
    deleted, _ = AuditLog.objects.filter(created_at__lt=limit).delete()
    from accounts.models import UserSession

    UserSession.objects.filter(last_seen__lt=timezone.now() - timezone.timedelta(days=30)).delete()
    return {"entrees_supprimees": deleted}


def labels() -> dict:
    from dossiers.tasks import TASK_LABELS

    return {**TASK_LABELS, "renouvellements": "Renouvellements d'abonnement",
            "webhooks_relances": "Nouvelles tentatives des webhooks", "purge_journal": "Purge du journal d'audit"}


def run_task(name: str, *, force: bool = False):
    """Lance une tâche et enregistre son exécution (TaskRun). Retourne le TaskRun, ou None si sautée."""
    from console.models import TaskRun

    func, once_a_day = registry()[name]
    today_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    if once_a_day and not force and TaskRun.objects.filter(
            name=name, status=TaskRun.Status.SUCCESS, started_at__gte=today_start).exists():
        return None
    run = TaskRun.objects.create(name=name)
    try:
        with transaction.atomic():
            stats = func()
    except Exception as exc:  # une tâche en erreur n'empêche pas les suivantes
        run.status, run.error = TaskRun.Status.ERROR, "".join(traceback.format_exception(exc))[-4000:]
    else:
        run.status, run.stats = TaskRun.Status.SUCCESS, stats
    run.finished_at = timezone.now()
    run.save()
    return run


def purge_old_runs(days: int = 90):
    from console.models import TaskRun

    TaskRun.objects.filter(started_at__lt=timezone.now() - timezone.timedelta(days=days)).delete()
