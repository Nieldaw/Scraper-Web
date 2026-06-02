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


def test_build_homegate_page_urls_generates_expected_pages() -> None:
    urls = MODULE._build_homegate_page_urls(
        "https://www.homegate.ch/acheter/maison/canton-neuchatel/liste-annonces",
        3,
    )
    assert len(urls) == 3
    assert "ep=1" in urls[0]
    assert "ep=2" in urls[1]
    assert "ep=3" in urls[2]


def test_validate_args_rejects_max_pages_over_limit() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--canton", "NE", "--max-pages", "11"])
    try:
        MODULE._validate_args(args)
    except ValueError as exc:
        assert "--max-pages must be <= 10" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_validate_args_requires_canton_or_all_romandie() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args([])
    try:
        MODULE._validate_args(args)
    except ValueError as exc:
        assert "Either --canton or --all-romandie is required" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_validate_args_rejects_canton_and_all_romandie() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--canton", "NE", "--all-romandie"])
    try:
        MODULE._validate_args(args)
    except ValueError as exc:
        assert "Use either --canton or --all-romandie" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_resolve_cantons_all_romandie() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--all-romandie"])
    assert MODULE._resolve_cantons(args) == ["GE", "VD", "NE", "JU", "FR", "VS"]


def test_run_rejects_unknown_canton() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--canton", "XX", "--sources", "lookmove"])
    rc = asyncio.run(MODULE._run(args))
    assert rc == 2


def test_run_homegate_disabled_source_returns_warning_not_fail(monkeypatch, tmp_path: Path) -> None:
    parser = MODULE._build_parser()
    output_path = tmp_path / "audit_report.csv"
    args = parser.parse_args(
        ["--canton", "NE", "--sources", "homegate", "--max-pages", "1", "--output", str(output_path)]
    )

    async def fake_generate_exports(_canton):
        from types import SimpleNamespace

        return (
            [SimpleNamespace(name="MASTER", path=tmp_path / "master.csv", row_count=0)],
            SimpleNamespace(name="QUALITY_REPORT", path=tmp_path / "quality.csv", row_count=0),
            [SimpleNamespace(name="MASTER", path=tmp_path / "by_canton_master.csv", row_count=0)],
            SimpleNamespace(name="QUALITY_REPORT", path=tmp_path / "by_canton_quality.csv", row_count=0),
        )

    monkeypatch.setattr(MODULE, "_generate_exports", fake_generate_exports)
    monkeypatch.setattr(MODULE, "_validate_by_canton_exports", lambda _canton: ([], []))
    rc = asyncio.run(MODULE._run(args))
    assert rc == 0
    with output_path.open("r", encoding="utf-8", newline="") as file_obj:
        rows = list(csv.DictReader(file_obj))
    assert rows
    assert all(row["source_status"] == "WARNING" for row in rows)
    assert all(row["pagination_stopped_reason"] == "HOMEGATE_DISABLED_ANTI_BOT_RISK" for row in rows)


def test_run_immoscout_disabled_source_returns_warning_not_fail(monkeypatch, tmp_path: Path) -> None:
    parser = MODULE._build_parser()
    output_path = tmp_path / "audit_report.csv"
    args = parser.parse_args(
        ["--canton", "NE", "--sources", "immoscout", "--max-pages", "1", "--output", str(output_path)]
    )

    async def fake_generate_exports(_canton):
        from types import SimpleNamespace

        return (
            [SimpleNamespace(name="MASTER", path=tmp_path / "master.csv", row_count=0)],
            SimpleNamespace(name="QUALITY_REPORT", path=tmp_path / "quality.csv", row_count=0),
            [SimpleNamespace(name="MASTER", path=tmp_path / "by_canton_master.csv", row_count=0)],
            SimpleNamespace(name="QUALITY_REPORT", path=tmp_path / "by_canton_quality.csv", row_count=0),
        )

    monkeypatch.setattr(MODULE, "_generate_exports", fake_generate_exports)
    monkeypatch.setattr(MODULE, "_validate_by_canton_exports", lambda _canton: ([], []))
    rc = asyncio.run(MODULE._run(args))
    assert rc == 0
    with output_path.open("r", encoding="utf-8", newline="") as file_obj:
        rows = list(csv.DictReader(file_obj))
    assert rows
    assert all(row["source_status"] == "WARNING" for row in rows)
    assert all(row["pagination_stopped_reason"] == "IMMOSCOUT_DISABLED_VALIDATION_REQUIRED" for row in rows)


def test_immoscout_http_403_first_page_is_warning(monkeypatch) -> None:
    async def fake_fetch_or_reuse_page(**kwargs):
        raise MODULE.ScraperHTTPError(source="immoscout", status_code=403, url=kwargs["url"])

    monkeypatch.setattr(MODULE, "_fetch_or_reuse_page", fake_fetch_or_reuse_page)

    rows, warnings, source_status, stopped_at_page, stopped_reason, fetched_pages, loaded_from_cache = asyncio.run(
        MODULE._collect_source_audit_rows(
            source="immoscout",
            url_kind="residential",
            canton="NE",
            base_url="https://www.immoscout24.ch/fr/immobilier/acheter/canton-neuchatel",
            max_pages=1,
            max_listings=None,
            skip_fetch=False,
            use_cache=False,
            cache_max_age_hours=24,
            timeout=None,
            retries=None,
            delay_seconds=0,
        )
    )

    assert rows
    assert source_status == "WARNING"
    assert stopped_at_page == 1
    assert stopped_reason == "IMMOSCOUT_HTTP_403"
    assert fetched_pages == 0
    assert loaded_from_cache == 0
    assert any("ImmoScout pagination stopped at page 1" in warning for warning in warnings)


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
            url_kind="default",
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
        url_kind="default",
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
    assert rows[0]["url_kind"] == "default"
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
            url_kind="default",
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


def test_homegate_http_403_after_success_stops_with_warning(monkeypatch, tmp_path: Path) -> None:
    page1 = tmp_path / "homegate_p1.html"
    page1.write_text("<html><body></body></html>", encoding="utf-8")

    calls = {"count": 0}

    async def fake_fetch_or_reuse_page(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return ("200", page1.stat().st_size, page1, page1.read_text(encoding="utf-8"), [])
        raise MODULE.ScraperHTTPError(source="homegate", status_code=403, url=kwargs["url"])

    async def fake_collect_and_normalize(_scraper):
        return CollectionBatch(
            source="homegate_cached",
            collected_count=1,
            listings=[
                _listing(
                    idx=1,
                    url="https://www.homegate.ch/acheter/maison/canton-neuchatel/listing-4000000001",
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
            source="homegate",
            url_kind="default",
            canton="NE",
            base_url="https://www.homegate.ch/acheter/maison/canton-neuchatel/liste-annonces",
            max_pages=3,
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
    assert stopped_reason == "HOMEGATE_HTTP_403"
    assert rows
    assert rows[-1].warning_count == 1
    assert rows[-1].error_count == 0
    assert fetched_pages == 1
    assert loaded_from_cache == 0
    assert any("pagination stopped at page 2" in w for w in [rows[-1].warnings, *warnings])
    assert any("anti-bot" in w.lower() for w in [rows[-1].warnings, *warnings])


def test_homegate_http_429_first_page_is_warning(monkeypatch) -> None:
    async def fake_fetch_or_reuse_page(**kwargs):
        raise MODULE.ScraperHTTPError(source="homegate", status_code=429, url=kwargs["url"])

    monkeypatch.setattr(MODULE, "_fetch_or_reuse_page", fake_fetch_or_reuse_page)

    rows, warnings, source_status, stopped_at_page, stopped_reason, fetched_pages, loaded_from_cache = asyncio.run(
        MODULE._collect_source_audit_rows(
            source="homegate",
            url_kind="residential",
            canton="NE",
            base_url="https://www.homegate.ch/acheter/biens-immobiliers/canton-neuchatel/liste-annonces",
            max_pages=1,
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
    assert stopped_at_page == 1
    assert stopped_reason == "HOMEGATE_HTTP_429"
    assert rows[0].pagination_stopped_reason == "HOMEGATE_HTTP_429"
    assert fetched_pages == 0
    assert loaded_from_cache == 0
    assert any("HTTP 429" in w for w in [rows[0].warnings, *warnings])


def test_homegate_timeout_first_page_is_warning(monkeypatch) -> None:
    async def fake_fetch_or_reuse_page(**kwargs):
        raise MODULE.ScraperTimeoutError("homegate timeout")

    monkeypatch.setattr(MODULE, "_fetch_or_reuse_page", fake_fetch_or_reuse_page)

    rows, warnings, source_status, stopped_at_page, stopped_reason, fetched_pages, loaded_from_cache = asyncio.run(
        MODULE._collect_source_audit_rows(
            source="homegate",
            url_kind="land",
            canton="NE",
            base_url="https://www.homegate.ch/acheter/terrain/canton-neuchatel/liste-annonces",
            max_pages=1,
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
    assert stopped_at_page == 1
    assert stopped_reason == "HOMEGATE_TIMEOUT"
    assert rows[0].pagination_stopped_reason == "HOMEGATE_TIMEOUT"
    assert fetched_pages == 0
    assert loaded_from_cache == 0
    assert any("TIMEOUT" in w for w in [rows[0].warnings, *warnings])


def test_homegate_challenge_html_detected_as_warning(monkeypatch, tmp_path: Path) -> None:
    challenge = tmp_path / "homegate_challenge.html"
    challenge.write_text(
        (
            "<html><head><title>Just a moment...</title></head>"
            "<body><div>Cloudflare</div><div>challenge-platform</div></body></html>"
        ),
        encoding="utf-8",
    )

    async def fake_fetch_or_reuse_page(**kwargs):
        return ("200", challenge.stat().st_size, challenge, challenge.read_text(encoding="utf-8"), [])

    monkeypatch.setattr(MODULE, "_fetch_or_reuse_page", fake_fetch_or_reuse_page)

    rows, warnings, source_status, stopped_at_page, stopped_reason, fetched_pages, loaded_from_cache = asyncio.run(
        MODULE._collect_source_audit_rows(
            source="homegate",
            url_kind="residential",
            canton="NE",
            base_url="https://www.homegate.ch/acheter/biens-immobiliers/canton-neuchatel/liste-annonces",
            max_pages=1,
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
    assert stopped_at_page == 1
    assert stopped_reason == "HOMEGATE_CHALLENGE_DETECTED"
    assert fetched_pages == 1
    assert loaded_from_cache == 0
    assert rows
    assert rows[0].page_parsed == "no"
    assert rows[0].warning_count > 0
    assert "challenge detected" in rows[0].warnings.lower()
    assert warnings == []


def test_homegate_empty_html_without_initial_state_gives_explicit_warning(monkeypatch, tmp_path: Path) -> None:
    empty_path = Path("tests/fixtures/html/homegate_empty_no_initial_state.html")
    html = empty_path.read_text(encoding="utf-8")

    async def fake_fetch_or_reuse_page(**kwargs):
        return ("200", len(html.encode("utf-8")), empty_path, html, [])

    monkeypatch.setattr(MODULE, "_fetch_or_reuse_page", fake_fetch_or_reuse_page)

    rows, warnings, source_status, stopped_at_page, stopped_reason, fetched_pages, loaded_from_cache = asyncio.run(
        MODULE._collect_source_audit_rows(
            source="homegate",
            url_kind="residential",
            canton="NE",
            base_url="https://www.homegate.ch/acheter/biens-immobiliers/canton-neuchatel/liste-annonces",
            max_pages=1,
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
    assert stopped_reason in {"HOMEGATE_NO_LISTINGS_FOUND", "HOMEGATE_INITIAL_STATE_MISSING"}
    assert rows
    assert rows[0].page_parsed == "no"
    assert rows[0].error_count == 0
    assert rows[0].warning_count > 0
    assert "parse warning" in rows[0].warnings.lower()
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


def test_fetch_or_reuse_page_stale_cache_refetches_with_warning(monkeypatch, tmp_path: Path) -> None:
    stale_file = tmp_path / "stale.html"
    stale_file.write_text("<html>stale</html>", encoding="utf-8")
    fetched_file = tmp_path / "fetched.html"
    fetched_file.write_text("<html>fresh</html>", encoding="utf-8")

    class _FetchResult:
        status_code = 200
        size_bytes = fetched_file.stat().st_size
        file_path = fetched_file

    async def fake_fetch_html_to_cache(**kwargs):
        return _FetchResult()

    monkeypatch.setattr(MODULE, "_find_fresh_cache_for_url", lambda *a, **k: None)
    monkeypatch.setattr(MODULE, "_find_latest_cache_for_url", lambda *a, **k: stale_file)
    monkeypatch.setattr(MODULE, "fetch_html_to_cache", fake_fetch_html_to_cache)

    status, size, path, html, warnings = asyncio.run(
        MODULE._fetch_or_reuse_page(
            source="anibis",
            url="https://example.test/listing",
            skip_fetch=False,
            use_cache=True,
            cache_max_age_hours=24,
            safety=MODULE._build_fetch_safety(None, None),
            cache_dir=tmp_path,
        )
    )
    assert status == "200"
    assert size == fetched_file.stat().st_size
    assert path == fetched_file
    assert "fresh" in html
    assert any("stale cache" in warning for warning in warnings)


def test_lookmove_http_403_on_first_page_is_warning(monkeypatch) -> None:
    async def fake_fetch_or_reuse_page(**kwargs):
        raise MODULE.ScraperHTTPError(source="lookmove", status_code=403, url=kwargs["url"])

    monkeypatch.setattr(MODULE, "_fetch_or_reuse_page", fake_fetch_or_reuse_page)

    rows, warnings, source_status, stopped_at_page, stopped_reason, fetched_pages, loaded_from_cache = asyncio.run(
        MODULE._collect_source_audit_rows(
            source="lookmove",
            url_kind="default",
            canton="NE",
            base_url="https://www.lookmove.ch/fr/immobilier/acheter/appartements-maisons%2C3/neuchatel-ne%2C100013",
            max_pages=3,
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
    assert stopped_at_page == 1
    assert stopped_reason == "HTTP_403"
    assert rows
    assert rows[0].warning_count == 1
    assert rows[0].error_count == 0
    assert fetched_pages == 0
    assert loaded_from_cache == 0
    assert any("Use cache or retry later" in warning for warning in warnings)


def test_anibis_timeout_after_success_stops_with_warning(monkeypatch, tmp_path: Path) -> None:
    page1 = tmp_path / "anibis_p1.html"
    page1.write_text("<html><body></body></html>", encoding="utf-8")

    calls = {"count": 0}

    async def fake_fetch_or_reuse_page(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return ("200", page1.stat().st_size, page1, page1.read_text(encoding="utf-8"), [])
        raise MODULE.ScraperTimeoutError("anibis: timeout")

    async def fake_collect_and_normalize(_scraper):
        return CollectionBatch(
            source="anibis_cached",
            collected_count=1,
            listings=[
                _listing(
                    idx=1,
                    url="https://www.anibis.ch/fr/vi/neuchatel/immobilier/appartements/test/1",
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
            source="anibis",
            url_kind="default",
            canton="NE",
            base_url="https://www.anibis.ch/fr/q/test?page=1",
            max_pages=3,
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
    assert stopped_reason == "TIMEOUT"
    assert rows
    assert rows[-1].warning_count == 1
    assert rows[-1].error_count == 0
    assert fetched_pages == 1
    assert loaded_from_cache == 0
    assert any("pagination stopped at page 2: TIMEOUT" in w for w in [rows[-1].warnings, *warnings])


def test_validate_by_canton_exports_fails_on_out_of_canton_urls(monkeypatch, tmp_path: Path) -> None:
    export_dir = tmp_path / "data" / "exports" / "by_canton" / "GE"
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "master.csv").write_text("property_id\n1\n", encoding="utf-8")
    (export_dir / "quality_report.csv").write_text("property_id,issue_code\n", encoding="utf-8")
    (export_dir / "ventes.csv").write_text(
        "property_id,transaction_type,city,postal_code,source_urls\n"
        "p1,sale,Geneve,1201,\"[\"\"https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans-neuchatel/1\"\"]\"\n",
        encoding="utf-8",
    )
    (export_dir / "deduplication_report.csv").write_text(
        "property_id,detected_cantons\n"
        "p1,\"[\"\"GE\"\",\"\"NE\"\"]\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)

    warnings, failures = MODULE._validate_by_canton_exports("GE")
    assert warnings == []
    joined = " | ".join(failures)
    assert "out-of-canton" in joined
    assert "incompatible detected_cantons" in joined


def test_global_status_fail_when_hard_failures_present() -> None:
    status = MODULE._global_status(
        rows=[],
        extra_warnings=[],
        source_statuses=["WARNING"],
        hard_failures=["strict by-canton failure"],
    )
    assert status == "FAIL"
