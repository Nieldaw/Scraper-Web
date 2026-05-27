from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from immo_ne_collector.scrapers.http_fetcher import (
    ScraperHTTPError,
    build_cache_filename,
    fetch_html_to_cache,
)
from immo_ne_collector.scrapers.safety import SafetyConfig


def test_build_cache_filename_is_stable_and_html() -> None:
    name = build_cache_filename(
        "https://www.anibis.ch/fr/immobilier?region=ne",
        fetched_at=datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC),
    )
    assert name.startswith("20260518T120000Z_")
    assert name.endswith(".html")
    assert "www_anibis_ch" in name


@pytest.mark.asyncio
async def test_fetch_html_to_cache_with_mocked_http_client(tmp_path: Path) -> None:
    async def fake_get(url: str) -> httpx.Response:
        return httpx.Response(200, text=f"<html><body>ok {url}</body></html>")

    result = await fetch_html_to_cache(
        url="https://www.anibis.ch/fr/immobilier/test",
        cache_dir=tmp_path,
        source="test_fetch",
        safety=SafetyConfig(timeout_seconds=5.0, max_retries=0, min_interval_seconds=0),
        http_get=fake_get,
    )
    assert result.status_code == 200
    assert result.file_path.exists()
    assert result.size_bytes > 0
    assert "ok https://www.anibis.ch/fr/immobilier/test" in result.file_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_fetch_html_to_cache_handles_403(tmp_path: Path) -> None:
    async def fake_get(_url: str) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    with pytest.raises(ScraperHTTPError):
        await fetch_html_to_cache(
            url="https://www.anibis.ch/fr/immobilier/forbidden",
            cache_dir=tmp_path,
            source="test_fetch_403",
            safety=SafetyConfig(timeout_seconds=5.0, max_retries=0, min_interval_seconds=0),
            http_get=fake_get,
        )
