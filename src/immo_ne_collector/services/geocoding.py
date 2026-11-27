"""Coordonnées (lat/lon) d'un bien à partir de son code postal, via l'API publique geo.admin.ch.

Seul le code postal est envoyé (jamais le titre, le prix ni l'adresse). Une requête par code
postal distinct ; un échec réseau ne bloque jamais la collecte.
"""

import asyncio
import logging
import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from immo_ne_collector.config import get_settings
from immo_ne_collector.models import Property

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api3.geo.admin.ch/rest/services/api/SearchServer"
_NPA_RE = re.compile(r"^[1-9]\d{3}$")
REQUEST_DELAY_SECONDS = 0.2
MAX_CODES_PER_RUN = 100


def parse_search_response(payload: Any) -> tuple[float, float] | None:
    """(lat, lon) du premier résultat valide, sinon None."""
    if not isinstance(payload, dict):
        return None
    for result in payload.get("results") or []:
        attrs = result.get("attrs") if isinstance(result, dict) else None
        if not isinstance(attrs, dict):
            continue
        lat, lon = attrs.get("lat"), attrs.get("lon")
        if isinstance(lat, int | float) and isinstance(lon, int | float):
            # La Suisse tient dans ce cadre : écarte les résultats aberrants.
            if 45.5 <= lat <= 48.0 and 5.5 <= lon <= 11.0:
                return float(lat), float(lon)
    return None


async def geocode_postal_code(client: httpx.AsyncClient, postal_code: str) -> tuple[float, float] | None:
    if not _NPA_RE.match(postal_code or ""):
        return None
    response = await client.get(
        SEARCH_URL,
        params={
            "searchText": postal_code,
            "type": "locations",
            "origins": "zipcode",
            "limit": 1,
            "sr": 4326,
        },
    )
    response.raise_for_status()
    return parse_search_response(response.json())


async def geocode_missing_properties(
    session: AsyncSession,
    *,
    client: httpx.AsyncClient | None = None,
    max_codes: int = MAX_CODES_PER_RUN,
) -> int:
    """Renseigne latitude/longitude des biens qui ont un code postal ; retourne le nombre de biens mis à jour."""
    rows = (
        (
            await session.execute(
                select(Property).where(
                    Property.latitude.is_(None),
                    Property.postal_code.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_code: dict[str, list[Property]] = {}
    for row in rows:
        by_code.setdefault(row.postal_code, []).append(row)
    if not by_code:
        return 0

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "immo-collector"})
    updated = 0
    try:
        for index, (code, properties) in enumerate(sorted(by_code.items())):
            if index >= max_codes:
                break
            try:
                coords = await geocode_postal_code(client, code)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Géocodage %s impossible : %s", code, exc)
                continue
            if coords is not None:
                for row in properties:
                    row.latitude, row.longitude = coords
                    updated += 1
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
        await session.commit()
    finally:
        if owns_client:
            await client.aclose()
    return updated


async def _main() -> None:
    from immo_ne_collector.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        count = await geocode_missing_properties(session)
    print(f"{count} bien(s) géocodé(s).")


if __name__ == "__main__":
    if not get_settings().geocoding_enabled:
        print("Géocodage désactivé (GEOCODING_ENABLED=false).")
    else:
        asyncio.run(_main())
