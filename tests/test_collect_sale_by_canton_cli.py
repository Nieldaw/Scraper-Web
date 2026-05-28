from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

SCRIPT_PATH = Path("scripts/collect_sale_by_canton.py")
SPEC = importlib.util.spec_from_file_location("collect_sale_by_canton", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class _FakeSessionCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _summary(source: str) -> MODULE.SourceSummary:
    return MODULE.SourceSummary(
        source=source,
        url_kind="default",
        base_url="https://example.test/search",
        requested_pages=1,
        fetched_pages=1,
        loaded_from_cache_pages=0,
        parsed_pages=1,
        cache_files=[Path(f"{source}.html")],
        detected_total=2,
        kept_canton_count=2,
        excluded_canton_count=0,
        tx_sale=2,
        tx_rent=0,
        tx_unknown=0,
        collected_count=2,
        created_count=1,
        updated_count=0,
        unchanged_count=1,
        errors=[],
        notes=[],
        source_status="PASS",
        stopped_at_page=None,
        pagination_stopped_reason=None,
    )


def test_parser_accepts_new_options() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(
        [
            "--all-romandie",
            "--sources",
            "anibis,lookmove,homegate",
            "--max-pages",
            "2",
            "--delay-seconds",
            "1.5",
            "--use-cache",
            "--cache-max-age-hours",
            "12",
        ]
    )
    assert args.all_romandie is True
    assert args.canton is None
    assert args.sources == "anibis,lookmove,homegate"
    assert args.max_pages == 2
    assert args.delay_seconds == 1.5
    assert args.use_cache is True
    assert args.cache_max_age_hours == 12


def test_validate_args_rejects_max_pages_above_limit() -> None:
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


def test_validate_args_rejects_canton_and_all_romandie_together() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--canton", "NE", "--all-romandie"])
    try:
        MODULE._validate_args(args)
    except ValueError as exc:
        assert "Use either --canton or --all-romandie" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_run_rejects_unsupported_source() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--canton", "NE", "--sources", "anibis,unknown", "--no-export"])
    rc = asyncio.run(MODULE._run(args))
    assert rc == 2


def test_run_rejects_unknown_canton() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--canton", "XX", "--sources", "anibis", "--no-export"])
    rc = asyncio.run(MODULE._run(args))
    assert rc == 2


def test_run_accepts_anibis_and_lookmove(monkeypatch) -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(
        ["--canton", "NE", "--sources", "anibis,lookmove", "--max-pages", "2", "--no-export"]
    )

    calls: list[str] = []

    async def fake_run_canton(*, canton, sources, args):
        calls.extend(sources)
        return [_summary(item) for item in sources], []

    monkeypatch.setattr(MODULE, "_run_canton", fake_run_canton)

    rc = asyncio.run(MODULE._run(args))
    assert rc == 0
    assert calls == ["anibis", "lookmove"]


def test_run_accepts_homegate_source(monkeypatch) -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--canton", "NE", "--sources", "homegate", "--max-pages", "1", "--no-export"])

    calls: list[str] = []

    async def fake_run_canton(*, canton, sources, args):
        calls.extend(sources)
        return [_summary(item) for item in sources], []

    monkeypatch.setattr(MODULE, "_run_canton", fake_run_canton)

    rc = asyncio.run(MODULE._run(args))
    assert rc == 0
    assert calls == ["homegate"]


def test_list_config_mode_returns_zero() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--list-config"])
    rc = asyncio.run(MODULE._run(args))
    assert rc == 0


def test_list_config_shows_homegate_residential_and_land(capsys) -> None:
    MODULE._print_list_config(sources=["homegate"])
    out = capsys.readouterr().out
    assert "homegate" in out
    assert "residential" in out
    assert "land" in out


def test_run_all_romandie_loops_all_cantons(monkeypatch) -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--all-romandie", "--sources", "lookmove", "--no-export"])

    called_cantons: list[str] = []

    async def fake_run_canton(*, canton, sources, args):
        called_cantons.append(canton)
        return [_summary("lookmove")], []

    monkeypatch.setattr(MODULE, "_run_canton", fake_run_canton)

    rc = asyncio.run(MODULE._run(args))
    assert rc == 0
    assert called_cantons == ["GE", "VD", "NE", "JU", "FR", "VS"]


def test_run_handles_disabled_source_as_warning(monkeypatch) -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--canton", "VD", "--sources", "anibis", "--no-export"])

    async def fake_run_canton(*, canton, sources, args):
        return [
            MODULE.SourceSummary(
                source="anibis",
                url_kind="default",
                base_url="https://example.test/disabled",
                requested_pages=1,
                fetched_pages=0,
                loaded_from_cache_pages=0,
                parsed_pages=0,
                cache_files=[],
                detected_total=0,
                kept_canton_count=0,
                excluded_canton_count=0,
                tx_sale=0,
                tx_rent=0,
                tx_unknown=0,
                collected_count=0,
                created_count=0,
                updated_count=0,
                unchanged_count=0,
                errors=[],
                notes=["disabled"],
                source_status="WARNING",
                stopped_at_page=None,
                pagination_stopped_reason="SOURCE_DISABLED",
            )
        ], []

    monkeypatch.setattr(MODULE, "_run_canton", fake_run_canton)

    rc = asyncio.run(MODULE._run(args))
    assert rc == 0


def test_run_lookmove_first_page_403_is_warning_not_fail(monkeypatch) -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--canton", "NE", "--sources", "lookmove", "--no-export"])

    async def fake_collect_source(**kwargs):
        raise MODULE.ScraperHTTPError(source="lookmove", status_code=403, url=kwargs["base_url"])

    monkeypatch.setattr(MODULE, "_collect_source", fake_collect_source)

    rc = asyncio.run(MODULE._run(args))
    assert rc == 0


def test_generate_exports_by_canton_writes_by_canton_paths(monkeypatch, tmp_path: Path) -> None:
    called_output_dirs: list[Path] = []
    by_canton_filter_flags: list[bool] = []

    async def fake_export_all_csv(*, output_dir, session=None, property_filter=None, canton=None):
        called_output_dirs.append(output_dir)
        by_canton_filter_flags.append(property_filter is not None)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "master.csv").write_text("property_id\n", encoding="utf-8")
        return [SimpleNamespace(name="MASTER", path=output_dir / "master.csv", row_count=0)]

    async def fake_export_quality_report_csv(_session, output_path, *, property_filter=None):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("property_id,issue_code\n", encoding="utf-8")
        return SimpleNamespace(name="QUALITY_REPORT", path=output_path, row_count=0)

    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "AsyncSessionLocal", lambda: _FakeSessionCtx())
    monkeypatch.setattr(MODULE, "export_all_csv", fake_export_all_csv)
    monkeypatch.setattr(MODULE, "export_quality_report_csv", fake_export_quality_report_csv)

    global_exports, global_quality, by_canton_exports, by_canton_quality = asyncio.run(
        MODULE._generate_exports_by_canton(canton="NE")
    )

    assert global_exports[0].path == tmp_path / "data" / "exports" / "master.csv"
    assert global_quality.path == tmp_path / "data" / "exports" / "quality_report.csv"
    assert by_canton_exports[0].path == tmp_path / "data" / "exports" / "by_canton" / "NE" / "master.csv"
    assert by_canton_quality.path == (
        tmp_path / "data" / "exports" / "by_canton" / "NE" / "quality_report.csv"
    )
    assert called_output_dirs == [
        tmp_path / "data" / "exports",
        tmp_path / "data" / "exports" / "by_canton" / "NE",
    ]
    assert by_canton_filter_flags == [False, True]


def test_fetch_pages_for_source_lookmove_uses_cache_when_enabled(monkeypatch, tmp_path: Path) -> None:
    cache_file = tmp_path / "lookmove_cached.html"
    cache_file.write_text("<html></html>", encoding="utf-8")

    async def fake_fetch_html_to_cache(**kwargs):
        raise AssertionError("Should not fetch when cache is fresh")

    monkeypatch.setattr(MODULE, "_find_fresh_cache_for_url", lambda *a, **k: cache_file)
    monkeypatch.setattr(MODULE, "fetch_html_to_cache", fake_fetch_html_to_cache)

    cache_paths, fetched_pages, loaded_from_cache, notes, source_status, stopped_at_page, stopped_reason = asyncio.run(
        MODULE._fetch_pages_for_source(
            source="lookmove",
            base_url="https://example.test/listing",
            max_pages=1,
            timeout=None,
            retries=None,
            delay_seconds=0,
            use_cache=True,
            cache_max_age_hours=24,
        )
    )
    assert cache_paths == [cache_file]
    assert fetched_pages == 0
    assert loaded_from_cache == 1
    assert notes == []
    assert source_status == "PASS"
    assert stopped_at_page is None
    assert stopped_reason is None


def test_fetch_pages_for_source_lookmove_403_stops_with_warning(monkeypatch, tmp_path: Path) -> None:
    first = tmp_path / "p1.html"
    first.write_text(
        "<html><head><link rel='next' href='https://example.test/listing?page=2'/></head><body></body></html>",
        encoding="utf-8",
    )

    calls = {"count": 0}

    async def fake_fetch_html_to_cache(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return SimpleNamespace(status_code=200, size_bytes=first.stat().st_size, file_path=first)
        raise MODULE.ScraperHTTPError(source="lookmove", status_code=403, url=kwargs["url"])

    monkeypatch.setattr(MODULE, "_find_fresh_cache_for_url", lambda *a, **k: None)
    monkeypatch.setattr(MODULE, "fetch_html_to_cache", fake_fetch_html_to_cache)

    cache_paths, fetched_pages, loaded_from_cache, notes, source_status, stopped_at_page, stopped_reason = asyncio.run(
        MODULE._fetch_pages_for_source(
            source="lookmove",
            base_url="https://example.test/listing",
            max_pages=10,
            timeout=None,
            retries=None,
            delay_seconds=0,
            use_cache=False,
            cache_max_age_hours=24,
        )
    )
    assert cache_paths == [first]
    assert fetched_pages == 1
    assert loaded_from_cache == 0
    assert source_status == "WARNING"
    assert stopped_at_page == 2
    assert stopped_reason == "HTTP_403"
    assert any("use cache or retry later" in note for note in notes)


def test_fetch_pages_for_source_homegate_uses_cache_when_enabled(monkeypatch, tmp_path: Path) -> None:
    page1 = tmp_path / "homegate_p1.html"
    page1.write_text("<html></html>", encoding="utf-8")

    async def fake_fetch_html_to_cache(**kwargs):
        raise AssertionError("Should not fetch when cache is fresh")

    monkeypatch.setattr(MODULE, "_find_fresh_cache_for_url", lambda *a, **k: page1)
    monkeypatch.setattr(MODULE, "fetch_html_to_cache", fake_fetch_html_to_cache)

    cache_paths, fetched_pages, loaded_from_cache, notes, source_status, stopped_at_page, stopped_reason = asyncio.run(
        MODULE._fetch_pages_for_source(
            source="homegate",
            base_url="https://www.homegate.ch/acheter/maison/canton-neuchatel/liste-annonces",
            max_pages=1,
            timeout=None,
            retries=None,
            delay_seconds=0,
            use_cache=True,
            cache_max_age_hours=24,
        )
    )

    assert cache_paths == [page1]
    assert fetched_pages == 0
    assert loaded_from_cache == 1
    assert notes == []
    assert source_status == "PASS"
    assert stopped_at_page is None
    assert stopped_reason is None
