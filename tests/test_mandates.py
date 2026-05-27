import csv
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from immo_ne_collector.db import AsyncSessionLocal, engine
from immo_ne_collector.models import Property, PropertyStatus, SearchMandate, SitnStatus
from immo_ne_collector.services.mandates import (
    MandateCriteria,
    apply_search_mandate,
    create_search_mandate,
    export_mandate_matches_csv,
)


@pytest.fixture(autouse=True)
async def _dispose_engine_pool_between_tests() -> None:
    await engine.dispose()
    yield
    await engine.dispose()


async def _insert_property(
    *,
    city: str,
    property_type: str = "appartement",
    price: Decimal | None = Decimal("1000000"),
    rooms: Decimal | None = Decimal("4.5"),
    area: Decimal | None = Decimal("120"),
    status: str = PropertyStatus.ACTIVE,
) -> Property:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        row = Property(
            title=f"Bien test {city}",
            property_type=property_type,
            price_chf=price,
            rooms=rooms,
            living_area_m2=area,
            address_full="Rue du Seyon 12",
            city=city,
            postal_code="2000",
            sources=[],
            source_urls=[],
            first_seen_at=now,
            last_seen_at=now,
            last_changed_at=now,
            status=status,
            needs_completion=False,
            completion_reason=None,
            sitn_eligible=False,
            sitn_status=SitnStatus.NOT_RUN,
            raw_data={"test": city},
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


@pytest.mark.asyncio
async def test_create_mandate() -> None:
    city = f"City-{uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        mandate = await create_search_mandate(
            session,
            criteria=MandateCriteria(
                name="Mandat creation",
                cities=[city],
                property_types=["appartement"],
                min_price_chf=Decimal("500000"),
                max_price_chf=Decimal("1500000"),
                min_rooms=Decimal("3"),
                max_rooms=Decimal("6"),
                min_living_area_m2=Decimal("80"),
                max_living_area_m2=Decimal("200"),
                only_active=True,
            ),
        )

    async with AsyncSessionLocal() as session:
        stored = (await session.execute(select(SearchMandate).where(SearchMandate.id == mandate.id))).scalar_one()
        assert stored.name == "Mandat creation"
        assert stored.max_rooms == Decimal("6")
        assert stored.max_living_area_m2 == Decimal("200")
        assert stored.only_active is True


@pytest.mark.asyncio
async def test_filter_by_city() -> None:
    city_match = f"CityMatch-{uuid4().hex[:8]}"
    city_other = f"CityOther-{uuid4().hex[:8]}"
    match_row = await _insert_property(city=city_match)
    await _insert_property(city=city_other)

    async with AsyncSessionLocal() as session:
        mandate = await create_search_mandate(
            session,
            criteria=MandateCriteria(name="By city", cities=[city_match]),
        )
        result = await apply_search_mandate(session, mandate_id=mandate.id)

    ids = {item.property_id for item in result.matches}
    assert match_row.id in ids
    assert all(item.property_id != match_row.id or "city_match" in item.reasons for item in result.matches)
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_filter_by_price_min_max() -> None:
    city = f"CityPrice-{uuid4().hex[:8]}"
    within = await _insert_property(city=city, price=Decimal("900000"))
    await _insert_property(city=city, price=Decimal("300000"))
    await _insert_property(city=city, price=Decimal("1800000"))

    async with AsyncSessionLocal() as session:
        mandate = await create_search_mandate(
            session,
            criteria=MandateCriteria(
                name="By price",
                cities=[city],
                min_price_chf=Decimal("700000"),
                max_price_chf=Decimal("1200000"),
            ),
        )
        result = await apply_search_mandate(session, mandate_id=mandate.id)
    ids = {item.property_id for item in result.matches}
    assert ids == {within.id}


@pytest.mark.asyncio
async def test_filter_by_rooms() -> None:
    city = f"CityRooms-{uuid4().hex[:8]}"
    within = await _insert_property(city=city, rooms=Decimal("4.5"))
    await _insert_property(city=city, rooms=Decimal("2.0"))
    await _insert_property(city=city, rooms=Decimal("7.0"))

    async with AsyncSessionLocal() as session:
        mandate = await create_search_mandate(
            session,
            criteria=MandateCriteria(
                name="By rooms",
                cities=[city],
                min_rooms=Decimal("3"),
                max_rooms=Decimal("6"),
            ),
        )
        result = await apply_search_mandate(session, mandate_id=mandate.id)
    assert {item.property_id for item in result.matches} == {within.id}


@pytest.mark.asyncio
async def test_filter_by_living_area() -> None:
    city = f"CityArea-{uuid4().hex[:8]}"
    within = await _insert_property(city=city, area=Decimal("120"))
    await _insert_property(city=city, area=Decimal("45"))
    await _insert_property(city=city, area=Decimal("290"))

    async with AsyncSessionLocal() as session:
        mandate = await create_search_mandate(
            session,
            criteria=MandateCriteria(
                name="By area",
                cities=[city],
                min_living_area_m2=Decimal("80"),
                max_living_area_m2=Decimal("200"),
            ),
        )
        result = await apply_search_mandate(session, mandate_id=mandate.id)
    assert {item.property_id for item in result.matches} == {within.id}


@pytest.mark.asyncio
async def test_only_active_excludes_inactive_and_removed() -> None:
    city = f"CityActive-{uuid4().hex[:8]}"
    active = await _insert_property(city=city, status=PropertyStatus.ACTIVE)
    await _insert_property(city=city, status=PropertyStatus.INACTIVE)
    await _insert_property(city=city, status=PropertyStatus.REMOVED)

    async with AsyncSessionLocal() as session:
        mandate = await create_search_mandate(
            session,
            criteria=MandateCriteria(name="Only active", cities=[city], only_active=True),
        )
        result = await apply_search_mandate(session, mandate_id=mandate.id)
    assert {item.property_id for item in result.matches} == {active.id}


@pytest.mark.asyncio
async def test_export_mandate_matches_csv(tmp_path: Path) -> None:
    city = f"CityExport-{uuid4().hex[:8]}"
    matching = await _insert_property(city=city, price=Decimal("950000"))
    await _insert_property(city=city, price=Decimal("250000"))

    async with AsyncSessionLocal() as session:
        mandate = await create_search_mandate(
            session,
            criteria=MandateCriteria(
                name="Export mandate",
                cities=[city],
                min_price_chf=Decimal("700000"),
                max_price_chf=Decimal("1200000"),
            ),
        )
        export_result = await export_mandate_matches_csv(
            session,
            mandate_id=mandate.id,
            output_dir=tmp_path,
        )

    assert export_result.path.exists()
    with export_result.path.open("r", encoding="utf-8", newline="") as file_obj:
        rows = list(csv.DictReader(file_obj))
    ids = {row["property_id"] for row in rows}
    assert str(matching.id) in ids
