from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from immo_ne_collector.db import AsyncSessionLocal, engine
from immo_ne_collector.models import SourceListing
from immo_ne_collector.scrapers.static_html import StaticHtmlScraper
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.persistence import persist_collection_batch


FIXTURE_PATH = Path("tests/fixtures/html/sample_listing_page.html")


@pytest.fixture(autouse=True)
async def _dispose_engine_pool_between_tests() -> None:
    await engine.dispose()
    yield
    await engine.dispose()


def test_fixture_html_exists_and_readable() -> None:
    assert FIXTURE_PATH.exists()
    content = FIXTURE_PATH.read_text(encoding="utf-8")
    assert "<article class=\"listing-card\"" in content


@pytest.mark.asyncio
async def test_static_html_scraper_extracts_raw_listings() -> None:
    scraper = StaticHtmlScraper(
        html_path=FIXTURE_PATH,
        source="test_static_extract",
        base_url="https://static-html.local",
    )
    listings = await scraper.collect()

    assert len(listings) == 3
    first = listings[0]
    assert first.source_listing_id == "sample-1001"
    assert first.url == "https://static-html.local/annonce/sample-1001"
    assert first.title == "Appartement 4.5 pièces à Neuchâtel"
    assert first.price_raw == "CHF 850'000"
    assert first.rooms_raw == "4.5 pièces"
    assert first.living_area_raw == "110 m²"
    assert first.address_raw == "Rue du Seyon 12"
    assert first.city_raw == "Neuchâtel"
    assert first.postal_code_raw == "2000"
    assert first.description_raw is not None
    assert first.raw_data["parser"] == "static_html"


@pytest.mark.asyncio
async def test_pipeline_static_html_to_normalization() -> None:
    scraper = StaticHtmlScraper(
        html_path=FIXTURE_PATH,
        source="test_static_norm",
        base_url="https://static-html.local",
    )
    batch = await collect_and_normalize(scraper)

    assert batch.collected_count == 3
    listing = batch.listings[0]
    assert listing.price_chf is not None
    assert listing.rooms is not None
    assert listing.living_area_m2 is not None
    assert listing.city == "Neuchâtel"
    assert listing.address_full == "Rue du Seyon 12"


@pytest.mark.asyncio
async def test_pipeline_static_html_to_persistence_db() -> None:
    source = f"test_static_persist_{uuid4().hex[:8]}"
    base_url = f"https://{source}.local"
    scraper = StaticHtmlScraper(
        html_path=FIXTURE_PATH,
        source=source,
        base_url=base_url,
    )

    first = await persist_collection_batch(await collect_and_normalize(scraper))
    second = await persist_collection_batch(await collect_and_normalize(scraper))

    assert first.collected_count == 3
    assert first.created_count == 3
    assert second.created_count == 0
    assert second.unchanged_count == 3

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(select(SourceListing).where(SourceListing.source == source))
        ).scalars().all()
        assert len(rows) == 3
