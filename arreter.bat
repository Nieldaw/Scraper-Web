@echo off
setlocal
cd /d "%~dp0"
title Immo Collector - arret
docker info >nul 2>&1
if errorlevel 1 goto docker_off
docker compose -f docker-compose.app.yml down
echo.
echo  Application arretee. Vos donnees sont conservees.
pause
exit /b 0

:docker_off
echo  Docker Desktop n'est pas lance : l'application est deja arretee.
pause
exit /b 0
