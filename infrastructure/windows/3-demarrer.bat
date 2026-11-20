@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
findstr /b /c:"REDIS_URL=redis://" .env >nul
if not errorlevel 1 if exist tools\redis\redis-server.exe (
  start "Growth IA - Redis" /min cmd /k "%~dp0_run-redis.bat"
  timeout /t 3 /nobreak >nul
  start "Growth IA - Celery worker" /min cmd /k "%~dp0_run-worker.bat"
  start "Growth IA - Celery Beat" /min cmd /k "%~dp0_run-beat.bat"
)
start "Growth IA - API" cmd /k "%~dp0_run-api.bat"
start "Growth IA - Frontend" cmd /k "%~dp0_run-web.bat"
timeout /t 15 /nobreak >nul
start "" http://localhost:5173
