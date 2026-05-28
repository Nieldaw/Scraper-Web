# Source Homegate (mode prudent MVP)

## Statut

- Homegate est integre techniquement comme 3e source.
- Configuration multi-URLs par canton:
  - `residential`
  - `land`
- Cantons configures: `GE`, `VD`, `NE`, `JU`, `FR`, `VS`.
- Homegate reste **desactive par defaut** (`enabled=false`).

## Pourquoi desactive par defaut

En fetch HTTP simple, Homegate peut renvoyer des pages anti-bot (Cloudflare/challenge) ou des `HTTP 403/429`.
Le projet conserve une approche strictement prudente:

- pas de Playwright
- pas de proxy
- pas de navigateur headless anti-bot
- pas de contournement Cloudflare
- pas de resolution CAPTCHA

## Parser local-only

Le parser Homegate fonctionne uniquement sur du HTML local (cache/fixture), sans appel reseau:

1. Detection explicite des pages challenge (`Just a moment`, `Cloudflare`, etc.).
2. Extraction prioritaire depuis `window.__INITIAL_STATE__` si present (`parser_strategy=initial_state_json`).
3. Fallback vers JSON-LD si disponible.
4. Fallback HTML selecteurs fixture (`parser_strategy=html_fixture_fallback`).

## Donnees extraites (si presentes)

- `source_listing_id`
- `url`
- `title`
- `price_raw`
- `rooms_raw`
- `living_area_raw`
- `property_type`
- `city_raw`
- `postal_code_raw`
- `address_raw`
- `transaction_type=sale`
- `detected_canton`
- `raw_data.url_kind`
- `raw_data.source_category`
- `raw_data.parser_strategy`

## Regles `url_kind`

- `url_kind=land` => `property_type=terrain`.
- `url_kind=residential` => detection appartement/maison si possible, sinon `None`.
- Aucune fusion inter-canton n'est autorisee.

## Audit

- Source Homegate desactivee => `WARNING` avec raison explicite:
  - `HOMEGATE_DISABLED_ANTI_BOT_RISK`
- Challenge detecte dans le HTML => `WARNING` explicite:
  - `HOMEGATE_CHALLENGE_DETECTED`
- HTTP 403 => `WARNING` explicite:
  - `HOMEGATE_HTTP_403`
- HTTP 429 => `WARNING` explicite:
  - `HOMEGATE_HTTP_429`
- Timeout reseau => `WARNING` explicite:
  - `HOMEGATE_TIMEOUT`
- HTML sans annonces exploitables => `WARNING` explicite:
  - `HOMEGATE_NO_LISTINGS_FOUND` ou `HOMEGATE_INITIAL_STATE_MISSING`
- Hors-canton reel dans exports by_canton => `FAIL` (regle globale du projet).

L'objectif est d'eviter tout faux positif \"0 annonces\" silencieux quand la cause est un challenge anti-bot.

## Activation future

Toute activation Homegate doit rester conforme au perimetre MVP prudent:

- validation par canton
- pagination limitee (max 10)
- pas de scan massif
- pas de contournement anti-bot
