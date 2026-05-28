from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import SourceListing
from immo_ne_collector.scrapers.immoscout import (
    ImmoscoutCachedHtmlScraper,
    ImmoscoutParseError,
    detect_immoscout_challenge_html,
)
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.persistence import persist_collection_batch


RESIDENTIAL_FIXTURE = Path("tests/fixtures/html/immoscout_sample_residential_listing_page.html")
LAND_FIXTURE = Path("tests/fixtures/html/immoscout_sample_land_listing_page.html")
CHALLENGE_FIXTURE = Path("tests/fixtures/html/immoscout_challenge_or_blocked.html")


@pytest.mark.asyncio
async def test_immoscout_parser_extracts_listing_from_residential_fixture() -> None:
    scraper = ImmoscoutCachedHtmlScraper(
        html_path=RESIDENTIAL_FIXTURE,
        source="test_immoscout_extract",
        base_url="https://www.immoscout24.ch",
    )
    listings = await scraper.collect()
    assert len(listings) == 2

    first = listings[0]
    assert first.source_listing_id == "90010001"
    assert first.url.endswith("/listing-90010001")
    assert first.title == "Appartement 4.5 pièces à Neuchâtel"
    assert first.raw_data.get("transaction_type") == "sale"
    assert first.raw_data.get("parser_strategy") == "html_fixture_fallback"
    assert first.raw_data.get("url_kind") == "residential"
    assert first.raw_data.get("source_category") == "residential"
    assert first.raw_data.get("challenge_detected") is False


def test_immoscout_parser_land_fixture_sets_terrain() -> None:
    scraper = ImmoscoutCachedHtmlScraper(
        html_path=LAND_FIXTURE,
        source="test_immoscout_land",
        base_url="https://www.immoscout24.ch",
        url_kind="land",
    )
    listings = scraper.parse_html(LAND_FIXTURE.read_text(encoding="utf-8"))
    assert len(listings) == 1
    first = listings[0]
    assert first.property_type == "terrain"
    assert first.raw_data.get("parser_strategy") == "initial_state_json"
    assert first.raw_data.get("url_kind") == "land"
    assert first.raw_data.get("source_category") == "land"


def test_immoscout_challenge_detection_and_parse_error() -> None:
    html = CHALLENGE_FIXTURE.read_text(encoding="utf-8")
    detected, reason = detect_immoscout_challenge_html(html)
    assert detected is True
    assert reason is not None

    scraper = ImmoscoutCachedHtmlScraper(html_path=CHALLENGE_FIXTURE)
    with pytest.raises(ImmoscoutParseError, match="challenge page detected"):
        scraper.parse_html(html)


@pytest.mark.asyncio
async def test_pipeline_immoscout_fixture_to_normalization() -> None:
    scraper = ImmoscoutCachedHtmlScraper(
        html_path=RESIDENTIAL_FIXTURE,
        source="test_immoscout_norm",
        base_url="https://www.immoscout24.ch",
    )
    batch = await collect_and_normalize(scraper)
    assert batch.collected_count == 2
    assert batch.listings[0].price_chf is not None
    assert batch.listings[0].rooms is not None
    assert batch.listings[0].living_area_m2 is not None


@pytest.mark.asyncio
@pytest.mark.db
async def test_pipeline_immoscout_fixture_to_persistence_and_idempotence() -> None:
    source = f"test_immoscout_persist_{uuid4().hex[:8]}"
    scraper = ImmoscoutCachedHtmlScraper(
        html_path=RESIDENTIAL_FIXTURE,
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
