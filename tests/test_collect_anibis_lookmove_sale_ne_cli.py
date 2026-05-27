from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from immo_ne_collector.services.anibis_filters import FilterStats
from immo_ne_collector.services.persistence import PersistenceResult


SCRIPT_PATH = Path("scripts/collect_anibis_lookmove_sale_ne.py")
SPEC = importlib.util.spec_from_file_location("collect_anibis_lookmove_sale_ne", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _result(name: str) -> MODULE.SourceRunResult:
    return MODULE.SourceRunResult(
        name=name,
        cache_path=Path(f"{name}.html"),
        stats=FilterStats(
            detected_total=2,
            transaction_counts={"sale": 2, "rent": 0, "unknown": 0},
            kept_canton_count=2,
            excluded_canton_count=0,
            excluded_examples=[],
            filtered_count=2,
        ),
        persistence=PersistenceResult(
            daily_run_id="00000000-0000-0000-0000-000000000001",
            collected_count=2,
            created_count=2,
            updated_count=0,
            unchanged_count=0,
            errors=[],
        ),
    )


def test_validate_requires_anibis_cache_with_skip() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--skip-fetch-anibis"])
    try:
        MODULE._validate_args(args)
    except ValueError as exc:
        assert "--skip-fetch-anibis requires --anibis-cache-path" in str(exc)
    else:
        raise AssertionError("Expected validation error")


def test_parser_default_max_pages_is_one() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args([])
    assert args.max_pages == 1


def test_validate_max_pages_rejects_too_high() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--max-pages", "11"])
    try:
        MODULE._validate_args(args)
    except ValueError as exc:
        assert "--max-pages must be <= 10" in str(exc)
    else:
        raise AssertionError("Expected validation error")


def test_validate_requires_lookmove_cache_with_skip() -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(["--skip-fetch-lookmove"])
    try:
        MODULE._validate_args(args)
    except ValueError as exc:
        assert "--skip-fetch-lookmove requires --lookmove-cache-path" in str(exc)
    else:
        raise AssertionError("Expected validation error")


def test_resolve_lookmove_pages_without_clear_pagination_stays_single_page(
    monkeypatch,
    tmp_path: Path,
) -> None:
    html_file = tmp_path / "lookmove_page.html"
    html_file.write_text("<html><body><a href='/foo'>x</a></body></html>", encoding="utf-8")

    async def _run_test() -> MODULE.SourceFetchResult:
        return await MODULE._resolve_cache_files_for_source(
            name="lookmove",
            skip_fetch=False,
            cache_path=None,
            url="https://example.test/listing",
            source_name="lookmove_sale_ne",
            timeout=None,
            retries=None,
            max_pages=3,
        )

    async def fake_resolve_cache_file(**kwargs):
        return html_file

    monkeypatch.setattr(MODULE, "_resolve_cache_file", fake_resolve_cache_file)
    result = asyncio.run(_run_test())

    assert result.cache_paths == [html_file]
    assert result.pages_fetched == 1
    assert any("pagination non détectée" in note for note in result.notes)


def test_run_passes_max_listings_to_each_source(monkeypatch) -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(
        [
            "--skip-fetch-anibis",
            "--anibis-cache-path",
            "tests/fixtures/html/anibis_sample_listing_page.html",
            "--skip-fetch-lookmove",
            "--lookmove-cache-path",
            "tests/fixtures/html/lookmove_sample_listing_page.html",
            "--max-listings",
            "7",
            "--no-export",
        ]
    )

    resolve_calls: list[str] = []
    collect_calls: list[tuple[str, int | None]] = []

    async def fake_resolve_cache_file(**kwargs):
        resolve_calls.append(kwargs["source_name"])
        return Path(f"{kwargs['source_name']}.html")

    async def fake_collect_source(*, name, cache_path, max_listings):
        collect_calls.append((name, max_listings))
        return _result(name)

    async def fake_print_dedup_summary():
        return None

    monkeypatch.setattr(MODULE, "_resolve_cache_file", fake_resolve_cache_file)
    monkeypatch.setattr(MODULE, "_collect_source", fake_collect_source)
    monkeypatch.setattr(MODULE, "_print_dedup_summary", fake_print_dedup_summary)

    rc = asyncio.run(MODULE._run(args))
    assert rc == 0
    assert resolve_calls == []
    assert collect_calls == [("anibis", 7), ("lookmove", 7)]


def test_run_with_exports_calls_export_and_quality(monkeypatch, tmp_path: Path) -> None:
    parser = MODULE._build_parser()
    args = parser.parse_args(
        [
            "--skip-fetch-anibis",
            "--anibis-cache-path",
            "tests/fixtures/html/anibis_sample_listing_page.html",
            "--skip-fetch-lookmove",
            "--lookmove-cache-path",
            "tests/fixtures/html/lookmove_sample_listing_page.html",
        ]
    )

    async def fake_resolve_cache_file(**kwargs):
        return Path(f"{kwargs['source_name']}.html")

    async def fake_collect_source(*, name, cache_path, max_listings):
        return _result(name)

    async def fake_export_all_csv(*, output_dir):
        return [SimpleNamespace(name="MASTER", path=output_dir / "master.csv", row_count=1)]

    class _FakeSessionCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_export_quality_report_csv(_session, output_path):
        return SimpleNamespace(name="QUALITY_REPORT", path=output_path, row_count=1)

    async def fake_print_dedup_summary():
        return None

    monkeypatch.setattr(MODULE, "_resolve_cache_file", fake_resolve_cache_file)
    monkeypatch.setattr(MODULE, "_collect_source", fake_collect_source)
    monkeypatch.setattr(MODULE, "export_all_csv", fake_export_all_csv)
    monkeypatch.setattr(MODULE, "AsyncSessionLocal", lambda: _FakeSessionCtx())
    monkeypatch.setattr(MODULE, "export_quality_report_csv", fake_export_quality_report_csv)
    monkeypatch.setattr(MODULE, "_print_dedup_summary", fake_print_dedup_summary)
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)

    rc = asyncio.run(MODULE._run(args))
    assert rc == 0
