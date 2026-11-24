@echo off
setlocal
cd /d "%~dp0"
title Immo Collector - demarrage
set COMPOSE=docker compose -f docker-compose.app.yml

echo.
echo  === Immo Collector ===
echo.

where docker >nul 2>&1
if errorlevel 1 goto no_docker

docker info >nul 2>&1
if errorlevel 1 goto docker_off

echo [1/3] Docker est pret.
echo [2/3] Demarrage de l'application. La premiere fois, cela peut prendre 5 a 10 minutes
echo       (telechargement et construction), les fois suivantes quelques secondes.
echo.
%COMPOSE% up -d --build
if errorlevel 1 goto compose_failed

echo.
echo [3/3] Attente du demarrage de l'interface...
set /a tries=0
:wait
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8000/health -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% GEQ 60 goto timeout
timeout /t 2 /nobreak >nul
goto wait

:ready
echo.
echo  L'application est prete : http://localhost:8000
echo  Ouverture du navigateur...
start "" http://localhost:8000
echo.
echo  Pour arreter l'application : double-cliquez sur arreter.bat
echo.
pause
exit /b 0

:no_docker
echo  ERREUR : Docker Desktop n'est pas installe sur ce PC.
echo.
echo  Installez-le depuis https://www.docker.com/products/docker-desktop/
echo  puis relancez ce fichier. Le detail est dans GUIDE_UTILISATION.md.
start "" https://www.docker.com/products/docker-desktop/
pause
exit /b 1

:docker_off
echo  ERREUR : Docker Desktop n'est pas lance.
echo.
echo  1. Ouvrez Docker Desktop depuis le menu Demarrer.
echo  2. Attendez que l'icone de la baleine en bas a droite ne bouge plus
echo     et que Docker affiche "Engine running".
echo  3. Relancez ce fichier.
pause
exit /b 1

:compose_failed
echo.
echo  ERREUR : l'application n'a pas pu demarrer. Lisez les messages ci-dessus.
echo  Causes frequentes : pas de connexion internet au premier lancement,
echo  ou le port 8000 est deja utilise par un autre programme.
pause
exit /b 1

:timeout
echo.
echo  L'application met trop de temps a demarrer.
echo  Pour voir ce qui se passe, ouvrez une invite de commandes dans ce dossier et tapez :
echo      docker compose -f docker-compose.app.yml logs app
pause
exit /b 1
