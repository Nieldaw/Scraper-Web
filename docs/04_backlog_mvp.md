# Backlog MVP

## P0 - Obligatoire

- [ ] API `/health`.
- [ ] Connexion PostgreSQL.
- [ ] Modeles `Property`, `SourceListing`, `SearchMandate`, `DailyRun`.
- [ ] Migration initiale Alembic.
- [ ] Normalisation prix / surface / pieces.
- [ ] Collecte quotidienne executable manuellement.
- [ ] Deduplication permissive avec score et raison.
- [ ] Statuts NEW / ACTIVE / UPDATED / INACTIVE / REMOVED.
- [ ] Exports CSV MASTER / NOUVEAUX / MODIFIES / RETIRES.
- [ ] Garde-fou SITN adresse complete.
- [ ] Tests unitaires sur normalisation, deduplication, SITN guard.

## P1 - Important

- [ ] Logs structures.
- [ ] Table `daily_runs` avec stats par execution.
- [ ] Gestion des erreurs par site sans crash global.
- [ ] Mandats de recherche sauvegardes.
- [ ] Export resultats par mandat.
- [ ] Documentation data contract.

## P2 - Plus tard

- [ ] Interface web interne.
- [ ] Notifications email recapitulatives.
- [ ] Cache Redis.
- [ ] Celery / scheduler avance.
- [ ] Recherche full-text avancee.
- [ ] Scoring explicable non sensible.

## Hors scope explicite v1

- [ ] Detection deces / divorce / difficulte financiere.
- [ ] Scraping de donnees personnelles non necessaires.
- [ ] Enrichissement telephone/email prive.
- [ ] Kubernetes.
