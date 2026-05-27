import pytest

from immo_ne_collector.scrapers.base import BaseScraper, RawListing
from immo_ne_collector.scrapers.mock import MockScraper
from immo_ne_collector.services.collection import collect_and_normalize


@pytest.mark.asyncio
async def test_mock_pipeline_collects_and_normalizes() -> None:
    batch = await collect_and_normalize(MockScraper())

    assert batch.source == "mock"
    assert batch.collected_count == 3
    assert len(batch.listings) == 3

    first = batch.listings[0]
    assert str(first.price_chf) == "850000"
    assert str(first.rooms) == "4.5"
    assert str(first.living_area_m2) == "110"
    assert first.city == "Neuchatel"
    assert first.postal_code == "2000"
    assert first.address_full == "Rue du Seyon 12"


class _MissingFieldScraper(BaseScraper):
    source = "missing-demo"

    async def collect(self) -> list[RawListing]:
        return [
            RawListing(
                source=self.source,
                source_listing_id="x-1",
                url="https://mock.local/missing",
                title=None,
                property_type="appartement",
                price_raw=None,
                city_raw=None,
                address_raw=None,
            )
        ]


@pytest.mark.asyncio
async def test_pipeline_handles_missing_fields() -> None:
    batch = await collect_and_normalize(_MissingFieldScraper())

    assert batch.collected_count == 1
    listing = batch.listings[0]
    assert listing.price_chf is None
    assert listing.city is None
    assert "price_chf" in listing.missing_fields
    assert "city" in listing.missing_fields
