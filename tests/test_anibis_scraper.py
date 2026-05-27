from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from immo_ne_collector.db import AsyncSessionLocal, engine
from immo_ne_collector.models import SourceListing
from immo_ne_collector.scrapers.anibis import AnibisCachedHtmlScraper
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.persistence import persist_collection_batch


FIXTURE_PATH = Path("tests/fixtures/html/anibis_sample_listing_page.html")


@pytest.fixture(autouse=True)
async def _dispose_engine_pool_between_tests() -> None:
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_anibis_parser_extracts_raw_listing_from_fixture() -> None:
    scraper = AnibisCachedHtmlScraper(
        html_path=FIXTURE_PATH,
        source="test_anibis_extract",
        base_url="https://test-anibis.local",
    )
    listings = await scraper.collect()
    assert len(listings) == 2
    first = listings[0]
    assert first.source_listing_id == "anibis-2001"
    assert first.url == "https://test-anibis.local/fr/immobilier/anibis-2001"
    assert first.title == "Appartement 4.5 pièces à Neuchâtel"
    assert first.city_raw == "Neuchâtel"


@pytest.mark.asyncio
async def test_pipeline_anibis_fixture_to_normalization() -> None:
    scraper = AnibisCachedHtmlScraper(
        html_path=FIXTURE_PATH,
        source="test_anibis_norm",
        base_url="https://test-anibis.local",
    )
    batch = await collect_and_normalize(scraper)
    assert batch.collected_count == 2
    first = batch.listings[0]
    assert first.price_chf is not None
    assert first.rooms is not None
    assert first.living_area_m2 is not None
    assert first.property_type == "appartement"


@pytest.mark.asyncio
async def test_pipeline_anibis_fixture_to_persistence_and_idempotence() -> None:
    source = f"test_anibis_persist_{uuid4().hex[:8]}"
    scraper = AnibisCachedHtmlScraper(
        html_path=FIXTURE_PATH,
        source=source,
        base_url=f"https://{source}.local",
    )

    first = await persist_collection_batch(await collect_and_normalize(scraper))
    second = await persist_collection_batch(await collect_and_normalize(scraper))

    assert first.collected_count == 2
    assert first.created_count == 2
    assert second.created_count == 0
    assert second.unchanged_count == 2

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(select(SourceListing).where(SourceListing.source == source))
        ).scalars().all()
        assert len(rows) == 2
