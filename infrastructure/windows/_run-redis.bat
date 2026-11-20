@echo off
title Growth IA - Redis (localhost:6379)
cd /d "%~dp0tools\redis"
redis-server.exe growth.conf
