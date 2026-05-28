from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import SourceListing
from immo_ne_collector.scrapers.anibis import AnibisCachedHtmlScraper, AnibisParseError
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.persistence import persist_collection_batch

FIXTURE_PATH = Path("tests/fixtures/html/anibis_sample_listing_page.html")


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
    assert first.raw_data.get("detected_canton") == "NE"
    assert first.raw_data.get("detected_canton_reason") in {"url", "city", "postal_code", "unknown"}


def test_anibis_parser_raises_readable_error_for_unknown_structure(tmp_path: Path) -> None:
    file_path = tmp_path / "unknown.html"
    file_path.write_text("<html><body><p>no listings here</p></body></html>", encoding="utf-8")
    scraper = AnibisCachedHtmlScraper(html_path=file_path)

    with pytest.raises(AnibisParseError, match="No Anibis listing cards found"):
        scraper.parse_html(file_path.read_text(encoding="utf-8"))


def test_anibis_parser_handles_missing_fields_without_crash(tmp_path: Path) -> None:
    file_path = tmp_path / "minimal.html"
    file_path.write_text(
        (
            "<html><body>"
            "<div data-private-srp-listing-item-id='123456'>"
            "<h2>"
            "<a href='/fr/vi/neuchatel/immobilier/appartements/test-minimal/123456'>"
            "Test"
            "</a>"
            "</h2>"
            "</div>"
            "</body></html>"
        ),
        encoding="utf-8",
    )

    scraper = AnibisCachedHtmlScraper(html_path=file_path, source="test_missing_fields")
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
    assert listing.raw_data.get("transaction_type") == "unknown"


def test_anibis_parser_classifies_rent_keywords() -> None:
    scraper = AnibisCachedHtmlScraper(html_path=FIXTURE_PATH)
    html = (
        "<html><body>"
        "<div data-private-srp-listing-item-id='9001'>"
        "<h2><a href='/fr/vi/neuchatel/immobilier/appartements/studio-location/9001'>"
        "Studio équipé en location"
        "</a></h2>"
        "<span>900.- par mois</span>"
        "</div>"
        "</body></html>"
    )
    listings = scraper.parse_html(html)
    assert listings[0].raw_data.get("transaction_type") == "rent"


def test_anibis_parser_classifies_sale_keywords() -> None:
    scraper = AnibisCachedHtmlScraper(html_path=FIXTURE_PATH)
    html = (
        "<html><body>"
        "<div data-private-srp-listing-item-id='9002'>"
        "<h2><a href='/fr/vi/neuchatel/immobilier/maisons/maison-a-vendre/9002'>"
        "Maison à vendre à Peseux"
        "</a></h2>"
        "<span>Prix de vente 1 200 000.-</span>"
        "</div>"
        "</body></html>"
    )
    listings = scraper.parse_html(html)
    assert listings[0].raw_data.get("transaction_type") == "sale"


def test_anibis_parser_classifies_unknown_when_not_enough_info() -> None:
    scraper = AnibisCachedHtmlScraper(html_path=FIXTURE_PATH)
    html = (
        "<html><body>"
        "<div data-private-srp-listing-item-id='9003'>"
        "<h2><a href='/fr/vi/neuchatel/immobilier/appartements/bien-neutre/9003'>"
        "Bien neutre"
        "</a></h2>"
        "<span>Texte sans contexte transaction</span>"
        "</div>"
        "</body></html>"
    )
    listings = scraper.parse_html(html)
    assert listings[0].raw_data.get("transaction_type") == "unknown"


def test_anibis_parser_buy_page_context_promotes_unknown_to_sale() -> None:
    scraper = AnibisCachedHtmlScraper(html_path=FIXTURE_PATH)
    html = (
        "<html><head>"
        "<title>Immobilier - Acheter - Neuchâtel</title>"
        "<link rel='canonical' href='https://www.anibis.ch/fr/q/immobilier-neuchatel-appartements-maisons-acheter/test'>"
        "</head><body>"
        "<div data-private-srp-listing-item-id='9010'>"
        "<h2><a href='/fr/vi/neuchatel/immobilier/appartements/bien-neutre/9010'>Bien neutre</a></h2>"
        "<span>Neuchâtel, 2000</span>"
        "</div>"
        "</body></html>"
    )
    listings = scraper.parse_html(html)
    assert listings[0].raw_data.get("transaction_type") == "sale"


def test_anibis_parser_rent_stays_rent_on_buy_page_context() -> None:
    scraper = AnibisCachedHtmlScraper(html_path=FIXTURE_PATH)
    html = (
        "<html><head>"
        "<title>Immobilier - Acheter - Neuchâtel</title>"
        "</head><body>"
        "<div data-private-srp-listing-item-id='9011'>"
        "<h2><a href='/fr/vi/neuchatel/immobilier/appartements/location-courte/9011'>À louer studio meublé</a></h2>"
        "<span>1 100.- par mois</span>"
        "</div>"
        "</body></html>"
    )
    listings = scraper.parse_html(html)
    assert listings[0].raw_data.get("transaction_type") == "rent"


def test_anibis_parser_generates_stable_source_listing_id_from_url(tmp_path: Path) -> None:
    file_path = tmp_path / "stable-id.html"
    html = (
        "<html><body>"
        "<article class='anibis-card' data-item-id=''>"
        "<h2>"
        "<a href='/fr/vi/neuchatel/immobilier/appartements/no-numeric-id'>"
        "Stable ID Listing"
        "</a>"
        "</h2>"
        "<span>Neuchâtel, 2000, Aujourd'hui</span>"
        "</article>"
        "</body></html>"
    )
    file_path.write_text(html, encoding="utf-8")
    scraper = AnibisCachedHtmlScraper(html_path=file_path)

    parsed = scraper.parse_html(html)
    parsed_again = scraper.parse_html(html)

    assert len(parsed) == 1
    assert parsed[0].source_listing_id is not None
    assert parsed[0].source_listing_id.startswith("url_")
    assert parsed[0].source_listing_id == parsed_again[0].source_listing_id


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
@pytest.mark.db
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
