@echo off
REM Tâches automatiques NEURALIS Mobility — à planifier toutes les heures
REM (Planificateur de tâches Windows > Créer une tâche > Déclencheur : toutes les heures).
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
python manage.py run_scheduled_tasks >> logs\taches.log 2>&1
