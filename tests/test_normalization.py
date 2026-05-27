from decimal import Decimal

from immo_ne_collector.scrapers.base import RawListing
from immo_ne_collector.services.normalization import (
    normalize_area_m2,
    normalize_price_chf,
    normalize_raw_listing,
    normalize_rooms,
)


def test_normalize_price_chf_values() -> None:
    assert normalize_price_chf("CHF 850'000") == Decimal("850000")
    assert normalize_price_chf("1 150 000.-") == Decimal("1150000")
    assert normalize_price_chf(None) is None


def test_normalize_area_m2_values() -> None:
    assert normalize_area_m2("110 m2") == Decimal("110")
    assert normalize_area_m2("165,5 m²") == Decimal("165.5")
    assert normalize_area_m2(None) is None


def test_normalize_rooms_values() -> None:
    assert normalize_rooms("4.5 pieces") == Decimal("4.5")
    assert normalize_rooms("6 pièces") == Decimal("6")
    assert normalize_rooms(None) is None


def test_normalize_raw_listing_marks_important_missing_fields() -> None:
    raw = RawListing(
        source="mock",
        source_listing_id="missing-1",
        url="https://mock.local/listings/missing-1",
        title=" ",
        property_type=None,
        price_raw=None,
        city_raw=" ",
        address_raw=None,
    )

    normalized = normalize_raw_listing(raw)

    assert normalized.price_chf is None
    assert normalized.city is None
    assert normalized.title is None
    assert normalized.missing_fields == [
        "title",
        "property_type",
        "price_chf",
        "city",
        "address_full",
    ]
