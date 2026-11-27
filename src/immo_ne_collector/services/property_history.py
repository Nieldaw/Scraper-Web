"""Historique des modifications d'un bien : prix, titre, agence."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from immo_ne_collector.models import PropertyHistory

FIELD_LABELS: dict[str, str] = {"price": "Prix", "title": "Titre", "agency": "Agence"}
_AGENCY_KEYS = ("agency_name", "agency", "advertiser_name", "advertiser", "provider_name", "seller")


def extract_agency_name(raw_data: Mapping[str, Any] | None) -> str | None:
    """Nom de l'agence si une clé connue de raw_data le contient (texte ou {name: …})."""
    if not isinstance(raw_data, Mapping):
        return None
    for key in _AGENCY_KEYS:
        value = raw_data.get(key)
        if isinstance(value, Mapping):
            value = value.get("name") or value.get("companyName")
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return None


def _price_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(Decimal(str(value)).quantize(Decimal("1")))
    except InvalidOperation:
        return str(value)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def diff_tracked_fields(
    *,
    old_price: Any,
    new_price: Any,
    old_title: str | None,
    new_title: str | None,
    old_agency: str | None,
    new_agency: str | None,
) -> list[tuple[str, str | None, str | None]]:
    """[(champ, ancienne valeur, nouvelle valeur)] pour ce qui a réellement changé."""
    pairs = (
        ("price", _price_str(old_price), _price_str(new_price)),
        ("title", _text(old_title), _text(new_title)),
        ("agency", _text(old_agency), _text(new_agency)),
    )
    return [(field, old, new) for field, old, new in pairs if old != new]


def add_history_rows(
    session: AsyncSession,
    *,
    property_id: UUID,
    changes: list[tuple[str, str | None, str | None]],
    changed_at: datetime,
    source: str | None,
) -> None:
    for field, old, new in changes:
        session.add(
            PropertyHistory(
                property_id=property_id,
                field=field,
                old_value=old,
                new_value=new,
                source=source,
                changed_at=changed_at,
            )
        )


async def list_history(session: AsyncSession, property_id: UUID) -> list[PropertyHistory]:
    result = await session.execute(
        select(PropertyHistory)
        .where(PropertyHistory.property_id == property_id)
        .order_by(PropertyHistory.changed_at.desc(), PropertyHistory.field)
    )
    return list(result.scalars().all())
