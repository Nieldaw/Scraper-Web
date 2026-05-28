from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from immo_ne_collector.services.collection import CollectionBatch
from immo_ne_collector.services.normalization import NormalizedListing


SCRIPT_PATH = Path("scripts/parse_cached_immoscout_to_db.py")
SPEC = importlib.util.spec_from_file_location("parse_cached_immoscout_to_db", SCRIPT_PATH)
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
        source="immoscout_cached",
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
        source="immoscout_cached",
        collected_count=3,
        listings=[
            _listing_with_url(
                idx=1,
                transaction_type="sale",
                url="https://www.immoscout24.ch/fr/acheter/appartement/canton-neuchatel/listing-1",
                city="Neuchatel",
                postal_code="2000",
            ),
            _listing_with_url(
                idx=2,
                transaction_type="rent",
                url="https://www.immoscout24.ch/fr/louer/appartement/canton-neuchatel/listing-2",
                city="Neuchatel",
                postal_code="2000",
            ),
            _listing_with_url(
                idx=3,
                transaction_type="sale",
                url="https://www.immoscout24.ch/fr/acheter/maison/canton-geneve/listing-3",
                city="Geneve",
                postal_code="1200",
            ),
        ],
    )

    filtered, stats = MODULE.filter_collection_batch(
        batch,
        max_listings=None,
        transaction_type="sale",
        canton="NE",
    )

    assert stats.detected_total == 3
    assert stats.kept_canton_count == 2
    assert stats.excluded_canton_count == 1
    assert filtered.collected_count == 1
    assert len(filtered.listings) == 1
    assert filtered.listings[0].raw_data["transaction_type"] == "sale"


def test_cli_parser_defaults_and_options() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(
        ["data/cache/html/immoscout.html", "--max-listings", "5", "--region", "neuchatel", "--url-kind", "land"]
    )

    assert str(args.cache_file).endswith("data/cache/html/immoscout.html")
    assert args.max_listings == 5
    assert args.transaction_type == "sale"
    assert args.canton == "NE"
    assert args.region == "neuchatel"
    assert args.url_kind == "land"
