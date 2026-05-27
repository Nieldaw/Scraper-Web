import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from immo_ne_collector.scrapers.base import RawListing


def normalize_price_chf(value: str | int | float | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return Decimal(str(value))
    cleaned = value.replace("CHF", "").replace("chf", "")
    cleaned = cleaned.replace("'", "").replace(" ", "").replace(".-", "")
    cleaned = cleaned.replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def normalize_area_m2(value: str | int | float | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return Decimal(str(value))
    cleaned = value.lower().replace("m2", "").replace("m²", "").strip().replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    return Decimal(match.group(0))


def normalize_rooms(value: str | int | float | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return Decimal(str(value))
    cleaned = value.lower().replace("pieces", "").replace("piece", "")
    cleaned = cleaned.replace("pièces", "").replace("pièce", "")
    cleaned = cleaned.replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    return Decimal(match.group(0))


def normalize_city(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def normalize_postal_code(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    match = re.search(r"\b(\d{4})\b", cleaned)
    return match.group(1) if match else None


def normalize_address_full(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split()).strip(",.;")
    return cleaned or None


def normalize_title(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def normalize_property_type(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split()).lower()
    if not cleaned:
        return None

    aliases = {
        "appartement": {"appartement", "appart", "apartment", "flat"},
        "maison": {"maison", "house", "villa"},
        "immeuble": {"immeuble", "building"},
        "terrain": {"terrain", "parcelle", "land"},
    }
    for normalized, variants in aliases.items():
        if cleaned in variants:
            return normalized
    return cleaned


def normalize_description(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


class NormalizedListing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    source_listing_id: str | None
    url: str
    title: str | None
    property_type: str | None
    price_chf: Decimal | None
    rooms: Decimal | None
    living_area_m2: Decimal | None
    address_full: str | None
    city: str | None
    postal_code: str | None
    description: str | None
    raw_data: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime
    missing_fields: list[str] = Field(default_factory=list)


IMPORTANT_FIELDS = (
    "title",
    "property_type",
    "price_chf",
    "city",
    "address_full",
)


def normalize_raw_listing(listing: RawListing) -> NormalizedListing:
    normalized = NormalizedListing(
        source=listing.source,
        source_listing_id=listing.source_listing_id,
        url=listing.url,
        title=normalize_title(listing.title),
        property_type=normalize_property_type(listing.property_type),
        price_chf=normalize_price_chf(listing.price_raw),
        rooms=normalize_rooms(listing.rooms_raw),
        living_area_m2=normalize_area_m2(listing.living_area_raw),
        address_full=normalize_address_full(listing.address_raw),
        city=normalize_city(listing.city_raw),
        postal_code=normalize_postal_code(listing.postal_code_raw),
        description=normalize_description(listing.description_raw),
        raw_data=dict(listing.raw_data),
        fetched_at=listing.fetched_at,
    )
    missing_fields = [field for field in IMPORTANT_FIELDS if getattr(normalized, field) is None]
    return normalized.model_copy(update={"missing_fields": missing_fields})
