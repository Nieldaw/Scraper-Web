from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from immo_ne_collector.db import get_session
from immo_ne_collector.models import DailyRun, Property
from immo_ne_collector.schemas import (
    DailyRunOut,
    MandateMatchesOut,
    PropertyListResponse,
    PropertyOut,
    SearchMandateCreate,
    SearchMandateOut,
    StatsOut,
)
from immo_ne_collector.services.mandates import (
    MandateCriteria,
    apply_search_mandate,
    create_search_mandate,
    list_search_mandates,
)
from immo_ne_collector.services.property_queries import (
    MAX_PAGE_SIZE,
    PRICE_STATUS_LABELS,
    SORTS,
    PropertyFilters,
    count_by_status,
    extract_image_url,
    get_property,
    price_status_of,
    search_properties,
    status_label,
)

router = APIRouter(prefix="/api")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def property_to_out(row: Property) -> PropertyOut:
    return PropertyOut(
        id=row.id,
        title=row.title,
        property_type=row.property_type,
        price_chf=float(row.price_chf) if row.price_chf is not None else None,
        rooms=float(row.rooms) if row.rooms is not None else None,
        living_area_m2=float(row.living_area_m2) if row.living_area_m2 is not None else None,
        address_full=row.address_full,
        city=row.city,
        postal_code=row.postal_code,
        sources=list(row.sources or []),
        source_urls=list(row.source_urls or []),
        status=row.status,
        status_label=status_label(row.status),
        image_url=extract_image_url(row.raw_data),
        price_status=price_status_of(row.raw_data),
        price_status_label=PRICE_STATUS_LABELS.get(price_status_of(row.raw_data) or ""),
        is_processed=bool(row.is_processed),
        latitude=row.latitude,
        longitude=row.longitude,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        last_changed_at=row.last_changed_at,
        needs_completion=row.needs_completion,
        sitn_status=row.sitn_status,
    )


async def _list(
    session: AsyncSession,
    filters: PropertyFilters,
    page: int,
    page_size: int,
) -> PropertyListResponse:
    rows, total = await search_properties(session, filters, page=page, page_size=page_size)
    return PropertyListResponse(
        items=[property_to_out(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/properties", response_model=PropertyListResponse)
async def list_properties(
    session: SessionDep,
    q: str | None = None,
    status: Annotated[str, Query(pattern="^(all|new|modified|inactive)$")] = "all",
    city: str | None = None,
    canton: str | None = None,
    min_price: Annotated[float | None, Query(ge=0)] = None,
    max_price: Annotated[float | None, Query(ge=0)] = None,
    min_rooms: Annotated[float | None, Query(ge=0)] = None,
    unprocessed: bool = False,
    sort: Annotated[str, Query(pattern=f"^({'|'.join(SORTS)})$")] = "recent",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 24,
) -> PropertyListResponse:
    filters = PropertyFilters(
        q=q,
        status=status,
        city=city,
        canton=canton,
        min_price=min_price,
        max_price=max_price,
        min_rooms=min_rooms,
        unprocessed=unprocessed,
        sort=sort,
    )
    return await _list(session, filters, page, page_size)


def _status_view(status: str):
    async def view(
        session: SessionDep,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 24,
    ) -> PropertyListResponse:
        return await _list(session, PropertyFilters(status=status), page, page_size)

    return view


router.add_api_route("/properties/new", _status_view("new"), response_model=PropertyListResponse)
router.add_api_route(
    "/properties/updated", _status_view("modified"), response_model=PropertyListResponse
)
router.add_api_route(
    "/properties/inactive", _status_view("inactive"), response_model=PropertyListResponse
)


@router.get("/properties/{property_id}", response_model=PropertyOut)
async def read_property(property_id: UUID, session: SessionDep) -> PropertyOut:
    row = await get_property(session, property_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Bien introuvable")
    return property_to_out(row)


@router.get("/stats", response_model=StatsOut)
async def read_stats(session: SessionDep) -> StatsOut:
    return StatsOut(**await count_by_status(session))


@router.get("/runs", response_model=list[DailyRunOut])
async def list_runs(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[DailyRun]:
    result = await session.execute(
        select(DailyRun).order_by(DailyRun.started_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def mandate_create_to_criteria(payload: SearchMandateCreate) -> MandateCriteria:
    return MandateCriteria(
        name=payload.name,
        cities=payload.cities,
        property_types=payload.property_types,
        min_price_chf=_dec(payload.min_price_chf),
        max_price_chf=_dec(payload.max_price_chf),
        min_rooms=_dec(payload.min_rooms),
        max_rooms=_dec(payload.max_rooms),
        min_living_area_m2=_dec(payload.min_living_area_m2),
        max_living_area_m2=_dec(payload.max_living_area_m2),
        only_active=payload.only_active,
    )


@router.get("/mandates", response_model=list[SearchMandateOut])
async def list_mandates(session: SessionDep, active_only: bool = False):
    return await list_search_mandates(session, active_only=active_only)


@router.post("/mandates", response_model=SearchMandateOut, status_code=201)
async def create_mandate(payload: SearchMandateCreate, session: SessionDep):
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="Le nom du mandat est obligatoire")
    return await create_search_mandate(session, criteria=mandate_create_to_criteria(payload))


@router.get("/mandates/{mandate_id}/matches", response_model=MandateMatchesOut)
async def mandate_matches(mandate_id: UUID, session: SessionDep) -> MandateMatchesOut:
    try:
        result = await apply_search_mandate(session, mandate_id=mandate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Mandat introuvable") from exc
    ids = [m.property_id for m in result.matches]
    rows = (
        (await session.execute(select(Property).where(Property.id.in_(ids)))).scalars().all()
        if ids
        else []
    )
    order = {pid: i for i, pid in enumerate(ids)}
    rows = sorted(rows, key=lambda r: order[r.id])
    return MandateMatchesOut(
        mandate_id=mandate_id, total=len(rows), items=[property_to_out(r) for r in rows]
    )
