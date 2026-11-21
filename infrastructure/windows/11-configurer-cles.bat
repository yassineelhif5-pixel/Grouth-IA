@echo off
title Growth IA - Cles Claude et Supabase
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_set-keys.ps1"
echo.
choice /m "Relancer Growth IA maintenant pour prendre en compte les cles"
if errorlevel 2 exit /b 0
call "%~dp00-relancer-tout.bat"
