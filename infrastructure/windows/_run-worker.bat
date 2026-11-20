@echo off
title Growth IA - Celery worker
cd /d "%~dp0"
call _load-env.bat
cd backend
echo Worker Celery (pool solo, compatible Windows) - journal : logs\worker.log
.venv\Scripts\celery.exe -A config worker --pool=solo -l info -Q default,health,notifications,maintenance,integrations,dead_letter > ..\logs\worker.log 2>&1
