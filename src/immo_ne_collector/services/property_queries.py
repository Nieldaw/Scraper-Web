"""Requêtes de lecture sur les biens, partagées par l'API JSON et les pages HTML."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from immo_ne_collector.models import Property, PropertyStatus
from immo_ne_collector.services.images import extract_image_url

# Filtre d'interface -> statuts en base.
STATUS_FILTERS: dict[str, tuple[str, ...]] = {
    "new": (PropertyStatus.NEW,),
    "modified": (PropertyStatus.UPDATED,),
    "inactive": (PropertyStatus.INACTIVE, PropertyStatus.REMOVED),
}
STATUS_LABELS: dict[str, str] = {
    PropertyStatus.NEW: "new",
    PropertyStatus.ACTIVE: "active",
    PropertyStatus.UPDATED: "modified",
    PropertyStatus.INACTIVE: "inactive",
    PropertyStatus.REMOVED: "inactive",
}
SORTS = ("recent", "price_asc", "price_desc")
MAX_PAGE_SIZE = 100

__all__ = ["extract_image_url"]

# raw_data["price_status"] (posé à la collecte) -> fiabilité affichée du prix.
PRICE_STATUS_LABELS: dict[str, str] = {
    "verified": "Prix vérifié",
    "estimated": "Prix estimé",
}


def price_status_of(raw_data: Mapping[str, Any] | None) -> str | None:
    """« verified » : lu sur la fiche de l'annonce ; « estimated » : page de résultats, non vérifié.

    None quand on ne sait pas (autres sources, ou données collectées avant ce suivi) : aucune
    pastille n'est alors affichée plutôt que d'affirmer quelque chose d'inexact.
    """
    if not isinstance(raw_data, Mapping):
        return None
    raw = raw_data.get("price_status")
    if raw == "detail_page":
        return "verified"
    if raw == "unverified_search_page":
        return "estimated"
    return None


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status.lower())


@dataclass(frozen=True)
class PropertyFilters:
    q: str | None = None
    status: str = "all"
    city: str | None = None
    canton: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    min_rooms: float | None = None
    sort: str = "recent"


def _apply_filters(query, filters: PropertyFilters):
    if filters.status in STATUS_FILTERS:
        query = query.where(Property.status.in_([str(s) for s in STATUS_FILTERS[filters.status]]))
    if filters.q and filters.q.strip():
        pattern = f"%{filters.q.strip()}%"
        query = query.where(
            or_(
                Property.title.ilike(pattern, escape="\\"),
                Property.city.ilike(pattern, escape="\\"),
                Property.address_full.ilike(pattern, escape="\\"),
            )
        )
    if filters.city and filters.city.strip():
        query = query.where(func.lower(Property.city) == filters.city.strip().lower())
    if filters.canton and filters.canton.strip():
        query = query.where(
            func.upper(Property.raw_data["detected_canton"].astext)
            == filters.canton.strip().upper()
        )
    if filters.min_price is not None:
        query = query.where(Property.price_chf >= filters.min_price)
    if filters.max_price is not None:
        query = query.where(Property.price_chf <= filters.max_price)
    if filters.min_rooms is not None:
        query = query.where(Property.rooms >= filters.min_rooms)
    return query


def _apply_sort(query, sort: str):
    if sort == "price_asc":
        return query.order_by(Property.price_chf.asc().nulls_last(), Property.id)
    if sort == "price_desc":
        return query.order_by(Property.price_chf.desc().nulls_last(), Property.id)
    return query.order_by(Property.last_seen_at.desc(), Property.id)


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_properties(
    session: AsyncSession,
    filters: PropertyFilters,
    *,
    page: int = 1,
    page_size: int = 24,
) -> tuple[list[Property], int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    if filters.q:
        filters = replace(filters, q=escape_like(filters.q))

    base = _apply_filters(select(Property), filters)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                _apply_sort(base, filters.sort).limit(page_size).offset((page - 1) * page_size)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total


async def get_property(session: AsyncSession, property_id: UUID) -> Property | None:
    result = await session.execute(
        select(Property).options(selectinload(Property.listings)).where(Property.id == property_id)
    )
    return result.scalar_one_or_none()


async def count_by_status(session: AsyncSession) -> dict[str, int]:
    """Compteurs groupés par libellé d'interface (new / active / modified / inactive)."""
    rows = (
        await session.execute(select(Property.status, func.count()).group_by(Property.status))
    ).all()
    counts = {"new": 0, "active": 0, "modified": 0, "inactive": 0}
    for status, count in rows:
        counts[status_label(status)] = counts.get(status_label(status), 0) + count
    counts["total"] = sum(counts.values())
    return counts
