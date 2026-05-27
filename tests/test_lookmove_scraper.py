from pathlib import Path
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import SourceListing
from immo_ne_collector.scrapers.lookmove import LookmoveCachedHtmlScraper, LookmoveParseError
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.persistence import persist_collection_batch

FIXTURE_PATH = Path("tests/fixtures/html/lookmove_sample_listing_page.html")


@pytest.mark.asyncio
async def test_lookmove_parser_extracts_raw_listing_from_fixture() -> None:
    scraper = LookmoveCachedHtmlScraper(
        html_path=FIXTURE_PATH,
        source="test_lookmove_extract",
        base_url="https://test-lookmove.local",
    )
    listings = await scraper.collect()
    assert len(listings) == 3

    first = listings[0]
    assert first.source_listing_id == "900001"
    assert first.url == "https://test-lookmove.local/fr/annonce/acheter/appartement/neuchatel/900001"
    assert first.title == "Appartement 4.5 pièces avec balcon"
    assert first.city_raw == "Neuchâtel"
    assert first.raw_data.get("transaction_type") == "sale"


def test_lookmove_parser_raises_readable_error_for_unknown_structure(tmp_path: Path) -> None:
    file_path = tmp_path / "unknown.html"
    file_path.write_text("<html><body><p>no listings here</p></body></html>", encoding="utf-8")
    scraper = LookmoveCachedHtmlScraper(html_path=file_path)

    with pytest.raises(LookmoveParseError, match="No Lookmove listing cards found"):
        scraper.parse_html(file_path.read_text(encoding="utf-8"))


def test_lookmove_parser_handles_missing_fields_without_crash(tmp_path: Path) -> None:
    file_path = tmp_path / "minimal.html"
    file_path.write_text(
        (
            "<html><body>"
            "<article data-listing-id='123456'>"
            "<h2><a href='/fr/annonce/acheter/appartement/neuchatel/123456'>Test</a></h2>"
            "</article>"
            "</body></html>"
        ),
        encoding="utf-8",
    )

    scraper = LookmoveCachedHtmlScraper(html_path=file_path, source="test_missing_fields")
    listings = scraper.parse_html(file_path.read_text(encoding="utf-8"))

    assert len(listings) == 1
    listing = listings[0]
    assert listing.source_listing_id == "123456"
    assert listing.title == "Test"
    assert listing.price_raw is None
    assert listing.rooms_raw is None
    assert listing.living_area_raw is None
    assert listing.address_raw is None
    assert listing.city_raw is None
    assert listing.postal_code_raw is None


def test_lookmove_parser_generates_stable_source_listing_id_from_url(tmp_path: Path) -> None:
    file_path = tmp_path / "stable-id.html"
    html = (
        "<html><body>"
        "<article class='lookmove-card' data-listing-id=''>"
        "<h2><a href='/fr/annonce/acheter/appartement/neuchatel/sans-id'>Stable ID</a></h2>"
        "</article>"
        "</body></html>"
    )
    file_path.write_text(html, encoding="utf-8")

    scraper = LookmoveCachedHtmlScraper(html_path=file_path)
    parsed = scraper.parse_html(html)
    parsed_again = scraper.parse_html(html)

    assert len(parsed) == 1
    assert parsed[0].source_listing_id is not None
    assert parsed[0].source_listing_id.startswith("url_")
    assert parsed[0].source_listing_id == parsed_again[0].source_listing_id


def test_lookmove_parser_extracts_id_from_comma_url(tmp_path: Path) -> None:
    file_path = tmp_path / "comma-id.html"
    html = (
        "<html><body>"
        "<article class='lookmove-card'>"
        "<h2><a href='/fr/annonce/acheter/a-vendre-appartement-dans-neuchatel,14258004'>"
        "Annonce"
        "</a></h2>"
        "</article>"
        "</body></html>"
    )
    file_path.write_text(html, encoding="utf-8")
    scraper = LookmoveCachedHtmlScraper(html_path=file_path)

    parsed = scraper.parse_html(html)
    assert len(parsed) == 1
    assert parsed[0].source_listing_id == "14258004"


def test_lookmove_anchor_page_uses_window_app_price_and_slug_city() -> None:
    state = {
        "state": {
            "coords": {
                "result": [
                    {
                        "id": 14258004,
                        "price": 675000,
                        "rooms": 4,
                        "livingSpace": 123,
                    }
                ]
            }
        }
    }
    html = (
        "<html><head><title>Lookmove - Acheter</title></head><body>"
        "<a href='/fr/annonce/acheter/a-vendre-appartement-dans-neuchatel,14258004'></a>"
        f"<script>window.App={json.dumps(state)}</script>"
        "</body></html>"
    )
    scraper = LookmoveCachedHtmlScraper(html_path=FIXTURE_PATH, base_url="https://www.lookmove.ch")
    parsed = scraper.parse_html(html)

    assert len(parsed) == 1
    listing = parsed[0]
    assert listing.title is not None
    assert listing.city_raw == "Neuchâtel"
    assert listing.postal_code_raw == "2000"
    assert listing.price_raw == "CHF 675000"
    assert listing.rooms_raw == "4 pièces"
    assert listing.living_area_raw == "123 m²"


def test_lookmove_rooms_out_of_range_is_ignored() -> None:
    state = {
        "state": {
            "coords": {
                "result": [
                    {
                        "id": 14354040,
                        "price": 1450000,
                        "rooms": 30,
                        "livingSpace": 225,
                    }
                ]
            }
        }
    }
    html = (
        "<html><head><title>Lookmove - Acheter</title></head><body>"
        "<a href='/fr/annonce/acheter/a-vendre-maison-dans-la-chaux-de-fonds,14354040'></a>"
        f"<script>window.App={json.dumps(state)}</script>"
        "</body></html>"
    )
    scraper = LookmoveCachedHtmlScraper(html_path=FIXTURE_PATH, base_url="https://www.lookmove.ch")
    parsed = scraper.parse_html(html)

    assert len(parsed) == 1
    listing = parsed[0]
    assert listing.price_raw == "CHF 1450000"
    assert listing.rooms_raw is None
    assert listing.living_area_raw == "225 m²"
    assert listing.city_raw == "La Chaux-de-Fonds"


def test_lookmove_price_does_not_fallback_to_postal_code() -> None:
    html = (
        "<html><body>"
        "<a href='/fr/annonce/acheter/a-vendre-appartement-dans-neuchatel,14258004'>"
        "Neuchâtel 2000 4.5 pièces"
        "</a>"
        "</body></html>"
    )
    scraper = LookmoveCachedHtmlScraper(html_path=FIXTURE_PATH, base_url="https://www.lookmove.ch")
    parsed = scraper.parse_html(html)

    assert len(parsed) == 1
    listing = parsed[0]
    assert listing.price_raw is None
    assert listing.postal_code_raw == "2000"


@pytest.mark.asyncio
async def test_pipeline_lookmove_fixture_to_normalization() -> None:
    scraper = LookmoveCachedHtmlScraper(
        html_path=FIXTURE_PATH,
        source="test_lookmove_norm",
        base_url="https://test-lookmove.local",
    )
    batch = await collect_and_normalize(scraper)
    assert batch.collected_count == 3
    first = batch.listings[0]
    assert first.price_chf is not None
    assert first.rooms is not None
    assert first.living_area_m2 is not None
    assert first.property_type == "appartement"


@pytest.mark.asyncio
@pytest.mark.db
async def test_pipeline_lookmove_fixture_to_persistence_and_idempotence() -> None:
    source = f"test_lookmove_persist_{uuid4().hex[:8]}"
    scraper = LookmoveCachedHtmlScraper(
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
