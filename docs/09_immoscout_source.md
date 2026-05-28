# Source ImmoScout (MVP prudent)

## Statut actuel

- ImmoScout est intégré comme source configurable.
- Les cantons romands configurés sont: GE, VD, NE, JU, FR, VS.
- Chaque canton a deux URLs:
  - `url_kind=residential`
  - `url_kind=land`
- La source reste `enabled=false` par défaut.

## URLs configurées (manuelles validées)

- GE:
  - `https://www.immoscout24.ch/fr/immobilier/acheter/canton-geneve`
  - `https://www.immoscout24.ch/fr/terrain/acheter/canton-geneve`
- VD:
  - `https://www.immoscout24.ch/fr/immobilier/acheter/canton-vaud`
  - `https://www.immoscout24.ch/fr/terrain/acheter/canton-vaud`
- NE:
  - `https://www.immoscout24.ch/fr/immobilier/acheter/canton-neuchatel`
  - `https://www.immoscout24.ch/fr/terrain/acheter/canton-neuchatel`
- JU:
  - `https://www.immoscout24.ch/fr/immobilier/acheter/canton-jura`
  - `https://www.immoscout24.ch/fr/terrain/acheter/canton-jura`
- FR:
  - `https://www.immoscout24.ch/fr/immobilier/acheter/canton-fribourg`
  - `https://www.immoscout24.ch/fr/terrain/acheter/canton-fribourg`
- VS:
  - `https://www.immoscout24.ch/fr/immobilier/acheter/canton-valais`
  - `https://www.immoscout24.ch/fr/terrain/acheter/canton-valais`

## Parser

- Parser local-only: `src/immo_ne_collector/scrapers/immoscout.py`.
- Utilisable sur cache HTML/fixtures via:
  - `scripts/inspect_immoscout_cached_html.py`
  - `scripts/parse_cached_immoscout_to_db.py`

## Anti-bot et prudence

- Aucun contournement anti-bot n'est implémenté.
- Aucun Playwright, proxy, navigateur headless, SDK de bypass ou résolution CAPTCHA.
- Activation future seulement après validation réseau prudente.
