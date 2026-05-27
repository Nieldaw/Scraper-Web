import asyncio
from time import monotonic

import pytest

from immo_ne_collector.scrapers.safety import (
    RateLimiter,
    SafetyConfig,
    ScraperHTTPError,
    ScraperTimeoutError,
    SourceDisabledError,
    run_with_safety,
)


@pytest.mark.asyncio
async def test_run_with_safety_raises_when_source_disabled() -> None:
    async def operation() -> str:
        return "ok"

    with pytest.raises(SourceDisabledError):
        await run_with_safety(
            source="mock",
            operation=operation,
            config=SafetyConfig(enabled=False),
        )


@pytest.mark.asyncio
async def test_run_with_safety_retries_on_429() -> None:
    attempts = {"count": 0}

    async def operation() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ScraperHTTPError(source="mock", status_code=429, url="https://mock.local")
        return "ok"

    result = await run_with_safety(
        source="mock",
        operation=operation,
        config=SafetyConfig(max_retries=2, retry_backoff_seconds=0),
    )
    assert result == "ok"
    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_run_with_safety_does_not_retry_on_403() -> None:
    attempts = {"count": 0}

    async def operation() -> str:
        attempts["count"] += 1
        raise ScraperHTTPError(source="mock", status_code=403, url="https://mock.local")

    with pytest.raises(ScraperHTTPError):
        await run_with_safety(
            source="mock",
            operation=operation,
            config=SafetyConfig(max_retries=3, retry_backoff_seconds=0),
        )
    assert attempts["count"] == 1


@pytest.mark.asyncio
async def test_run_with_safety_timeout_raises_after_retries() -> None:
    async def operation() -> str:
        await asyncio.sleep(0.02)
        return "too-late"

    with pytest.raises(ScraperTimeoutError):
        await run_with_safety(
            source="mock",
            operation=operation,
            config=SafetyConfig(timeout_seconds=0.005, max_retries=1, retry_backoff_seconds=0),
        )


@pytest.mark.asyncio
async def test_rate_limiter_waits_between_calls() -> None:
    limiter = RateLimiter(min_interval_seconds=0.02)
    await limiter.wait()
    start = monotonic()
    await limiter.wait()
    elapsed = monotonic() - start
    assert elapsed >= 0.018
