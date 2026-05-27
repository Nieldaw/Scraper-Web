import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from immo_ne_collector.config import get_settings
from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import Property, PropertyStatus

EXPORT_HEADERS = [
    "property_id",
    "title",
    "property_type",
    "price_chf",
    "rooms",
    "living_area_m2",
    "address_full",
    "city",
    "postal_code",
    "sources",
    "source_urls",
    "first_seen_at",
    "last_seen_at",
    "last_changed_at",
    "status",
    "needs_completion",
    "completion_reason",
    "sitn_eligible",
    "sitn_status",
    "sitn_bien_fonds",
    "sitn_owner_name",
    "sitn_url",
]


@dataclass(frozen=True)
class ExportFileResult:
    name: str
    path: Path
    row_count: int


def _to_iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).isoformat()


def _to_text(value) -> str:
    return "" if value is None else str(value)


def property_to_export_row(property_row: Property) -> dict[str, str]:
    source_urls_from_rows = [listing.url for listing in property_row.listings if listing.url]
    merged_source_urls: list[str] = []
    for url in [*property_row.source_urls, *source_urls_from_rows]:
        if url not in merged_source_urls:
            merged_source_urls.append(url)

    source_names_from_rows = [listing.source for listing in property_row.listings if listing.source]
    merged_sources: list[str] = []
    for source in [*property_row.sources, *source_names_from_rows]:
        if source not in merged_sources:
            merged_sources.append(source)

    return {
        "property_id": str(property_row.id),
        "title": _to_text(property_row.title),
        "property_type": _to_text(property_row.property_type),
        "price_chf": _to_text(property_row.price_chf),
        "rooms": _to_text(property_row.rooms),
        "living_area_m2": _to_text(property_row.living_area_m2),
        "address_full": _to_text(property_row.address_full),
        "city": _to_text(property_row.city),
        "postal_code": _to_text(property_row.postal_code),
        "sources": json.dumps(merged_sources, ensure_ascii=False),
        "source_urls": json.dumps(merged_source_urls, ensure_ascii=False),
        "first_seen_at": _to_iso(property_row.first_seen_at),
        "last_seen_at": _to_iso(property_row.last_seen_at),
        "last_changed_at": _to_iso(property_row.last_changed_at),
        "status": _to_text(property_row.status),
        "needs_completion": str(property_row.needs_completion),
        "completion_reason": _to_text(property_row.completion_reason),
        "sitn_eligible": str(property_row.sitn_eligible),
        "sitn_status": _to_text(property_row.sitn_status),
        "sitn_bien_fonds": _to_text(property_row.sitn_bien_fonds),
        "sitn_owner_name": _to_text(property_row.sitn_owner_name),
        "sitn_url": _to_text(property_row.sitn_url),
    }


async def _fetch_properties(session: AsyncSession, query) -> list[Property]:
    result = await session.execute(query)
    return result.scalars().all()


async def _write_export(
    session: AsyncSession,
    *,
    name: str,
    path: Path,
    query,
) -> ExportFileResult:
    properties = await _fetch_properties(session, query)
    rows = [property_to_export_row(row) for row in properties]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=EXPORT_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    return ExportFileResult(name=name, path=path, row_count=len(rows))


async def export_master_csv(session: AsyncSession, output_path: Path) -> ExportFileResult:
    query = select(Property).options(selectinload(Property.listings)).order_by(Property.first_seen_at.desc())
    return await _write_export(session, name="MASTER", path=output_path, query=query)


async def export_nouveaux_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    window_hours: int | None = None,
) -> ExportFileResult:
    settings = get_settings()
    effective_window = window_hours if window_hours is not None else settings.new_window_hours
    cutoff = datetime.now(UTC) - timedelta(hours=effective_window)
    query = (
        select(Property)
        .options(selectinload(Property.listings))
        .where(Property.first_seen_at >= cutoff)
        .order_by(Property.first_seen_at.desc())
    )
    return await _write_export(session, name="NOUVEAUX", path=output_path, query=query)


async def export_modifies_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    window_hours: int | None = None,
) -> ExportFileResult:
    settings = get_settings()
    effective_window = window_hours if window_hours is not None else settings.updated_window_hours
    cutoff = datetime.now(UTC) - timedelta(hours=effective_window)
    query = (
        select(Property)
        .options(selectinload(Property.listings))
        .where(Property.last_changed_at.is_not(None), Property.last_changed_at >= cutoff)
        .order_by(Property.last_changed_at.desc())
    )
    return await _write_export(session, name="MODIFIES", path=output_path, query=query)


async def export_inactifs_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    inactive_after_days: int | None = None,
) -> ExportFileResult:
    settings = get_settings()
    effective_days = inactive_after_days if inactive_after_days is not None else settings.inactive_after_days
    cutoff = datetime.now(UTC) - timedelta(days=effective_days)
    query = (
        select(Property)
        .options(selectinload(Property.listings))
        .where(
            or_(
                Property.status.in_([PropertyStatus.INACTIVE, PropertyStatus.REMOVED]),
                Property.last_seen_at < cutoff,
            )
        )
        .order_by(Property.last_seen_at.asc())
    )
    return await _write_export(session, name="INACTIFS", path=output_path, query=query)


async def export_all_csv(
    *,
    output_dir: Path | None = None,
    session: AsyncSession | None = None,
) -> list[ExportFileResult]:
    export_dir = output_dir or Path("data/exports")
    owns_session = session is None
    active_session = session
    if active_session is None:
        active_session = AsyncSessionLocal()

    try:
        master = await export_master_csv(active_session, export_dir / "master.csv")
        nouveaux = await export_nouveaux_csv(active_session, export_dir / "nouveaux.csv")
        modifies = await export_modifies_csv(active_session, export_dir / "modifies.csv")
        inactifs = await export_inactifs_csv(active_session, export_dir / "inactifs.csv")
        return [master, nouveaux, modifies, inactifs]
    finally:
        if owns_session and active_session is not None:
            await active_session.close()
