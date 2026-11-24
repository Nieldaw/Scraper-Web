from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from immo_ne_collector.scrapers.anibis_detail import AnibisDetailParseError, parse_anibis_detail
from immo_ne_collector.scrapers.safety import ScraperHTTPError
from immo_ne_collector.services.anibis_enrichment import enrich_anibis_batch
from immo_ne_collector.services.collection import CollectionBatch
from immo_ne_collector.services.normalization import NormalizedListing

FIX = Path("tests/fixtures/html")


def _html(name: str) -> str:
    return (FIX / f"anibis_detail_{name}.html").read_text(encoding="utf-8")


def test_detail_apartment_gives_exact_values():
    d = parse_anibis_detail(_html("apartment"))
    assert d.price_raw == "890 000.-"
    assert d.rooms_raw == "4,5"  # le titre est plus précis que l'attribut arrondi (« 4 »)
    assert d.living_area_raw == "120"  # et non le balcon de 20 m²
    assert d.address_raw == "Blaise-Cendrars 3"


def test_detail_land_area_is_plot_not_living_and_price_on_request():
    d = parse_anibis_detail(_html("land"))
    assert d.price_raw is None
    assert d.living_area_raw is None and d.plot_area_raw == "850"


def test_detail_rent_price_is_not_used():
    d = parse_anibis_detail(_html("rent"))
    assert d.price_is_rent and d.price_raw is None


def test_detail_missing_next_data_raises():
    with pytest.raises(AnibisDetailParseError):
        parse_anibis_detail("<html></html>")


def _listing(url: str, price="1052727") -> NormalizedListing:
    return NormalizedListing(
        source="anibis_cached",
        source_listing_id=url[-4:],
        url=url,
        title="Bel appartement 2,5 pièces",
        property_type="appartement",
        price_chf=Decimal(price),
        rooms=Decimal("2.5"),
        living_area_m2=None,
        address_full=None,
        city="Boudry",
        postal_code="2017",
        description=None,
        raw_data={},
        fetched_at=datetime.now(UTC),
        missing_fields=[],
    )


def _batch(*urls: str) -> CollectionBatch:
    return CollectionBatch(
        source="anibis_cached", collected_count=len(urls), listings=[_listing(u) for u in urls]
    )


def _fetch_from(tmp_path: Path, html: str, calls: list[str]):
    async def fetch(*, url, cache_dir, source, safety, rate_limiter):
        calls.append(url)
        path = tmp_path / f"d{len(calls)}.html"
        path.write_text(html, encoding="utf-8")
        return SimpleNamespace(file_path=path, status_code=200)

    return fetch


async def test_enrichment_replaces_search_page_values(tmp_path):
    calls: list[str] = []
    batch, report = await enrich_anibis_batch(
        _batch("https://x.test/fr/vi/1"),
        delay_seconds=0,
        cache_dir=tmp_path / "cache",
        fetch=_fetch_from(tmp_path, _html("apartment"), calls),
    )
    item = batch.listings[0]
    assert item.price_chf == Decimal("890000")
    assert item.rooms == Decimal("4.5") and item.living_area_m2 == Decimal("120")
    assert item.address_full == "Blaise-Cendrars 3"
    assert item.raw_data["price_status"] == "detail_page"
    assert item.raw_data["search_page_values"]["price_chf"] == "1052727"
    assert report.enriched == 1 and not report.warnings


async def test_enrichment_respects_cap_and_marks_rest_unverified(tmp_path):
    calls: list[str] = []
    batch, report = await enrich_anibis_batch(
        _batch("https://x.test/1", "https://x.test/2", "https://x.test/3"),
        max_details=1,
        delay_seconds=0,
        cache_dir=tmp_path / "cache",
        fetch=_fetch_from(tmp_path, _html("apartment"), calls),
    )
    assert len(calls) == 1
    assert [i.raw_data["price_status"] for i in batch.listings] == [
        "detail_page",
        "unverified_search_page",
        "unverified_search_page",
    ]
    assert report.skipped_over_cap == 2 and any("plafond" in w for w in report.warnings)


async def test_enrichment_stops_on_block(tmp_path):
    calls: list[str] = []

    async def blocked(*, url, **_):
        calls.append(url)
        raise ScraperHTTPError(source="anibis_detail", status_code=403, url=url)

    batch, report = await enrich_anibis_batch(
        _batch("https://x.test/1", "https://x.test/2"),
        delay_seconds=0,
        cache_dir=tmp_path / "cache",
        fetch=blocked,
    )
    assert len(calls) == 1  # arrêt après le premier blocage, pas d'insistance
    assert report.stopped_reason == "HTTP_403"
    assert all(i.raw_data["price_status"] == "unverified_search_page" for i in batch.listings)
    assert any("bloque" in w for w in report.warnings)


async def test_enrichment_reuses_cache(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    from immo_ne_collector.scrapers.http_fetcher import build_cache_filename

    url = "https://x.test/fr/vi/9"
    (cache / build_cache_filename(url)).write_text(_html("apartment"), encoding="utf-8")
    calls: list[str] = []
    _, report = await enrich_anibis_batch(
        _batch(url),
        delay_seconds=0,
        cache_dir=cache,
        fetch=_fetch_from(tmp_path, "", calls),
    )
    assert calls == [] and report.from_cache == 1 and report.enriched == 1
