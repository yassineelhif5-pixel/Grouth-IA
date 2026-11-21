@echo off
cd /d "%~dp0"
powershell -NoProfile -Command "$p='.env'; $c=Get-Content $p; $c=$c | Where-Object { $_ -notmatch '^(REDIS_URL|CELERY_TASK_ALWAYS_EAGER|CELERY_BROKER_URL)=' }; $c += 'REDIS_URL=memory://'; $c += 'CELERY_TASK_ALWAYS_EAGER=true'; [IO.File]::WriteAllLines((Resolve-Path $p), [string[]]$c, (New-Object Text.UTF8Encoding($false)))"
echo Mode sans Redis retabli (taches executees directement par l'API).
pause
