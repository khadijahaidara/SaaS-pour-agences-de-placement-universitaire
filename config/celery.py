"""File de tâches Celery.

Avec REDIS_URL : les tâches partent dans Redis et sont traitées par le service
« worker » ; « beat » déclenche les tâches planifiées.
Sans REDIS_URL (développement, tests, petit hébergement) : les tâches s'exécutent
immédiatement dans le processus web (mode « eager ») — aucune dépendance requise.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("neuralis")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
