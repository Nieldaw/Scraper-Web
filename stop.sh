#!/usr/bin/env bash
cd "$(dirname "$0")"
docker compose -f docker-compose.app.yml down && echo "Application arrêtée. Vos données sont conservées."
