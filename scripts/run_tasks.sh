#!/bin/sh
# Tâches automatiques NEURALIS Mobility — exemple de cron : 0 * * * * /chemin/scripts/run_tasks.sh
cd "$(dirname "$0")/.." && python manage.py run_scheduled_tasks
