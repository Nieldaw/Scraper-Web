import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import Property, PropertyStatus, SourceListing
from immo_ne_collector.services.exports import (
    DEDUPLICATION_HEADERS,
    export_deduplication_report_csv,
)

pytestmark = pytest.mark.db


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as file_obj:
        return list(csv.DictReader(file_obj))


async def _insert_property_with_sources(
    *,
    token: str,
    sources: list[str],
) -> Property:
    now = datetime.now(UTC)
    row = Property(
        title=f"Bien {token}",
        property_type="appartement",
        price_chf=850000,
        rooms=4.5,
        living_area_m2=110,
        address_full="Rue du Seyon 12",
        city="Neuchatel",
        postal_code="2000",
        sources=sources,
        source_urls=[f"https://{source}.local/{token}" for source in sources],
        first_seen_at=now,
        last_seen_at=now,
        last_changed_at=now,
        status=PropertyStatus.ACTIVE,
        raw_data={},
    )

    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.flush()
        for idx, source in enumerate(sources, start=1):
            session.add(
                SourceListing(
                    source=source,
                    source_listing_id=f"{token}-{idx}",
                    url=f"https://{source}.local/{token}/{idx}",
                    title=row.title,
                    property_type=row.property_type,
                    price_chf=row.price_chf,
                    rooms=row.rooms,
                    living_area_m2=row.living_area_m2,
                    address_full=row.address_full,
                    city=row.city,
                    postal_code=row.postal_code,
                    description="desc",
                    raw_data={"transaction_type": "sale"},
                    first_seen_at=now,
                    last_seen_at=now,
                    collected_at=now,
                    property_id=row.id,
                )
            )
        await session.commit()
        await session.refresh(row)
        return row


@pytest.mark.asyncio
async def test_deduplication_report_single_source(tmp_path: Path) -> None:
    token = "dedup-single"
    created = await _insert_property_with_sources(token=token, sources=["anibis_cached"])

    async with AsyncSessionLocal() as session:
        result = await export_deduplication_report_csv(session, tmp_path / "deduplication_report.csv")

    rows = _read_csv(result.path)
    selected = next(item for item in rows if item["property_id"] == str(created.id))
    assert selected["source_count"] == "1"
    assert selected["merge_status"] == "single_source"
    assert json.loads(selected["sources"]) == ["anibis_cached"]


@pytest.mark.asyncio
async def test_deduplication_report_multi_source(tmp_path: Path) -> None:
    token = "dedup-multi"
    created = await _insert_property_with_sources(
        token=token,
        sources=["anibis_cached", "lookmove_cached"],
    )

    async with AsyncSessionLocal() as session:
        result = await export_deduplication_report_csv(session, tmp_path / "deduplication_report.csv")

    rows = _read_csv(result.path)
    selected = next(item for item in rows if item["property_id"] == str(created.id))
    assert selected["source_count"] == "2"
    assert selected["merge_status"] == "merged_same_canton"
    assert selected["canton_conflict"] == "false"
    assert selected["source_listing_count"] == "2"
    assert json.loads(selected["detected_cantons"]) == ["NE"]
    assert sorted(json.loads(selected["sources"])) == ["anibis_cached", "lookmove_cached"]


@pytest.mark.asyncio
async def test_deduplication_report_contains_expected_headers(tmp_path: Path) -> None:
    await _insert_property_with_sources(token="dedup-headers", sources=["anibis_cached"])

    async with AsyncSessionLocal() as session:
        result = await export_deduplication_report_csv(session, tmp_path / "deduplication_report.csv")

    rows = _read_csv(result.path)
    assert rows
    for header in DEDUPLICATION_HEADERS:
        assert header in rows[0]


@pytest.mark.asyncio
async def test_deduplication_report_marks_canton_conflict(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    row = Property(
        title="Conflict test",
        property_type="appartement",
        price_chf=900000,
        rooms=4.5,
        living_area_m2=115,
        address_full="Rue test 1",
        city="Neuchatel",
        postal_code="2000",
        sources=["anibis_cached", "lookmove_cached"],
        source_urls=[
            "https://www.anibis.ch/fr/vi/neuchatel/appartement/111",
            "https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans-geneve/222",
        ],
        first_seen_at=now,
        last_seen_at=now,
        last_changed_at=now,
        status=PropertyStatus.ACTIVE,
        raw_data={},
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.flush()
        session.add(
            SourceListing(
                source="anibis_cached",
                source_listing_id="conflict-ne",
                url="https://www.anibis.ch/fr/vi/neuchatel/appartement/111",
                title=row.title,
                property_type=row.property_type,
                price_chf=row.price_chf,
                rooms=row.rooms,
                living_area_m2=row.living_area_m2,
                address_full=row.address_full,
                city="Neuchatel",
                postal_code="2000",
                description="desc",
                raw_data={"transaction_type": "sale", "detected_canton": "NE"},
                first_seen_at=now,
                last_seen_at=now,
                collected_at=now,
                property_id=row.id,
            )
        )
        session.add(
            SourceListing(
                source="lookmove_cached",
                source_listing_id="conflict-ge",
                url="https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans-geneve/222",
                title=row.title,
                property_type=row.property_type,
                price_chf=row.price_chf,
                rooms=row.rooms,
                living_area_m2=row.living_area_m2,
                address_full=row.address_full,
                city="Geneve",
                postal_code="1201",
                description="desc",
                raw_data={"transaction_type": "sale", "detected_canton": "GE"},
                first_seen_at=now,
                last_seen_at=now,
                collected_at=now,
                property_id=row.id,
            )
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        result = await export_deduplication_report_csv(session, tmp_path / "deduplication_report.csv")

    rows = _read_csv(result.path)
    selected = next(item for item in rows if item["property_id"] == str(row.id))
    detected_cantons = json.loads(selected["detected_cantons"])
    assert sorted(detected_cantons) == ["GE", "NE"]
    assert selected["canton_conflict"] == "true"
    assert selected["merge_status"] == "canton_conflict_prevented"
