from __future__ import annotations

from collections.abc import Callable

from immo_ne_collector.models import Property
from immo_ne_collector.scrapers.anibis_utils import is_canton_ne_listing

DEFAULT_ANIBIS_NE_SALE_URL = (
    "https://www.anibis.ch/fr/q/immobilier-neuchatel-appartements-maisons-acheter/"
    "Ak8CqcmVhbEVzdGF0ZZSSkqtsaXN0aW5nVHlwZZKpYXBhcnRtZW50pWhvdXNlkqlwcmljZVR5cGWjQlVZwMCRk6hsb2NhdGlv"
    "brRnZW8tY2FudG9uLW5ldWNoYXRlbMA?sorting=newest&page=1"
)
DEFAULT_LOOKMOVE_NE_SALE_URL = (
    "https://www.lookmove.ch/fr/immobilier/acheter/"
    "appartements-maisons%2C3/neuchatel-ne%2C100013"
)

SALE_SOURCE_CANTON_URLS: dict[str, dict[str, str]] = {
    "anibis": {
        "NE": DEFAULT_ANIBIS_NE_SALE_URL,
        # "VD": "TODO",
    },
    "lookmove": {
        "NE": DEFAULT_LOOKMOVE_NE_SALE_URL,
        # "VD": "TODO",
    },
}

SUPPORTED_SOURCES: tuple[str, ...] = tuple(SALE_SOURCE_CANTON_URLS.keys())

CANTON_MATCHERS: dict[str, Callable[[str, str | None, str | None], bool]] = {
    "NE": is_canton_ne_listing,
}


def normalize_source(value: str) -> str:
    return value.strip().lower()


def normalize_canton(value: str) -> str:
    return value.strip().upper()


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


def get_sale_search_url(*, source: str, canton: str) -> str:
    normalized_source = normalize_source(source)
    normalized_canton = normalize_canton(canton)

    if normalized_source not in SALE_SOURCE_CANTON_URLS:
        raise ValueError(
            f"Source '{source}' is not supported. Supported: {', '.join(SUPPORTED_SOURCES)}"
        )

    source_map = SALE_SOURCE_CANTON_URLS[normalized_source]
    if normalized_canton not in source_map:
        configured = ", ".join(sorted(source_map.keys())) or "(none)"
        raise ValueError(
            f"No configured sale URL for source='{normalized_source}' canton='{normalized_canton}'. "
            f"Configured cantons for this source: {configured}."
        )
    return source_map[normalized_canton]


def build_canton_property_filter(canton: str) -> Callable[[Property], bool]:
    normalized_canton = normalize_canton(canton)
    if normalized_canton not in CANTON_MATCHERS:
        raise ValueError(f"Canton '{normalized_canton}' is not configured for filtering.")

    matcher = CANTON_MATCHERS[normalized_canton]

    def is_in_canton(property_row: Property) -> bool:
        for listing in property_row.listings:
            if matcher(listing.url, listing.city, listing.postal_code):
                return True
        for url in property_row.source_urls:
            if matcher(url, property_row.city, property_row.postal_code):
                return True
        return matcher("", property_row.city, property_row.postal_code)

    return is_in_canton

