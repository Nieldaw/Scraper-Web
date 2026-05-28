# Source Anibis (MVP)

## Perimetre

Source cible MVP: Anibis, annonces de vente immobilieres sur cantons romands configures.

Cantons Anibis valides actuellement:
- GE
- VD
- NE
- JU
- VS

Cantons Anibis encore en attente:
- FR (URL candidate testee mais non fiable, reste disabled)

Validation/collecte pilotee via:

```bash
python3 scripts/collect_sale_by_canton.py --canton NE --sources anibis --max-pages 1
```

## Fonctionnement prudent

- Une URL de recherche controlee a la fois.
- Pagination controlee uniquement.
- Maximum `--max-pages 10`.
- Pas de scraping massif.
- Pas de Playwright, pas de proxy, pas de contournement anti-bot.

## Methode de validation prudente

Pour chaque nouveau canton:
- Ajouter l'URL en config avec `enabled=false`.
- Tester en audit avec `--max-pages 1`.
- Verifier:
  - HTTP 200
  - annonces detectees
  - transaction majoritairement `sale`
  - filtrage canton strict correct
  - aucun hors-canton dans `data/exports/by_canton/<CANTON>/ventes.csv`
  - audit sans FAIL
- Passer `enabled=true` seulement apres validation.

## Cache HTML local

Le HTML recupere est enregistre dans:

- `data/cache/html/`

Ensuite le parser travaille sur le fichier local en mode offline.

## Filtrage applique

- Qualification transaction: `sale`, `rent`, `unknown`.
- Filtre de collecte pour ce flux: `sale`.
- Filtre geographique strict: canton cible.

## Limites actuelles

- L'adresse complete est souvent absente sur la page liste.
- Regle SITN: pas de lancement SITN si adresse incomplete.
- Certaines valeurs surface/pieces/prix peuvent etre suspectes sur une page liste.
- Avant exploitation metier, verifier `data/exports/quality_report.csv`.
