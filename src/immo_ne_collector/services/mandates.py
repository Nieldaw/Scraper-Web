import csv
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import Property, PropertyStatus, SearchMandate
from immo_ne_collector.services.exports import EXPORT_HEADERS, ExportFileResult, property_to_export_row


@dataclass(frozen=True)
class MandateCriteria:
    name: str
    cities: list[str] = field(default_factory=list)
    property_types: list[str] = field(default_factory=list)
    min_price_chf: Decimal | None = None
    max_price_chf: Decimal | None = None
    min_rooms: Decimal | None = None
    max_rooms: Decimal | None = None
    min_living_area_m2: Decimal | None = None
    max_living_area_m2: Decimal | None = None
    only_active: bool = True
    is_active: bool = True


@dataclass(frozen=True)
class MandatePropertyMatch:
    property_id: UUID
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MandateApplyResult:
    mandate_id: UUID
    criteria: MandateCriteria
    matches: list[MandatePropertyMatch] = field(default_factory=list)


def _normalize_text_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        cleaned = " ".join(value.strip().split())
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _criteria_from_mandate(mandate: SearchMandate) -> MandateCriteria:
    return MandateCriteria(
        name=mandate.name,
        cities=list(mandate.cities),
        property_types=list(mandate.property_types),
        min_price_chf=_to_decimal(mandate.min_price_chf),
        max_price_chf=_to_decimal(mandate.max_price_chf),
        min_rooms=_to_decimal(mandate.min_rooms),
        max_rooms=_to_decimal(mandate.max_rooms),
        min_living_area_m2=_to_decimal(mandate.min_living_area_m2),
        max_living_area_m2=_to_decimal(mandate.max_living_area_m2),
        only_active=mandate.only_active,
        is_active=mandate.is_active,
    )


def _in_range(value, minimum: Decimal | None, maximum: Decimal | None) -> bool:
    if minimum is None and maximum is None:
        return True
    if value is None:
        return False
    as_decimal = _to_decimal(value)
    if as_decimal is None:
        return False
    if minimum is not None and as_decimal < minimum:
        return False
    if maximum is not None and as_decimal > maximum:
        return False
    return True


def _matches_criteria(property_row: Property, criteria: MandateCriteria) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if criteria.only_active and property_row.status in (PropertyStatus.INACTIVE, PropertyStatus.REMOVED):
        return False, reasons

    if criteria.cities:
        if property_row.city is None:
            return False, reasons
        allowed = {city.lower() for city in criteria.cities}
        if property_row.city.lower() not in allowed:
            return False, reasons
        reasons.append("city_match")

    if criteria.property_types:
        if property_row.property_type is None:
            return False, reasons
        allowed_types = {value.lower() for value in criteria.property_types}
        if property_row.property_type.lower() not in allowed_types:
            return False, reasons
        reasons.append("property_type_match")

    if not _in_range(property_row.price_chf, criteria.min_price_chf, criteria.max_price_chf):
        return False, reasons
    if criteria.min_price_chf is not None or criteria.max_price_chf is not None:
        reasons.append("price_in_range")

    if not _in_range(property_row.rooms, criteria.min_rooms, criteria.max_rooms):
        return False, reasons
    if criteria.min_rooms is not None or criteria.max_rooms is not None:
        reasons.append("rooms_in_range")

    if not _in_range(property_row.living_area_m2, criteria.min_living_area_m2, criteria.max_living_area_m2):
        return False, reasons
    if criteria.min_living_area_m2 is not None or criteria.max_living_area_m2 is not None:
        reasons.append("living_area_in_range")

    return True, reasons


async def create_search_mandate(
    session: AsyncSession,
    *,
    criteria: MandateCriteria,
) -> SearchMandate:
    mandate = SearchMandate(
        name=criteria.name,
        cities=_normalize_text_list(criteria.cities),
        property_types=[item.lower() for item in _normalize_text_list(criteria.property_types)],
        min_price_chf=criteria.min_price_chf,
        max_price_chf=criteria.max_price_chf,
        min_rooms=criteria.min_rooms,
        max_rooms=criteria.max_rooms,
        min_living_area_m2=criteria.min_living_area_m2,
        max_living_area_m2=criteria.max_living_area_m2,
        only_active=criteria.only_active,
        is_active=criteria.is_active,
    )
    session.add(mandate)
    await session.commit()
    await session.refresh(mandate)
    return mandate


async def list_search_mandates(session: AsyncSession, *, active_only: bool = False) -> list[SearchMandate]:
    query = select(SearchMandate).order_by(SearchMandate.created_at.desc())
    if active_only:
        query = query.where(SearchMandate.is_active.is_(True))
    result = await session.execute(query)
    return result.scalars().all()


async def apply_search_mandate(
    session: AsyncSession,
    *,
    mandate_id: UUID,
) -> MandateApplyResult:
    mandate = await session.get(SearchMandate, mandate_id)
    if mandate is None:
        raise ValueError(f"Mandate not found: {mandate_id}")

    criteria = _criteria_from_mandate(mandate)
    properties = (
        await session.execute(select(Property).options(selectinload(Property.listings)).order_by(Property.last_seen_at.desc()))
    ).scalars().all()

    matches: list[MandatePropertyMatch] = []
    for property_row in properties:
        is_match, reasons = _matches_criteria(property_row, criteria)
        if is_match:
            matches.append(MandatePropertyMatch(property_id=property_row.id, reasons=reasons))

    return MandateApplyResult(
        mandate_id=mandate.id,
        criteria=criteria,
        matches=matches,
    )


async def export_mandate_matches_csv(
    session: AsyncSession,
    *,
    mandate_id: UUID,
    output_dir: Path = Path("data/exports"),
) -> ExportFileResult:
    apply_result = await apply_search_mandate(session, mandate_id=mandate_id)
    properties = (
        await session.execute(select(Property).options(selectinload(Property.listings)))
    ).scalars().all()
    by_id = {row.id: row for row in properties}

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"mandate_{mandate_id}_matches.csv"
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=[*EXPORT_HEADERS, "match_reasons"])
        writer.writeheader()
        for match in apply_result.matches:
            property_row = by_id.get(match.property_id)
            if property_row is None:
                continue
            row = property_to_export_row(property_row)
            row["match_reasons"] = ";".join(match.reasons)
            writer.writerow(row)

    return ExportFileResult(
        name="MANDATE_MATCHES",
        path=path,
        row_count=len(apply_result.matches),
    )


async def create_demo_mandate_if_missing(session: AsyncSession) -> SearchMandate:
    existing = await list_search_mandates(session, active_only=True)
    if existing:
        return existing[0]

    return await create_search_mandate(
        session,
        criteria=MandateCriteria(
            name="Mandat demo Neuchatel",
            cities=["Neuchatel"],
            property_types=["appartement", "maison"],
            min_price_chf=Decimal("400000"),
            max_price_chf=Decimal("1500000"),
            min_rooms=Decimal("3"),
            max_rooms=Decimal("7"),
            min_living_area_m2=Decimal("70"),
            max_living_area_m2=Decimal("260"),
            only_active=True,
            is_active=True,
        ),
    )


async def run_mandate_and_export(
    *,
    mandate_id: UUID | None = None,
    output_dir: Path = Path("data/exports"),
) -> tuple[SearchMandate, MandateApplyResult, ExportFileResult]:
    async with AsyncSessionLocal() as session:
        if mandate_id is None:
            mandate = await create_demo_mandate_if_missing(session)
        else:
            mandate = await session.get(SearchMandate, mandate_id)
            if mandate is None:
                raise ValueError(f"Mandate not found: {mandate_id}")

        result = await apply_search_mandate(session, mandate_id=mandate.id)
        export_result = await export_mandate_matches_csv(
            session,
            mandate_id=mandate.id,
            output_dir=output_dir,
        )
        return mandate, result, export_result
