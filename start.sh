#!/usr/bin/env bash
# Lance l'application (macOS / Linux). Équivalent de demarrer.bat.
set -u
cd "$(dirname "$0")"
COMPOSE=(docker compose -f docker-compose.app.yml)
URL="http://localhost:8000"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERREUR : Docker n'est pas installé. Voir https://www.docker.com/products/docker-desktop/" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "ERREUR : Docker n'est pas lancé. Démarrez Docker Desktop, attendez qu'il soit prêt, puis relancez." >&2
  exit 1
fi

echo "[1/3] Docker est prêt."
echo "[2/3] Démarrage de l'application (5 à 10 minutes la première fois)..."
if ! "${COMPOSE[@]}" up -d --build; then
  echo "ERREUR : démarrage impossible (connexion internet ? port 8000 déjà utilisé ?)." >&2
  exit 1
fi

echo "[3/3] Attente de l'interface..."
for _ in $(seq 1 60); do
  if curl -fsS "$URL/health" >/dev/null 2>&1; then
    echo "L'application est prête : $URL"
    if command -v open >/dev/null 2>&1; then open "$URL"
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
    fi
    echo "Pour arrêter : ./stop.sh"
    exit 0
  fi
  sleep 2
done
echo "L'application met trop de temps à démarrer. Voir : ${COMPOSE[*]} logs app" >&2
exit 1
