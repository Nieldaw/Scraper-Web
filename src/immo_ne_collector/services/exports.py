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
from immo_ne_collector.services.source_config import CANTON_MATCHERS, infer_detected_canton, normalize_canton, normalize_detected_canton

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
    "detected_cantons",
    "canton_conflict",
    "source_listing_count",
    "source_urls_by_canton",
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


def _normalized_canton_for_export(value: str | None) -> str:
    detected = normalize_detected_canton(value)
    return detected if detected != "unknown" else "unknown"


def _get_listing_detected_canton(listing, *, fallback_canton: str | None = None) -> str:
    raw_detected = None
    if isinstance(listing.raw_data, dict):
        raw_detected = listing.raw_data.get("detected_canton")
    inferred, _ = infer_detected_canton(
        url=listing.url,
        city=listing.city,
        postal_code=listing.postal_code,
        fallback_canton=fallback_canton,
    )
    detected = _normalized_canton_for_export(raw_detected if isinstance(raw_detected, str) else None)
    if detected != "unknown" and inferred != "unknown" and detected != inferred:
        return inferred
    if detected != "unknown":
        return detected
    return inferred


def _filter_listings_for_canton(property_row: Property, *, canton: str | None) -> list:
    if canton is None:
        return list(property_row.listings)
    normalized_canton = normalize_canton(canton)
    matcher = CANTON_MATCHERS.get(normalized_canton)
    if matcher is None:
        return list(property_row.listings)

    selected: list = []
    for listing in property_row.listings:
        detected = _get_listing_detected_canton(listing, fallback_canton=None)
        if detected == normalized_canton:
            selected.append(listing)
            continue
        if detected != "unknown":
            continue
        if matcher(listing.url, listing.city, listing.postal_code):
            selected.append(listing)
    return selected


def _and_property_filters(
    left: Callable[[Property], bool] | None,
    right: Callable[[Property], bool] | None,
) -> Callable[[Property], bool] | None:
    if left is None:
        return right
    if right is None:
        return left
    return lambda row: left(row) and right(row)


def _extract_transaction_types(property_row: Property, *, listings: list | None = None) -> list[str]:
    target_listings = listings if listings is not None else list(property_row.listings)
    detected: list[str] = []
    for listing in target_listings:
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


def property_to_export_row(property_row: Property, *, canton: str | None = None) -> dict[str, str]:
    selected_listings = _filter_listings_for_canton(property_row, canton=canton)
    source_urls_from_rows = [listing.url for listing in selected_listings if listing.url]
    merged_source_urls: list[str] = []
    base_urls = property_row.source_urls if canton is None else []
    for url in [*base_urls, *source_urls_from_rows]:
        if url not in merged_source_urls:
            merged_source_urls.append(url)

    source_names_from_rows = [listing.source for listing in selected_listings if listing.source]
    merged_sources: list[str] = []
    base_sources = property_row.sources if canton is None else []
    for source in [*base_sources, *source_names_from_rows]:
        if source not in merged_sources:
            merged_sources.append(source)
    transaction_types = _extract_transaction_types(property_row, listings=selected_listings)
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


def property_to_deduplication_row(property_row: Property, *, canton: str | None = None) -> dict[str, str]:
    selected_listings = _filter_listings_for_canton(property_row, canton=canton)
    source_urls_from_rows = [listing.url for listing in selected_listings if listing.url]
    merged_source_urls: list[str] = []
    base_urls = property_row.source_urls if canton is None else []
    for url in [*base_urls, *source_urls_from_rows]:
        if url not in merged_source_urls:
            merged_source_urls.append(url)

    source_names_from_rows = [listing.source for listing in selected_listings if listing.source]
    merged_sources: list[str] = []
    base_sources = property_row.sources if canton is None else []
    for source in [*base_sources, *source_names_from_rows]:
        if source not in merged_sources:
            merged_sources.append(source)

    source_count = len(merged_sources)
    detected_cantons: list[str] = []
    source_urls_by_canton: dict[str, list[str]] = {}
    source_listing_count = 0
    for listing in selected_listings:
        source_listing_count += 1
        detected = _get_listing_detected_canton(listing, fallback_canton=canton)
        if detected not in detected_cantons:
            detected_cantons.append(detected)
        source_urls_by_canton.setdefault(detected, [])
        if listing.url and listing.url not in source_urls_by_canton[detected]:
            source_urls_by_canton[detected].append(listing.url)

    known_cantons = [item for item in detected_cantons if item != "unknown"]
    has_canton_conflict = len(set(known_cantons)) > 1
    if source_count <= 1:
        merge_status = "single_source"
    elif has_canton_conflict:
        merge_status = "canton_conflict_prevented"
    else:
        merge_status = "merged_same_canton"

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
        "detected_cantons": json.dumps(detected_cantons, ensure_ascii=False),
        "canton_conflict": "true" if has_canton_conflict else "false",
        "source_listing_count": str(source_listing_count),
        "source_urls_by_canton": json.dumps(source_urls_by_canton, ensure_ascii=False),
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
    canton: str | None = None,
) -> ExportFileResult:
    properties = await _fetch_properties(session, query)
    if property_filter is not None:
        properties = [row for row in properties if property_filter(row)]
    rows = [property_to_export_row(row, canton=canton) for row in properties]
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
    canton: str | None = None,
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
        canton=canton,
    )


async def export_nouveaux_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    window_hours: int | None = None,
    property_filter: Callable[[Property], bool] | None = None,
    canton: str | None = None,
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
        canton=canton,
    )


async def export_modifies_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    window_hours: int | None = None,
    property_filter: Callable[[Property], bool] | None = None,
    canton: str | None = None,
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
        canton=canton,
    )


async def export_inactifs_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    inactive_after_days: int | None = None,
    property_filter: Callable[[Property], bool] | None = None,
    canton: str | None = None,
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
        canton=canton,
    )


async def export_ventes_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    property_filter: Callable[[Property], bool] | None = None,
    canton: str | None = None,
) -> ExportFileResult:
    query = (
        select(Property)
        .options(selectinload(Property.listings))
        .order_by(Property.first_seen_at.desc())
    )
    def sale_filter(row: Property) -> bool:
        selected = _filter_listings_for_canton(row, canton=canton) if canton else None
        return _aggregate_transaction_type(_extract_transaction_types(row, listings=selected)) == "sale"

    return await _write_export(
        session,
        name="VENTES",
        path=output_path,
        query=query,
        property_filter=_and_property_filters(sale_filter, property_filter),
        canton=canton,
    )


async def export_locations_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    property_filter: Callable[[Property], bool] | None = None,
    canton: str | None = None,
) -> ExportFileResult:
    query = (
        select(Property)
        .options(selectinload(Property.listings))
        .order_by(Property.first_seen_at.desc())
    )
    def rent_filter(row: Property) -> bool:
        selected = _filter_listings_for_canton(row, canton=canton) if canton else None
        return _aggregate_transaction_type(_extract_transaction_types(row, listings=selected)) == "rent"

    return await _write_export(
        session,
        name="LOCATIONS",
        path=output_path,
        query=query,
        property_filter=_and_property_filters(rent_filter, property_filter),
        canton=canton,
    )


async def export_deduplication_report_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    property_filter: Callable[[Property], bool] | None = None,
    canton: str | None = None,
) -> ExportFileResult:
    query = (
        select(Property)
        .options(selectinload(Property.listings))
        .order_by(Property.first_seen_at.desc())
    )
    properties = await _fetch_properties(session, query)
    if property_filter is not None:
        properties = [row for row in properties if property_filter(row)]
    rows = [property_to_deduplication_row(row, canton=canton) for row in properties]
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
    canton: str | None = None,
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
            canton=canton,
        )
        nouveaux = await export_nouveaux_csv(
            active_session,
            export_dir / "nouveaux.csv",
            property_filter=property_filter,
            canton=canton,
        )
        modifies = await export_modifies_csv(
            active_session,
            export_dir / "modifies.csv",
            property_filter=property_filter,
            canton=canton,
        )
        inactifs = await export_inactifs_csv(
            active_session,
            export_dir / "inactifs.csv",
            property_filter=property_filter,
            canton=canton,
        )
        ventes = await export_ventes_csv(
            active_session,
            export_dir / "ventes.csv",
            property_filter=property_filter,
            canton=canton,
        )
        locations = await export_locations_csv(
            active_session,
            export_dir / "locations.csv",
            property_filter=property_filter,
            canton=canton,
        )
        dedup_report = await export_deduplication_report_csv(
            active_session,
            export_dir / "deduplication_report.csv",
            property_filter=property_filter,
            canton=canton,
        )
        return [master, nouveaux, modifies, inactifs, ventes, locations, dedup_report]
    finally:
        if owns_session and active_session is not None:
            await active_session.close()
