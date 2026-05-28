import csv
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import Property, PropertyStatus, SitnStatus, SourceListing
from immo_ne_collector.services.quality import build_quality_rows, export_quality_report_csv

pytestmark = pytest.mark.db


async def _create_property(
    *,
    title: str,
    transaction_type: str,
    price_chf,
    rooms,
    living_area_m2,
    city: str | None = "Neuchatel",
    postal_code: str | None = "2000",
    address_full: str | None = "Rue du Seyon 12",
    sitn_eligible: bool = False,
    completion_reason: str | None = None,
    sitn_status: str = SitnStatus.NOT_RUN,
    property_type: str = "appartement",
) -> Property:
    token = uuid4().hex[:8]
    now = datetime.now(UTC)
    property_row = Property(
        title=title,
        property_type=property_type,
        price_chf=price_chf,
        rooms=rooms,
        living_area_m2=living_area_m2,
        address_full=address_full,
        city=city,
        postal_code=postal_code,
        sources=[],
        source_urls=[],
        first_seen_at=now,
        last_seen_at=now,
        last_changed_at=now,
        status=PropertyStatus.NEW,
        needs_completion=not bool(address_full),
        completion_reason=completion_reason,
        sitn_eligible=sitn_eligible,
        sitn_status=sitn_status,
        raw_data={},
    )
    async with AsyncSessionLocal() as session:
        session.add(property_row)
        await session.flush()
        session.add(
            SourceListing(
                source=f"src-{token}",
                source_listing_id=f"id-{token}",
                url=f"https://example.local/{token}",
                title=title,
                property_type=property_type,
                price_chf=price_chf,
                rooms=rooms,
                living_area_m2=living_area_m2,
                address_full=address_full,
                city=city,
                postal_code=postal_code,
                description="desc",
                raw_data={"transaction_type": transaction_type},
                first_seen_at=now,
                last_seen_at=now,
                collected_at=now,
                property_id=property_row.id,
            )
        )
        await session.commit()
        await session.refresh(property_row)
        return property_row


async def _quality_rows() -> list[dict[str, str]]:
    async with AsyncSessionLocal() as session:
        properties = (
            await session.execute(select(Property).options(selectinload(Property.listings)))
        ).scalars().all()
    return build_quality_rows(properties)


@pytest.mark.asyncio
async def test_quality_price_missing_on_sale_creates_issue() -> None:
    await _create_property(
        title="Sale without price",
        transaction_type="sale",
        price_chf=None,
        rooms=4.5,
        living_area_m2=120,
    )
    rows = await _quality_rows()
    codes = {row["issue_code"] for row in rows}
    assert "SALE_PRICE_MISSING" in codes


@pytest.mark.asyncio
async def test_quality_price_too_low_on_sale_creates_issue() -> None:
    await _create_property(
        title="Sale low price",
        transaction_type="sale",
        price_chf=50000,
        rooms=4.5,
        living_area_m2=120,
    )
    rows = await _quality_rows()
    codes = {row["issue_code"] for row in rows}
    assert "SALE_PRICE_TOO_LOW" in codes


@pytest.mark.asyncio
async def test_quality_area_too_low_creates_issue() -> None:
    await _create_property(
        title="Tiny area",
        transaction_type="sale",
        price_chf=500000,
        rooms=2.0,
        living_area_m2=8.3,
    )
    rows = await _quality_rows()
    codes = {row["issue_code"] for row in rows}
    assert "AREA_TOO_LOW" in codes


@pytest.mark.asyncio
async def test_quality_city_missing_creates_issue() -> None:
    await _create_property(
        title="No city",
        transaction_type="sale",
        price_chf=500000,
        rooms=2.0,
        living_area_m2=50,
        city=None,
    )
    rows = await _quality_rows()
    codes = {row["issue_code"] for row in rows}
    assert "CITY_MISSING" in codes


@pytest.mark.asyncio
async def test_quality_address_missing_creates_issue() -> None:
    await _create_property(
        title="No address",
        transaction_type="sale",
        price_chf=500000,
        rooms=2.0,
        living_area_m2=50,
        address_full=None,
        completion_reason="Adresse manquante",
        sitn_status=SitnStatus.NOT_ELIGIBLE_MISSING_ADDRESS,
    )
    rows = await _quality_rows()
    codes = {row["issue_code"] for row in rows}
    assert "ADDRESS_MISSING" in codes
    assert "SITN_NOT_ELIGIBLE_ADDRESS" in codes


@pytest.mark.asyncio
async def test_quality_report_csv_is_generated(tmp_path: Path) -> None:
    await _create_property(
        title="CSV quality",
        transaction_type="sale",
        price_chf=None,
        rooms=2.0,
        living_area_m2=50,
    )

    async with AsyncSessionLocal() as session:
        result = await export_quality_report_csv(session, tmp_path / "quality_report.csv")

    assert result.row_count >= 1
    with result.path.open("r", encoding="utf-8", newline="") as file_obj:
        rows = list(csv.DictReader(file_obj))
    assert rows
    assert "issue_code" in rows[0]


@pytest.mark.asyncio
async def test_quality_terrain_does_not_trigger_rooms_or_area_residential_warnings() -> None:
    await _create_property(
        title="Terrain constructible",
        transaction_type="sale",
        price_chf=420000,
        rooms=30,
        living_area_m2=8,
        property_type="terrain",
        city="Fribourg",
        postal_code="1700",
    )
    rows = await _quality_rows()
    codes = {row["issue_code"] for row in rows}
    assert "ROOMS_TOO_HIGH" not in codes
    assert "ROOMS_TOO_LOW" not in codes
    assert "AREA_TOO_LOW" not in codes
    assert "AREA_TOO_HIGH" not in codes
