"""Options des listes déroulantes, cases à cocher et curseurs (mandats et filtres).

Tout est calculé à partir de la base : villes réellement présentes, bornes réelles des curseurs.
Les types de bien proposés sont fixes (valeurs normalisées par ``normalize_property_type``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from immo_ne_collector.models import Property
from immo_ne_collector.services.source_config import ROMANDY_CANTONS

# (valeur stockée en base, libellé affiché)
PROPERTY_TYPE_CHOICES: tuple[tuple[str, str], ...] = (
    ("appartement", "Appartement"),
    ("maison", "Maison"),
    ("terrain", "Terrain"),
)

# Paliers des filtres de la page Propriétés
PRICE_STEPS: tuple[int, ...] = (
    100_000, 200_000, 300_000, 400_000, 500_000, 600_000, 800_000,
    1_000_000, 1_500_000, 2_000_000, 3_000_000, 5_000_000,
)  # fmt: skip
ROOM_STEPS: tuple[float, ...] = (1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 7, 8)


@dataclass(frozen=True)
class SliderBounds:
    """Bornes et pas d'un curseur double (min/max)."""

    low: float
    high: float
    step: float

    def including(self, *values: float | None) -> SliderBounds:
        """Élargit les bornes pour que des valeurs préremplies restent atteignables."""
        known = [v for v in values if v is not None]
        if not known:
            return self
        return SliderBounds(
            low=min(self.low, math.floor(min(known) / self.step) * self.step),
            high=max(self.high, math.ceil(max(known) / self.step) * self.step),
            step=self.step,
        )


# Bornes de secours quand la base est vide
DEFAULT_PRICE = SliderBounds(0, 3_000_000, 10_000)
DEFAULT_ROOMS = SliderBounds(1, 10, 0.5)
DEFAULT_AREA = SliderBounds(0, 500, 5)


def _nice_bounds(
    low: float | None,
    high: float | None,
    step: float,
    default: SliderBounds,
    *,
    floor_at: float = 0,
) -> SliderBounds:
    if low is None or high is None:
        return default
    lo = max(floor_at, math.floor(float(low) / step) * step)
    hi = math.ceil(float(high) / step) * step
    if hi <= lo:
        hi = lo + step
    return SliderBounds(lo, hi, step)


@dataclass(frozen=True)
class FilterOptions:
    cities: list[str]
    cantons: tuple[str, ...]
    property_types: tuple[tuple[str, str], ...]
    price: SliderBounds
    rooms: SliderBounds
    area: SliderBounds


async def list_cities(session: AsyncSession) -> list[str]:
    """Villes distinctes présentes en base (insensible à la casse, triées, sans vide)."""
    rows = (
        await session.execute(
            select(Property.city)
            .where(Property.city.is_not(None), func.trim(Property.city) != "")
            .group_by(Property.city)
            .order_by(func.lower(Property.city))
        )
    ).scalars()
    seen: dict[str, str] = {}
    for city in rows:
        seen.setdefault(city.strip().lower(), city.strip())
    return sorted(seen.values(), key=lambda c: c.lower())


async def load_filter_options(session: AsyncSession) -> FilterOptions:
    """Listes et bornes de curseurs (98e centile : les valeurs aberrantes n'écrasent pas le curseur)."""

    def span(column):
        return (
            func.min(column),
            func.percentile_cont(0.98).within_group(column.asc()),
        )

    p_lo, p_hi = span(Property.price_chf)
    r_lo, r_hi = span(Property.rooms)
    a_lo, a_hi = span(Property.living_area_m2)
    row = (await session.execute(select(p_lo, p_hi, r_lo, r_hi, a_lo, a_hi))).one()
    return FilterOptions(
        cities=await list_cities(session),
        cantons=ROMANDY_CANTONS,
        property_types=PROPERTY_TYPE_CHOICES,
        # Le prix minimal du curseur reste à 0 : « sans minimum » doit toujours être possible.
        price=_nice_bounds(0, row[1], 10_000, DEFAULT_PRICE),
        rooms=_nice_bounds(row[2], row[3], 0.5, DEFAULT_ROOMS, floor_at=1),
        area=_nice_bounds(0, row[5], 5, DEFAULT_AREA),
    )


def with_current_option(values: list, current) -> list:
    """Ajoute la valeur courante à une liste de paliers si elle n'y figure pas (URL ancienne)."""
    if current in (None, "", 0) or current in values:
        return values
    return sorted([*values, current])
