# Image de l'application web seule (sans outils de développement), pour l'installation « utilisateur ».
# L'environnement de développement garde son propre Dockerfile / docker-compose.yml.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Installation en mode éditable : le code reste dans /app/src, et les chemins relatifs du projet
# (scripts/, data/, migrations/) restent valides.
COPY pyproject.toml alembic.ini ./
COPY src ./src
COPY scripts ./scripts
COPY migrations ./migrations
RUN pip install -e .

# Dossiers de travail (montés depuis l'hôte par docker-compose.app.yml).
RUN mkdir -p data/cache/html data/exports data/logs

EXPOSE 8000

# 1) crée/met à jour le schéma de la base ; 2) démarre le serveur web.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn immo_ne_collector.main:app --host 0.0.0.0 --port 8000"]
