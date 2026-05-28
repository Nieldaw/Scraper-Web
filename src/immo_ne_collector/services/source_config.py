from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
import unicodedata

from immo_ne_collector.models import Property

def normalize_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


ROMANDY_CANTONS: tuple[str, ...] = ("GE", "VD", "NE", "JU", "FR", "VS")
DetectedCanton = Literal["GE", "VD", "NE", "JU", "FR", "VS", "unknown"]

DEFAULT_ANIBIS_NE_SALE_URL = (
    "https://www.anibis.ch/fr/q/immobilier-neuchatel-appartements-maisons-terrains-acheter/"
    "Ak8CqcmVhbEVzdGF0ZZSSkqtsaXN0aW5nVHlwZZOpYXBhcnRtZW50pWhvdXNlrmJ1aWxkaW5nR3JvdW5kkqlwcmljZVR5cGWj"
    "QlVZwMCRk6hsb2NhdGlvbrRnZW8tY2FudG9uLW5ldWNoYXRlbMA?sorting=newest&page=1"
)
DEFAULT_ANIBIS_GE_SALE_URL = (
    "https://www.anibis.ch/fr/q/immobilier-geneve-appartements-maisons-terrains-acheter/"
    "Ak8CqcmVhbEVzdGF0ZZSSkqtsaXN0aW5nVHlwZZOpYXBhcnRtZW50pWhvdXNlrmJ1aWxkaW5nR3JvdW5kkqlwcmljZVR5cGWj"
    "QlVZwMCRk6hsb2NhdGlvbrFnZW8tY2FudG9uLWdlbmV2ZcA?sorting=newest&page=1"
)
DEFAULT_ANIBIS_VD_SALE_URL = (
    "https://www.anibis.ch/fr/q/immobilier-vaud-appartements-maisons-terrains-acheter/"
    "Ak8CqcmVhbEVzdGF0ZZSSkqtsaXN0aW5nVHlwZZOpYXBhcnRtZW50pWhvdXNlrmJ1aWxkaW5nR3JvdW5kkqlwcmljZVR5cGWj"
    "QlVZwMCRk6hsb2NhdGlvbq9nZW8tY2FudG9uLXZhdWTA?sorting=newest&page=1"
)
DEFAULT_ANIBIS_JU_SALE_URL = (
    "https://www.anibis.ch/fr/q/immobilier-jura-appartements-maisons-terrains-acheter/"
    "Ak8CqcmVhbEVzdGF0ZZSSkqtsaXN0aW5nVHlwZZOpYXBhcnRtZW50pWhvdXNlrmJ1aWxkaW5nR3JvdW5kkqlwcmljZVR5cGWj"
    "QlVZwMCRk6hsb2NhdGlvbq9nZW8tY2FudG9uLWp1cmHA?sorting=newest&page=1"
)
DEFAULT_ANIBIS_VS_SALE_URL = (
    "https://www.anibis.ch/fr/q/immobilier-valais-appartements-maisons-terrains-acheter/"
    "Ak8CqcmVhbEVzdGF0ZZSSkqtsaXN0aW5nVHlwZZOpYXBhcnRtZW50pWhvdXNlrmJ1aWxkaW5nR3JvdW5kkqlwcmljZVR5cGWj"
    "QlVZwMCRk6hsb2NhdGlvbrFnZW8tY2FudG9uLXZhbGFpc8A?sorting=newest&page=1"
)
DEFAULT_ANIBIS_FR_SALE_URL_CANDIDATE = (
    "https://www.anibis.ch/fr/q/immobilier-fribourg-appartements-maisons-terrains-acheter/"
    "Ak8CqcmVhbEVzdGF0ZZSSkqtsaXN0aW5nVHlwZZOpYXBhcnRtZW50pWhvdXNlrmJ1aWxkaW5nR3JvdW5kkqlwcmljZVR5cGWj"
    "QlVZwMCRk6hsb2NhdGlvbrNnZW8tY2FudG9uLWZyaWJvdXJnwA?sorting=newest&page=1"
)
DEFAULT_ANIBIS_BE_SALE_URL_FUTURE = (
    "https://www.anibis.ch/fr/q/immobilier-berne-appartements-maisons-terrains-acheter/"
    "Ak8CqcmVhbEVzdGF0ZZSSkqtsaXN0aW5nVHlwZZOpYXBhcnRtZW50pWhvdXNlrmJ1aWxkaW5nR3JvdW5kkqlwcmljZVR5cGWj"
    "QlVZwMCRk6hsb2NhdGlvbq9nZW8tY2FudG9uLWJlcm7A?sorting=newest&page=1"
)

DEFAULT_LOOKMOVE_GE_SALE_URL = (
    "https://www.lookmove.ch/fr/immobilier/acheter/"
    "appartements-maisons%2C3/geneve-ge%2C100008"
)
DEFAULT_LOOKMOVE_VD_SALE_URL = (
    "https://www.lookmove.ch/fr/immobilier/acheter/"
    "appartements-maisons%2C3/vaud-vd%2C100023"
)
DEFAULT_LOOKMOVE_NE_SALE_URL = (
    "https://www.lookmove.ch/fr/immobilier/acheter/"
    "appartements-maisons%2C3/neuchatel-ne%2C100013"
)
DEFAULT_LOOKMOVE_JU_SALE_URL = (
    "https://www.lookmove.ch/fr/immobilier/acheter/"
    "appartements-maisons%2C3/jura-ju%2C100011"
)
DEFAULT_LOOKMOVE_FR_SALE_URL = (
    "https://www.lookmove.ch/fr/immobilier/acheter/"
    "appartements-maisons%2C3/fribourg-fr%2C100007"
)
DEFAULT_LOOKMOVE_VS_SALE_URL = (
    "https://www.lookmove.ch/fr/immobilier/acheter/"
    "appartements-maisons%2C3/valais-vs%2C100024"
)

DEFAULT_HOMEGATE_GE_SALE_RESIDENTIAL_URL = (
    "https://www.homegate.ch/acheter/biens-immobiliers/canton-geneve/liste-annonces"
)
DEFAULT_HOMEGATE_GE_SALE_LAND_URL = (
    "https://www.homegate.ch/acheter/terrain/canton-geneve/liste-annonces"
)
DEFAULT_HOMEGATE_VD_SALE_RESIDENTIAL_URL = (
    "https://www.homegate.ch/acheter/biens-immobiliers/canton-vaud/liste-annonces"
)
DEFAULT_HOMEGATE_VD_SALE_LAND_URL = (
    "https://www.homegate.ch/acheter/terrain/canton-vaud/liste-annonces"
)
DEFAULT_HOMEGATE_NE_SALE_RESIDENTIAL_URL = (
    "https://www.homegate.ch/acheter/biens-immobiliers/canton-neuchatel/liste-annonces"
)
DEFAULT_HOMEGATE_NE_SALE_LAND_URL = (
    "https://www.homegate.ch/acheter/terrain/canton-neuchatel/liste-annonces"
)
DEFAULT_HOMEGATE_JU_SALE_RESIDENTIAL_URL = (
    "https://www.homegate.ch/acheter/biens-immobiliers/canton-jura/liste-annonces"
)
DEFAULT_HOMEGATE_JU_SALE_LAND_URL = (
    "https://www.homegate.ch/acheter/terrain/canton-jura/liste-annonces"
)
DEFAULT_HOMEGATE_FR_SALE_RESIDENTIAL_URL = (
    "https://www.homegate.ch/acheter/biens-immobiliers/canton-fribourg/liste-annonces"
)
DEFAULT_HOMEGATE_FR_SALE_LAND_URL = (
    "https://www.homegate.ch/acheter/terrain/canton-fribourg/liste-annonces"
)
DEFAULT_HOMEGATE_VS_SALE_RESIDENTIAL_URL = (
    "https://www.homegate.ch/acheter/biens-immobiliers/canton-valais/liste-annonces"
)
DEFAULT_HOMEGATE_VS_SALE_LAND_URL = (
    "https://www.homegate.ch/acheter/terrain/canton-valais/liste-annonces"
)


@dataclass(frozen=True)
class SourceUrlConfig:
    url: str
    url_kind: str = "default"
    note: str | None = None


@dataclass(frozen=True)
class SourceCantonConfig:
    source: str
    canton: str
    url: str | None
    enabled: bool
    urls: tuple[SourceUrlConfig, ...] = ()
    note: str | None = None


# Anibis: URLs validées en mode prudent pour GE, VD, NE, JU, FR, VS.
SALE_SOURCE_CANTON_CONFIGS: dict[str, dict[str, SourceCantonConfig]] = {
    "anibis": {
        "GE": SourceCantonConfig(
            source="anibis",
            canton="GE",
            url=DEFAULT_ANIBIS_GE_SALE_URL,
            enabled=True,
            note="URL vente GE validée en mode prudent (1 page, filtre strict).",
        ),
        "VD": SourceCantonConfig(
            source="anibis",
            canton="VD",
            url=DEFAULT_ANIBIS_VD_SALE_URL,
            enabled=True,
            note="URL vente VD validée en mode prudent (1 page, filtre strict).",
        ),
        "NE": SourceCantonConfig(
            source="anibis",
            canton="NE",
            url=DEFAULT_ANIBIS_NE_SALE_URL,
            enabled=True,
            note="URL validée sur pipeline MVP.",
        ),
        "JU": SourceCantonConfig(
            source="anibis",
            canton="JU",
            url=DEFAULT_ANIBIS_JU_SALE_URL,
            enabled=True,
            note="URL vente JU validée en mode prudent (1 page, filtre strict).",
        ),
        "FR": SourceCantonConfig(
            source="anibis",
            canton="FR",
            url=DEFAULT_ANIBIS_FR_SALE_URL_CANDIDATE,
            enabled=True,
            note="URL vente FR validée en mode prudent (appartements/maisons/terrains, filtre strict).",
        ),
        "VS": SourceCantonConfig(
            source="anibis",
            canton="VS",
            url=DEFAULT_ANIBIS_VS_SALE_URL,
            enabled=True,
            note="URL vente VS validée en mode prudent (1 page, filtre strict).",
        ),
    },
    "lookmove": {
        "GE": SourceCantonConfig(
            source="lookmove",
            canton="GE",
            url=DEFAULT_LOOKMOVE_GE_SALE_URL,
            enabled=True,
            note="URL publique canton Genève.",
        ),
        "VD": SourceCantonConfig(
            source="lookmove",
            canton="VD",
            url=DEFAULT_LOOKMOVE_VD_SALE_URL,
            enabled=True,
            note="URL publique canton Vaud.",
        ),
        "NE": SourceCantonConfig(
            source="lookmove",
            canton="NE",
            url=DEFAULT_LOOKMOVE_NE_SALE_URL,
            enabled=True,
            note="URL validée sur pipeline MVP.",
        ),
        "JU": SourceCantonConfig(
            source="lookmove",
            canton="JU",
            url=DEFAULT_LOOKMOVE_JU_SALE_URL,
            enabled=True,
            note="URL publique canton Jura.",
        ),
        "FR": SourceCantonConfig(
            source="lookmove",
            canton="FR",
            url=DEFAULT_LOOKMOVE_FR_SALE_URL,
            enabled=True,
            note="URL publique canton Fribourg.",
        ),
        "VS": SourceCantonConfig(
            source="lookmove",
            canton="VS",
            url=DEFAULT_LOOKMOVE_VS_SALE_URL,
            enabled=True,
            note="URL publique canton Valais.",
        ),
    },
    "homegate": {
        "GE": SourceCantonConfig(
            source="homegate",
            canton="GE",
            url=DEFAULT_HOMEGATE_GE_SALE_RESIDENTIAL_URL,
            enabled=False,
            urls=(
                SourceUrlConfig(
                    url=DEFAULT_HOMEGATE_GE_SALE_RESIDENTIAL_URL,
                    url_kind="residential",
                ),
                SourceUrlConfig(
                    url=DEFAULT_HOMEGATE_GE_SALE_LAND_URL,
                    url_kind="land",
                ),
            ),
            note=(
                "URLs candidates Homegate vente GE (residential + land). Désactivée par défaut: validation prudente requise "
                "(anti-bot/Cloudflare fréquent en fetch HTTP simple)."
            ),
        ),
        "VD": SourceCantonConfig(
            source="homegate",
            canton="VD",
            url=DEFAULT_HOMEGATE_VD_SALE_RESIDENTIAL_URL,
            enabled=False,
            urls=(
                SourceUrlConfig(
                    url=DEFAULT_HOMEGATE_VD_SALE_RESIDENTIAL_URL,
                    url_kind="residential",
                ),
                SourceUrlConfig(
                    url=DEFAULT_HOMEGATE_VD_SALE_LAND_URL,
                    url_kind="land",
                ),
            ),
            note=(
                "URLs candidates Homegate vente VD (residential + land). Désactivée par défaut: validation prudente requise "
                "(anti-bot/Cloudflare fréquent en fetch HTTP simple)."
            ),
        ),
        "NE": SourceCantonConfig(
            source="homegate",
            canton="NE",
            url=DEFAULT_HOMEGATE_NE_SALE_RESIDENTIAL_URL,
            enabled=False,
            urls=(
                SourceUrlConfig(
                    url=DEFAULT_HOMEGATE_NE_SALE_RESIDENTIAL_URL,
                    url_kind="residential",
                ),
                SourceUrlConfig(
                    url=DEFAULT_HOMEGATE_NE_SALE_LAND_URL,
                    url_kind="land",
                ),
            ),
            note=(
                "URLs candidates Homegate vente NE (residential + land). Désactivée par défaut: validation prudente requise "
                "(anti-bot/Cloudflare fréquent en fetch HTTP simple)."
            ),
        ),
        "JU": SourceCantonConfig(
            source="homegate",
            canton="JU",
            url=DEFAULT_HOMEGATE_JU_SALE_RESIDENTIAL_URL,
            enabled=False,
            urls=(
                SourceUrlConfig(
                    url=DEFAULT_HOMEGATE_JU_SALE_RESIDENTIAL_URL,
                    url_kind="residential",
                ),
                SourceUrlConfig(
                    url=DEFAULT_HOMEGATE_JU_SALE_LAND_URL,
                    url_kind="land",
                ),
            ),
            note=(
                "URLs candidates Homegate vente JU (residential + land). Désactivée par défaut: validation prudente requise "
                "(anti-bot/Cloudflare fréquent en fetch HTTP simple)."
            ),
        ),
        "FR": SourceCantonConfig(
            source="homegate",
            canton="FR",
            url=DEFAULT_HOMEGATE_FR_SALE_RESIDENTIAL_URL,
            enabled=False,
            urls=(
                SourceUrlConfig(
                    url=DEFAULT_HOMEGATE_FR_SALE_RESIDENTIAL_URL,
                    url_kind="residential",
                ),
                SourceUrlConfig(
                    url=DEFAULT_HOMEGATE_FR_SALE_LAND_URL,
                    url_kind="land",
                ),
            ),
            note=(
                "URLs candidates Homegate vente FR (residential + land). Désactivée par défaut: validation prudente requise "
                "(anti-bot/Cloudflare fréquent en fetch HTTP simple)."
            ),
        ),
        "VS": SourceCantonConfig(
            source="homegate",
            canton="VS",
            url=DEFAULT_HOMEGATE_VS_SALE_RESIDENTIAL_URL,
            enabled=False,
            urls=(
                SourceUrlConfig(
                    url=DEFAULT_HOMEGATE_VS_SALE_RESIDENTIAL_URL,
                    url_kind="residential",
                ),
                SourceUrlConfig(
                    url=DEFAULT_HOMEGATE_VS_SALE_LAND_URL,
                    url_kind="land",
                ),
            ),
            note=(
                "URLs candidates Homegate vente VS (residential + land). Désactivée par défaut: validation prudente requise "
                "(anti-bot/Cloudflare fréquent en fetch HTTP simple)."
            ),
        ),
    },
}

SUPPORTED_SOURCES: tuple[str, ...] = tuple(SALE_SOURCE_CANTON_CONFIGS.keys())
SUPPORTED_CANTONS: tuple[str, ...] = ROMANDY_CANTONS

# Future source note:
# BE URL is known but intentionally excluded from SUPPORTED_CANTONS and --all-romandie.
# It needs a dedicated strategy for Bern/Jura bernois/Bienne before activation.


_CANTON_URL_TOKENS: dict[str, tuple[str, ...]] = {
    "GE": ("/geneve/", "geneve-ge", "geo-canton-geneve", "canton-geneve", "dans-geneve", "-geneve,"),
    "VD": ("/vaud/", "vaud-vd", "geo-canton-vaud", "canton-vaud", "dans-vaud", "-vaud,"),
    "NE": ("/neuchatel/", "neuchatel-ne", "geo-canton-neuchatel", "canton-neuchatel", "dans-neuchatel", "-neuchatel,"),
    "JU": ("/jura/", "jura-ju", "geo-canton-jura", "canton-jura", "dans-jura", "-jura,"),
    "FR": ("/fribourg/", "fribourg-fr", "geo-canton-fribourg", "canton-fribourg", "dans-fribourg", "-fribourg,"),
    "VS": ("/valais/", "valais-vs", "geo-canton-valais", "canton-valais", "dans-valais", "-valais,"),
}

_CANTON_CITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "GE": ("geneve", "carouge", "meyrin", "vernier", "onex", "lancy", "versoix"),
    "VD": ("lausanne", "nyon", "morges", "vevey", "yverdon", "renens", "pully", "montreux"),
    "NE": (
        "neuchatel",
        "la chaux-de-fonds",
        "chaux-de-fonds",
        "le locle",
        "val-de-travers",
        "couvet",
        "colombier",
        "cernier",
        "peseux",
        "st-blaise",
        "saint-blaise",
        "le landeron",
        "boudry",
        "cortaillod",
    ),
    "JU": ("delemont", "porrentruy", "saignelegier", "courgenay", "courrendlin", "bassecourt"),
    "FR": ("fribourg", "bulle", "romont", "murten", "morat", "villars-sur-glane", "estavayer"),
    "VS": ("sion", "sierre", "martigny", "monthey", "verbier", "crans-montana", "visp", "brig"),
}

# Table MVP volontairement non exhaustive, utilisée en fallback prudent.
_CANTON_POSTAL_PREFIXES: dict[str, tuple[str, ...]] = {
    "GE": ("12",),
    "VD": ("10", "11", "13", "14"),
    "NE": ("20", "21", "22", "23", "24"),
    "JU": ("27", "28", "29"),
    "FR": ("16", "17"),
    "VS": ("19", "39"),
}


def _build_canton_matcher(canton: str) -> Callable[[str, str | None, str | None], bool]:
    own_tokens = tuple(normalize_text(token) for token in _CANTON_URL_TOKENS[canton])
    own_keywords = tuple(normalize_text(keyword) for keyword in _CANTON_CITY_KEYWORDS[canton])
    own_postal_prefixes = _CANTON_POSTAL_PREFIXES[canton]

    other_tokens: list[str] = []
    for other_canton, tokens in _CANTON_URL_TOKENS.items():
        if other_canton == canton:
            continue
        other_tokens.extend(normalize_text(token) for token in tokens)

    canton_suffix = f" {canton.lower()}"

    def matcher(url: str, city: str | None, postal_code: str | None) -> bool:
        normalized_url = normalize_text(url)
        normalized_city = normalize_text(city)

        if any(token and token in normalized_url for token in own_tokens):
            return True

        if any(token and token in normalized_url for token in other_tokens):
            return False

        if normalized_url and any(keyword and keyword in normalized_url for keyword in own_keywords):
            return True

        if normalized_city.endswith(canton_suffix):
            return True

        if normalized_city and any(keyword in normalized_city for keyword in own_keywords):
            return True

        cleaned_postal = (postal_code or "").strip()
        if cleaned_postal.isdigit() and len(cleaned_postal) >= 2:
            if cleaned_postal.startswith(own_postal_prefixes):
                return True

        return False

    return matcher


CANTON_MATCHERS: dict[str, Callable[[str, str | None, str | None], bool]] = {
    canton: _build_canton_matcher(canton) for canton in ROMANDY_CANTONS
}


def normalize_source(value: str) -> str:
    return value.strip().lower()


def normalize_canton(value: str) -> str:
    return value.strip().upper()


def normalize_detected_canton(value: str | None) -> DetectedCanton:
    if value is None:
        return "unknown"
    normalized = normalize_canton(value)
    if normalized in ROMANDY_CANTONS:
        return normalized  # type: ignore[return-value]
    return "unknown"


def infer_detected_canton(
    *,
    url: str,
    city: str | None,
    postal_code: str | None,
    fallback_canton: str | None = None,
) -> tuple[DetectedCanton, str]:
    normalized_url = normalize_text(url)
    normalized_city = normalize_text(city)
    cleaned_postal = (postal_code or "").strip()

    url_matches: list[str] = []
    for canton, tokens in _CANTON_URL_TOKENS.items():
        normalized_tokens = tuple(normalize_text(token) for token in tokens)
        if any(token and token in normalized_url for token in normalized_tokens):
            url_matches.append(canton)
    if len(url_matches) == 1:
        return normalize_detected_canton(url_matches[0]), "url"

    # Fallback URL inference based on city keywords embedded in slugs.
    url_keyword_matches: list[str] = []
    for canton, keywords in _CANTON_CITY_KEYWORDS.items():
        normalized_keywords = tuple(normalize_text(keyword) for keyword in keywords)
        if any(
            keyword
            and (
                keyword in normalized_url
                or keyword.replace(" ", "-") in normalized_url
                or keyword.replace(" ", "") in normalized_url
            )
            for keyword in normalized_keywords
        ):
            url_keyword_matches.append(canton)
    if len(url_keyword_matches) == 1:
        return normalize_detected_canton(url_keyword_matches[0]), "url"

    city_matches: list[str] = []
    for canton, keywords in _CANTON_CITY_KEYWORDS.items():
        normalized_keywords = tuple(normalize_text(keyword) for keyword in keywords)
        if normalized_city and any(keyword and keyword in normalized_city for keyword in normalized_keywords):
            city_matches.append(canton)
    if len(city_matches) == 1:
        return normalize_detected_canton(city_matches[0]), "city"

    if cleaned_postal.isdigit():
        postal_matches = [
            canton
            for canton, prefixes in _CANTON_POSTAL_PREFIXES.items()
            if any(cleaned_postal.startswith(prefix) for prefix in prefixes)
        ]
        if len(postal_matches) == 1:
            return normalize_detected_canton(postal_matches[0]), "postal_code"

    fallback = normalize_detected_canton(fallback_canton)
    if fallback != "unknown":
        return fallback, "source_config"

    return "unknown", "unknown"


def parse_sources_csv(value: str) -> list[str]:
    items = [normalize_source(item) for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError("--sources must contain at least one source")
    unsupported = [item for item in items if item not in SUPPORTED_SOURCES]
    if unsupported:
        raise ValueError(
            f"Unsupported source(s): {', '.join(sorted(set(unsupported)))}. "
            f"Supported: {', '.join(SUPPORTED_SOURCES)}"
        )
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def list_sale_source_configs(*, cantons: list[str] | None = None, sources: list[str] | None = None) -> list[SourceCantonConfig]:
    selected_sources = sources or list(SUPPORTED_SOURCES)
    selected_cantons = [normalize_canton(canton) for canton in (cantons or list(ROMANDY_CANTONS))]
    rows: list[SourceCantonConfig] = []
    for source in selected_sources:
        normalized_source = normalize_source(source)
        if normalized_source not in SALE_SOURCE_CANTON_CONFIGS:
            continue
        for canton in selected_cantons:
            config = SALE_SOURCE_CANTON_CONFIGS[normalized_source].get(canton)
            if config is not None:
                rows.append(config)
    return rows


def get_sale_source_config(*, source: str, canton: str) -> SourceCantonConfig:
    normalized_source = normalize_source(source)
    normalized_canton = normalize_canton(canton)

    if normalized_source not in SALE_SOURCE_CANTON_CONFIGS:
        raise ValueError(
            f"Source '{source}' is not supported. Supported: {', '.join(SUPPORTED_SOURCES)}"
        )

    if normalized_canton not in SUPPORTED_CANTONS:
        raise ValueError(
            f"Canton '{normalized_canton}' is not supported in MVP. "
            f"Supported cantons: {', '.join(SUPPORTED_CANTONS)}"
        )

    source_map = SALE_SOURCE_CANTON_CONFIGS[normalized_source]
    config = source_map.get(normalized_canton)
    if config is None:
        configured = ", ".join(sorted(source_map.keys())) or "(none)"
        raise ValueError(
            f"No configured sale URL for source='{normalized_source}' canton='{normalized_canton}'. "
            f"Configured cantons for this source: {configured}."
        )
    return config


def get_sale_search_url(*, source: str, canton: str) -> str:
    config = get_sale_source_config(source=source, canton=canton)
    if not config.enabled:
        note = f" Note: {config.note}" if config.note else ""
        raise ValueError(
            f"Source '{config.source}' is configured but disabled for canton '{config.canton}'.{note}"
        )
    urls = get_sale_source_urls(source=source, canton=canton)
    if not urls:
        raise ValueError(
            f"Source '{config.source}' canton '{config.canton}' has no URL configured."
        )
    return urls[0].url


def get_sale_source_urls(*, source: str, canton: str) -> list[SourceUrlConfig]:
    config = get_sale_source_config(source=source, canton=canton)
    if config.urls:
        return list(config.urls)
    if config.url:
        return [SourceUrlConfig(url=config.url, url_kind="default")]
    return []


def build_canton_property_filter(canton: str) -> Callable[[Property], bool]:
    normalized_canton = normalize_canton(canton)
    if normalized_canton not in CANTON_MATCHERS:
        raise ValueError(f"Canton '{normalized_canton}' is not configured for filtering.")

    matcher = CANTON_MATCHERS[normalized_canton]

    def is_in_canton(property_row: Property) -> bool:
        has_unknown = False
        for listing in property_row.listings:
            detected_raw = "unknown"
            if isinstance(listing.raw_data, dict):
                detected_raw = normalize_detected_canton(listing.raw_data.get("detected_canton"))  # type: ignore[arg-type]
            inferred, _ = infer_detected_canton(
                url=listing.url,
                city=listing.city,
                postal_code=listing.postal_code,
            )
            if (
                detected_raw != "unknown"
                and inferred != "unknown"
                and detected_raw != inferred
            ):
                detected = inferred
            elif detected_raw != "unknown":
                detected = detected_raw
            else:
                detected = inferred
            if detected == normalized_canton:
                return True
            if detected == "unknown":
                has_unknown = True
                if matcher(listing.url, listing.city, listing.postal_code):
                    return True

        if has_unknown:
            for url in property_row.source_urls:
                if matcher(url, property_row.city, property_row.postal_code):
                    return True
            return matcher("", property_row.city, property_row.postal_code)
        return False

    return is_in_canton
