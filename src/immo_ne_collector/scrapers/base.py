from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from immo_ne_collector.scrapers.safety import RateLimiter, SafetyConfig, run_with_safety


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RawListing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    source_listing_id: str | None = None
    url: str
    title: str | None = None
    property_type: str | None = None
    price_raw: str | None = None
    rooms_raw: str | None = None
    living_area_raw: str | None = None
    address_raw: str | None = None
    city_raw: str | None = None
    postal_code_raw: str | None = None
    description_raw: str | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime = Field(default_factory=_utcnow)

    @field_validator("source", "url")
    @classmethod
    def _must_not_be_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned


class BaseScraper(ABC):
    source: str

    def __init__(self, *, safety: SafetyConfig | None = None, rate_limiter: RateLimiter | None = None) -> None:
        if not getattr(self, "source", "").strip():
            raise ValueError("source must be defined on scraper class")
        self.safety = safety or SafetyConfig()
        self.rate_limiter = rate_limiter or RateLimiter(self.safety.min_interval_seconds)

    @property
    def is_enabled(self) -> bool:
        return self.safety.enabled

    @abstractmethod
    async def collect(self) -> list[RawListing]:
        """Collect raw listings from one source."""

    async def collect_safe(self) -> list[RawListing]:
        if not self.is_enabled:
            return []
        listings = await run_with_safety(
            source=self.source,
            operation=self.collect,
            config=self.safety,
            rate_limiter=self.rate_limiter,
        )
        return [self._normalize_source(listing) for listing in listings]

    def _normalize_source(self, listing: RawListing) -> RawListing:
        if listing.source == self.source:
            return listing
        return listing.model_copy(update={"source": self.source})
