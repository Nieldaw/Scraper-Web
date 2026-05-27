import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

import httpx

from immo_ne_collector.scrapers.safety import (
    RateLimiter,
    SafetyConfig,
    ScraperHTTPError,
    ScraperTimeoutError,
    run_with_safety,
)


@dataclass(frozen=True)
class CachedFetchResult:
    url: str
    status_code: int
    file_path: Path
    size_bytes: int


def build_cache_filename(url: str, *, fetched_at: datetime | None = None) -> str:
    parsed = urlparse(url)
    domain = (parsed.netloc or "unknown").replace(":", "_").replace(".", "_")
    path = parsed.path.strip("/") or "root"
    path_slug = "_".join(part for part in path.split("/") if part)[:80]
    query_suffix = ""
    if parsed.query:
        query_hash = hashlib.sha1(parsed.query.encode("utf-8")).hexdigest()[:8]
        query_suffix = f"_q{query_hash}"
    stamp = (fetched_at or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{domain}_{path_slug}{query_suffix}.html"


async def _default_http_get(url: str) -> httpx.Response:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        return await client.get(
            url,
            headers={
                "User-Agent": "ImmoNECollector/0.1 (+local-test)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )


async def fetch_html_to_cache(
    *,
    url: str,
    cache_dir: Path = Path("data/cache/html"),
    source: str = "http_fetcher",
    safety: SafetyConfig | None = None,
    rate_limiter: RateLimiter | None = None,
    http_get: Callable[[str], Awaitable[httpx.Response]] | None = None,
) -> CachedFetchResult:
    safe_cfg = safety or SafetyConfig(timeout_seconds=20.0, max_retries=1, min_interval_seconds=1.0)
    limiter = rate_limiter or RateLimiter(safe_cfg.min_interval_seconds)
    getter = http_get or _default_http_get

    async def operation() -> httpx.Response:
        try:
            response = await getter(url)
        except httpx.TimeoutException as exc:
            raise TimeoutError from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"{source}: network_error for {url}: {exc}") from exc
        if response.status_code in (403, 429) or response.status_code >= 400:
            raise ScraperHTTPError(source=source, status_code=response.status_code, url=url)
        return response

    response = await run_with_safety(
        source=source,
        operation=operation,
        config=safe_cfg,
        rate_limiter=limiter,
    )
    fetched_at = datetime.now(UTC)
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_path = cache_dir / build_cache_filename(url, fetched_at=fetched_at)
    content = response.text
    file_path.write_text(content, encoding="utf-8")
    size_bytes = file_path.stat().st_size
    return CachedFetchResult(
        url=url,
        status_code=response.status_code,
        file_path=file_path,
        size_bytes=size_bytes,
    )


__all__ = [
    "CachedFetchResult",
    "ScraperHTTPError",
    "ScraperTimeoutError",
    "build_cache_filename",
    "fetch_html_to_cache",
]
