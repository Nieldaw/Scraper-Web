import csv
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, or_, select
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
    "transaction_type",
    "transaction_types",
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

DEDUPLICATION_HEADERS = [
    "property_id",
    "sources",
    "source_urls",
    "title",
    "city",
    "postal_code",
    "price_chf",
    "rooms",
    "living_area_m2",
    "source_count",
    "merge_status",
    "deduplication_reason",
    "deduplication_score",
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


def _normalized_transaction_type(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in {"sale", "rent", "unknown"}:
        return cleaned
    return "unknown"


def _and_property_filters(
    left: Callable[[Property], bool] | None,
    right: Callable[[Property], bool] | None,
) -> Callable[[Property], bool] | None:
    if left is None:
        return right
    if right is None:
        return left
    return lambda row: left(row) and right(row)


def _extract_transaction_types(property_row: Property) -> list[str]:
    detected: list[str] = []
    for listing in property_row.listings:
        raw_value = None
        if isinstance(listing.raw_data, dict):
            raw_value = listing.raw_data.get("transaction_type")
        tx_type = _normalized_transaction_type(raw_value if isinstance(raw_value, str) else None)
        if tx_type not in detected:
            detected.append(tx_type)

    if detected:
        return detected

    fallback = None
    if isinstance(property_row.raw_data, dict):
        fallback = property_row.raw_data.get("transaction_type")
    return [_normalized_transaction_type(fallback if isinstance(fallback, str) else None)]


def _aggregate_transaction_type(transaction_types: list[str]) -> str:
    if not transaction_types:
        return "unknown"
    if len(transaction_types) == 1:
        return transaction_types[0]
    return "mixed"


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
    transaction_types = _extract_transaction_types(property_row)
    transaction_type = _aggregate_transaction_type(transaction_types)

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
        "transaction_type": transaction_type,
        "transaction_types": json.dumps(transaction_types, ensure_ascii=False),
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


def property_to_deduplication_row(property_row: Property) -> dict[str, str]:
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

    source_count = len(merged_sources)
    merge_status = "merged" if source_count > 1 else "single_source"

    dedup_reason = ""
    dedup_score = ""
    if isinstance(property_row.raw_data, dict):
        raw_reason = property_row.raw_data.get("deduplication_reason")
        raw_score = property_row.raw_data.get("deduplication_score")
        if isinstance(raw_reason, str):
            dedup_reason = raw_reason
        if raw_score is not None:
            dedup_score = str(raw_score)

    return {
        "property_id": str(property_row.id),
        "sources": json.dumps(merged_sources, ensure_ascii=False),
        "source_urls": json.dumps(merged_source_urls, ensure_ascii=False),
        "title": _to_text(property_row.title),
        "city": _to_text(property_row.city),
        "postal_code": _to_text(property_row.postal_code),
        "price_chf": _to_text(property_row.price_chf),
        "rooms": _to_text(property_row.rooms),
        "living_area_m2": _to_text(property_row.living_area_m2),
        "source_count": str(source_count),
        "merge_status": merge_status,
        "deduplication_reason": dedup_reason,
        "deduplication_score": dedup_score,
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
    property_filter: Callable[[Property], bool] | None = None,
) -> ExportFileResult:
    properties = await _fetch_properties(session, query)
    if property_filter is not None:
        properties = [row for row in properties if property_filter(row)]
    rows = [property_to_export_row(row) for row in properties]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=EXPORT_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    return ExportFileResult(name=name, path=path, row_count=len(rows))


async def export_master_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    property_filter: Callable[[Property], bool] | None = None,
) -> ExportFileResult:
    query = (
        select(Property)
        .options(selectinload(Property.listings))
        .order_by(Property.first_seen_at.desc())
    )
    return await _write_export(
        session,
        name="MASTER",
        path=output_path,
        query=query,
        property_filter=property_filter,
    )


async def export_nouveaux_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    window_hours: int | None = None,
    property_filter: Callable[[Property], bool] | None = None,
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
    return await _write_export(
        session,
        name="NOUVEAUX",
        path=output_path,
        query=query,
        property_filter=property_filter,
    )


async def export_modifies_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    window_hours: int | None = None,
    property_filter: Callable[[Property], bool] | None = None,
) -> ExportFileResult:
    settings = get_settings()
    effective_updated_window = window_hours if window_hours is not None else settings.updated_window_hours
    updated_cutoff = datetime.now(UTC) - timedelta(hours=effective_updated_window)
    new_cutoff = datetime.now(UTC) - timedelta(hours=settings.new_window_hours)
    query = (
        select(Property)
        .options(selectinload(Property.listings))
        .where(
            Property.first_seen_at < new_cutoff,
            or_(
                Property.status == PropertyStatus.UPDATED,
                and_(
                    Property.last_changed_at.is_not(None),
                    Property.last_changed_at >= updated_cutoff,
                ),
            ),
        )
        .order_by(Property.last_changed_at.desc())
    )
    return await _write_export(
        session,
        name="MODIFIES",
        path=output_path,
        query=query,
        property_filter=property_filter,
    )


async def export_inactifs_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    inactive_after_days: int | None = None,
    property_filter: Callable[[Property], bool] | None = None,
) -> ExportFileResult:
    settings = get_settings()
    effective_days = (
        inactive_after_days if inactive_after_days is not None else settings.inactive_after_days
    )
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
    return await _write_export(
        session,
        name="INACTIFS",
        path=output_path,
        query=query,
        property_filter=property_filter,
    )


async def export_ventes_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    property_filter: Callable[[Property], bool] | None = None,
) -> ExportFileResult:
    query = (
        select(Property)
        .options(selectinload(Property.listings))
        .order_by(Property.first_seen_at.desc())
    )
    sale_filter = lambda row: _aggregate_transaction_type(_extract_transaction_types(row)) == "sale"
    return await _write_export(
        session,
        name="VENTES",
        path=output_path,
        query=query,
        property_filter=_and_property_filters(sale_filter, property_filter),
    )


async def export_locations_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    property_filter: Callable[[Property], bool] | None = None,
) -> ExportFileResult:
    query = (
        select(Property)
        .options(selectinload(Property.listings))
        .order_by(Property.first_seen_at.desc())
    )
    rent_filter = lambda row: _aggregate_transaction_type(_extract_transaction_types(row)) == "rent"
    return await _write_export(
        session,
        name="LOCATIONS",
        path=output_path,
        query=query,
        property_filter=_and_property_filters(rent_filter, property_filter),
    )


async def export_deduplication_report_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    property_filter: Callable[[Property], bool] | None = None,
) -> ExportFileResult:
    query = (
        select(Property)
        .options(selectinload(Property.listings))
        .order_by(Property.first_seen_at.desc())
    )
    properties = await _fetch_properties(session, query)
    if property_filter is not None:
        properties = [row for row in properties if property_filter(row)]
    rows = [property_to_deduplication_row(row) for row in properties]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=DEDUPLICATION_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    return ExportFileResult(name="DEDUPLICATION_REPORT", path=output_path, row_count=len(rows))


async def export_all_csv(
    *,
    output_dir: Path | None = None,
    session: AsyncSession | None = None,
    property_filter: Callable[[Property], bool] | None = None,
) -> list[ExportFileResult]:
    export_dir = output_dir or Path("data/exports")
    owns_session = session is None
    active_session = session
    if active_session is None:
        active_session = AsyncSessionLocal()

    try:
        master = await export_master_csv(
            active_session,
            export_dir / "master.csv",
            property_filter=property_filter,
        )
        nouveaux = await export_nouveaux_csv(
            active_session,
            export_dir / "nouveaux.csv",
            property_filter=property_filter,
        )
        modifies = await export_modifies_csv(
            active_session,
            export_dir / "modifies.csv",
            property_filter=property_filter,
        )
        inactifs = await export_inactifs_csv(
            active_session,
            export_dir / "inactifs.csv",
            property_filter=property_filter,
        )
        ventes = await export_ventes_csv(
            active_session,
            export_dir / "ventes.csv",
            property_filter=property_filter,
        )
        locations = await export_locations_csv(
            active_session,
            export_dir / "locations.csv",
            property_filter=property_filter,
        )
        dedup_report = await export_deduplication_report_csv(
            active_session,
            export_dir / "deduplication_report.csv",
            property_filter=property_filter,
        )
        return [master, nouveaux, modifies, inactifs, ventes, locations, dedup_report]
    finally:
        if owns_session and active_session is not None:
            await active_session.close()
