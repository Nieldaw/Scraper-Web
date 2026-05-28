from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import SourceListing
from immo_ne_collector.scrapers.homegate import HomegateCachedHtmlScraper, HomegateParseError
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.persistence import persist_collection_batch

FIXTURE_PATH = Path("tests/fixtures/html/homegate_sample_listing_page.html")


@pytest.mark.asyncio
async def test_homegate_parser_extracts_raw_listing_from_fixture() -> None:
    scraper = HomegateCachedHtmlScraper(
        html_path=FIXTURE_PATH,
        source="test_homegate_extract",
        base_url="https://test-homegate.local",
    )
    listings = await scraper.collect()
    assert len(listings) == 3

    first = listings[0]
    assert first.source_listing_id == "4001000001"
    assert first.url == "https://test-homegate.local/acheter/appartement/canton-neuchatel/listing-4001000001"
    assert first.title == "Appartement 4.5 pièces à Neuchâtel"
    assert first.property_type == "appartement"
    assert first.city_raw == "Neuchâtel"
    assert first.postal_code_raw == "2000"
    assert first.raw_data.get("transaction_type") == "sale"
    assert first.raw_data.get("detected_canton") == "NE"
    assert first.raw_data.get("url_kind") == "residential"
    assert first.raw_data.get("source_category") == "residential"


def test_homegate_parser_raises_readable_error_for_unknown_structure(tmp_path: Path) -> None:
    file_path = tmp_path / "unknown.html"
    file_path.write_text("<html><body><p>no listings here</p></body></html>", encoding="utf-8")
    scraper = HomegateCachedHtmlScraper(html_path=file_path)

    with pytest.raises(HomegateParseError, match="No Homegate listing cards found"):
        scraper.parse_html(file_path.read_text(encoding="utf-8"))


def test_homegate_parser_handles_missing_fields_without_crash(tmp_path: Path) -> None:
    file_path = tmp_path / "minimal.html"
    file_path.write_text(
        (
            "<html><body>"
            "<article data-test='result-item'>"
            "<h2><a href='/acheter/appartement/canton-neuchatel/objet-sans-id'>Test Homegate</a></h2>"
            "</article>"
            "</body></html>"
        ),
        encoding="utf-8",
    )

    scraper = HomegateCachedHtmlScraper(html_path=file_path, source="test_missing_fields")
    listings = scraper.parse_html(file_path.read_text(encoding="utf-8"))

    assert len(listings) == 1
    listing = listings[0]
    assert listing.source_listing_id.startswith("url_")
    assert listing.title == "Test Homegate"
    assert listing.price_raw is None
    assert listing.rooms_raw is None
    assert listing.living_area_raw is None


def test_homegate_parser_recognizes_terrain_property_type_from_url() -> None:
    scraper = HomegateCachedHtmlScraper(html_path=FIXTURE_PATH)
    html = (
        "<html><body>"
        "<article data-test='result-item'>"
        "<h2><a href='/acheter/terrain/canton-neuchatel/listing-4009990001'>Terrain constructible</a></h2>"
        "<div data-test='result-address'>2400 Le Locle</div>"
        "</article>"
        "</body></html>"
    )
    parsed = scraper.parse_html(html)
    assert len(parsed) == 1
    assert parsed[0].property_type == "terrain"


def test_homegate_parser_land_url_kind_forces_terrain() -> None:
    scraper = HomegateCachedHtmlScraper(html_path=FIXTURE_PATH, url_kind="land")
    listings = scraper.parse_html(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert len(listings) == 3
    assert all(item.property_type == "terrain" for item in listings)
    assert all(item.raw_data.get("url_kind") == "land" for item in listings)


@pytest.mark.asyncio
async def test_pipeline_homegate_fixture_to_normalization() -> None:
    scraper = HomegateCachedHtmlScraper(
        html_path=FIXTURE_PATH,
        source="test_homegate_norm",
        base_url="https://test-homegate.local",
    )
    batch = await collect_and_normalize(scraper)
    assert batch.collected_count == 3
    first = batch.listings[0]
    assert first.price_chf is not None
    assert first.rooms is not None
    assert first.living_area_m2 is not None


@pytest.mark.asyncio
@pytest.mark.db
async def test_pipeline_homegate_fixture_to_persistence_and_idempotence() -> None:
    source = f"test_homegate_persist_{uuid4().hex[:8]}"
    scraper = HomegateCachedHtmlScraper(
        html_path=FIXTURE_PATH,
        source=source,
        base_url=f"https://{source}.local",
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
