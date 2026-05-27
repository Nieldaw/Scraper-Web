from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from immo_ne_collector.services.collection import CollectionBatch
from immo_ne_collector.services.normalization import NormalizedListing


SCRIPT_PATH = Path("scripts/parse_cached_anibis_to_db.py")
SPEC = importlib.util.spec_from_file_location("parse_cached_anibis_to_db", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _listing(transaction_type: str, idx: int) -> NormalizedListing:
    return NormalizedListing(
        source="anibis_cached",
        source_listing_id=f"id-{idx}",
        url=f"https://www.anibis.ch/fr/vi/neuchatel/immobilier/appartements/test/{idx}",
        title=f"Listing {idx}",
        property_type="appartement",
        price_chf=Decimal("1000000"),
        rooms=Decimal("4.5"),
        living_area_m2=Decimal("100"),
        address_full="Rue du Seyon 12",
        city="Neuchatel",
        postal_code="2000",
        description="desc",
        raw_data={"transaction_type": transaction_type},
        fetched_at=datetime.now(UTC),
        missing_fields=[],
    )


def _listing_with_url(
    *,
    idx: int,
    url: str,
    city: str | None = None,
    postal_code: str | None = None,
    transaction_type: str = "sale",
) -> NormalizedListing:
    return NormalizedListing(
        source="anibis_cached",
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


def test_cli_filter_batch_respects_transaction_type_and_max_listings() -> None:
    batch = CollectionBatch(
        source="anibis_cached",
        collected_count=4,
        listings=[
            _listing("rent", 1),
            _listing("sale", 2),
            _listing("rent", 3),
            _listing("unknown", 4),
        ],
    )

    filtered, original_count = MODULE.filter_collection_batch(
        batch,
        max_listings=1,
        transaction_type="rent",
        canton=None,
    )

    assert original_count.detected_total == 4
    assert filtered.collected_count == 1
    assert len(filtered.listings) == 1
    assert filtered.listings[0].raw_data["transaction_type"] == "rent"


def test_cli_filter_batch_all_keeps_everything_without_limit() -> None:
    batch = CollectionBatch(
        source="anibis_cached",
        collected_count=3,
        listings=[_listing("rent", 1), _listing("sale", 2), _listing("unknown", 3)],
    )

    filtered, original_count = MODULE.filter_collection_batch(
        batch,
        max_listings=None,
        transaction_type="all",
        canton=None,
    )

    assert original_count.detected_total == 3
    assert filtered.collected_count == 3
    assert len(filtered.listings) == 3


def test_cli_filter_batch_canton_ne_keeps_neuchatel_excludes_berne() -> None:
    batch = CollectionBatch(
        source="anibis_cached",
        collected_count=2,
        listings=[
            _listing_with_url(
                idx=1,
                url="https://www.anibis.ch/fr/vi/neuchatel/immobilier/appartements/a/1",
                city="Neuchatel",
                postal_code="2000",
            ),
            _listing_with_url(
                idx=2,
                url="https://www.anibis.ch/fr/vi/berne/immobilier/appartements/b/2",
                city="Berne",
                postal_code="3000",
            ),
        ],
    )
    filtered, stats = MODULE.filter_collection_batch(
        batch,
        max_listings=None,
        transaction_type="all",
        canton="NE",
    )

    assert filtered.collected_count == 1
    assert len(filtered.listings) == 1
    assert "/neuchatel/" in filtered.listings[0].url
    assert stats.kept_canton_count == 1
    assert stats.excluded_canton_count == 1
    assert stats.excluded_examples
    assert "/berne/" in stats.excluded_examples[0]


def test_cli_parser_accepts_new_options() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(
        [
            "data/cache/html/test.html",
            "--max-listings",
            "5",
            "--transaction-type",
            "sale",
            "--canton",
            "NE",
            "--region",
            "neuchatel",
        ]
    )
    assert str(args.cache_file).endswith("data/cache/html/test.html")
    assert args.max_listings == 5
    assert args.transaction_type == "sale"
    assert args.canton == "NE"
    assert args.region == "neuchatel"
