@echo off
title Growth IA - Celery Beat (planification)
cd /d "%~dp0"
call _load-env.bat
cd backend
echo Celery Beat (planificateur en base) - journal : logs\beat.log
.venv\Scripts\celery.exe -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler > ..\logs\beat.log 2>&1
