# Architecture technique

## Decision principale

Architecture modulaire Python, simple a comprendre et a modifier en Vibe coding.

On evite une architecture trop lourde. Pas de Kubernetes, pas d'Elasticsearch au demarrage, pas de microservices. On commence par un backend FastAPI + jobs de collecte + PostgreSQL.

## Pipeline global

```text
Sites sources
  -> Scrapers / adapters
  -> Normalisation
  -> Stockage annonces brutes
  -> Deduplication permissive
  -> Fusion en biens internes
  -> Historisation changements
  -> Mandats de recherche
  -> Exports / API / vues
  -> SITN si adresse complete uniquement
```

## Modules

### 1. Scrapers

Chaque site cible aura un adapter dedie dans `src/immo_ne_collector/scrapers/`.

Regles :

- Un scraper retourne des objets normalisables, jamais directement des lignes SQL.
- Chaque annonce conserve son URL source.
- Le HTML brut ou les donnees brutes utiles sont stockes dans `raw_data`.
- Un scraper ne doit pas faire de deduplication globale.

### 2. Normalisation

Objectif : transformer les donnees heterogenes en format stable.

Exemples :

- Prix vers `price_chf` numerique.
- Surface vers `living_area_m2` numerique.
- Pieces vers `rooms` numerique.
- Communes vers valeurs propres.
- Sources vers noms constants.

### 3. Deduplication permissive

On calcule un score de similarite entre annonces candidates.

Regle : fusion uniquement si le score est suffisamment fort. En cas de doute, on garde deux biens separes.

Signaux possibles :

- Meme commune.
- Meme type de bien.
- Surface proche.
- Nombre de pieces proche.
- Prix proche.
- Similarite titre / description.
- Adresse identique si disponible.

On stocke toujours les raisons de fusion pour audit.

### 4. Historisation

Champs minimum :

- `first_seen_at`
- `last_seen_at`
- `last_changed_at`
- `status`

Statuts :

- `NEW`
- `ACTIVE`
- `UPDATED`
- `INACTIVE`
- `REMOVED`

### 5. SITN

Le service SITN est isole dans `services/sitn.py`.

Il expose d'abord un garde-fou d'eligibilite. Aucune requete externe SITN ne doit etre lancee tant que l'adresse n'est pas complete.

### 6. API et exports

Endpoints MVP :

- `GET /health`
- `GET /properties`
- `GET /properties/new`
- `GET /properties/updated`
- `GET /properties/inactive`
- `GET /exports/master.csv`
- `GET /mandates`
- `POST /mandates`

## Choix techniques

| Besoin | Choix | Raison |
|---|---|---|
| API | FastAPI | Simple, rapide, bon support OpenAPI |
| DB | PostgreSQL | Donnees relationnelles + JSONB pour brut |
| ORM | SQLAlchemy 2 | Standard Python robuste |
| Migrations | Alembic | Versionner le schema |
| Scraping simple | httpx + BeautifulSoup | Rapide si HTML statique |
| Scraping dynamique | Playwright | Sites JS / rendu navigateur |
| Similarite | RapidFuzz | Simple pour titres/descriptions |
| Jobs | CLI + cron au depart | Moins lourd que Celery pour MVP |
| Tests | pytest | Base fiable pour Codex |

## Decisions futures possibles

- Ajouter Redis si files de jobs ou cache necessaire.
- Ajouter Celery si orchestration multi-sites devient lourde.
- Ajouter un dashboard Vue/React si les exports/API ne suffisent plus.
- Ajouter Elasticsearch seulement si la recherche PostgreSQL devient insuffisante.
