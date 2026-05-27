from __future__ import annotations

import asyncio
import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from immo_ne_collector.services.anibis_filters import FilterStats
from immo_ne_collector.services.collection import CollectionBatch
from immo_ne_collector.services.normalization import NormalizedListing


SCRIPT_PATH = Path("scripts/collect_anibis_sale_ne.py")
SPEC = importlib.util.spec_from_file_location("collect_anibis_sale_ne", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class _FakeSessionCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _listing(idx: int) -> NormalizedListing:
    return NormalizedListing(
        source="anibis_cached",
        source_listing_id=f"id-{idx}",
        url=f"https://www.anibis.ch/fr/vi/neuchatel/immobilier/appartements/test/{idx}",
        title=f"Listing {idx}",
        property_type="appartement",
        price_chf=Decimal("1000000"),
        rooms=Decimal("4.5"),
        living_area_m2=Decimal("100"),
        address_full="Rue test 1",
        city="Neuchatel",
        postal_code="2000",
        description="desc",
        raw_data={"transaction_type": "sale"},
        fetched_at=datetime.now(UTC),
        missing_fields=[],
    )


def test_validate_args_skip_fetch_requires_cache_path() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--skip-fetch"])

    try:
        MODULE._validate_args(args)
    except ValueError as exc:
        assert "--skip-fetch requires --cache-path" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing --cache-path")


def test_parser_has_default_url() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args([])
    assert args.url == MODULE.DEFAULT_ANIBIS_NE_SALE_URL


def test_parser_default_max_pages_is_one() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args([])
    assert args.max_pages == 1


def test_validate_args_max_pages_rejects_too_high() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--max-pages", "11"])
    try:
        MODULE._validate_args(args)
    except ValueError as exc:
        assert "--max-pages must be <= 10" in str(exc)
    else:
        raise AssertionError("Expected ValueError for max-pages > 10")


def test_build_anibis_page_urls_generates_page_1_and_2() -> None:
    urls = MODULE._build_anibis_page_urls(
        "https://www.anibis.ch/fr/q/test?sorting=newest&page=1",
        2,
    )
    assert len(urls) == 2
    assert "page=1" in urls[0]
    assert "page=2" in urls[1]


def test_fetch_pages_fetch_called_when_not_skip(monkeypatch) -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["https://example.test/listing"])

    captured_urls: list[str] = []

    async def fake_fetch_html_to_cache(**kwargs):
        captured_urls.append(kwargs["url"])
        return SimpleNamespace(status_code=200, size_bytes=123, file_path=Path("dummy.html"))

    monkeypatch.setattr(MODULE, "fetch_html_to_cache", fake_fetch_html_to_cache)

    cache_paths, fetched_pages = asyncio.run(MODULE._fetch_pages(args))

    assert captured_urls == ["https://example.test/listing?page=1"]
    assert cache_paths == [Path("dummy.html")]
    assert fetched_pages == 1


def test_run_passes_max_listings_to_filter(monkeypatch) -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(
        [
            "--skip-fetch",
            "--cache-path",
            "tests/fixtures/html/anibis_sample_listing_page.html",
            "--max-listings",
            "5",
            "--no-export",
        ]
    )

    captured: dict[str, int] = {}

    async def fake_fetch_pages(_args):
        return [Path("tests/fixtures/html/anibis_sample_listing_page.html")], 0

    async def fake_collect_and_normalize(_scraper):
        listings = [_listing(1), _listing(2)]
        return CollectionBatch(source="anibis_cached", collected_count=2, listings=listings)

    def fake_filter_collection_batch(batch, *, max_listings, transaction_type, canton):
        captured["max_listings"] = max_listings
        return (
            batch,
            FilterStats(
                detected_total=2,
                transaction_counts={"sale": 2, "rent": 0, "unknown": 0},
                kept_canton_count=2,
                excluded_canton_count=0,
                excluded_examples=[],
                filtered_count=2,
            ),
        )

    async def fake_persist_collection_batch(_batch):
        return SimpleNamespace(
            collected_count=2,
            created_count=2,
            updated_count=0,
            unchanged_count=0,
            errors=[],
        )

    monkeypatch.setattr(MODULE, "_fetch_pages", fake_fetch_pages)
    monkeypatch.setattr(MODULE, "collect_and_normalize", fake_collect_and_normalize)
    monkeypatch.setattr(MODULE, "filter_collection_batch", fake_filter_collection_batch)
    monkeypatch.setattr(MODULE, "persist_collection_batch", fake_persist_collection_batch)

    rc = asyncio.run(MODULE._run(args))

    assert rc == 0
    assert captured["max_listings"] == 5


def test_run_with_exports_uses_quality_report(monkeypatch, tmp_path: Path) -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(
        [
            "--skip-fetch",
            "--cache-path",
            "tests/fixtures/html/anibis_sample_listing_page.html",
        ]
    )

    async def fake_fetch_pages(_args):
        return [Path("tests/fixtures/html/anibis_sample_listing_page.html")], 0

    async def fake_collect_and_normalize(_scraper):
        listings = [_listing(1)]
        return CollectionBatch(source="anibis_cached", collected_count=1, listings=listings)

    def fake_filter_collection_batch(batch, *, max_listings, transaction_type, canton):
        return (
            batch,
            FilterStats(
                detected_total=1,
                transaction_counts={"sale": 1, "rent": 0, "unknown": 0},
                kept_canton_count=1,
                excluded_canton_count=0,
                excluded_examples=[],
                filtered_count=1,
            ),
        )

    async def fake_persist_collection_batch(_batch):
        return SimpleNamespace(
            collected_count=1,
            created_count=1,
            updated_count=0,
            unchanged_count=0,
            errors=[],
        )

    async def fake_export_all_csv(*, output_dir):
        return [SimpleNamespace(name="MASTER", path=output_dir / "master.csv", row_count=1)]

    async def fake_export_quality_report_csv(_session, output_path):
        return SimpleNamespace(name="QUALITY_REPORT", path=output_path, row_count=1)

    monkeypatch.setattr(MODULE, "_fetch_pages", fake_fetch_pages)
    monkeypatch.setattr(MODULE, "collect_and_normalize", fake_collect_and_normalize)
    monkeypatch.setattr(MODULE, "filter_collection_batch", fake_filter_collection_batch)
    monkeypatch.setattr(MODULE, "persist_collection_batch", fake_persist_collection_batch)
    monkeypatch.setattr(MODULE, "export_all_csv", fake_export_all_csv)
    monkeypatch.setattr(MODULE, "export_quality_report_csv", fake_export_quality_report_csv)
    monkeypatch.setattr(MODULE, "AsyncSessionLocal", lambda: _FakeSessionCtx())
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)

    rc = asyncio.run(MODULE._run(args))
    assert rc == 0
