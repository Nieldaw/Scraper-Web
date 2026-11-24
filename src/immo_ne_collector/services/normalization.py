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


# Bornes de plausibilité pour une VENTE en Suisse (CHF). Hors bornes -> prix écarté + signalé.
MIN_PLAUSIBLE_SALE_PRICE_CHF = Decimal("20000")
MAX_PLAUSIBLE_SALE_PRICE_CHF = Decimal("50000000")
# Prix au m² suspect (signalé, mais conservé).
MIN_PLAUSIBLE_PRICE_PER_M2 = Decimal("500")
MAX_PLAUSIBLE_PRICE_PER_M2 = Decimal("40000")

_NPA_CITY_RE = re.compile(r"\b([1-9]\d{3})\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’ .\-/]*)")


def validate_sale_price(
    price: Decimal | None, area_m2: Decimal | None
) -> tuple[Decimal | None, str | None]:
    """Retourne (prix retenu, anomalie). Un prix hors bornes est écarté (None)."""
    if price is None:
        return None, None
    if price < MIN_PLAUSIBLE_SALE_PRICE_CHF:
        return None, "price_too_low"
    if price > MAX_PLAUSIBLE_SALE_PRICE_CHF:
        return None, "price_too_high"
    if area_m2 and area_m2 > 0:
        per_m2 = price / area_m2
        if per_m2 < MIN_PLAUSIBLE_PRICE_PER_M2:
            return price, "price_per_m2_low"
        if per_m2 > MAX_PLAUSIBLE_PRICE_PER_M2:
            return price, "price_per_m2_high"
    return price, None


def split_postal_and_city(*texts: str | None) -> tuple[str | None, str | None]:
    """Extrait (NPA, ville) du premier texte contenant « 2000 Neuchâtel » (ou « 2000 Neuchâtel, rue… »)."""
    for text in texts:
        if not text:
            continue
        for chunk in re.split(r"[,;|\n]", text):
            match = _NPA_CITY_RE.search(chunk)
            if match:
                city = " ".join(match.group(2).split()).strip(" -/.")
                if city:
                    return match.group(1), city
    return None, None


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
    area = normalize_area_m2(listing.living_area_raw)
    price, price_anomaly = validate_sale_price(normalize_price_chf(listing.price_raw), area)
    city = normalize_city(listing.city_raw)
    postal_code = normalize_postal_code(listing.postal_code_raw)
    raw_data = dict(listing.raw_data)
    if price_anomaly:
        raw_data["price_anomaly"] = price_anomaly
        raw_data["price_raw_original"] = listing.price_raw
    # Ville/NPA : « 2000 Neuchâtel » dans la ville ou l'adresse sert à compléter ou nettoyer.
    npa, npa_city = split_postal_and_city(listing.city_raw, listing.address_raw)
    if postal_code is None and npa:
        postal_code = npa
    if npa_city and (city is None or (npa and npa in (listing.city_raw or ""))):
        city = npa_city
    normalized = NormalizedListing(
        source=listing.source,
        source_listing_id=listing.source_listing_id,
        url=listing.url,
        title=normalize_title(listing.title),
        property_type=normalize_property_type(listing.property_type),
        price_chf=price,
        rooms=normalize_rooms(listing.rooms_raw),
        living_area_m2=area,
        address_full=normalize_address_full(listing.address_raw),
        city=city,
        postal_code=postal_code,
        description=normalize_description(listing.description_raw),
        raw_data=raw_data,
        fetched_at=listing.fetched_at,
    )
    missing_fields = [field for field in IMPORTANT_FIELDS if getattr(normalized, field) is None]
    return normalized.model_copy(update={"missing_fields": missing_fields})
