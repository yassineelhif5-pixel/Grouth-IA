@echo off
title Growth IA - Activer Redis + Celery + Beat
cd /d "%~dp0"
echo == 1/3 Installation de Redis (cache + broker) ==
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_redis-install.ps1"
if errorlevel 1 (echo Echec de l'installation de Redis. Vous pouvez installer Memurai ^(https://www.memurai.com^) puis relancer ce script. & pause & exit /b 1)
echo == 2/3 Configuration du fichier .env (copie de sauvegarde : .env.avant-redis) ==
if not exist .env.avant-redis copy /y .env .env.avant-redis >nul
powershell -NoProfile -Command "$p='.env'; $c=Get-Content $p; $c=$c | Where-Object { $_ -notmatch '^(REDIS_URL|CELERY_TASK_ALWAYS_EAGER|CELERY_BROKER_URL)=' }; $c += 'REDIS_URL=redis://localhost:6379/0'; $c += 'CELERY_TASK_ALWAYS_EAGER=false'; [IO.File]::WriteAllLines((Resolve-Path $p), [string[]]$c, (New-Object Text.UTF8Encoding($false)))"
echo == 3/3 Termine ==
echo Lancez 3-demarrer.bat : il demarre Redis, l'API, le worker Celery, Celery Beat et le site.
echo Pour revenir au mode sans Redis : 10b-desactiver-redis-celery.bat
pause
