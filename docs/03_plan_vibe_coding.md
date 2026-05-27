# Plan de travail Vibe coding

## Regle de base

Une session = une tache claire = un test ou une verification.

Eviter les prompts trop larges du type "code tout le projet". Preferer des increments petits, testables et documentes.

## Sequence recommandee

### Etape 1 - Socle projet

- Verifier installation locale.
- Lancer FastAPI.
- Lancer PostgreSQL via Docker Compose.
- Faire passer les tests existants.

### Etape 2 - Modele de donnees

- Finaliser SQLAlchemy models.
- Creer migration initiale Alembic.
- Ajouter contraintes et index utiles.
- Tester creation DB.

### Etape 3 - Normalisation

- Implementer parse prix.
- Implementer parse surface.
- Implementer parse pieces.
- Tester sur cas reels.

### Etape 4 - Premier scraper test

- Choisir un site cible legalement acceptable.
- Lire robots.txt / CGU.
- Implementer extraction minimale.
- Stocker annonces brutes.

### Etape 5 - Deduplication

- Implementer scoring candidat.
- Ajouter traces de fusion.
- Tester les cas limites.

### Etape 6 - Vues metier

- MASTER.
- NOUVEAUX.
- MODIFIES.
- RETIRES/INACTIFS.

### Etape 7 - Mandats de recherche

- Modeliser criteres.
- Matcher les biens.
- Exporter resultats.

### Etape 8 - SITN guard

- Implementer uniquement l'eligibilite.
- Ajouter tests garantissant qu'aucun appel SITN n'est fait si adresse incomplete.
- Ajouter integration SITN seulement apres validation.

## Prompts Codex utiles

Voir `docs/06_prompt_codex.md`.
