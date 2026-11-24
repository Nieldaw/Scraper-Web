@echo off
setlocal
cd /d "%~dp0"
title Immo Collector - demarrage
set COMPOSE=docker compose -f docker-compose.app.yml

echo.
echo  === Immo Collector ===
echo.

where docker >nul 2>&1
if errorlevel 1 goto install_docker

:check_engine
docker info >nul 2>&1
if not errorlevel 1 goto docker_ok
call :start_docker_desktop
set /a dtries=0
:wait_engine
docker info >nul 2>&1
if not errorlevel 1 goto docker_ok
set /a dtries+=1
if %dtries% GEQ 60 goto docker_off
echo       Attente du demarrage de Docker Desktop... (%dtries%/60)
timeout /t 5 /nobreak >nul
goto wait_engine

:docker_ok

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

:install_docker
echo  Docker Desktop n'est pas installe : installation automatique via winget.
echo  Windows va demander une autorisation (fenetre bleue/jaune) : acceptez.
echo.
where winget >nul 2>&1
if errorlevel 1 goto no_winget
winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto install_failed
set "PATH=%PATH%;%ProgramFiles%\Docker\Docker\resources\bin"
where docker >nul 2>&1
if errorlevel 1 goto reboot_needed
echo.
echo  Docker Desktop est installe. Si une fenetre Docker demande d'accepter les
echo  conditions d'utilisation, acceptez-les (Docker ne demarre pas avant).
echo.
goto check_engine

:reboot_needed
echo.
echo  Docker Desktop est installe, mais Windows doit redemarrer pour finir.
echo  1. Redemarrez le PC.
echo  2. Double-cliquez a nouveau sur demarrer.bat : tout continuera tout seul.
pause
exit /b 0

:no_winget
echo  ERREUR : l'outil d'installation automatique (winget) est absent de ce Windows.
echo  Installez Docker Desktop a la main : https://www.docker.com/products/docker-desktop/
echo  puis relancez ce fichier.
start "" https://www.docker.com/products/docker-desktop/
pause
exit /b 1

:install_failed
echo.
echo  ERREUR : l'installation de Docker Desktop a echoue (ou a ete refusee).
echo  Installez-le a la main : https://www.docker.com/products/docker-desktop/
echo  puis relancez ce fichier.
start "" https://www.docker.com/products/docker-desktop/
pause
exit /b 1

:start_docker_desktop
echo  Docker Desktop n'est pas lance : demarrage automatique...
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
  start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
)
exit /b 0

:docker_off
echo  ERREUR : Docker Desktop n'a pas demarre a temps.
echo.
echo  1. Ouvrez Docker Desktop depuis le menu Demarrer (acceptez ses conditions si demande).
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
