# Source Anibis (MVP)

## Perimetre

Source cible MVP: Anibis, canton de Neuchatel, annonces de vente.

Le flux courant est pilote via:

```bash
python3 scripts/collect_anibis_sale_ne.py
```

## Fonctionnement prudent

- Une URL a la fois.
- Pas de pagination automatique.
- Pas de scraping massif.
- Pas de Playwright, pas de proxy, pas de contournement anti-bot.

## Cache HTML local

Le HTML recupere est enregistre dans:

- `data/cache/html/`

Ensuite le parser travaille sur le fichier local en mode offline.

## Filtrage applique

- Qualification transaction: `sale`, `rent`, `unknown`.
- Filtre de collecte pour ce flux: `sale`.
- Filtre geographique pour ce flux: canton `NE`.

## Limites actuelles

- L'adresse complete est souvent absente sur la page liste.
- Regle SITN: pas de lancement SITN si adresse incomplete.
- Certaines valeurs surface/pieces/prix peuvent etre suspectes sur une page liste.
- Avant exploitation metier, verifier `data/exports/quality_report.csv`.
