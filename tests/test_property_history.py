from decimal import Decimal

from immo_ne_collector.services.property_history import diff_tracked_fields, extract_agency_name


def test_diff_detects_price_title_agency_only():
    changes = diff_tracked_fields(
        old_price=Decimal("500000.00"),
        new_price=Decimal("480000"),
        old_title="Villa",
        new_title="Villa  ",
        old_agency=None,
        new_agency="Régie du Lac",
    )
    assert changes == [("price", "500000", "480000"), ("agency", None, "Régie du Lac")]


def test_diff_no_change():
    assert not diff_tracked_fields(
        old_price=Decimal("1.0"), new_price=1, old_title="a", new_title="a",
        old_agency=None, new_agency=None,
    )


def test_agency_extraction():
    assert extract_agency_name({"agency_name": " Régie  X "}) == "Régie X"
    assert extract_agency_name({"advertiser": {"name": "Y SA"}}) == "Y SA"
    assert extract_agency_name({}) is None


import pytest
from datetime import UTC, datetime

from sqlalchemy import select

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import Property, PropertyHistory
from immo_ne_collector.scrapers.base import RawListing
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.persistence import persist_collection_batch
from immo_ne_collector.services.property_queries import PropertyFilters, search_properties


class _Fake:
    source = "anibis"

    def __init__(self, price, title, agency=None):
        self.price, self.title, self.agency = price, title, agency

    async def collect_safe(self):
        return [
            RawListing(
                source="anibis",
                source_listing_id="h1",
                url="https://www.anibis.ch/fr/d/h1",
                title=self.title,
                property_type="house",
                price_raw=self.price,
                city_raw="Neuchâtel",
                postal_code_raw="2000",
                address_raw="Rue du Lac 1, 2000 Neuchâtel",
                fetched_at=datetime.now(UTC),
                raw_data={"agency_name": self.agency} if self.agency else {},
            )
        ]


@pytest.mark.db
async def test_history_rows_written_on_price_title_agency_change():
    for price, title, agency in (
        ("CHF 600'000", "Maison", None),
        ("CHF 600'000", "Maison", None),
        ("CHF 580'000", "Maison rénovée", "Régie Lac"),
    ):
        batch = await collect_and_normalize(_Fake(price, title, agency))
        await persist_collection_batch(batch)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(PropertyHistory))).scalars().all()
        assert {r.field for r in rows} == {"price", "title", "agency"}
        price_row = next(r for r in rows if r.field == "price")
        assert (price_row.old_value, price_row.new_value) == ("600000", "580000")


@pytest.mark.db
async def test_unprocessed_filter():
    await persist_collection_batch(await collect_and_normalize(_Fake("CHF 600'000", "Maison")))
    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(Property))).scalars().one()
        assert row.is_processed is False
        rows, total = await search_properties(session, PropertyFilters(unprocessed=True))
        assert total == 1
        row.is_processed = True
        await session.commit()
        _, total = await search_properties(session, PropertyFilters(unprocessed=True))
        assert total == 0


@pytest.mark.db
async def test_detail_page_toggle_processed_and_timeline():
    from httpx import ASGITransport, AsyncClient

    from immo_ne_collector.main import app

    for price in ("CHF 600'000", "CHF 590'000"):
        await persist_collection_batch(await collect_and_normalize(_Fake(price, "Maison")))
    async with AsyncSessionLocal() as session:
        pid = (await session.execute(select(Property.id))).scalar_one()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        page = (await client.get(f"/properties/{pid}")).text
        assert "Marquer comme traité" in page and "600000" in page and "590000" in page
        resp = await client.post(f"/properties/{pid}/processed", data={"processed": "1"})
        assert resp.status_code == 303
        assert "✓ traité" in (await client.get(f"/properties/{pid}")).text
        html = (await client.get("/properties?unprocessed=1")).text
        assert "Maison" not in html.split('id="results"')[-1]
