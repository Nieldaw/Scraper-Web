import pytest

from immo_ne_collector.scrapers.base import BaseScraper, RawListing
from immo_ne_collector.scrapers.mock import MockScraper
from immo_ne_collector.scrapers.safety import SafetyConfig


def test_base_scraper_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseScraper()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_mock_scraper_collect_returns_listings() -> None:
    scraper = MockScraper()
    listings = await scraper.collect()
    assert len(listings) == 3
    assert all(isinstance(item, RawListing) for item in listings)
    assert all(item.source == "mock" for item in listings)


@pytest.mark.asyncio
async def test_collect_safe_returns_empty_when_source_disabled() -> None:
    scraper = MockScraper(safety=SafetyConfig(enabled=False))
    listings = await scraper.collect_safe()
    assert listings == []


class _MismatchSourceScraper(BaseScraper):
    source = "expected-source"

    async def collect(self) -> list[RawListing]:
        return [RawListing(source="wrong-source", url="https://mock.local/wrong")]


@pytest.mark.asyncio
async def test_collect_safe_normalizes_listing_source() -> None:
    scraper = _MismatchSourceScraper()
    listings = await scraper.collect_safe()
    assert len(listings) == 1
    assert listings[0].source == "expected-source"
