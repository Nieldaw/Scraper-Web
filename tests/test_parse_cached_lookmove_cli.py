from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from immo_ne_collector.services.collection import CollectionBatch
from immo_ne_collector.services.normalization import NormalizedListing


SCRIPT_PATH = Path("scripts/parse_cached_lookmove_to_db.py")
SPEC = importlib.util.spec_from_file_location("parse_cached_lookmove_to_db", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _listing_with_url(
    *,
    idx: int,
    url: str,
    city: str | None = None,
    postal_code: str | None = None,
    transaction_type: str = "sale",
) -> NormalizedListing:
    return NormalizedListing(
        source="lookmove_cached",
        source_listing_id=f"id-{idx}",
        url=url,
        title=f"Listing {idx}",
        property_type="appartement",
        price_chf=Decimal("1000000"),
        rooms=Decimal("4.5"),
        living_area_m2=Decimal("100"),
        address_full="Rue du Seyon 12",
        city=city,
        postal_code=postal_code,
        description="desc",
        raw_data={"transaction_type": transaction_type},
        fetched_at=datetime.now(UTC),
        missing_fields=[],
    )


def test_cli_filter_batch_sale_and_canton_ne() -> None:
    batch = CollectionBatch(
        source="lookmove_cached",
        collected_count=4,
        listings=[
            _listing_with_url(
                idx=1,
                transaction_type="sale",
                url="https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans-neuchatel,1",
                city="Neuchatel",
                postal_code="2000",
            ),
            _listing_with_url(
                idx=2,
                transaction_type="rent",
                url="https://www.lookmove.ch/fr/annonce/louer/appartement/neuchatel/2",
                city="Neuchatel",
                postal_code="2000",
            ),
            _listing_with_url(
                idx=3,
                transaction_type="sale",
                url="https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans-la-chaux-de-fonds,30",
                city=None,
                postal_code=None,
            ),
            _listing_with_url(
                idx=4,
                transaction_type="sale",
                url="https://www.lookmove.ch/fr/annonce/acheter/maison/berne/3",
                city="Berne",
                postal_code="3000",
            ),
        ],
    )

    filtered, stats = MODULE.filter_collection_batch(
        batch,
        max_listings=None,
        transaction_type="sale",
        canton="NE",
    )

    assert stats.detected_total == 4
    assert stats.kept_canton_count == 3
    assert stats.excluded_canton_count == 1
    assert filtered.collected_count == 2
    assert len(filtered.listings) == 2
    assert all(item.raw_data["transaction_type"] == "sale" for item in filtered.listings)
    assert any("neuchatel" in item.url for item in filtered.listings)
    assert any("la-chaux-de-fonds" in item.url for item in filtered.listings)


def test_cli_filter_batch_max_listings_applied() -> None:
    batch = CollectionBatch(
        source="lookmove_cached",
        collected_count=2,
        listings=[
            _listing_with_url(
                idx=1,
                transaction_type="sale",
                url="https://www.lookmove.ch/fr/annonce/acheter/appartement/neuchatel/1",
                city="Neuchatel",
                postal_code="2000",
            ),
            _listing_with_url(
                idx=2,
                transaction_type="sale",
                url="https://www.lookmove.ch/fr/annonce/acheter/appartement/neuchatel/2",
                city="Neuchatel",
                postal_code="2000",
            ),
        ],
    )

    filtered, _ = MODULE.filter_collection_batch(
        batch,
        max_listings=1,
        transaction_type="sale",
        canton="NE",
    )

    assert filtered.collected_count == 1
    assert len(filtered.listings) == 1


def test_cli_parser_defaults_and_options() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["data/cache/html/lookmove.html", "--max-listings", "5", "--region", "neuchatel"])

    assert str(args.cache_file).endswith("data/cache/html/lookmove.html")
    assert args.max_listings == 5
    assert args.transaction_type == "sale"
    assert args.canton == "NE"
    assert args.region == "neuchatel"
