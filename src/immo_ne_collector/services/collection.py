from pydantic import BaseModel, ConfigDict, Field

from immo_ne_collector.scrapers.base import BaseScraper
from immo_ne_collector.services.normalization import NormalizedListing, normalize_raw_listing


class CollectionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    collected_count: int
    listings: list[NormalizedListing] = Field(default_factory=list)


async def collect_and_normalize(scraper: BaseScraper) -> CollectionBatch:
    raw_listings = await scraper.collect_safe()
    normalized_listings = [normalize_raw_listing(listing) for listing in raw_listings]
    return CollectionBatch(
        source=scraper.source,
        collected_count=len(normalized_listings),
        listings=normalized_listings,
    )
