"""Tâches Celery transverses : courriels et tâches planifiées."""
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(OSError,), retry_backoff=60, retry_backoff_max=1800,
             max_retries=5, ignore_result=True)
def send_email(self, subject: str, body: str, to: list[str], html: str = ""):
    """Envoi d'un courriel hors du cycle de la requête, avec nouvelles tentatives si le SMTP échoue."""
    message = EmailMultiAlternatives(subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=to)
    if html:
        message.attach_alternative(html, "text/html")
    message.send(fail_silently=False)


@shared_task(ignore_result=True)
def run_scheduled(name: str):
    from .scheduler import purge_old_runs, run_task

    run = run_task(name)
    if run is not None and run.status == run.Status.ERROR:
        logger.error("Tâche %s en erreur : %s", name, run.error[-500:])
    purge_old_runs()


def queue_email(subject: str, body: str, to: list[str], html: str = "") -> None:
    """Met le courriel en file après validation de la transaction ; ne lève jamais d'exception."""
    from django.db import transaction

    def _enqueue():
        try:
            send_email.delay(subject, body, to, html)
        except Exception:  # broker indisponible : on journalise, l'action métier reste valide
            logger.exception("Impossible de mettre en file le courriel pour %s", to)

    transaction.on_commit(_enqueue)
