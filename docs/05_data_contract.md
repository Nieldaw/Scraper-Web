# Data contract MVP

## MASTER properties

| Champ | Type | Description |
|---|---|---|
| property_id | UUID | ID interne stable du bien fusionne |
| title | text | Titre normalise si disponible |
| property_type | text | appartement, maison, immeuble, terrain, etc. |
| price_chf | numeric | Prix en CHF |
| rooms | numeric | Nombre de pieces |
| living_area_m2 | numeric | Surface habitable |
| address_full | text | Adresse complete si disponible |
| city | text | Commune |
| postal_code | text | NPA |
| sources | jsonb | Liste des sources |
| source_urls | jsonb | Liste des URLs sources |
| first_seen_at | timestamptz | Premiere collecte |
| last_seen_at | timestamptz | Derniere collecte |
| last_changed_at | timestamptz | Dernier changement detecte |
| status | text | NEW, ACTIVE, UPDATED, INACTIVE, REMOVED |
| needs_completion | boolean | TRUE si donnees cles manquantes |
| completion_reason | text | 'Adresse manquante' si applicable |
| sitn_eligible | boolean | TRUE seulement si adresse complete |
| sitn_status | text | OK, AMBIGUOUS, NOT_FOUND, NOT_ELIGIBLE_MISSING_ADDRESS, NOT_RUN |
| sitn_bien_fonds | text | Numero bien-fonds si trouve |
| sitn_owner_name | text | Nom proprietaire si public et trouve |
| sitn_url | text | URL SITN de reference |

## SourceListing

Une annonce source est conservee meme si elle est fusionnee dans un bien.

| Champ | Type | Description |
|---|---|---|
| listing_id | UUID | ID interne annonce |
| source | text | Nom source |
| source_listing_id | text | ID externe si disponible |
| url | text | URL source |
| collected_at | timestamptz | Date collecte |
| raw_data | jsonb | Donnees brutes utiles |
| property_id | UUID | Bien fusionne associe |

## SearchMandate

| Champ | Type | Description |
|---|---|---|
| mandate_id | UUID | ID mandat |
| name | text | Nom du mandat |
| cities | jsonb | Communes ciblees |
| property_types | jsonb | Types acceptes |
| min_price_chf | numeric | Prix min |
| max_price_chf | numeric | Prix max |
| min_rooms | numeric | Pieces min |
| min_living_area_m2 | numeric | Surface min |
| is_active | boolean | Mandat actif |
