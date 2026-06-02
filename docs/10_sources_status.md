# Sources status (MVP)

Ce document centralise le statut operationnel des sources du projet en mode MVP prudent.

## Regles globales

- Pas de scraping massif.
- Pagination controlee (`max-pages <= 10`).
- Filtrage canton strict.
- En cas de doute de deduplication: ne pas fusionner.
- Pas de contournement anti-bot (pas de Playwright, proxy, headless furtif, CAPTCHA, SDK bypass).

## Statut par source

| Source | Cantons configures | Types couverts | Statut | Raison / notes |
|---|---|---|---|---|
| Anibis | GE, VD, NE, JU, FR, VS | appartements, maisons, terrains | **ACTIF** | URLs de recherche filtrees vente, collecte prudente, audit Romandie attendu PASS. |
| Lookmove | GE, VD, NE, JU, FR, VS | appartements, maisons (vente), terrains selon donnees source | **ACTIF** | Collecte prudente, pagination detectee si disponible, arret propre en cas de blocage HTTP. |
| Homegate | GE, VD, NE, JU, FR, VS (`residential` + `land`) | residential + terrains | **DISABLED** | Risque anti-bot/Cloudflare en fetch HTTP simple. Parser local-only pret sur cache HTML. |
| ImmoScout | GE, VD, NE, JU, FR, VS (`residential` + `land`) | residential + terrains | **DISABLED** | URLs manuelles configurees; activation reportee tant que validation reseau prudente anti-bot non terminee. |

## Comportement audit attendu

- `anibis,lookmove`: **PASS** attendu sur collecte/caches valides.
- `homegate,immoscout` (disabled): **WARNING** attendu, pas FAIL.
- FAIL reserve aux erreurs critiques (ex: hors-canton dans exports by_canton, erreurs hard non recuperables).

## Commandes de verification rapides

```bash
python3 scripts/collect_sale_by_canton.py --list-config --sources anibis,lookmove,homegate,immoscout
python3 scripts/audit_sale_collection.py --all-romandie --sources anibis,lookmove --max-pages 3 --use-cache
python3 scripts/audit_sale_collection.py --all-romandie --sources homegate,immoscout --max-pages 1
python3 scripts/export_csv.py
pytest -q
```
