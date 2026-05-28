from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import DailyRun, Property, PropertyStatus, SourceListing
from immo_ne_collector.scrapers.mock_multisource import CatalogMockScraper, MockListingSeed
from immo_ne_collector.services.collection import CollectionBatch
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.normalization import NormalizedListing
from immo_ne_collector.services import persistence as persistence_module
from immo_ne_collector.services.persistence import persist_collection_batch

pytestmark = pytest.mark.db


def _build_batch(
    *,
    source: str,
    source_listing_id: str,
    title: str = "Appartement test",
    description: str = "Description test",
    price_chf: Decimal | None = Decimal("1000000"),
    rooms: Decimal | None = Decimal("4.5"),
    living_area_m2: Decimal | None = Decimal("120"),
    city: str = "Neuchatel",
    address_full: str = "Rue du Seyon 12",
    postal_code: str = "2000",
    raw_data: dict | None = None,
) -> CollectionBatch:
    listing = NormalizedListing(
        source=source,
        source_listing_id=source_listing_id,
        url=f"https://{source}.local/listings/{source_listing_id}",
        title=title,
        property_type="appartement",
        price_chf=price_chf,
        rooms=rooms,
        living_area_m2=living_area_m2,
        address_full=address_full,
        city=city,
        postal_code=postal_code,
        description=description,
        raw_data=raw_data or {"test": True},
        fetched_at=datetime.now(UTC),
        missing_fields=[],
    )
    return CollectionBatch(source=source, collected_count=1, listings=[listing])


@pytest.mark.asyncio
async def test_persistence_inserts_new_listing() -> None:
    source = f"test-persist-{uuid4().hex[:8]}"
    listing_id = f"listing-{uuid4().hex[:8]}"
    unique_city = f"UniqueCity-{uuid4().hex[:8]}"
    unique_address = f"Rue Unique {uuid4().hex[:8]} 99"
    unique_price = Decimal("9876543")
    batch = _build_batch(
        source=source,
        source_listing_id=listing_id,
        city=unique_city,
        address_full=unique_address,
        postal_code="2999",
        price_chf=unique_price,
        title="Appartement test totalement unique",
    )

    result = await persist_collection_batch(batch)

    assert result.collected_count == 1
    assert result.created_count == 1
    assert result.updated_count == 0
    assert result.unchanged_count == 0
    assert result.errors == []

    async with AsyncSessionLocal() as session:
        source_row = (
            await session.execute(
                select(SourceListing).where(
                    SourceListing.source == source,
                    SourceListing.source_listing_id == listing_id,
                )
            )
        ).scalar_one()
        property_row = (await session.execute(select(Property).where(Property.id == source_row.property_id))).scalar_one()

        assert property_row.status == PropertyStatus.NEW
        assert property_row.title == "Appartement test totalement unique"
        assert property_row.city == unique_city
        assert property_row.address_full == unique_address
        assert property_row.price_chf == unique_price


@pytest.mark.asyncio
async def test_persistence_rerun_is_idempotent_no_duplicates() -> None:
    source = f"test-idempotent-{uuid4().hex[:8]}"
    listing_id = "listing-1"
    batch = _build_batch(source=source, source_listing_id=listing_id)

    first = await persist_collection_batch(batch)
    second = await persist_collection_batch(batch)

    assert first.created_count == 1
    assert second.created_count == 0
    assert second.updated_count == 0
    assert second.unchanged_count == 1

    async with AsyncSessionLocal() as session:
        source_count = (
            await session.execute(
                select(SourceListing).where(
                    SourceListing.source == source,
                    SourceListing.source_listing_id == listing_id,
                )
            )
        ).scalars().all()
        assert len(source_count) == 1


@pytest.mark.asyncio
async def test_persistence_updates_existing_listing_when_values_change() -> None:
    source = f"test-update-{uuid4().hex[:8]}"
    listing_id = "listing-1"
    original_batch = _build_batch(source=source, source_listing_id=listing_id)
    changed_batch = _build_batch(
        source=source,
        source_listing_id=listing_id,
        title="Appartement test modifie",
        description="Description modifiee",
        price_chf=Decimal("1100000"),
    )

    await persist_collection_batch(original_batch)
    second = await persist_collection_batch(changed_batch)

    assert second.created_count == 0
    assert second.updated_count == 1
    assert second.unchanged_count == 0

    async with AsyncSessionLocal() as session:
        source_row = (
            await session.execute(
                select(SourceListing).where(
                    SourceListing.source == source,
                    SourceListing.source_listing_id == listing_id,
                )
            )
        ).scalar_one()
        property_row = (await session.execute(select(Property).where(Property.id == source_row.property_id))).scalar_one()

        assert source_row.price_chf == Decimal("1100000")
        assert source_row.title == "Appartement test modifie"
        assert source_row.description == "Description modifiee"
        assert property_row.status == PropertyStatus.UPDATED
        assert property_row.last_changed_at is not None


@pytest.mark.asyncio
async def test_persistence_creates_property_linked_to_source_listing() -> None:
    source = f"test-link-{uuid4().hex[:8]}"
    listing_id = "listing-1"
    batch = _build_batch(source=source, source_listing_id=listing_id)

    await persist_collection_batch(batch)

    async with AsyncSessionLocal() as session:
        source_row = (
            await session.execute(
                select(SourceListing).where(
                    SourceListing.source == source,
                    SourceListing.source_listing_id == listing_id,
                )
            )
        ).scalar_one()
        assert source_row.property_id is not None

        property_row = (await session.execute(select(Property).where(Property.id == source_row.property_id))).scalar_one()
        assert property_row.id == source_row.property_id
        assert source in property_row.sources
        assert source_row.url in property_row.source_urls


@pytest.mark.asyncio
async def test_persistence_creates_daily_run() -> None:
    source = f"test-dailyrun-{uuid4().hex[:8]}"
    listing_id = "listing-1"
    batch = _build_batch(source=source, source_listing_id=listing_id)

    result = await persist_collection_batch(batch)

    async with AsyncSessionLocal() as session:
        daily_run = (await session.execute(select(DailyRun).where(DailyRun.id == result.daily_run_id))).scalar_one()

        assert daily_run.status == "SUCCESS"
        assert daily_run.finished_at is not None
        assert daily_run.stats["source"] == source
        assert daily_run.stats["created_count"] == 1


@pytest.mark.asyncio
async def test_persistence_rolls_back_and_marks_daily_run_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    source = f"test-failed-{uuid4().hex[:8]}"
    listing_id = "listing-1"
    batch = _build_batch(source=source, source_listing_id=listing_id)

    async def _boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced failure for rollback test")

    monkeypatch.setattr(persistence_module, "_persist_one_listing", _boom)

    result = await persist_collection_batch(batch)

    assert result.created_count == 0
    assert result.updated_count == 0
    assert result.unchanged_count == 0
    assert result.errors

    async with AsyncSessionLocal() as session:
        source_rows = (
            await session.execute(
                select(SourceListing).where(
                    SourceListing.source == source,
                    SourceListing.source_listing_id == listing_id,
                )
            )
        ).scalars().all()
        assert source_rows == []

        daily_run = (await session.execute(select(DailyRun).where(DailyRun.id == result.daily_run_id))).scalar_one()
        assert daily_run.status == "FAILED"
        assert daily_run.error is not None


@pytest.mark.asyncio
async def test_persistence_merges_two_sources_into_one_property_on_confident_match() -> None:
    suffix = uuid4().hex[:8]
    source_a = f"mock_homegate_{suffix}"
    source_b = f"mock_immoscout_{suffix}"

    scraper_a = CatalogMockScraper(
        source=source_a,
        seeds=[
            MockListingSeed(
                source_listing_id="a-1",
                url=f"https://{source_a}.local/a-1",
                title="Appartement 4.5 pieces a Neuchatel",
                property_type="appartement",
                price_raw="CHF 850'000",
                rooms_raw="4.5",
                living_area_raw="110 m2",
                address_raw="Rue du Seyon 12",
                city_raw="Neuchatel",
                postal_code_raw="2000",
                description_raw="Source A",
            )
        ],
    )
    scraper_b = CatalogMockScraper(
        source=source_b,
        seeds=[
            MockListingSeed(
                source_listing_id="b-1",
                url=f"https://{source_b}.local/b-1",
                title="Bel appartement 4.5 pieces Neuchatel",
                property_type="appartement",
                price_raw="CHF 855'000",
                rooms_raw="4.5",
                living_area_raw="112 m2",
                address_raw="Rue du Seyon 12",
                city_raw="Neuchatel",
                postal_code_raw="2000",
                description_raw="Source B",
            )
        ],
    )

    await persist_collection_batch(await collect_and_normalize(scraper_a))
    await persist_collection_batch(await collect_and_normalize(scraper_b))

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SourceListing).where(SourceListing.source.in_([source_a, source_b]))
            )
        ).scalars().all()
        assert len(rows) == 2
        property_ids = {row.property_id for row in rows}
        assert len(property_ids) == 1


@pytest.mark.asyncio
async def test_persistence_keeps_separate_properties_when_ambiguous() -> None:
    suffix = uuid4().hex[:8]
    source_a = f"mock_amb_a_{suffix}"
    source_b = f"mock_amb_b_{suffix}"

    scraper_a = CatalogMockScraper(
        source=source_a,
        seeds=[
            MockListingSeed(
                source_listing_id="a-1",
                url=f"https://{source_a}.local/a-1",
                title="Appartement centre-ville",
                property_type="appartement",
                city_raw="Neuchatel",
                description_raw="Peu d'informations",
            )
        ],
    )
    scraper_b = CatalogMockScraper(
        source=source_b,
        seeds=[
            MockListingSeed(
                source_listing_id="b-1",
                url=f"https://{source_b}.local/b-1",
                title="Bel appartement au centre-ville",
                property_type="appartement",
                city_raw="Neuchatel",
                description_raw="Infos insuffisantes aussi",
            )
        ],
    )

    await persist_collection_batch(await collect_and_normalize(scraper_a))
    await persist_collection_batch(await collect_and_normalize(scraper_b))

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SourceListing).where(SourceListing.source.in_([source_a, source_b]))
            )
        ).scalars().all()
        assert len(rows) == 2
        property_ids = {row.property_id for row in rows}
        assert len(property_ids) == 2


@pytest.mark.asyncio
async def test_persistence_idempotence_is_preserved_after_cross_source_match() -> None:
    suffix = uuid4().hex[:8]
    source_a = f"mock_idemp_a_{suffix}"
    source_b = f"mock_idemp_b_{suffix}"

    scraper_a = CatalogMockScraper(
        source=source_a,
        seeds=[
            MockListingSeed(
                source_listing_id="a-1",
                url=f"https://{source_a}.local/a-1",
                title="Appartement 4.5 pieces a Neuchatel",
                property_type="appartement",
                price_raw="CHF 850'000",
                rooms_raw="4.5",
                living_area_raw="110 m2",
                address_raw="Rue du Seyon 12",
                city_raw="Neuchatel",
                postal_code_raw="2000",
            )
        ],
    )
    scraper_b = CatalogMockScraper(
        source=source_b,
        seeds=[
            MockListingSeed(
                source_listing_id="b-1",
                url=f"https://{source_b}.local/b-1",
                title="Bel appartement 4.5 pieces Neuchatel",
                property_type="appartement",
                price_raw="CHF 852'000",
                rooms_raw="4.5",
                living_area_raw="111 m2",
                address_raw="Rue du Seyon 12",
                city_raw="Neuchatel",
                postal_code_raw="2000",
            )
        ],
    )

    await persist_collection_batch(await collect_and_normalize(scraper_a))
    first_b = await persist_collection_batch(await collect_and_normalize(scraper_b))
    second_b = await persist_collection_batch(await collect_and_normalize(scraper_b))

    assert first_b.created_count == 1
    assert second_b.created_count == 0
    assert second_b.unchanged_count == 1


@pytest.mark.asyncio
async def test_persistence_does_not_merge_when_detected_canton_differs() -> None:
    source_a = f"test-canton-a-{uuid4().hex[:8]}"
    source_b = f"test-canton-b-{uuid4().hex[:8]}"

    batch_a = _build_batch(
        source=source_a,
        source_listing_id="a-1",
        title="Appartement 4.5 pieces",
        city="Commune Test",
        postal_code=None,
        raw_data={"transaction_type": "sale", "detected_canton": "NE"},
    )
    batch_b = _build_batch(
        source=source_b,
        source_listing_id="b-1",
        title="Appartement 4.5 pieces",
        city="Commune Test",
        postal_code=None,
        raw_data={"transaction_type": "sale", "detected_canton": "GE"},
    )

    await persist_collection_batch(batch_a)
    await persist_collection_batch(batch_b)

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SourceListing).where(SourceListing.source.in_([source_a, source_b]))
            )
        ).scalars().all()
        assert len(rows) == 2
        property_ids = {row.property_id for row in rows}
        assert len(property_ids) == 2
