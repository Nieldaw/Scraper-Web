"""Insère (ou supprime avec --clear) quelques biens de démonstration pour l'interface web.

Les biens portent le titre « [DEMO] … » et la source « demo ». Attention : la suite de tests
fait un TRUNCATE de ces tables, donc lancer pytest efface aussi les données de démo.
"""

import argparse
import asyncio
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import Property, PropertyStatus

BASE = "http://localhost:8000/static/demo"
ROWS = [
    ("Villa avec vue sur le lac", "Neuchâtel", "2000", "NE", 1_450_000, 6.5, 210, "house", "NEW", "demo1.svg"),
    ("Appartement 4.5 pièces rénové", "Lausanne", "1003", "VD", 890_000, 4.5, 112, "apartment", "NEW", "demo2.svg"),
    ("Maison de village mitoyenne", "Boudry", "2017", "NE", 720_000, 5.5, 160, "house", "UPDATED", "demo3.svg"),
    ("Attique lumineux proche gare", "Genève", "1201", "GE", 1_980_000, 5.0, 150, "apartment", "ACTIVE", None),
    ("Studio investisseur", "Fribourg", "1700", "FR", 310_000, 1.5, 34, "apartment", "ACTIVE", None),
    ("Ferme à rénover", "Le Locle", "2400", "NE", 540_000, 8.0, 280, "house", "INACTIVE", None),
    ("Terrain constructible", "Delémont", "2800", "JU", 260_000, None, None, "land", "ACTIVE", None),
    ("Duplex avec terrasse", "Sion", "1950", "VS", 760_000, 4.5, 125, "apartment", "UPDATED", "demo2.svg"),
]


async def seed() -> None:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        for i, (title, city, npa, canton, price, rooms, area, kind, status, img) in enumerate(ROWS):
            seen = now - timedelta(hours=random.randint(1, 72))
            session.add(
                Property(
                    title=f"[DEMO] {title}",
                    property_type=kind,
                    price_chf=price,
                    rooms=rooms,
                    living_area_m2=area,
                    address_full=None,
                    city=city,
                    postal_code=npa,
                    sources=["demo"],
                    source_urls=[f"https://example.org/demo/{i}"],
                    first_seen_at=seen - timedelta(days=2),
                    last_seen_at=seen,
                    status=getattr(PropertyStatus, status),
                    raw_data={"detected_canton": canton, "image_url": f"{BASE}/{img}" if img else None},
                )
            )
        await session.commit()


async def clear() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Property).where(Property.title.like("[DEMO]%")))
        await session.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clear", action="store_true", help="supprime les biens de démo")
    args = parser.parse_args()
    asyncio.run(clear() if args.clear else seed())
