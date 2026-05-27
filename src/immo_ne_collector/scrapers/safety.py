import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class SourceDisabledError(RuntimeError):
    pass


class ScraperHTTPError(RuntimeError):
    def __init__(self, *, source: str, status_code: int, url: str | None = None) -> None:
        self.source = source
        self.status_code = status_code
        self.url = url
        super().__init__(f"{source}: HTTP {status_code}" + (f" ({url})" if url else ""))


class ScraperTimeoutError(RuntimeError):
    pass


@dataclass(frozen=True)
class SafetyConfig:
    enabled: bool = True
    timeout_seconds: float = 10.0
    max_retries: int = 2
    min_interval_seconds: float = 0.0
    retry_backoff_seconds: float = 0.2

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be >= 0")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be >= 0")


class RateLimiter:
    def __init__(self, min_interval_seconds: float = 0.0) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be >= 0")
        self.min_interval_seconds = min_interval_seconds
        self._last_call_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if self.min_interval_seconds == 0:
            return
        async with self._lock:
            now = monotonic()
            sleep_for = self.min_interval_seconds - (now - self._last_call_at)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
                now = monotonic()
            self._last_call_at = now


def ensure_source_enabled(*, source: str, enabled: bool) -> None:
    if not enabled:
        raise SourceDisabledError(f"Source '{source}' is disabled")


def raise_for_status(*, source: str, status_code: int, url: str | None = None) -> None:
    if status_code >= 400:
        raise ScraperHTTPError(source=source, status_code=status_code, url=url)


def _is_retryable_http_error(exc: ScraperHTTPError) -> bool:
    return exc.status_code == 429


async def run_with_safety(
    *,
    source: str,
    operation: Callable[[], Awaitable[T]],
    config: SafetyConfig,
    rate_limiter: RateLimiter | None = None,
) -> T:
    ensure_source_enabled(source=source, enabled=config.enabled)
    if rate_limiter is not None:
        await rate_limiter.wait()

    for attempt in range(config.max_retries + 1):
        try:
            return await asyncio.wait_for(operation(), timeout=config.timeout_seconds)
        except ScraperHTTPError as exc:
            if not _is_retryable_http_error(exc) or attempt >= config.max_retries:
                raise
        except TimeoutError as exc:
            if attempt >= config.max_retries:
                raise ScraperTimeoutError(f"{source}: timeout after {attempt + 1} attempts") from exc

        if config.retry_backoff_seconds > 0:
            await asyncio.sleep(config.retry_backoff_seconds)

    raise RuntimeError("unreachable")
