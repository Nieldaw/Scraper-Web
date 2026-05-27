from __future__ import annotations

import asyncio
import csv
import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from immo_ne_collector.services.collection import CollectionBatch
from immo_ne_collector.services.normalization import NormalizedListing

SCRIPT_PATH = Path("scripts/audit_sale_collection.py")
SPEC = importlib.util.spec_from_file_location("audit_sale_collection", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _listing(
    *,
    idx: int,
    url: str,
    city: str | None,
    postal_code: str | None,
    transaction_type: str = "sale",
    price_chf: Decimal | None = Decimal("750000"),
    rooms: Decimal | None = Decimal("4.5"),
) -> NormalizedListing:
    return NormalizedListing(
        source="test_source",
        source_listing_id=f"id-{idx}",
        url=url,
        title=f"Listing {idx}",
        property_type="appartement",
        price_chf=price_chf,
        rooms=rooms,
        living_area_m2=Decimal("100"),
        address_full=None,
        city=city,
        postal_code=postal_code,
        description="desc",
        raw_data={"transaction_type": transaction_type},
        fetched_at=datetime.now(UTC),
        missing_fields=[],
    )


def test_build_anibis_page_urls_generates_expected_pages() -> None:
    urls = MODULE._build_anibis_page_urls(
        "https://www.anibis.ch/fr/q/test?sorting=newest&page=1",
        3,
    )
    assert len(urls) == 3
    assert "page=1" in urls[0]
    assert "page=2" in urls[1]
    assert "page=3" in urls[2]


def test_validate_args_rejects_max_pages_over_limit() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--canton", "NE", "--max-pages", "11"])
    try:
        MODULE._validate_args(args)
    except ValueError as exc:
        assert "--max-pages must be <= 10" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_lookmove_without_clear_pagination_stops_after_page_one(monkeypatch, tmp_path: Path) -> None:
    cache_file = tmp_path / "lookmove_cache.html"
    cache_file.write_text("<html><body><a href='/foo'>x</a></body></html>", encoding="utf-8")

    async def fake_fetch_or_reuse_page(**kwargs):
        return ("CACHED", cache_file.stat().st_size, cache_file, cache_file.read_text(encoding="utf-8"), [])

    async def fake_collect_and_normalize(_scraper):
        batch = CollectionBatch(
            source="lookmove_cached",
            collected_count=1,
            listings=[_listing(idx=1, url="https://www.lookmove.ch/fr/annonce/acheter/neuchatel/1", city="Neuchatel", postal_code="2000")],
        )
        return batch

    def fake_filter_collection_batch(batch, *, max_listings, transaction_type, canton):
        stats = MODULE.Counter()  # not used in assertions
        from immo_ne_collector.services.anibis_filters import FilterStats

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
        class _R:
            collected_count = 1
            created_count = 1
            updated_count = 0
            unchanged_count = 0
            errors: list[str] = []

        return _R()

    monkeypatch.setattr(MODULE, "_fetch_or_reuse_page", fake_fetch_or_reuse_page)
    monkeypatch.setattr(MODULE, "collect_and_normalize", fake_collect_and_normalize)
    monkeypatch.setattr(MODULE, "filter_collection_batch", fake_filter_collection_batch)
    monkeypatch.setattr(MODULE, "persist_collection_batch", fake_persist_collection_batch)

    rows, warnings, source_status, stopped_at_page, stopped_reason, fetched_pages, loaded_from_cache = asyncio.run(
        MODULE._collect_source_audit_rows(
            source="lookmove",
            canton="NE",
            base_url="https://www.lookmove.ch/fr/immobilier/acheter/appartements-maisons%2C3/neuchatel-ne%2C100013",
            max_pages=3,
            max_listings=None,
            skip_fetch=True,
            use_cache=False,
            cache_max_age_hours=24,
            timeout=None,
            retries=None,
            delay_seconds=0,
        )
    )

    assert len(rows) == 1
    assert any("pagination not detected" in warning for warning in warnings)
    assert source_status == "WARNING"
    assert stopped_at_page == 2
    assert stopped_reason == "PAGINATION_NOT_DETECTED"
    assert fetched_pages == 0
    assert loaded_from_cache == 1


def test_detect_listing_warnings_finds_out_of_canton_and_suspect_npa_price() -> None:
    detected = CollectionBatch(
        source="test",
        collected_count=2,
        listings=[
            _listing(
                idx=1,
                url="https://www.example.test/fr/annonce/acheter/appartement/berne/1",
                city="Berne",
                postal_code="3000",
                price_chf=Decimal("2000"),
            ),
            _listing(
                idx=2,
                url="https://www.example.test/fr/annonce/acheter/appartement/neuchatel/2",
                city="Neuchatel",
                postal_code="2000",
                rooms=Decimal("30"),
            ),
        ],
    )
    filtered = detected
    warnings, _ = MODULE._detect_listing_warnings(
        source="anibis",
        canton="NE",
        detected_batch=detected,
        filtered_batch=filtered,
        previous_page_ids=set(),
    )
    joined = " | ".join(warnings).lower()
    assert "suspicious price" in joined
    assert "suspicious rooms value" in joined
    assert "out-of-canton listing" in joined


def test_audit_report_csv_is_generated(tmp_path: Path) -> None:
    row = MODULE.AuditPageRow(
        source="anibis",
        canton="NE",
        page_requested=1,
        page_parsed="yes",
        url_called="https://example.test?page=1",
        http_status="200",
        html_size_bytes=1234,
        cache_path="/tmp/cache.html",
        detected_total=5,
        detected_sale=4,
        detected_rent=1,
        detected_unknown=0,
        kept_canton_count=4,
        excluded_canton_count=1,
        collected_count=4,
        created_count=3,
        updated_count=1,
        unchanged_count=0,
        error_count=0,
        warning_count=1,
        warnings="warn",
        errors="",
        source_status="WARNING",
        stopped_at_page=5,
        pagination_stopped_reason="HTTP_403",
    )
    output = tmp_path / "audit_report.csv"
    MODULE._write_audit_report(output, [row])

    assert output.exists()
    with output.open("r", encoding="utf-8", newline="") as file_obj:
        rows = list(csv.DictReader(file_obj))
    assert len(rows) == 1
    assert rows[0]["source"] == "anibis"
    assert rows[0]["source_status"] == "WARNING"
    assert rows[0]["stopped_at_page"] == "5"
    assert rows[0]["pagination_stopped_reason"] == "HTTP_403"


def test_lookmove_http_403_after_success_stops_with_warning(monkeypatch, tmp_path: Path) -> None:
    page1 = tmp_path / "lookmove_p1.html"
    page1.write_text(
        "<html><head><link rel='next' href='https://example.test/listings?page=2'/></head><body></body></html>",
        encoding="utf-8",
    )

    calls = {"count": 0}

    async def fake_fetch_or_reuse_page(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return ("200", page1.stat().st_size, page1, page1.read_text(encoding="utf-8"), [])
        raise MODULE.ScraperHTTPError(source="lookmove", status_code=403, url=kwargs["url"])

    async def fake_collect_and_normalize(_scraper):
        return CollectionBatch(
            source="lookmove_cached",
            collected_count=1,
            listings=[
                _listing(
                    idx=1,
                    url="https://www.lookmove.ch/fr/annonce/acheter/neuchatel/1",
                    city="Neuchatel",
                    postal_code="2000",
                )
            ],
        )

    def fake_filter_collection_batch(batch, *, max_listings, transaction_type, canton):
        from immo_ne_collector.services.anibis_filters import FilterStats

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
        class _R:
            collected_count = 1
            created_count = 1
            updated_count = 0
            unchanged_count = 0
            errors: list[str] = []

        return _R()

    monkeypatch.setattr(MODULE, "_fetch_or_reuse_page", fake_fetch_or_reuse_page)
    monkeypatch.setattr(MODULE, "collect_and_normalize", fake_collect_and_normalize)
    monkeypatch.setattr(MODULE, "filter_collection_batch", fake_filter_collection_batch)
    monkeypatch.setattr(MODULE, "persist_collection_batch", fake_persist_collection_batch)

    rows, warnings, source_status, stopped_at_page, stopped_reason, fetched_pages, loaded_from_cache = asyncio.run(
        MODULE._collect_source_audit_rows(
            source="lookmove",
            canton="NE",
            base_url="https://www.lookmove.ch/fr/immobilier/acheter/appartements-maisons%2C3/neuchatel-ne%2C100013",
            max_pages=10,
            max_listings=None,
            skip_fetch=False,
            use_cache=False,
            cache_max_age_hours=24,
            timeout=None,
            retries=None,
            delay_seconds=0,
        )
    )

    assert source_status == "WARNING"
    assert stopped_at_page == 2
    assert stopped_reason == "HTTP_403"
    assert any("HTTP 403" in warning for warning in warnings)
    assert rows
    assert rows[-1].pagination_stopped_reason == "HTTP_403"
    assert fetched_pages == 1
    assert loaded_from_cache == 0


def test_fetch_or_reuse_page_use_cache_skips_fetch(monkeypatch, tmp_path: Path) -> None:
    cache_file = tmp_path / "cached.html"
    cache_file.write_text("<html>cached</html>", encoding="utf-8")

    async def fake_fetch_html_to_cache(**kwargs):
        raise AssertionError("fetch should not be called when fresh cache is available")

    monkeypatch.setattr(MODULE, "_find_fresh_cache_for_url", lambda *a, **k: cache_file)
    monkeypatch.setattr(MODULE, "fetch_html_to_cache", fake_fetch_html_to_cache)

    status, size, path, html, warnings = asyncio.run(
        MODULE._fetch_or_reuse_page(
            source="lookmove",
            url="https://example.test/listing",
            skip_fetch=False,
            use_cache=True,
            cache_max_age_hours=24,
            safety=MODULE._build_fetch_safety(None, None),
            cache_dir=tmp_path,
        )
    )
    assert status == "CACHED"
    assert size == cache_file.stat().st_size
    assert path == cache_file
    assert "cached" in html
    assert warnings == []
