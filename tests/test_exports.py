import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import Property, PropertyStatus, SitnStatus, SourceListing
from immo_ne_collector.services.exports import (
    EXPORT_HEADERS,
    export_all_csv,
    export_inactifs_csv,
    export_locations_csv,
    export_master_csv,
    export_modifies_csv,
    export_nouveaux_csv,
    export_ventes_csv,
)
from immo_ne_collector.services.quality import export_quality_report_csv
from immo_ne_collector.services.source_config import build_canton_property_filter

pytestmark = pytest.mark.db


async def _create_property_with_listings(
    *,
    token: str,
    first_seen_at: datetime,
    last_seen_at: datetime,
    last_changed_at: datetime | None,
    status: str,
    title: str = "Bien test",
    city: str = "Neuchatel",
    postal_code: str = "2000",
    source_names: list[str] | None = None,
    transaction_types: list[str] | None = None,
) -> Property:
    names = source_names or [f"src_{token}_a", f"src_{token}_b"]
    property_row = Property(
        title=title,
        property_type="appartement",
        price_chf=1000000,
        rooms=4.5,
        living_area_m2=120,
        address_full="Rue du Seyon 12",
        city=city,
        postal_code=postal_code,
        sources=[],
        source_urls=[],
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        last_changed_at=last_changed_at,
        status=status,
        needs_completion=False,
        completion_reason=None,
        sitn_eligible=False,
        sitn_status=SitnStatus.NOT_RUN,
        raw_data={"test": token},
    )
    async with AsyncSessionLocal() as session:
        session.add(property_row)
        await session.flush()
        for index, source in enumerate(names, start=1):
            url = f"https://{source}.local/{token}/{index}"
            tx_type = (
                transaction_types[index - 1]
                if transaction_types and index - 1 < len(transaction_types)
                else "unknown"
            )
            session.add(
                SourceListing(
                    source=source,
                    source_listing_id=f"{token}-{index}",
                    url=url,
                    title=title,
                    property_type="appartement",
                    price_chf=1000000,
                    rooms=4.5,
                    living_area_m2=120,
                    address_full="Rue du Seyon 12",
                    city=city,
                    postal_code=postal_code,
                    description=f"description {token}",
                    raw_data={"test": token, "transaction_type": tx_type},
                    first_seen_at=first_seen_at,
                    last_seen_at=last_seen_at,
                    collected_at=last_seen_at,
                    property_id=property_row.id,
                )
            )
        await session.commit()
        await session.refresh(property_row)
        return property_row


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as file_obj:
        return list(csv.DictReader(file_obj))


@pytest.mark.asyncio
async def test_export_master_with_single_property_and_multiple_source_listings(tmp_path: Path) -> None:
    token = f"exp-master-{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    row = await _create_property_with_listings(
        token=token,
        first_seen_at=now,
        last_seen_at=now,
        last_changed_at=now,
        status=PropertyStatus.ACTIVE,
        source_names=[f"{token}-s1", f"{token}-s2"],
    )

    async with AsyncSessionLocal() as session:
        result = await export_master_csv(session, tmp_path / "master.csv")

    assert result.row_count >= 1
    rows = _read_csv(result.path)
    exported = next(item for item in rows if item["property_id"] == str(row.id))
    sources = json.loads(exported["sources"])
    source_urls = json.loads(exported["source_urls"])
    assert len(sources) == 2
    assert len(source_urls) == 2
    assert exported["transaction_type"] == "unknown"
    assert json.loads(exported["transaction_types"]) == ["unknown"]


@pytest.mark.asyncio
async def test_export_master_contains_minimum_data_contract_fields(tmp_path: Path) -> None:
    token = f"exp-fields-{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    await _create_property_with_listings(
        token=token,
        first_seen_at=now,
        last_seen_at=now,
        last_changed_at=now,
        status=PropertyStatus.ACTIVE,
    )
    async with AsyncSessionLocal() as session:
        result = await export_master_csv(session, tmp_path / "master.csv")
    rows = _read_csv(result.path)
    assert rows
    for header in EXPORT_HEADERS:
        assert header in rows[0]


@pytest.mark.asyncio
async def test_export_nouveaux_filters_by_first_seen_at(tmp_path: Path) -> None:
    token_recent = f"exp-new-recent-{uuid4().hex[:6]}"
    token_old = f"exp-new-old-{uuid4().hex[:6]}"
    now = datetime.now(UTC)
    recent = await _create_property_with_listings(
        token=token_recent,
        first_seen_at=now - timedelta(hours=1),
        last_seen_at=now,
        last_changed_at=now,
        status=PropertyStatus.ACTIVE,
    )
    old = await _create_property_with_listings(
        token=token_old,
        first_seen_at=now - timedelta(hours=72),
        last_seen_at=now - timedelta(hours=72),
        last_changed_at=now - timedelta(hours=72),
        status=PropertyStatus.ACTIVE,
    )

    async with AsyncSessionLocal() as session:
        result = await export_nouveaux_csv(session, tmp_path / "nouveaux.csv", window_hours=24)
    rows = _read_csv(result.path)
    ids = {item["property_id"] for item in rows}
    assert str(recent.id) in ids
    assert str(old.id) not in ids


@pytest.mark.asyncio
async def test_export_modifies_filters_by_last_changed_at(tmp_path: Path) -> None:
    token_recent = f"exp-mod-recent-{uuid4().hex[:6]}"
    token_old = f"exp-mod-old-{uuid4().hex[:6]}"
    now = datetime.now(UTC)
    recent = await _create_property_with_listings(
        token=token_recent,
        first_seen_at=now - timedelta(days=3),
        last_seen_at=now,
        last_changed_at=now - timedelta(hours=2),
        status=PropertyStatus.UPDATED,
    )
    old = await _create_property_with_listings(
        token=token_old,
        first_seen_at=now - timedelta(days=10),
        last_seen_at=now - timedelta(days=1),
        last_changed_at=now - timedelta(days=5),
        status=PropertyStatus.ACTIVE,
    )

    async with AsyncSessionLocal() as session:
        result = await export_modifies_csv(session, tmp_path / "modifies.csv", window_hours=24)
    rows = _read_csv(result.path)
    ids = {item["property_id"] for item in rows}
    assert str(recent.id) in ids
    assert str(old.id) not in ids


@pytest.mark.asyncio
async def test_export_modifies_excludes_newly_created_properties(tmp_path: Path) -> None:
    token_new = f"exp-mod-new-{uuid4().hex[:6]}"
    token_updated = f"exp-mod-updated-{uuid4().hex[:6]}"
    now = datetime.now(UTC)
    newly_created = await _create_property_with_listings(
        token=token_new,
        first_seen_at=now - timedelta(hours=2),
        last_seen_at=now - timedelta(hours=2),
        last_changed_at=now - timedelta(hours=2),
        status=PropertyStatus.NEW,
    )
    updated = await _create_property_with_listings(
        token=token_updated,
        first_seen_at=now - timedelta(days=3),
        last_seen_at=now - timedelta(hours=1),
        last_changed_at=now - timedelta(hours=1),
        status=PropertyStatus.UPDATED,
    )

    async with AsyncSessionLocal() as session:
        result = await export_modifies_csv(session, tmp_path / "modifies.csv", window_hours=24)
    rows = _read_csv(result.path)
    ids = {item["property_id"] for item in rows}
    assert str(updated.id) in ids
    assert str(newly_created.id) not in ids


@pytest.mark.asyncio
async def test_export_inactifs_contains_inactive_and_removed(tmp_path: Path) -> None:
    token_inactive = f"exp-inactive-{uuid4().hex[:6]}"
    token_removed = f"exp-removed-{uuid4().hex[:6]}"
    token_active = f"exp-active-{uuid4().hex[:6]}"
    now = datetime.now(UTC)
    inactive = await _create_property_with_listings(
        token=token_inactive,
        first_seen_at=now - timedelta(days=10),
        last_seen_at=now - timedelta(days=2),
        last_changed_at=now - timedelta(days=2),
        status=PropertyStatus.INACTIVE,
    )
    removed = await _create_property_with_listings(
        token=token_removed,
        first_seen_at=now - timedelta(days=10),
        last_seen_at=now - timedelta(days=1),
        last_changed_at=now - timedelta(days=1),
        status=PropertyStatus.REMOVED,
    )
    active = await _create_property_with_listings(
        token=token_active,
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now,
        last_changed_at=now,
        status=PropertyStatus.ACTIVE,
    )

    async with AsyncSessionLocal() as session:
        result = await export_inactifs_csv(session, tmp_path / "inactifs.csv", inactive_after_days=30)
    rows = _read_csv(result.path)
    ids = {item["property_id"] for item in rows}
    assert str(inactive.id) in ids
    assert str(removed.id) in ids
    assert str(active.id) not in ids


@pytest.mark.asyncio
async def test_export_csv_is_utf8_encoded(tmp_path: Path) -> None:
    token = f"exp-utf8-{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    created = await _create_property_with_listings(
        token=token,
        first_seen_at=now,
        last_seen_at=now,
        last_changed_at=now,
        status=PropertyStatus.ACTIVE,
        title="Étage rénové – centre",
        city="La Chaux-de-Fonds",
    )

    async with AsyncSessionLocal() as session:
        result = await export_master_csv(session, tmp_path / "master.csv")

    raw = result.path.read_bytes()
    decoded = raw.decode("utf-8")
    assert "Étage rénové" in decoded
    rows = _read_csv(result.path)
    selected = next(item for item in rows if item["property_id"] == str(created.id))
    assert selected["city"] == "La Chaux-de-Fonds"


@pytest.mark.asyncio
async def test_export_master_transaction_type_mixed_when_sources_disagree(tmp_path: Path) -> None:
    token = f"exp-mixed-{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    created = await _create_property_with_listings(
        token=token,
        first_seen_at=now - timedelta(days=2),
        last_seen_at=now - timedelta(days=1),
        last_changed_at=now - timedelta(days=1),
        status=PropertyStatus.ACTIVE,
        transaction_types=["rent", "sale"],
    )

    async with AsyncSessionLocal() as session:
        result = await export_master_csv(session, tmp_path / "master.csv")

    rows = _read_csv(result.path)
    selected = next(item for item in rows if item["property_id"] == str(created.id))
    assert selected["transaction_type"] == "mixed"
    assert json.loads(selected["transaction_types"]) == ["rent", "sale"]


@pytest.mark.asyncio
async def test_export_ventes_contains_only_sale(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    sale_row = await _create_property_with_listings(
        token=f"exp-sale-{uuid4().hex[:6]}",
        first_seen_at=now - timedelta(days=3),
        last_seen_at=now - timedelta(days=1),
        last_changed_at=now - timedelta(days=1),
        status=PropertyStatus.ACTIVE,
        transaction_types=["sale"],
        source_names=[f"sale-src-{uuid4().hex[:6]}"],
    )
    await _create_property_with_listings(
        token=f"exp-rent-{uuid4().hex[:6]}",
        first_seen_at=now - timedelta(days=3),
        last_seen_at=now - timedelta(days=1),
        last_changed_at=now - timedelta(days=1),
        status=PropertyStatus.ACTIVE,
        transaction_types=["rent"],
        source_names=[f"rent-src-{uuid4().hex[:6]}"],
    )

    async with AsyncSessionLocal() as session:
        result = await export_ventes_csv(session, tmp_path / "ventes.csv")

    rows = _read_csv(result.path)
    assert rows
    ids = {row["property_id"] for row in rows}
    assert str(sale_row.id) in ids
    assert all(row["transaction_type"] == "sale" for row in rows)


@pytest.mark.asyncio
async def test_export_locations_contains_only_rent(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    rent_row = await _create_property_with_listings(
        token=f"exp-rent2-{uuid4().hex[:6]}",
        first_seen_at=now - timedelta(days=3),
        last_seen_at=now - timedelta(days=1),
        last_changed_at=now - timedelta(days=1),
        status=PropertyStatus.ACTIVE,
        transaction_types=["rent"],
        source_names=[f"rent2-src-{uuid4().hex[:6]}"],
    )
    await _create_property_with_listings(
        token=f"exp-unknown-{uuid4().hex[:6]}",
        first_seen_at=now - timedelta(days=3),
        last_seen_at=now - timedelta(days=1),
        last_changed_at=now - timedelta(days=1),
        status=PropertyStatus.ACTIVE,
        transaction_types=["unknown"],
        source_names=[f"unk-src-{uuid4().hex[:6]}"],
    )

    async with AsyncSessionLocal() as session:
        result = await export_locations_csv(session, tmp_path / "locations.csv")

    rows = _read_csv(result.path)
    assert rows
    ids = {row["property_id"] for row in rows}
    assert str(rent_row.id) in ids
    assert all(row["transaction_type"] == "rent" for row in rows)


@pytest.mark.asyncio
async def test_export_by_canton_generates_filtered_files(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    ne_row = await _create_property_with_listings(
        token=f"exp-ne-{uuid4().hex[:6]}",
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now - timedelta(hours=1),
        last_changed_at=now - timedelta(hours=1),
        status=PropertyStatus.ACTIVE,
        city="Neuchatel",
        transaction_types=["sale"],
        source_names=[f"ne-src-{uuid4().hex[:6]}"],
    )
    await _create_property_with_listings(
        token=f"exp-be-{uuid4().hex[:6]}",
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now - timedelta(hours=1),
        last_changed_at=now - timedelta(hours=1),
        status=PropertyStatus.ACTIVE,
        city="Berne",
        postal_code="3000",
        source_names=[f"be-src-{uuid4().hex[:6]}"],
        transaction_types=["sale"],
    )

    canton_filter = build_canton_property_filter("NE")
    by_canton_dir = tmp_path / "by_canton" / "NE"

    async with AsyncSessionLocal() as session:
        export_results = await export_all_csv(
            output_dir=by_canton_dir,
            session=session,
            property_filter=canton_filter,
        )
        quality_result = await export_quality_report_csv(
            session,
            by_canton_dir / "quality_report.csv",
            property_filter=canton_filter,
        )

    master = next(item for item in export_results if item.name == "MASTER")
    ventes = next(item for item in export_results if item.name == "VENTES")
    assert master.path.exists()
    assert ventes.path.exists()
    assert quality_result.path.exists()

    master_rows = _read_csv(master.path)
    ids = {row["property_id"] for row in master_rows}
    assert str(ne_row.id) in ids
    assert all("berne" not in row["city"].lower() for row in master_rows if row["city"])
