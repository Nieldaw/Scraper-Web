# Backlog MVP

## P0 - Obligatoire

- [ ] API `/health`.
- [x] Connexion PostgreSQL.
- [x] Modeles `Property`, `SourceListing`, `SearchMandate`, `DailyRun`.
- [x] Migration initiale Alembic.
- [x] Normalisation prix / surface / pieces.
- [x] Collecte quotidienne executable manuellement.
- [x] Deduplication permissive avec score et raison.
- [x] Statuts NEW / ACTIVE / UPDATED / INACTIVE / REMOVED.
- [x] Exports CSV MASTER / NOUVEAUX / MODIFIES / RETIRES.
- [x] Garde-fou SITN adresse complete.
- [x] Tests unitaires sur normalisation, deduplication, SITN guard.
- [x] Parser Anibis sur cache HTML local.
- [x] Filtrage Anibis `sale/rent/unknown`.
- [x] Filtrage Anibis canton `NE`.
- [x] Exports `ventes.csv` et `locations.csv`.
- [x] Rapport qualite `quality_report.csv`.
- [x] Commande unique `scripts/collect_anibis_sale_ne.py`.

## P1 - Important

- [ ] Logs structures.
- [x] Table `daily_runs` avec stats par execution.
- [x] Gestion des erreurs par site sans crash global.
- [x] Mandats de recherche sauvegardes.
- [x] Export resultats par mandat.
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
