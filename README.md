# Immo NE Collector

Collecteur d'annonces immobilieres pour le canton de Neuchatel.

Ce repository est un starter kit concu pour travailler en Vibe coding dans VS Code avec Codex + ChatGPT. Il fixe le perimetre MVP, la structure du code, les conventions et les premiers fichiers techniques.

## Objectif MVP

Construire un programme qui collecte quotidiennement des annonces immobilieres publiques sur une liste de sites fournie par le client, normalise les donnees, detecte les doublons de maniere permissive, stocke les biens dans PostgreSQL et expose des sorties exploitables pour un prospecteur.

Le MVP couvre prioritairement :

- Canton de Neuchatel uniquement.
- Collecte multi-sites.
- Normalisation prix / surfaces / pieces / communes.
- Deduplication permissive : mieux vaut garder un doublon que fusionner deux biens differents.
- Vues MASTER, NOUVEAUX, MODIFIES, RETIRES/INACTIFS.
- Mandats de recherche sauvegardes.
- Module SITN uniquement si adresse complete.

## Hors perimetre v1

- Detection de deces, divorce, difficulte financiere ou situation personnelle.
- Enrichissement agressif de contacts prives.
- Scraping de bases privees ou protegees.
- Architecture lourde Kubernetes / haute disponibilite.
- Couverture hors canton NE.

## Stack recommandee

### Backend

- Python 3.11+
- FastAPI pour API REST et documentation OpenAPI automatique
- Pydantic Settings pour la configuration
- SQLAlchemy 2 + Alembic pour ORM et migrations
- PostgreSQL pour stockage principal
- Playwright / httpx / BeautifulSoup pour collecteurs selon les sites
- RapidFuzz pour scoring de similarite deduplication
- Typer pour commandes CLI internes
- pytest pour tests

### Infrastructure locale

- Docker Compose pour PostgreSQL
- VS Code + Codex pour Vibe coding
- `.env` local a partir de `.env.example`

### Frontend

Pas de frontend lourd au depart. Le MVP expose :

1. API REST minimale.
2. Exports CSV.
3. Eventuellement une mini interface FastAPI plus tard.

## Demarrage local

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
playwright install chromium
docker compose up -d db
uvicorn immo_ne_collector.main:app --reload
```

API locale : http://127.0.0.1:8000
Docs API : http://127.0.0.1:8000/docs

## Commandes utiles

```bash
make run
make test
make lint
make format
make collect-once
```

## Structure

```text
.
|-- docs/
|-- src/immo_ne_collector/
|   |-- api/
|   |-- jobs/
|   |-- scrapers/
|   |-- services/
|   |-- main.py
|   |-- models.py
|   |-- schemas.py
|-- tests/
|-- migrations/
|-- scripts/
|-- docker-compose.yml
|-- pyproject.toml
|-- .env.example
```

## Regle SITN importante

Le module SITN ne doit jamais etre appele si l'adresse est incomplete. Une adresse est consideree complete seulement si elle contient au minimum : rue + numero + commune, NPA recommande.

Si l'adresse est incomplete :

- `needs_completion = true`
- `completion_reason = 'Adresse manquante'`
- `sitn_eligible = false`
- `sitn_status = 'NOT_ELIGIBLE_MISSING_ADDRESS'`

## Methode de travail Vibe coding

1. Garder le CDC comme source de verite.
2. Demander a Codex une seule tache a la fois.
3. Faire tourner les tests apres chaque generation.
4. Refuser les ajouts hors perimetre v1.
5. Documenter chaque decision dans `docs/02_architecture_technique.md`.

Voir `docs/06_prompt_codex.md` pour les prompts de demarrage.
