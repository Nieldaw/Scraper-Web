from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import Property
from immo_ne_collector.scrapers.base import RawListing
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.geocoding import (
    geocode_missing_properties,
    geocode_postal_code,
    parse_search_response,
)
from immo_ne_collector.services.persistence import persist_collection_batch

MARTIGNY = {"results": [{"attrs": {"lat": 46.106361, "lon": 7.099298, "origin": "zipcode"}}]}


def test_parse_search_response():
    assert parse_search_response(MARTIGNY) == (46.106361, 7.099298)
    assert parse_search_response({"results": []}) is None
    assert parse_search_response({"results": [{"attrs": {"lat": 10, "lon": 7}}]}) is None  # hors Suisse
    assert parse_search_response("x") is None


async def test_geocode_sends_only_postal_code():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=MARTIGNY)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await geocode_postal_code(client, "1920") == (46.106361, 7.099298)
        assert await geocode_postal_code(client, "pas un npa") is None
    assert len(seen) == 1
    assert seen[0].url.params["searchText"] == "1920" and seen[0].url.params["origins"] == "zipcode"
    assert "api3.geo.admin.ch" in str(seen[0].url)


class _Fake:
    source = "anibis"

    def __init__(self, sid="g1", city="Martigny", npa="1920", price="CHF 700'000", rooms="4.5 pièces"):
        self.sid, self.city, self.npa, self.price, self.rooms = sid, city, npa, price, rooms

    async def collect_safe(self):
        return [
            RawListing(
                source="anibis",
                source_listing_id=self.sid,
                url=f"https://www.anibis.ch/fr/d/{self.sid}",
                title="Villa",
                property_type="house",
                price_raw=self.price,
                rooms_raw=self.rooms,
                city_raw=self.city,
                postal_code_raw=self.npa,
                fetched_at=datetime.now(UTC),
                raw_data={},
            )
        ]


@pytest.mark.db
async def test_geocode_missing_properties_updates_all_with_same_npa():
    await persist_collection_batch(await collect_and_normalize(_Fake("g1")))
    await persist_collection_batch(await collect_and_normalize(_Fake("g2")))
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=MARTIGNY)

    async with AsyncSessionLocal() as session:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            updated = await geocode_missing_properties(session, client=client)
        rows = (await session.execute(select(Property))).scalars().all()
    assert updated == len(rows) and all(r.latitude == 46.106361 for r in rows)
    assert len(calls) == 1  # une requête par code postal distinct


@pytest.mark.db
async def test_geocode_failure_does_not_raise():
    await persist_collection_batch(await collect_and_normalize(_Fake("g3")))

    def handler(request):
        return httpx.Response(500)

    async with AsyncSessionLocal() as session:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await geocode_missing_properties(session, client=client) == 0


@pytest.mark.db
async def test_mandate_prefill_preview_and_wording():
    from httpx import ASGITransport, AsyncClient

    from immo_ne_collector.main import app

    await persist_collection_batch(await collect_and_normalize(_Fake("m1")))
    await persist_collection_batch(
        await collect_and_normalize(_Fake("m2", city="Sion", npa="1950", price="CHF 300'000"))
    )
    async with AsyncSessionLocal() as session:
        pid = (
            await session.execute(select(Property.id).where(Property.city == "Martigny"))
        ).scalar_one()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        detail = (await client.get(f"/properties/{pid}")).text
        assert "Créer un mandat depuis cette annonce" in detail
        assert f"/mandates?from_property={pid}" in detail
        form = (await client.get(f"/mandates?from_property={pid}")).text
        assert 'value="Martigny"' in form and 'value="560000"' in form and 'value="840000"' in form
        assert "pré-rempli" in form and "/mandates/preview" in form
        one = (await client.get("/mandates/preview?cities=Martigny&only_active=on")).text
        assert 'data-count="1"' in one and "1 bien correspond actuellement" in one
        two = (await client.get("/mandates/preview")).text
        assert 'data-count="2"' in two and "2 biens correspondent" in two
        none = (await client.get("/mandates/preview?cities=Nulle%20part")).text
        assert 'data-count="0"' in none
        grid = (await client.get("/properties")).text
        assert "Plus disponible" in grid and "Inactifs" not in grid
        assert 'data-tip="Plus vus sur le site depuis 7 jours' in grid
