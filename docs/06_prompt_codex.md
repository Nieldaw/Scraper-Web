# Prompts Codex pour VS Code

## Prompt systeme a garder en tete

Tu travailles sur Immo NE Collector. Respecte le perimetre MVP : canton de Neuchatel, collecte d'annonces publiques, normalisation, deduplication permissive, historique minimal, exports/API, mandats de recherche, SITN uniquement si adresse complete. Ne pas ajouter de detection de situations personnelles, ni d'enrichissement agressif de contacts prives.

## Prompt 1 - Comprendre le repo

Lis `README.md`, `docs/01_resume_projet.md`, `docs/02_architecture_technique.md` et `docs/05_data_contract.md`. Resume-moi la structure du projet et propose la prochaine petite tache executable en moins de 30 minutes.

## Prompt 2 - Migration initiale

A partir de `src/immo_ne_collector/models.py` et `docs/05_data_contract.md`, cree une migration Alembic initiale propre. Ajoute les index utiles pour `status`, `city`, `price_chf`, `last_seen_at`, et l'unicite `source + source_listing_id` quand `source_listing_id` existe.

## Prompt 3 - Normalisation

Complete `services/normalization.py` avec des fonctions pures pour normaliser prix CHF, surface m2, nombre de pieces et commune. Ajoute des tests pytest couvrant les formats suisses francophones courants.

## Prompt 4 - Deduplication

Ameliore `services/deduplication.py` pour calculer un score explicable. La fusion doit etre permissive : si le doute est eleve, ne fusionne pas. Ajoute des tests avec au moins 3 cas : meme bien evident, bien different, cas ambigu.

## Prompt 5 - SITN guard

Renforce `services/sitn.py` pour garantir qu'aucun appel externe SITN ne peut etre lance sans adresse complete. Ajoute des tests pour rue manquante, numero manquant, commune manquante et adresse complete.

## Prompt 6 - Export CSV

Ajoute des endpoints d'export CSV pour MASTER, NOUVEAUX, MODIFIES, RETIRES. Les colonnes doivent suivre `docs/05_data_contract.md`.

## Prompt 7 - Premier scraper

Cree un scraper pour un site cible donne. Avant de coder, isole les selecteurs dans une classe adapter. Le scraper doit tolerer les champs manquants, journaliser les erreurs et retourner des annonces brutes normalisables.
