@echo off
title Growth IA - Relance complete
cd /d "%~dp0"
if not exist logs mkdir logs
echo == 1/3 Arret des processus existants ==
call "%~dp00-arreter.bat"
timeout /t 3 /nobreak >nul
echo == 2/3 Migrations de la base ==
call _load-env.bat
set DB_ROLE=
cd backend
(.venv\Scripts\python.exe manage.py migrate --noinput && echo === MIGRATE OK || echo === MIGRATE FAILED) > ..\logs\migrate.log 2>&1
cd ..
findstr /c:"=== MIGRATE OK" logs\migrate.log >nul
if errorlevel 1 ( type logs\migrate.log & echo. & echo Migrations en echec : voir logs\migrate.log & pause & exit /b 1 )
echo Migrations OK.
echo == 3/3 Demarrage ==
call "%~dp03-demarrer.bat"
